"""Tests for CMP-002 worker pipeline (Slice 7) — W2/W3, CS-4 ordering, caps, recovery."""

from __future__ import annotations

import io
from uuid import uuid4

from slack_devops_agent.components.worker import (
    DefaultAnswerComposer,
    Worker,
    WorkerConfig,
    WorkerOutcome,
)
from slack_devops_agent.domain.entities import GroundingSource, OriginatingMessageRef, ThreadMessage
from slack_devops_agent.domain.enums import JobStatus, SafetyAction
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


def _seed_job(
    jobs: FakeJobCoordinator,
    clock: FakeClock,
    *,
    file_name: str | None = None,
    file_text: str | None = None,
) -> None:
    ref = OriginatingMessageRef(channel_id="C1", thread_ts=None, message_ts="111.1", author_id="U1")
    jobs.register_or_get(
        IDENTITY,
        ref,
        uuid4(),
        clock.now(),
        attached_file_name=file_name,
        attached_file_text=file_text,
    )


def _worker(
    *,
    jobs: FakeJobCoordinator,
    clock: FakeClock,
    slack: FakeSlackGateway | None = None,
    safety: FakeSafety | None = None,
    inference: FakeInference | None = None,
    grounding: FakeGrounding | None = None,
    opdata: FakeOperationalData | None = None,
    config: WorkerConfig | None = None,
) -> tuple[Worker, dict[str, object]]:
    slack = slack or FakeSlackGateway(
        thread=[ThreadMessage(author_id="U1", text="How many AZs should I use?", ts="111.1")]
    )
    inference = inference or FakeInference(
        output="Recommendation: use 3 AZs.\nRationale: resilience."
    )
    grounding = grounding or FakeGrounding()
    opdata = opdata or FakeOperationalData()
    worker = Worker(
        jobs=jobs,
        slack=slack,
        safety=safety or FakeSafety(),
        inference=inference,
        grounding=grounding,
        opdata=opdata,
        config_store=FakeConfigStore(["C1"]),
        composer=DefaultAnswerComposer(),
        clock=clock,
        metrics=Metrics(stream=io.StringIO()),
        config=config or WorkerConfig(),
    )
    return worker, {
        "slack": slack,
        "inference": inference,
        "grounding": grounding,
        "opdata": opdata,
    }


def test_happy_path_resolves_and_posts_ungrounded() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    worker, deps = _worker(jobs=jobs, clock=clock)
    outcome = worker.process(IDENTITY, uuid4(), "U1")
    assert outcome == WorkerOutcome.RESOLVED
    assert jobs.get(IDENTITY).status == JobStatus.RESOLVED  # type: ignore[union-attr]
    slack = deps["slack"]
    assert any("Recommendation" in t for _, t in slack.posts)  # type: ignore[attr-defined]
    assert deps["opdata"].usage == 50  # type: ignore[attr-defined]
    # DEFECT-1/FR-18/BR-019: adoption is attributed to the developer (author_id), not channel
    assert deps["opdata"].adoptions == ["U1"]  # type: ignore[attr-defined]
    # F8: answer ts stamped for later reaction resolution
    assert jobs.get(IDENTITY).answer_message_ts is not None  # type: ignore[union-attr]
    # Guardrail: the operator system prompt is sent on the inference call (scope/PII/injection)
    assert "architecture" in (deps["inference"].last_system or "").lower()  # type: ignore[attr-defined]


def test_grounded_answer_carries_citations() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    grounding = FakeGrounding(
        [
            GroundingSource(
                title="VPC docs", url="https://docs.aws/vpc", tool_name="documentation-search"
            )
        ]
    )
    worker, deps = _worker(jobs=jobs, clock=clock, grounding=grounding)
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.RESOLVED
    assert any("Sources:" in t for _, t in deps["slack"].posts)  # type: ignore[attr-defined]


def test_safety_refuse_blocks_inference_and_fails() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    inference = FakeInference()
    worker, deps = _worker(
        jobs=jobs, clock=clock, safety=FakeSafety(SafetyAction.REFUSE), inference=inference
    )
    outcome = worker.process(IDENTITY, uuid4(), "U1")
    assert outcome == WorkerOutcome.FAILED
    assert jobs.get(IDENTITY).status == JobStatus.FAILED  # type: ignore[union-attr]
    # CS-4: a refuse verdict must block any inference call (NFR-4 invariant)
    assert inference.calls == 0
    assert any("secret" in t.lower() for _, t in deps["slack"].posts)  # type: ignore[attr-defined]


def test_attached_file_text_reaches_inference_prompt() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(
        jobs,
        clock,
        file_name="explore-s3.yaml",
        file_text="AWSTemplateFormatVersion: 2010-09-09",
    )
    inference = FakeInference()
    worker, _ = _worker(jobs=jobs, clock=clock, inference=inference)
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.RESOLVED
    assert "ATTACHED FILE (explore-s3.yaml)" in (inference.last_prompt or "")
    assert "AWSTemplateFormatVersion" in (inference.last_prompt or "")


def test_attached_file_with_secret_is_refused_by_safety_gate() -> None:
    from slack_devops_agent.components.safety import SecretScanner

    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(
        jobs,
        clock,
        file_name="creds.tf",
        file_text='provider "aws" { access_key = "AKIAIOSFODNN7EXAMPLE" }',
    )
    inference = FakeInference()
    worker, _ = _worker(jobs=jobs, clock=clock, safety=SecretScanner(), inference=inference)
    outcome = worker.process(IDENTITY, uuid4(), "U1")
    assert outcome == WorkerOutcome.FAILED
    # The secret inside the uploaded file must block inference (never forwarded to the gateway).
    assert inference.calls == 0


def test_budget_deny_fails_with_reask_message() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    worker, deps = _worker(jobs=jobs, clock=clock, opdata=FakeOperationalData(within=False))
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.FAILED
    assert any("budget" in t.lower() for _, t in deps["slack"].posts)  # type: ignore[attr-defined]


def test_oversize_question_alone_is_rejected() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    big = "x" * 1000
    slack = FakeSlackGateway(thread=[ThreadMessage(author_id="U1", text=big, ts="111.1")])
    worker, deps = _worker(
        jobs=jobs, clock=clock, slack=slack, config=WorkerConfig(max_input_tokens=10)
    )
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.FAILED
    assert any("too large" in t.lower() for _, t in deps["slack"].posts)  # type: ignore[attr-defined]


def test_oversize_thread_trims_with_in_thread_notice_br007() -> None:
    """DEFECT-2/BR-007/NFR-14: when only older context overflows, trim and post a notice."""
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    # Old context overflows the budget, but the current question alone fits → trim, not reject.
    slack = FakeSlackGateway(
        thread=[
            ThreadMessage(author_id="U1", text="x" * 400, ts="000.1"),
            ThreadMessage(author_id="U1", text="how many AZs?", ts="111.1"),
        ]
    )
    worker, deps = _worker(
        jobs=jobs, clock=clock, slack=slack, config=WorkerConfig(max_input_tokens=20)
    )
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.RESOLVED
    posts = deps["slack"].posts  # type: ignore[attr-defined]
    # never silent: an in-thread trim notice is posted before the answer
    assert any("trimmed" in t.lower() for _, t in posts)
    assert any("Recommendation" in t for _, t in posts)


def test_completed_job_is_skipped() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    jobs.acquire_lease(IDENTITY, clock.now(), 90)
    jobs.transition(IDENTITY, JobStatus.RESOLVED, clock.now())
    worker, _ = _worker(jobs=jobs, clock=clock)
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.SKIPPED_COMPLETE


def test_attempts_exhausted_abandons_to_failed() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    ref = OriginatingMessageRef(channel_id="C1", thread_ts=None, message_ts="111.1", author_id="U1")
    jobs.register_or_get(IDENTITY, ref, uuid4(), clock.now())
    # drive attempt_count to the limit via repeated stale reclaims
    for _ in range(3):
        clock.advance(90)
        jobs.acquire_lease(IDENTITY, clock.now(), 90)
    clock.advance(90)  # let the lease go stale so the next worker can reclaim
    worker, deps = _worker(jobs=jobs, clock=clock)
    # next process reclaims (attempt 4 > max 3) and must abandon to failed
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.FAILED
    assert jobs.get(IDENTITY).status == JobStatus.FAILED  # type: ignore[union-attr]


def test_reclaim_with_stamped_answer_does_not_repost_br027() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    # a prior attempt posted the answer (ts stamped) but crashed before resolving
    jobs.acquire_lease(IDENTITY, clock.now(), 90)
    jobs.stamp_answer_ts(IDENTITY, "already-posted-ts")
    clock.advance(90)  # lease goes stale -> a recovery worker reclaims
    worker, deps = _worker(jobs=jobs, clock=clock)
    outcome = worker.process(IDENTITY, uuid4(), "U1")
    assert outcome == WorkerOutcome.RESOLVED
    assert jobs.get(IDENTITY).status == JobStatus.RESOLVED  # type: ignore[union-attr]
    # BR-027: must NOT post a second answer
    assert deps["slack"].posts == []  # type: ignore[attr-defined]


def test_reclaim_with_only_post_intent_does_not_repost_br027() -> None:
    """BR-027 hardening (MINOR-b): a crash AFTER posting but BEFORE stamping answer-ts.

    The pre-post intent marker is stamped, the Slack post may have landed, but
    ``answer_message_ts`` was never written. A recovery-spawned worker MUST resolve the job
    without reposting — closing the repost window so no duplicate in-thread answer appears.
    """
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    jobs.acquire_lease(IDENTITY, clock.now(), 90)
    # simulate the crash window: intent stamped (+ Slack post landed) but ts stamp lost.
    jobs.mark_post_intent(IDENTITY, clock.now())
    assert jobs.get(IDENTITY).answer_message_ts is None  # type: ignore[union-attr]
    clock.advance(90)  # lease goes stale -> a recovery worker reclaims
    worker, deps = _worker(jobs=jobs, clock=clock)
    outcome = worker.process(IDENTITY, uuid4(), "U1")
    assert outcome == WorkerOutcome.RESOLVED
    assert jobs.get(IDENTITY).status == JobStatus.RESOLVED  # type: ignore[union-attr]
    # BR-027 hardening: must NOT repost despite the missing answer-ts.
    assert deps["slack"].posts == []  # type: ignore[attr-defined]


def test_happy_path_stamps_post_intent_before_resolving_br027() -> None:
    """The success path stamps the pre-post intent marker (ordered before the Slack post)."""
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    worker, _ = _worker(jobs=jobs, clock=clock)
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.RESOLVED
    job = jobs.get(IDENTITY)
    assert job is not None
    assert job.post_intent_at is not None
    assert job.answer_message_ts is not None
    assert job.post_attempted is True
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    # a previous worker took the lease then died
    jobs.acquire_lease(IDENTITY, clock.now(), 90)
    # 90s later (inclusive boundary) a recovery worker reclaims and completes
    clock.advance(90)
    worker, _ = _worker(jobs=jobs, clock=clock)
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.RESOLVED
    assert jobs.get(IDENTITY).attempt_count == 2  # type: ignore[union-attr]


def test_breaker_opens_after_threshold_and_fails_fast_without_calling_dependency() -> None:
    """A shared breaker per dependency (not one per call) actually trips (NFR-16)."""
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    identities = [("C1", "111.1"), ("C2", "111.1"), ("C3", "111.1")]
    for cid, ts in identities:
        ref = OriginatingMessageRef(channel_id=cid, thread_ts=None, message_ts=ts, author_id="U1")
        jobs.register_or_get((cid, ts), ref, uuid4(), clock.now())

    grounding = FakeGrounding(raises=True)
    worker, _ = _worker(
        jobs=jobs,
        clock=clock,
        grounding=grounding,
        config=WorkerConfig(breaker_failure_threshold=2, retry_max_attempts=0),
    )
    for identity in identities[:2]:
        assert worker.process(identity, uuid4(), "U1") == WorkerOutcome.FAILED
    assert grounding.calls == 2

    # breaker is now open: the third job must fail fast without calling the dependency again
    assert worker.process(identities[2], uuid4(), "U1") == WorkerOutcome.FAILED
    assert grounding.calls == 2


def test_retry_max_attempts_config_bounds_dependency_calls() -> None:
    jobs = FakeJobCoordinator()
    clock = FakeClock()
    _seed_job(jobs, clock)
    grounding = FakeGrounding(raises=True)
    worker, _ = _worker(
        jobs=jobs,
        clock=clock,
        grounding=grounding,
        config=WorkerConfig(retry_max_attempts=0, breaker_failure_threshold=100),
    )
    assert worker.process(IDENTITY, uuid4(), "U1") == WorkerOutcome.FAILED
    assert grounding.calls == 1
