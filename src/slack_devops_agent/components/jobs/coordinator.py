"""CMP-006 — Job Coordinator (DynamoDB adapter, API-INT-002).

Owns the ProcessingJob lifecycle on the CS-1 shared-state boundary:

* **De-dup (BR-010/F1):** conditional ``PutItem`` on the ``(channel-id, message-ts)``
  identity → at most one job per identity, absorbing Slack redelivery and re-enqueue.
* **Single-winner lease (BR-027):** optimistic conditional ``UpdateItem`` keyed on the
  last-transition timestamp → exactly one worker (live or recovery-spawned) enters
  ``in-progress``; the loser yields.
* **Recovery (BR-021/NFR-19/F5):** a scan finds in-flight jobs whose lease is stale
  (inclusive ``>=`` 90s) and re-eligible for retry-or-abandon.
* **F8 mapping:** the worker stamps ``answer-message-ts`` on the job at answer-post; a GSI
  on that attribute lets intake resolve a reaction back to the correlation-id.

The DynamoDB item PK is the identity string so dedup and transitions share one item.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from botocore.exceptions import ClientError

from ...domain.entities import OriginatingMessageRef, ProcessingJob
from ...domain.enums import JobStatus
from ...domain.rules import is_lease_stale
from ...domain.state_machine import assert_transition

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

_IDENTITY_SEP = "#"


def _identity_key(identity: tuple[str, str]) -> str:
    """Render the (channel-id, message-ts) identity as the item PK string."""
    return f"{identity[0]}{_IDENTITY_SEP}{identity[1]}"


class DynamoJobCoordinator:
    """DynamoDB-backed :class:`JobCoordinator`."""

    def __init__(self, table: Table, answer_ts_gsi: str) -> None:
        self._table = table
        self._gsi = answer_ts_gsi

    # -- registration / dedup (BR-010) --------------------------------------

    def register_or_get(
        self,
        identity: tuple[str, str],
        ref: OriginatingMessageRef,
        job_id: UUID,
        now: datetime,
        attached_file_name: str | None = None,
        attached_file_text: str | None = None,
    ) -> tuple[ProcessingJob, bool]:
        pk = _identity_key(identity)
        item: dict[str, Any] = {
            "pk": pk,
            "job_id": str(job_id),
            "channel_id": ref.channel_id,
            "thread_ts": ref.thread_ts or "",
            "message_ts": ref.message_ts,
            "author_id": ref.author_id,
            "status": JobStatus.SEEN.value,
            "attempt_count": 0,
            "last_transition_at": now.isoformat(),
        }
        if attached_file_text:
            item["attached_file_text"] = attached_file_text
            item["attached_file_name"] = attached_file_name or ""
        try:
            self._table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
            return self._to_job(item), True
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            existing = self.get(identity)
            if existing is None:  # extremely unlikely: item vanished between put and get
                raise RuntimeError(f"dedup race: job for {identity!r} disappeared") from err
            return existing, False

    def get(self, identity: tuple[str, str]) -> ProcessingJob | None:
        response = self._table.get_item(Key={"pk": _identity_key(identity)})
        item = response.get("Item")
        return self._to_job(dict(item)) if item else None

    # -- single-winner lease (BR-021/BR-027) --------------------------------

    def acquire_lease(
        self, identity: tuple[str, str], now: datetime, staleness_seconds: int
    ) -> ProcessingJob | None:
        job = self.get(identity)
        if job is None or job.status.is_terminal:
            return None
        stale_threshold = (now - timedelta(seconds=staleness_seconds)).isoformat()
        try:
            response = self._table.update_item(
                Key={"pk": _identity_key(identity)},
                UpdateExpression=(
                    "SET #s = :inprog, attempt_count = attempt_count + :one, "
                    "last_transition_at = :now"
                ),
                # Single-winner: acquire a fresh `seen` job, or reclaim an in-progress job
                # only once its lease is stale (>= staleness). The CAS on last_transition_at
                # ensures two competing recovery workers cannot both win.
                ConditionExpression=(
                    "last_transition_at = :prev AND "
                    "(#s = :seen OR (#s = :inprog AND last_transition_at <= :stale))"
                ),
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":inprog": JobStatus.IN_PROGRESS.value,
                    ":seen": JobStatus.SEEN.value,
                    ":one": 1,
                    ":now": now.isoformat(),
                    ":prev": job.last_transition_at.isoformat(),
                    ":stale": stale_threshold,
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return None  # competing worker won, or a live (non-stale) lease is held
            raise
        return self._to_job(dict(response["Attributes"]))

    # -- transitions (BR-013/BR-022) ----------------------------------------

    def transition(
        self, identity: tuple[str, str], target: JobStatus, now: datetime
    ) -> ProcessingJob:
        job = self.get(identity)
        if job is None:
            raise KeyError(f"no job for identity {identity!r}")
        assert_transition(job.status, target)
        response = self._table.update_item(
            Key={"pk": _identity_key(identity)},
            UpdateExpression="SET #s = :t, last_transition_at = :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":t": target.value, ":now": now.isoformat()},
            ReturnValues="ALL_NEW",
        )
        return self._to_job(dict(response["Attributes"]))

    # -- F8 answer-ts mapping (BR-018) --------------------------------------

    def stamp_answer_ts(self, identity: tuple[str, str], answer_message_ts: str) -> None:
        self._table.update_item(
            Key={"pk": _identity_key(identity)},
            UpdateExpression="SET answer_message_ts = :ts",
            ExpressionAttributeValues={":ts": answer_message_ts},
        )

    def mark_post_intent(self, identity: tuple[str, str], now: datetime) -> None:
        # BR-027: stamp the pre-post intent marker only if not already set (idempotent), so
        # the first attempt's marker survives a reclaim and blocks a duplicate answer post.
        try:
            self._table.update_item(
                Key={"pk": _identity_key(identity)},
                UpdateExpression="SET post_intent_at = :now",
                ConditionExpression="attribute_not_exists(post_intent_at)",
                ExpressionAttributeValues={":now": now.isoformat()},
            )
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            # Marker already present (a prior attempt stamped it) — nothing to do.

    def resolve_answer_ts(self, answer_message_ts: str) -> UUID | None:
        response = self._table.query(
            IndexName=self._gsi,
            KeyConditionExpression="answer_message_ts = :ts",
            ExpressionAttributeValues={":ts": answer_message_ts},
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            return None
        return UUID(str(items[0]["job_id"]))

    # -- recovery scan (BR-021/F5) ------------------------------------------

    def find_stale_jobs(self, now: datetime, staleness_seconds: int) -> list[ProcessingJob]:
        response = self._table.scan(
            FilterExpression="#s = :seen OR #s = :inprog",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":seen": JobStatus.SEEN.value,
                ":inprog": JobStatus.IN_PROGRESS.value,
            },
        )
        jobs = [self._to_job(dict(item)) for item in response.get("Items", [])]
        return [j for j in jobs if is_lease_stale(j, now, staleness_seconds)]

    # -- mapping --------------------------------------------------------------

    @staticmethod
    def _to_job(item: dict[str, object]) -> ProcessingJob:
        thread_ts = str(item.get("thread_ts") or "") or None
        answer_ts = str(item.get("answer_message_ts") or "") or None
        post_intent_raw = str(item.get("post_intent_at") or "") or None
        post_intent_at = datetime.fromisoformat(post_intent_raw) if post_intent_raw else None
        return ProcessingJob(
            job_id=UUID(str(item["job_id"])),
            channel_id=str(item["channel_id"]),
            message_ts=str(item["message_ts"]),
            originating_message_ref=OriginatingMessageRef(
                channel_id=str(item["channel_id"]),
                thread_ts=thread_ts,
                message_ts=str(item["message_ts"]),
                author_id=str(item.get("author_id") or ""),
            ),
            status=JobStatus(str(item["status"])),
            attempt_count=int(str(item["attempt_count"])),
            last_transition_at=datetime.fromisoformat(str(item["last_transition_at"])),
            post_intent_at=post_intent_at,
            answer_message_ts=answer_ts,
            attached_file_name=str(item.get("attached_file_name") or "") or None,
            attached_file_text=str(item.get("attached_file_text") or "") or None,
        )
