"""Bounded-context tests for the DynamoDB adapters (Slice 5) — moto + injected clock."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from slack_devops_agent.components.config import DynamoConfigStore
from slack_devops_agent.components.jobs import DynamoJobCoordinator
from slack_devops_agent.components.opdata import DynamoOperationalData
from slack_devops_agent.domain.entities import (
    FeedbackSignal,
    GuardrailConfig,
    OriginatingMessageRef,
)
from slack_devops_agent.domain.enums import EventAction, JobStatus, ReactionKind

from .conftest import FakeClock


def _coord(job_table: object) -> DynamoJobCoordinator:
    return DynamoJobCoordinator(table=job_table, answer_ts_gsi="answer-ts-index")  # type: ignore[arg-type]


def _ref() -> OriginatingMessageRef:
    return OriginatingMessageRef(
        channel_id="C1", thread_ts=None, message_ts="111.1", author_id="U1"
    )


# --- CMP-006 dedup (BR-010/F1) --------------------------------------------


def test_register_is_idempotent_per_identity(job_table: object, clock: FakeClock) -> None:
    coord = _coord(job_table)
    identity = ("C1", "111.1")
    job1, created1 = coord.register_or_get(identity, _ref(), uuid4(), clock.now())
    job2, created2 = coord.register_or_get(identity, _ref(), uuid4(), clock.now())
    assert created1 is True
    assert created2 is False
    assert job1.job_id == job2.job_id  # the second delivery attaches to the existing job
    assert job2.status == JobStatus.SEEN
    # DEFECT-1: author_id is persisted durably and read back (FR-18/BR-019 attribution).
    assert job2.originating_message_ref.author_id == "U1"


# --- CMP-006 single-winner lease (BR-027) ---------------------------------


def test_acquire_lease_is_single_winner(job_table: object, clock: FakeClock) -> None:
    coord = _coord(job_table)
    identity = ("C1", "111.1")
    coord.register_or_get(identity, _ref(), uuid4(), clock.now())
    first = coord.acquire_lease(identity, clock.now(), staleness_seconds=90)
    # second acquire: job now in-progress and NOT stale => must lose
    second = coord.acquire_lease(identity, clock.now(), staleness_seconds=90)
    assert first is not None
    assert first.status == JobStatus.IN_PROGRESS
    assert first.attempt_count == 1
    assert second is None


def test_terminal_job_cannot_be_leased(job_table: object, clock: FakeClock) -> None:
    coord = _coord(job_table)
    identity = ("C1", "111.1")
    coord.register_or_get(identity, _ref(), uuid4(), clock.now())
    coord.acquire_lease(identity, clock.now(), staleness_seconds=90)
    coord.transition(identity, JobStatus.RESOLVED, clock.now())
    assert coord.acquire_lease(identity, clock.now(), staleness_seconds=90) is None


# --- CMP-006 recovery 90s inclusive boundary (BR-021/F5/NFR-19) -----------


def test_recovery_uses_inclusive_90s_boundary(job_table: object, clock: FakeClock) -> None:
    coord = _coord(job_table)
    identity = ("C1", "111.1")
    coord.register_or_get(identity, _ref(), uuid4(), clock.now())
    coord.acquire_lease(identity, clock.now(), staleness_seconds=90)  # in-progress at T0

    # 89s later: not yet stale.
    near = clock.now() + timedelta(seconds=89)
    assert coord.find_stale_jobs(near, staleness_seconds=90) == []

    # Exactly 90s later: reclaimable (inclusive >=).
    at90 = clock.now() + timedelta(seconds=90)
    stale = coord.find_stale_jobs(at90, staleness_seconds=90)
    assert len(stale) == 1
    assert stale[0].slack_event_identity == identity

    # The stale in-progress job can be reclaimed (attempt++); a live one could not.
    reclaimed = coord.acquire_lease(identity, at90, staleness_seconds=90)
    assert reclaimed is not None
    assert reclaimed.attempt_count == 2


# --- CMP-006 F8 answer-ts → correlation-id (BR-018) -----------------------


def test_stamp_and_resolve_answer_ts(job_table: object, clock: FakeClock) -> None:
    coord = _coord(job_table)
    identity = ("C1", "111.1")
    job, _ = coord.register_or_get(identity, _ref(), uuid4(), clock.now())
    coord.stamp_answer_ts(identity, "999.9")
    resolved = coord.resolve_answer_ts("999.9")
    assert resolved == job.job_id
    assert coord.resolve_answer_ts("nope") is None


# --- CMP-006 BR-027 pre-post intent marker --------------------------------


def test_mark_post_intent_is_idempotent(job_table: object, clock: FakeClock) -> None:
    coord = _coord(job_table)
    identity = ("C1", "111.1")
    coord.register_or_get(identity, _ref(), uuid4(), clock.now())
    assert coord.get(identity).post_intent_at is None  # type: ignore[union-attr]

    coord.mark_post_intent(identity, clock.now())
    first = coord.get(identity).post_intent_at  # type: ignore[union-attr]
    assert first is not None
    assert coord.get(identity).post_attempted is True  # type: ignore[union-attr]

    # a second mark (e.g. a reclaiming worker) must not overwrite the first attempt's marker.
    coord.mark_post_intent(identity, clock.now() + timedelta(seconds=120))
    assert coord.get(identity).post_intent_at == first  # type: ignore[union-attr]


# --- CMP-007 atomic usage + budget (BR-008/BR-019) ------------------------


def test_usage_counter_is_atomic_and_budget_decides(opdata_table: object, clock: FakeClock) -> None:
    svc = DynamoOperationalData(table=opdata_table, clock=clock, period_definition="day")  # type: ignore[arg-type]
    guardrail = GuardrailConfig(per_period_limit=100)
    assert svc.within_budget(guardrail) is True
    for _ in range(10):
        svc.record_usage(10)  # 10 concurrent-style increments of 10 => 100
    assert svc.within_budget(guardrail) is False  # usage 100 >= limit 100


def test_adoption_records_distinct_developers(opdata_table: object, clock: FakeClock) -> None:
    svc = DynamoOperationalData(table=opdata_table, clock=clock, period_definition="day")  # type: ignore[arg-type]
    svc.record_adoption("U1")
    svc.record_adoption("U1")
    svc.record_adoption("U2")
    item = opdata_table.get_item(  # type: ignore[attr-defined]
        Key={"pk": f"adoption#{clock.now().date().isoformat()}", "sk": "agg"}
    )["Item"]
    assert int(item["questions_handled"]) == 3
    assert set(item["developer_ids"]) == {"U1", "U2"}


# --- CMP-007 append-only feedback + F-1 aggregation (BR-020) --------------


def test_feedback_append_only_and_withdrawal_aggregation(
    opdata_table: object, clock: FakeClock
) -> None:
    svc = DynamoOperationalData(table=opdata_table, clock=clock, period_definition="day")  # type: ignore[arg-type]
    answer_ref = uuid4()
    base = clock.now()

    def fb(signal: ReactionKind, action: EventAction, secs: int) -> FeedbackSignal:
        return FeedbackSignal(
            answer_ref=answer_ref,
            signal=signal,
            recorded_at=base + timedelta(seconds=secs),
            reactor_id="U9",
            event_action=action,
        )

    svc.record_feedback(fb(ReactionKind.POSITIVE, EventAction.ADDED, 0))
    svc.record_feedback(fb(ReactionKind.NEGATIVE, EventAction.ADDED, 1))
    svc.record_feedback(fb(ReactionKind.NEGATIVE, EventAction.REMOVED, 2))
    tally = svc.feedback_tally(answer_ref)
    # withdrawn 👎 must not erase the still-present 👍
    assert tally[ReactionKind.POSITIVE] == 1
    assert tally[ReactionKind.NEGATIVE] == 0


# --- CMP-008 config read + fail-safe defaults (BR-024/F-3) ----------------


def test_config_failsafe_defaults_when_unset(config_table: object) -> None:
    store = DynamoConfigStore(table=config_table)  # type: ignore[arg-type]
    allow = store.get_allowlist()
    assert allow.allowed_channel_ids == []
    assert allow.non_allowlisted_behaviour.value == "reply-not-designated"  # F-3 default
    assert store.get_guardrail().per_period_limit == 500
    assert "secrets" in store.get_usage_policy().policy_text.lower()


def test_config_reads_operator_values(config_table: object) -> None:
    config_table.put_item(  # type: ignore[attr-defined]
        Item={
            "pk": "allowlist",
            "allowed_channel_ids": ["C1", "C2"],
            "non_allowlisted_behaviour": "silent",
        }
    )
    store = DynamoConfigStore(table=config_table)  # type: ignore[arg-type]
    allow = store.get_allowlist()
    assert allow.allowed_channel_ids == ["C1", "C2"]
    assert allow.non_allowlisted_behaviour.value == "silent"
