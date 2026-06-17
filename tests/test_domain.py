"""Unit tests for the domain layer (Slice 1): entities, FSM, business rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from slack_devops_agent.domain import rules
from slack_devops_agent.domain.entities import (
    Answer,
    ChannelAllowlist,
    FeedbackSignal,
    GroundingSource,
    GuardrailConfig,
    InboundMention,
    OriginatingMessageRef,
    ProcessingJob,
    SafetyVerdict,
)
from slack_devops_agent.domain.enums import (
    AnswerType,
    EventAction,
    JobStatus,
    NonAllowlistedBehaviour,
    ReactionKind,
    SafetyAction,
)
from slack_devops_agent.domain.state_machine import (
    IllegalTransitionError,
    assert_transition,
    can_transition,
)

NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=UTC)


def _mention(**kw: object) -> InboundMention:
    base: dict[str, object] = {
        "correlation_id": uuid4(),
        "channel_id": "C1",
        "message_ts": "111.1",
        "author_id": "U1",
        "raw_text": "<@U0BOT> how do I size an ASG?",
    }
    base.update(kw)
    return InboundMention(**base)  # type: ignore[arg-type]


def _job(status: JobStatus = JobStatus.SEEN, **kw: object) -> ProcessingJob:
    base: dict[str, object] = {
        "job_id": uuid4(),
        "channel_id": "C1",
        "message_ts": "111.1",
        "originating_message_ref": OriginatingMessageRef(
            channel_id="C1", message_ts="111.1", author_id="U1"
        ),
        "status": status,
        "attempt_count": 0,
        "last_transition_at": NOW,
    }
    base.update(kw)
    return ProcessingJob(**base)  # type: ignore[arg-type]


# --- FSM (ENT-008, Q2=b) ---------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target", "ok"),
    [
        (JobStatus.SEEN, JobStatus.IN_PROGRESS, True),
        (JobStatus.SEEN, JobStatus.FAILED, True),
        (JobStatus.SEEN, JobStatus.RESOLVED, False),
        (JobStatus.IN_PROGRESS, JobStatus.RESOLVED, True),
        (JobStatus.IN_PROGRESS, JobStatus.IN_PROGRESS, True),
        (JobStatus.IN_PROGRESS, JobStatus.FAILED, True),
        (JobStatus.RESOLVED, JobStatus.IN_PROGRESS, False),
        (JobStatus.FAILED, JobStatus.IN_PROGRESS, False),
    ],
)
def test_fsm_transitions(current: JobStatus, target: JobStatus, ok: bool) -> None:
    assert can_transition(current, target) is ok


def test_terminal_states_have_no_exit() -> None:
    assert JobStatus.RESOLVED.is_terminal
    assert JobStatus.FAILED.is_terminal
    with pytest.raises(IllegalTransitionError):
        assert_transition(JobStatus.RESOLVED, JobStatus.FAILED)


# --- BR-001 / BR-002 -------------------------------------------------------


def test_channel_allowlist_and_bot_filter() -> None:
    allow = ChannelAllowlist(allowed_channel_ids=["C1"])
    assert rules.is_channel_allowed(_mention(channel_id="C1"), allow)
    assert not rules.is_channel_allowed(_mention(channel_id="C2"), allow)
    assert rules.is_bot_authored(_mention(is_bot_author=True))


def test_non_allowlisted_default_replies() -> None:
    allow = ChannelAllowlist(allowed_channel_ids=["C1"])
    assert allow.non_allowlisted_behaviour == NonAllowlistedBehaviour.REPLY_NOT_DESIGNATED
    assert rules.should_reply_not_designated(allow)


# --- BR-010 / BR-011 / BR-021 / BR-022 (dedup, recovery) -------------------


def test_should_process_existing_respects_terminal() -> None:
    assert rules.should_process_existing(_job(JobStatus.SEEN))
    assert rules.should_process_existing(_job(JobStatus.IN_PROGRESS))
    assert not rules.should_process_existing(_job(JobStatus.RESOLVED))
    assert not rules.should_process_existing(_job(JobStatus.FAILED))


def test_lease_staleness_is_inclusive_90s() -> None:
    # F5/NFR-19: inclusive >= boundary. Exactly 90s old => reclaimable.
    job = _job(JobStatus.IN_PROGRESS, last_transition_at=NOW - timedelta(seconds=90))
    assert rules.is_lease_stale(job, NOW, 90)
    fresh = _job(JobStatus.IN_PROGRESS, last_transition_at=NOW - timedelta(seconds=89))
    assert not rules.is_lease_stale(fresh, NOW, 90)
    # never reclaim a terminal job
    done = _job(JobStatus.RESOLVED, last_transition_at=NOW - timedelta(seconds=999))
    assert not rules.is_lease_stale(done, NOW, 90)


def test_attempts_exhausted() -> None:
    assert rules.attempts_exhausted(_job(attempt_count=3), 3)
    assert not rules.attempts_exhausted(_job(attempt_count=2), 3)


# --- BR-007 / NFR-14 size ---------------------------------------------------


def test_size_budget_and_question_overflow() -> None:
    assert rules.within_size_budget("a" * 40, max_input_tokens=20)  # ~10 tokens
    assert not rules.within_size_budget("a" * 400, max_input_tokens=20)
    assert rules.question_alone_overflows("a" * 400, max_input_tokens=20)
    assert not rules.question_alone_overflows("a" * 40, max_input_tokens=20)


# --- BR-008 budget ----------------------------------------------------------


def test_within_budget() -> None:
    assert rules.is_within_budget(usage_count=10, per_period_limit=500)
    assert not rules.is_within_budget(usage_count=500, per_period_limit=500)
    assert rules.is_within_budget(usage_count=0, per_period_limit=None)


# --- BR-012 safety gate -----------------------------------------------------


def test_safety_gate_decisions() -> None:
    refuse = SafetyVerdict(flagged=True, recommended_action=SafetyAction.REFUSE)
    warn = SafetyVerdict(flagged=True, recommended_action=SafetyAction.WARN)
    allow = SafetyVerdict(flagged=False, recommended_action=SafetyAction.ALLOW)
    assert rules.safety_blocks_forward(refuse)
    assert not rules.safety_blocks_forward(allow)
    assert rules.safety_requires_warning(warn)


# --- BR-014 cap -------------------------------------------------------------


def test_loop_cap() -> None:
    assert rules.loop_cap_reached(2, 0, max_inf=2, max_mcp=5)
    assert rules.loop_cap_reached(0, 5, max_inf=2, max_mcp=5)
    assert not rules.loop_cap_reached(1, 4, max_inf=2, max_mcp=5)


# --- BR-015 classification + answer structure -------------------------------


def test_classify_and_answer_structure() -> None:
    assert rules.classify_answer_type("Please review my architecture") == (
        AnswerType.ARCHITECTURE_REVIEW
    )
    assert rules.classify_answer_type("what is the price of S3") == AnswerType.COST
    assert rules.classify_answer_type("random text") == AnswerType.FACTUAL


def test_arch_review_answer_requires_trade_offs() -> None:
    with pytest.raises(ValidationError):
        Answer(
            correlation_id=uuid4(),
            answer_type=AnswerType.ARCHITECTURE_REVIEW,
            recommendation="use 3 AZs",
            rationale="resilience",
        )
    ok = Answer(
        correlation_id=uuid4(),
        answer_type=AnswerType.ARCHITECTURE_REVIEW,
        recommendation="use 3 AZs",
        rationale="resilience",
        trade_offs="cost vs availability",
    )
    assert ok.answer_type.requires_trade_offs


def test_grounding_citation_consistency_br016() -> None:
    src = GroundingSource(title="t", url="https://x", tool_name="documentation-search")
    with pytest.raises(ValidationError):
        Answer(
            correlation_id=uuid4(),
            recommendation="r",
            rationale="ra",
            is_grounded=True,
            citations=[],
        )
    with pytest.raises(ValidationError):
        Answer(
            correlation_id=uuid4(),
            recommendation="r",
            rationale="ra",
            is_grounded=False,
            citations=[src],
        )
    grounded = Answer(
        correlation_id=uuid4(),
        recommendation="r",
        rationale="ra",
        is_grounded=True,
        citations=[src],
    )
    assert grounded.is_grounded


# --- BR-020 / F-1 feedback aggregation --------------------------------------


def _fb(
    signal: ReactionKind, action: EventAction, secs: int, reactor: str = "U9"
) -> FeedbackSignal:
    return FeedbackSignal(
        answer_ref=uuid4(),
        signal=signal,
        recorded_at=NOW + timedelta(seconds=secs),
        reactor_id=reactor,
        event_action=action,
    )


def test_withdrawn_thumbsdown_keeps_present_thumbsup() -> None:
    rows = [
        _fb(ReactionKind.POSITIVE, EventAction.ADDED, 0),
        _fb(ReactionKind.NEGATIVE, EventAction.ADDED, 1),
        _fb(ReactionKind.NEGATIVE, EventAction.REMOVED, 2),
    ]
    assert rules.net_reactor_signal(rows) == ReactionKind.POSITIVE


def test_simple_reversal_up_to_down() -> None:
    rows = [
        _fb(ReactionKind.POSITIVE, EventAction.ADDED, 0),
        _fb(ReactionKind.POSITIVE, EventAction.REMOVED, 1),
        _fb(ReactionKind.NEGATIVE, EventAction.ADDED, 2),
    ]
    assert rules.net_reactor_signal(rows) == ReactionKind.NEGATIVE


def test_aggregate_feedback_counts_distinct_reactors() -> None:
    aref = uuid4()
    rows = [
        FeedbackSignal(
            answer_ref=aref,
            signal=ReactionKind.POSITIVE,
            recorded_at=NOW,
            reactor_id="A",
            event_action=EventAction.ADDED,
        ),
        FeedbackSignal(
            answer_ref=aref,
            signal=ReactionKind.POSITIVE,
            recorded_at=NOW,
            reactor_id="B",
            event_action=EventAction.ADDED,
        ),
        FeedbackSignal(
            answer_ref=aref,
            signal=ReactionKind.NEGATIVE,
            recorded_at=NOW,
            reactor_id="C",
            event_action=EventAction.ADDED,
        ),
    ]
    tally = rules.aggregate_feedback(rows)
    assert tally[ReactionKind.POSITIVE] == 2
    assert tally[ReactionKind.NEGATIVE] == 1


def test_guardrail_requires_a_limit() -> None:
    with pytest.raises(ValidationError):
        GuardrailConfig(period_definition="day")
    assert GuardrailConfig(per_period_limit=500).per_period_limit == 500
