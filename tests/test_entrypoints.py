"""Tests for Slice 8 — event dispatch, recovery reaper, and Lambda handlers."""

from __future__ import annotations

import io
import json
from uuid import uuid4

from slack_devops_agent.components.intake import IntakeHandler, IntakeOutcome
from slack_devops_agent.components.recovery import Reaper, ReaperAction
from slack_devops_agent.domain.entities import OriginatingMessageRef
from slack_devops_agent.domain.enums import JobStatus
from slack_devops_agent.entrypoints.dispatch import dispatch_slack_event, parse_sqs_record
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
IDENTITY = ("C1", "111.1")


def _intake() -> tuple[IntakeHandler, dict[str, object]]:
    jobs = FakeJobCoordinator()
    queue = FakeWorkQueue()
    slack = FakeSlackGateway()
    handler = IntakeHandler(
        config=FakeConfigStore(["C1"]),
        jobs=jobs,
        slack=slack,
        queue=queue,
        opdata=FakeOperationalData(),
        clock=FakeClock(),
        bot_user_id=BOT,
        metrics=Metrics(stream=io.StringIO()),
    )
    return handler, {"jobs": jobs, "queue": queue, "slack": slack}


# --- dispatch --------------------------------------------------------------


def test_dispatch_routes_mention() -> None:
    handler, deps = _intake()
    envelope = {
        "event": {
            "type": "app_mention",
            "channel": "C1",
            "user": "U1",
            "ts": "111.1",
            "text": f"<@{BOT}> how many AZs?",
        }
    }
    assert dispatch_slack_event(envelope, handler, BOT) == IntakeOutcome.ACCEPTED
    assert len(deps["queue"].enqueued) == 1  # type: ignore[attr-defined]


def test_dispatch_ignores_unknown_event() -> None:
    handler, _ = _intake()
    assert dispatch_slack_event({"event": {"type": "team_join"}}, handler, BOT) is None


def test_parse_sqs_record() -> None:
    cid = uuid4()
    body = json.dumps(
        {
            "job_id": str(cid),
            "channel_id": "C1",
            "message_ts": "111.1",
            "correlation_id": str(cid),
            "author_id": "U1",
        }
    )
    identity, correlation_id, author_id = parse_sqs_record(body)
    assert identity == IDENTITY
    assert correlation_id == cid
    assert author_id == "U1"


# --- reaper (F3/BR-021/BR-022) ---------------------------------------------


def _seed_inflight(jobs: FakeJobCoordinator, clock: FakeClock, attempts: int) -> None:
    ref = OriginatingMessageRef(channel_id="C1", thread_ts=None, message_ts="111.1", author_id="U1")
    jobs.register_or_get(IDENTITY, ref, uuid4(), clock.now())
    for _ in range(attempts):
        jobs.acquire_lease(IDENTITY, clock.now(), 90)


def test_reaper_requeues_retriable_stale_job() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_inflight(jobs, clock, attempts=1)
    queue = FakeWorkQueue()
    slack = FakeSlackGateway()
    reaper = Reaper(
        jobs=jobs, slack=slack, queue=queue, clock=clock, metrics=Metrics(stream=io.StringIO())
    )
    clock.advance(90)  # lease now stale (inclusive)
    actions = reaper.recover_stale()
    assert actions == [ReaperAction.REQUEUED]
    assert len(queue.enqueued) == 1


def test_reaper_abandons_exhausted_stale_job() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_inflight(jobs, clock, attempts=1)
    # bump attempt_count to the limit
    job = jobs.get(IDENTITY)
    jobs.jobs[IDENTITY] = job.model_copy(update={"attempt_count": 3})  # type: ignore[union-attr]
    slack = FakeSlackGateway()
    reaper = Reaper(
        jobs=jobs,
        slack=slack,
        queue=FakeWorkQueue(),
        clock=clock,
        metrics=Metrics(stream=io.StringIO()),
    )
    clock.advance(90)
    actions = reaper.recover_stale()
    assert actions == [ReaperAction.ABANDONED]
    assert jobs.get(IDENTITY).status == JobStatus.FAILED  # type: ignore[union-attr]
    assert slack.posts  # FR-17 message posted


def test_build_reaper_wires_from_settings() -> None:
    from slack_devops_agent.components.recovery import Reaper
    from slack_devops_agent.config.settings import Settings
    from slack_devops_agent.entrypoints import wiring

    settings = Settings(
        AWS_REGION="us-east-1",
        LEASE_STALENESS_SECONDS=42,
        MAX_ATTEMPTS=7,
        WORK_QUEUE_URL="https://sqs.example/q",
    )
    reaper = wiring.build_reaper(settings)
    assert isinstance(reaper, Reaper)
    assert reaper.staleness_seconds == 42
    assert reaper.max_attempts == 7


def test_reaper_drains_dead_letters() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_inflight(jobs, clock, attempts=1)
    slack = FakeSlackGateway()
    reaper = Reaper(
        jobs=jobs,
        slack=slack,
        queue=FakeWorkQueue(),
        clock=clock,
        metrics=Metrics(stream=io.StringIO()),
    )
    actions = reaper.drain_dead_letters([IDENTITY])
    assert actions == [ReaperAction.ABANDONED]
    assert jobs.get(IDENTITY).status == JobStatus.FAILED  # type: ignore[union-attr]
