"""CMP-002 — Agent Orchestrator / worker (W2 processing + W3 failure & recovery).

Drains a job off the C-1 queue and runs the CS-4-ordered pipeline under the CS-5 cap and
the NFR-17 time budget:

    completion re-check → single-winner lease → context fetch → size gate →
    **safety gate** → within-budget → agent loop (inference + MCP) → compose → post →
    record adoption → resolve.

Any terminal error (timeout, cap, budget-deny, oversize, safety-refuse, dependency,
exhausted retries) routes to W3: post a clear FR-17 message and resolve the job ``failed``
(BR-013) — never silence, never a dangling ack. The single-winner lease + idempotent post
(BR-027) guarantee at-most-once-*completed* so a recovery-spawned worker never double-posts.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from ...domain import rules
from ...domain.entities import GroundingSource, OriginatingMessageRef, ProcessingJob, ThreadMessage
from ...domain.enums import FailureCause, JobStatus
from ...observability.logging import get_logger
from ...observability.metrics import Metrics
from ...ports import (
    ConfigStore,
    GroundingClient,
    InferenceProvider,
    JobCoordinator,
    OperationalDataService,
    SafetyScanner,
    SlackGateway,
)
from ...resilience.backoff import BackoffPolicy, RetryableError, retry_call
from ...resilience.circuit_breaker import CircuitBreaker, CircuitOpenError
from ...resilience.clock import Clock
from ...resilience.time_budget import TimeBudget, TimeBudgetExceededError
from ..inference.provider import InferenceFailureError
from ..inference.system_prompt import GUARDRAIL_SYSTEM_PROMPT
from ..jobs import ClaimDecision, claim_and_guard
from .composer import DefaultAnswerComposer
from .heartbeat import HeartbeatEmitter
from .rendering import render_answer, render_failure

# BR-007/NFR-14 — posted in-thread when older context is trimmed so trimming is never silent.
_TRIM_NOTICE_TEXT = (
    "Heads up: this thread was long, so I trimmed the older context and answered from your "
    "most recent question. If I missed something, re-ask with the key details included."
)


class WorkerOutcome(StrEnum):
    """Observable result of processing one job (NFR-20)."""

    SKIPPED_COMPLETE = "skipped-complete"
    LEASE_LOST = "lease-lost"
    RESOLVED = "resolved"
    FAILED = "failed"


class _ProcessingError(Exception):
    """Internal: a terminal processing error carrying its FR-17 failure cause."""

    def __init__(self, cause: FailureCause, secret_classes: list[str] | None = None) -> None:
        super().__init__(cause.value)
        self.cause = cause
        self.secret_classes = secret_classes or []


@dataclass
class WorkerConfig:
    """Tunable worker bounds (sourced from :class:`Settings`)."""

    time_budget_seconds: float = 30.0
    lease_staleness_seconds: int = 90
    max_attempts: int = 3
    max_inference_calls: int = 2
    max_mcp_calls: int = 5
    max_input_tokens: int = 12000
    heartbeat_seconds: float = 15.0
    retry_base_ms: int = 500
    retry_max_attempts: int = 2
    retry_cap_ms: int = 8000
    breaker_failure_threshold: int = 5
    breaker_reset_seconds: float = 30.0


# A factory builds the heartbeat context manager for a given thread (injectable for tests).
HeartbeatFactory = Callable[[OriginatingMessageRef], AbstractContextManager[object]]


@dataclass
class _PipelineResult:
    """The successful product of the W2 pipeline."""

    answer_text: str
    token_usage: int
    grounded: bool


@dataclass
class Worker:
    """Wires the worker pipeline; one instance per Lambda invocation."""

    jobs: JobCoordinator
    slack: SlackGateway
    safety: SafetyScanner
    inference: InferenceProvider
    grounding: GroundingClient
    opdata: OperationalDataService
    config_store: ConfigStore
    composer: DefaultAnswerComposer
    clock: Clock
    metrics: Metrics
    config: WorkerConfig = field(default_factory=WorkerConfig)
    # Optional override for the NFR-11 heartbeat (tests inject a fake; production uses the
    # default thread-based :class:`HeartbeatEmitter`).
    heartbeat_factory: HeartbeatFactory | None = None
    _breakers: dict[str, CircuitBreaker] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._backoff_policy = BackoffPolicy(
            base_ms=self.config.retry_base_ms,
            max_attempts=self.config.retry_max_attempts,
            cap_ms=self.config.retry_cap_ms,
        )

    def process(
        self, identity: tuple[str, str], correlation_id: UUID, author_id: str
    ) -> WorkerOutcome:
        """Process one job by its de-dup identity. Returns the outcome (W2/W3).

        ``author_id`` (ENT-001.author-id) rides the C-1 message so adoption is attributed to
        a distinct developer, not the channel (FR-18/ENT-009/BR-019).
        """
        log = get_logger(__name__, str(correlation_id))

        # ADR-0001: claim_and_guard is the single at-most-once-completed gate — completion
        # short-circuit, single-winner lease, repost-after-intent refusal, and the attempt
        # bound all live there (see docs/adr/0001-claim-and-guard.md).
        claim = claim_and_guard(
            self.jobs,
            identity,
            self.clock.now(),
            staleness_seconds=self.config.lease_staleness_seconds,
            max_attempts=self.config.max_attempts,
        )
        if claim.decision == ClaimDecision.SKIP_COMPLETED:
            return self._record(WorkerOutcome.SKIPPED_COMPLETE)
        if claim.decision == ClaimDecision.LEASE_LOST:
            return self._record(WorkerOutcome.LEASE_LOST)
        if claim.decision == ClaimDecision.SKIP_ALREADY_POSTED:
            self.jobs.transition(identity, JobStatus.RESOLVED, self.clock.now())
            return self._record(WorkerOutcome.RESOLVED)
        job = claim.job
        assert job is not None  # PROCEED and EXHAUSTED always carry the claimed job
        if claim.decision == ClaimDecision.EXHAUSTED:
            self._fail(identity, job, FailureCause.EXHAUSTED_RETRIES)
            return self._record(WorkerOutcome.FAILED)

        budget = TimeBudget(self.clock, self.config.time_budget_seconds)
        try:
            # NFR-11: emit a periodic "still working…" heartbeat on a background timer while
            # the pipeline runs (inference + MCP). The context manager guarantees the timer
            # stops on both success and failure paths.
            with self._heartbeat(job.originating_message_ref):
                result = self._run_pipeline(job, budget)
        except _ProcessingError as err:
            log.warning(
                f"pipeline terminal failure cause={err.cause.value} "
                f"root_cause={type(err.__cause__).__name__}: {err.__cause__}"
            )
            self._fail(identity, job, err.cause, err.secret_classes)
            self.metrics.count("failure_by_cause", cause=err.cause.value)
            return self._record(WorkerOutcome.FAILED)
        except TimeBudgetExceededError:
            self._fail(identity, job, FailureCause.TIMEOUT)
            self.metrics.count("failure_by_cause", cause=FailureCause.TIMEOUT.value)
            return self._record(WorkerOutcome.FAILED)

        # BR-027: stamp the pre-post intent marker FIRST (closes the repost window), then post
        # idempotently, stamp answer-ts for F8, record adoption, resolve.
        self.jobs.mark_post_intent(identity, self.clock.now())
        answer_ts = self.slack.post_message(job.originating_message_ref, result.answer_text)
        self.jobs.stamp_answer_ts(identity, answer_ts)
        self.opdata.record_usage(result.token_usage)
        self.opdata.record_adoption(author_id)  # FR-18/BR-019: distinct developer, not channel
        self.jobs.transition(identity, JobStatus.RESOLVED, self.clock.now())
        self.metrics.count("answer_grounded" if result.grounded else "answer_ungrounded")
        log.info("job resolved")
        return self._record(WorkerOutcome.RESOLVED)

    # -- W2 pipeline ---------------------------------------------------------

    def _run_pipeline(self, job: ProcessingJob, budget: TimeBudget) -> _PipelineResult:
        ref = job.originating_message_ref

        # Step 3 — fetch thread context (BR-005, fetch-not-store).
        thread = self._guarded(
            "slack",
            lambda: self.slack.fetch_thread(ref.channel_id, ref.thread_ts or ref.message_ts),
            budget,
        )
        question = self._extract_question(thread, ref.message_ts)
        assembled = self._assemble(question, thread)

        # Include an attached file (downloaded + validated at intake) in the review input. It
        # becomes part of `assembled`, so the step-4 size gate and step-5 safety scan cover it too.
        if job.attached_file_text:
            name = job.attached_file_name or "attachment"
            assembled = (
                f"{assembled}\n\nATTACHED FILE ({name}):\n```\n{job.attached_file_text}\n```"
            )

        # Step 4 — size gate (BR-007 / NFR-14 hybrid trim-or-reject).
        assembled = self._enforce_size(ref, question, assembled)

        # Step 5 — safety gate FIRST (CS-4 / BR-012).
        verdict = self.safety.scan(assembled)
        if rules.safety_blocks_forward(verdict):
            raise _ProcessingError(FailureCause.SAFETY_REFUSE, [f.kind for f in verdict.findings])
        if rules.safety_requires_warning(verdict):
            self.slack.post_message(ref, "Heads up: your message may contain sensitive content.")

        # Step 6 — within-budget (BR-008).
        if not self.opdata.within_budget(self.config_store.get_guardrail()):
            raise _ProcessingError(FailureCause.BUDGET_DENY)

        # Step 7 — agent loop under the CS-5 cap + time budget (BR-014).
        sources, model_output, tokens = self._agent_loop(assembled, question, budget)

        # Steps 8-9 — classify + compose (BR-015/016/017).
        answer = self.composer.compose(job.job_id, question, model_output, sources)
        return _PipelineResult(
            answer_text=render_answer(answer),
            token_usage=tokens,
            grounded=answer.is_grounded,
        )

    def _agent_loop(
        self, assembled: str, question: str, budget: TimeBudget
    ) -> tuple[list[GroundingSource], str, int]:
        """One grounding + one inference round under the CS-5 cap and budget (BR-014).

        Both calls are well within the per-request cap (≤5 MCP / ≤2 inference); the cap is
        the runaway guard if the loop is later extended to iterate.
        """
        inference_calls = 0
        mcp_calls = 0

        if rules.loop_cap_reached(
            inference_calls, mcp_calls, self.config.max_inference_calls, self.config.max_mcp_calls
        ):
            raise _ProcessingError(FailureCause.CAP)
        sources = self._guarded("mcp", lambda: self.grounding.ground(question), budget)
        mcp_calls += 1

        exchange = self._guarded(
            "inference",
            lambda: self.inference.run_inference(assembled, system=GUARDRAIL_SYSTEM_PROMPT),
            budget,
        )
        inference_calls += 1
        self.metrics.count("inference_calls", float(inference_calls))
        self.metrics.count("mcp_calls", float(mcp_calls))

        if exchange.model_output is None:
            raise _ProcessingError(FailureCause.DEPENDENCY)
        return sources, exchange.model_output, exchange.token_usage

    def _guarded[T](self, dep: str, op: Callable[[], T], budget: TimeBudget) -> T:
        """Run an external call under retry + breaker, mapping failures to FR-17 causes."""
        budget.check()
        breaker = self._breakers.setdefault(
            dep,
            CircuitBreaker(
                dep,
                self.clock,
                failure_threshold=self.config.breaker_failure_threshold,
                reset_seconds=self.config.breaker_reset_seconds,
            ),
        )
        try:
            return breaker.call(
                lambda: retry_call(op, policy=self._backoff_policy, clock=self.clock)
            )
        except (CircuitOpenError, RetryableError, InferenceFailureError) as err:
            raise _ProcessingError(FailureCause.DEPENDENCY) from err

    # -- size gate (BR-007 / NFR-14) ----------------------------------------

    def _enforce_size(self, ref: OriginatingMessageRef, question: str, assembled: str) -> str:
        if rules.within_size_budget(assembled, self.config.max_input_tokens):
            return assembled
        if rules.question_alone_overflows(question, self.config.max_input_tokens):
            raise _ProcessingError(FailureCause.OVERSIZE)  # reject-and-ask
        # trim-with-notice (BR-007/NFR-14): drop the oldest thread context, keep the current
        # question, and tell the user in-thread that context was trimmed — never silent.
        self.slack.post_message(ref, _TRIM_NOTICE_TEXT)
        self.metrics.count("input_trimmed")
        return f"QUESTION: {question}"

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _extract_question(thread: list[ThreadMessage], message_ts: str) -> str:
        for msg in thread:
            if msg.ts == message_ts:
                return msg.text
        return thread[-1].text if thread else ""

    @staticmethod
    def _assemble(question: str, thread: list[ThreadMessage]) -> str:
        context = "\n".join(m.text for m in thread)
        return f"{context}\n\nQUESTION: {question}".strip()

    # -- W3 failure ----------------------------------------------------------

    def _fail(
        self,
        identity: tuple[str, str],
        job: ProcessingJob,
        cause: FailureCause,
        secret_classes: list[str] | None = None,
    ) -> None:
        try:
            self.slack.post_message(
                job.originating_message_ref,
                render_failure(cause, secret_classes=secret_classes),
            )
        except Exception:
            get_logger(__name__).error("failed to post FR-17 failure message")
        self.jobs.transition(identity, JobStatus.FAILED, self.clock.now())

    def _record(self, outcome: WorkerOutcome) -> WorkerOutcome:
        self.metrics.count("worker_outcome", outcome=outcome.value)
        return outcome

    def _heartbeat(self, ref: OriginatingMessageRef) -> AbstractContextManager[object]:
        """Build the NFR-11 heartbeat context for this job (overridable for tests)."""
        if self.heartbeat_factory is not None:
            return self.heartbeat_factory(ref)
        return HeartbeatEmitter(self.slack, ref, self.config.heartbeat_seconds, self.metrics)
