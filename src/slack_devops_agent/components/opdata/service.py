"""CMP-007 — Operational Data Service (DynamoDB adapter, API-INT-006/007).

Owns the durable aggregates on the CS-1 boundary and the within-budget decision:

* **UsageCounter (BR-019):** atomic ``ADD`` increments so concurrent workers never lose
  updates — correctness-critical for the NFR-8 guardrail.
* **AdoptionMetric (BR-019/FR-18):** distinct developers (a string set) + questions handled.
* **FeedbackSignal (BR-020/Q4):** append-only — each reaction add/remove is an immutable
  row; the success metric aggregates latest-per-(answer, reactor, signal) at read time.

The within-budget check (BR-008) reads the current period's usage versus the operator
guardrail threshold.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from boto3.dynamodb.conditions import Key

from ...domain.entities import FeedbackSignal, GuardrailConfig
from ...domain.enums import ReactionKind
from ...domain.rules import aggregate_feedback, is_within_budget
from ...resilience.clock import Clock

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

# Sort key for single-row aggregate items (usage/adoption) on the composite-key table.
_AGG_SK = "agg"


def period_key(definition: str, clock: Clock) -> str:
    """Compute the current period key (ENT-011/ENT-014) from the clock.

    ``day`` → ISO date; ``week`` → ISO year-week. Any other value falls back to ISO date.
    """
    now = clock.now()
    if definition == "week":
        iso = now.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return now.date().isoformat()


class DynamoOperationalData:
    """DynamoDB-backed :class:`OperationalDataService`."""

    def __init__(self, table: Table, clock: Clock, period_definition: str = "day") -> None:
        self._table = table
        self._clock = clock
        self._period_definition = period_definition

    def _period(self) -> str:
        return period_key(self._period_definition, self._clock)

    # -- cost guardrail (BR-008) --------------------------------------------

    def within_budget(self, guardrail: GuardrailConfig) -> bool:
        response = self._table.get_item(Key={"pk": f"usage#{self._period()}", "sk": _AGG_SK})
        item = response.get("Item")
        usage = int(item["usage_count"]) if item and "usage_count" in item else 0  # type: ignore[arg-type]
        return is_within_budget(usage, guardrail.per_period_limit, guardrail.per_request_limit)

    def record_usage(self, token_usage: int) -> None:
        """BR-019 — atomic increment of the per-period usage counter."""
        self._table.update_item(
            Key={"pk": f"usage#{self._period()}", "sk": _AGG_SK},
            UpdateExpression="ADD usage_count :u SET last_updated_at = :now",
            ExpressionAttributeValues={":u": token_usage, ":now": self._clock.now().isoformat()},
        )

    def record_adoption(self, author_id: str) -> None:
        """BR-019/FR-18 — record a resolved question for the period's adoption metric."""
        self._table.update_item(
            Key={"pk": f"adoption#{self._period()}", "sk": _AGG_SK},
            UpdateExpression="ADD developer_ids :d, questions_handled :one",
            ExpressionAttributeValues={":d": {author_id}, ":one": 1},
        )

    # -- feedback append-only (BR-020) --------------------------------------

    def record_feedback(self, signal: FeedbackSignal) -> None:
        """API-INT-007 — append an immutable feedback row (never update/delete)."""
        sort_key = (
            f"{signal.recorded_at.isoformat()}#{signal.reactor_id}#"
            f"{signal.signal.value}#{uuid.uuid4()}"
        )
        self._table.put_item(
            Item={
                "pk": f"feedback#{signal.answer_ref}",
                "sk": sort_key,
                "answer_ref": str(signal.answer_ref),
                "reactor_id": signal.reactor_id,
                "signal": signal.signal.value,
                "event_action": signal.event_action.value,
                "recorded_at": signal.recorded_at.isoformat(),
            }
        )

    def feedback_tally(self, answer_ref: uuid.UUID) -> dict[ReactionKind, int]:
        """Aggregate net positive/negative reactors for an answer (BR-020/F-1)."""
        response = self._table.query(KeyConditionExpression=Key("pk").eq(f"feedback#{answer_ref}"))
        rows = [self._to_feedback(dict(item)) for item in response.get("Items", [])]
        return aggregate_feedback(rows)

    @staticmethod
    def _to_feedback(item: dict[str, object]) -> FeedbackSignal:
        from datetime import datetime

        from ...domain.enums import EventAction

        return FeedbackSignal(
            answer_ref=uuid.UUID(str(item["answer_ref"])),
            signal=ReactionKind(str(item["signal"])),
            recorded_at=datetime.fromisoformat(str(item["recorded_at"])),
            reactor_id=str(item["reactor_id"]),
            event_action=EventAction(str(item["event_action"])),
        )
