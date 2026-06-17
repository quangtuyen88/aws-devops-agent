"""Tests for NFR-11 heartbeat — the emitter behaviour and its worker-pipeline wiring."""

from __future__ import annotations

import io
import threading
import time
from contextlib import AbstractContextManager
from types import TracebackType
from uuid import uuid4

from slack_devops_agent.components.worker import (
    DefaultAnswerComposer,
    HeartbeatEmitter,
    Worker,
    WorkerConfig,
    WorkerOutcome,
)
from slack_devops_agent.components.worker.rendering import HEARTBEAT_TEXT
from slack_devops_agent.domain.entities import OriginatingMessageRef, ThreadMessage
from slack_devops_agent.observability.metrics import Metrics

from .conftest import FakeClock
from .fakes import (
    FakeConfigStore,
    FakeGrounding,
    FakeInference,
    FakeJobCoordinator,
    FakeOperationalData,
    FakeSafety,
    FakeSlackGateway,
)

IDENTITY = ("C1", "111.1")
_REF = OriginatingMessageRef(channel_id="C1", thread_ts=None, message_ts="111.1", author_id="U1")


# --- emitter unit behaviour ------------------------------------------------


def test_beat_posts_heartbeat_text_and_counts() -> None:
    slack = FakeSlackGateway()
    metrics = Metrics(stream=io.StringIO())
    emitter = HeartbeatEmitter(slack, _REF, interval_seconds=15.0, metrics=metrics)
    emitter._beat()
    assert slack.posts == [(_REF, HEARTBEAT_TEXT)]
    assert emitter.beats == 1


def test_beat_swallows_post_failure() -> None:
    slack = FakeSlackGateway()
    slack.fail_on_post = True
    emitter = HeartbeatEmitter(slack, _REF, interval_seconds=15.0)
    # a failing Slack post must NOT raise — heartbeat is best-effort progress UX.
    emitter._beat()
    assert emitter.beats == 0


def test_emitter_thread_emits_then_stops() -> None:
    """With a tiny interval the background timer emits, and stop() halts further beats."""
    slack = FakeSlackGateway()
    emitter = HeartbeatEmitter(slack, _REF, interval_seconds=0.01)
    with emitter:
        time.sleep(0.06)  # allow several intervals to elapse
    beats_at_stop = emitter.beats
    assert beats_at_stop >= 1
    assert all(text == HEARTBEAT_TEXT for _, text in slack.posts)
    # after the context exits, the timer thread is stopped and no longer beats.
    time.sleep(0.03)
    assert emitter.beats == beats_at_stop


def test_long_interval_does_not_beat_for_a_fast_block() -> None:
    """A pipeline that finishes well inside the interval produces zero heartbeats."""
    slack = FakeSlackGateway()
    emitter = HeartbeatEmitter(slack, _REF, interval_seconds=15.0)
    with emitter:
        pass  # returns immediately
    assert emitter.beats == 0
    assert slack.posts == []


# --- worker wiring ---------------------------------------------------------


class _RecordingHeartbeat(AbstractContextManager["_RecordingHeartbeat"]):
    """A fake heartbeat that records enter/exit and emits one beat on entry."""

    def __init__(self, slack: FakeSlackGateway, ref: OriginatingMessageRef) -> None:
        self._slack = slack
        self._ref = ref
        self.entered = False
        self.exited = False

    def __enter__(self) -> _RecordingHeartbeat:
        self.entered = True
        self._slack.post_message(self._ref, HEARTBEAT_TEXT)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.exited = True


def _build_worker(
    jobs: FakeJobCoordinator, clock: FakeClock, slack: FakeSlackGateway, factory: object
) -> Worker:
    return Worker(
        jobs=jobs,
        slack=slack,
        safety=FakeSafety(),
        inference=FakeInference(output="Recommendation: use 3 AZs."),
        grounding=FakeGrounding(),
        opdata=FakeOperationalData(),
        config_store=FakeConfigStore(["C1"]),
        composer=DefaultAnswerComposer(),
        clock=clock,
        metrics=Metrics(stream=io.StringIO()),
        config=WorkerConfig(),
        heartbeat_factory=factory,  # type: ignore[arg-type]
    )


def test_worker_starts_and_stops_heartbeat_around_pipeline() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    ref = _REF
    jobs.register_or_get(IDENTITY, ref, uuid4(), clock.now())
    slack = FakeSlackGateway(
        thread=[ThreadMessage(author_id="U1", text="how many AZs?", ts="111.1")]
    )
    recorder: dict[str, _RecordingHeartbeat] = {}

    def factory(r: OriginatingMessageRef) -> _RecordingHeartbeat:
        hb = _RecordingHeartbeat(slack, r)
        recorder["hb"] = hb
        return hb

    worker = _build_worker(jobs, clock, slack, factory)
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.RESOLVED
    hb = recorder["hb"]
    assert hb.entered is True
    assert hb.exited is True  # stopped on the success path
    # the heartbeat emitted in-thread alongside the final answer
    assert any(text == HEARTBEAT_TEXT for _, text in slack.posts)


def test_default_heartbeat_is_real_emitter_and_is_silent_for_fast_jobs() -> None:
    """No injected factory → the worker uses the real thread emitter; a fast job is silent."""
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    jobs.register_or_get(IDENTITY, _REF, uuid4(), clock.now())
    slack = FakeSlackGateway(
        thread=[ThreadMessage(author_id="U1", text="how many AZs?", ts="111.1")]
    )
    worker = Worker(
        jobs=jobs,
        slack=slack,
        safety=FakeSafety(),
        inference=FakeInference(output="Recommendation: use 3 AZs."),
        grounding=FakeGrounding(),
        opdata=FakeOperationalData(),
        config_store=FakeConfigStore(["C1"]),
        composer=DefaultAnswerComposer(),
        clock=clock,
        metrics=Metrics(stream=io.StringIO()),
        config=WorkerConfig(heartbeat_seconds=15.0),
    )
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.RESOLVED
    # only the answer was posted (heartbeat interval far exceeds the fast in-memory pipeline)
    assert all("hourglass" not in text for _, text in slack.posts)
    # no lingering heartbeat threads
    assert not any(t.name == "worker-heartbeat" for t in threading.enumerate())
