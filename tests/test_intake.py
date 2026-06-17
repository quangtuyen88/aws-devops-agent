"""Tests for CMP-001 intake (W1) and feedback capture (W4) — Slice 6."""

from __future__ import annotations

import io
from uuid import uuid4

from slack_devops_agent.components.intake import (
    IntakeHandler,
    IntakeOutcome,
    parse_mention,
    parse_reaction,
)
from slack_devops_agent.domain.entities import InboundMention
from slack_devops_agent.domain.enums import EventAction, ReactionKind
from slack_devops_agent.observability.metrics import Metrics

from .conftest import FakeClock
from .fakes import (
    FakeConfigStore,
    FakeJobCoordinator,
    FakeOperationalData,
    FakeSlackGateway,
    FakeWorkQueue,
)

BOT = "U0BOT"


def _handler(allowed: list[str] | None = None) -> tuple[IntakeHandler, dict[str, object]]:
    config = FakeConfigStore(allowed if allowed is not None else ["C1"])
    jobs = FakeJobCoordinator()
    slack = FakeSlackGateway()
    queue = FakeWorkQueue()
    opdata = FakeOperationalData()
    handler = IntakeHandler(
        config=config,
        jobs=jobs,
        slack=slack,
        queue=queue,
        opdata=opdata,
        clock=FakeClock(),
        bot_user_id=BOT,
        metrics=Metrics(stream=io.StringIO()),
    )
    return handler, {"jobs": jobs, "slack": slack, "queue": queue, "opdata": opdata}


def _mention(text: str = f"<@{BOT}> how many AZs?", **kw: object) -> InboundMention:
    base: dict[str, object] = {
        "correlation_id": uuid4(),
        "channel_id": "C1",
        "message_ts": "111.1",
        "author_id": "U1",
        "raw_text": text,
    }
    base.update(kw)
    return InboundMention(**base)  # type: ignore[arg-type]


# --- parsing ---------------------------------------------------------------


def test_parse_mention_flags_bot_author() -> None:
    event = {"channel": "C1", "user": "U0BOT", "ts": "1.1", "text": "<@U0BOT> hi", "bot_id": "B1"}
    mention = parse_mention(event, bot_user_id=BOT)
    assert mention.is_bot_author


def test_parse_reaction_filters_non_thumbs() -> None:
    base = {"type": "reaction_added", "user": "U2", "item": {"type": "message", "ts": "9.9"}}
    assert parse_reaction({**base, "reaction": "+1"}).reaction_kind == ReactionKind.POSITIVE  # type: ignore[union-attr]
    assert parse_reaction({**base, "reaction": "tada"}) is None


# --- W1 outcomes -----------------------------------------------------------


def test_bot_authored_is_ignored() -> None:
    handler, _ = _handler()
    assert handler.handle_mention(_mention(is_bot_author=True)) == IntakeOutcome.IGNORED_BOT


def test_non_mention_is_ignored() -> None:
    handler, _ = _handler()
    assert handler.handle_mention(_mention(text="no mention here")) == (
        IntakeOutcome.IGNORED_NO_MENTION
    )


def test_non_allowlisted_replies_not_designated() -> None:
    handler, deps = _handler(allowed=["COTHER"])
    outcome = handler.handle_mention(_mention())
    assert outcome == IntakeOutcome.NOT_ALLOWLISTED
    slack = deps["slack"]
    assert any("designated" in text for _, text in slack.posts)  # type: ignore[attr-defined]
    assert deps["queue"].enqueued == []  # type: ignore[attr-defined]


def test_accepted_acks_and_enqueues() -> None:
    handler, deps = _handler()
    outcome = handler.handle_mention(_mention())
    assert outcome == IntakeOutcome.ACCEPTED
    assert len(deps["queue"].enqueued) == 1  # type: ignore[attr-defined]
    assert any("On it" in text for _, text in deps["slack"].posts)  # type: ignore[attr-defined]
    # DEFECT-1: author_id rides the C-1 message for adoption attribution (FR-18/BR-019)
    assert deps["queue"].enqueued[0][3] == "U1"  # type: ignore[attr-defined]


def test_redelivery_is_deduplicated() -> None:
    handler, deps = _handler()
    m1 = _mention()
    handler.handle_mention(m1)
    # same identity (channel+ts), new correlation id and a Slack retry
    m2 = _mention(slack_retry_num=1)
    assert handler.handle_mention(m2) == IntakeOutcome.DUPLICATE
    assert len(deps["queue"].enqueued) == 1  # type: ignore[attr-defined]  # not enqueued twice


def test_ack_failure_still_enqueues_br004_degrade() -> None:
    handler, deps = _handler()
    deps["slack"].fail_on_post = True  # type: ignore[attr-defined]
    outcome = handler.handle_mention(_mention())
    assert outcome == IntakeOutcome.ACCEPTED
    assert len(deps["queue"].enqueued) == 1  # type: ignore[attr-defined]


# --- W4 feedback -----------------------------------------------------------


def test_reaction_on_known_answer_is_recorded() -> None:
    handler, deps = _handler()
    jobs = deps["jobs"]
    # register a job and stamp an answer ts so resolution succeeds
    m = _mention()
    handler.handle_mention(m)
    jobs.stamp_answer_ts(m.slack_event_identity, "answer-ts-1")  # type: ignore[attr-defined]
    event = {
        "type": "reaction_added",
        "user": "U2",
        "reaction": "+1",
        "item": {"type": "message", "ts": "answer-ts-1"},
    }
    reaction = parse_reaction(event)
    assert reaction is not None
    assert handler.handle_reaction(reaction) == IntakeOutcome.FEEDBACK_RECORDED
    fb = deps["opdata"].feedback  # type: ignore[attr-defined]
    assert len(fb) == 1
    assert fb[0].signal == ReactionKind.POSITIVE
    assert fb[0].event_action == EventAction.ADDED


def test_reaction_on_unknown_message_is_ignored() -> None:
    handler, _ = _handler()
    event = {
        "type": "reaction_removed",
        "user": "U2",
        "reaction": "-1",
        "item": {"type": "message", "ts": "unknown-ts"},
    }
    reaction = parse_reaction(event)
    assert reaction is not None
    assert handler.handle_reaction(reaction) == IntakeOutcome.FEEDBACK_IGNORED
