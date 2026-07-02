"""Port interfaces — the stable internal seams API-INT-001..009 (api-specification.md).

These Protocols are the boundaries between components. The agent core (CMP-002) and
intake (CMP-001) depend only on these abstractions; concrete adapters (DynamoDB, SQS,
Slack, Kiro/Bedrock, MCP) implement them. This keeps the core testable with fakes and
preserves the A-1 inference swap seam and the C-1 queue extraction seam.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from ..domain.entities import (
    ChannelAllowlist,
    FeedbackSignal,
    GroundingSource,
    GuardrailConfig,
    InferenceExchange,
    OriginatingMessageRef,
    ProcessingJob,
    SafetyVerdict,
    ThreadMessage,
    UsagePolicy,
)
from ..domain.enums import JobStatus


class InferenceProvider(Protocol):
    """API-INT-001 — backend-agnostic inference (the A-1 swap seam)."""

    @property
    def backend_id(self) -> str:
        """Identifier of the concrete backend (e.g. ``kiro``, ``bedrock``)."""
        ...

    def run_inference(self, prompt_input: str, system: str | None = None) -> InferenceExchange:
        """Run one inference round-trip. Raises a typed failure on backend error.

        ``system`` carries an operator guardrail prompt sent with higher precedence than
        ``prompt_input`` (prompt-injection resistance).
        """
        ...


class JobCoordinator(Protocol):
    """API-INT-002 — ProcessingJob lifecycle, de-dup, lease, recovery.

    The natural key is the de-dup ``identity`` = (channel-id, message-ts) (Q3=a). Lifecycle
    operations key by identity so dedup and transitions share one item; ``job_id`` (==
    correlation-id) is carried on the item and returned for tracing / feedback resolution.
    """

    def register_or_get(
        self,
        identity: tuple[str, str],
        ref: OriginatingMessageRef,
        job_id: UUID,
        now: datetime,
        attached_file_name: str | None = None,
        attached_file_text: str | None = None,
    ) -> tuple[ProcessingJob, bool]:
        """Register a new job or return the existing one for ``identity`` (BR-010).

        Returns ``(job, created)`` where ``created`` is True only for a fresh ``seen`` job.
        Uses a conditional write so a redelivery/re-enqueue never creates a second job.
        """
        ...

    def get(self, identity: tuple[str, str]) -> ProcessingJob | None:
        """Return the job for ``identity`` if it exists."""
        ...

    def acquire_lease(
        self, identity: tuple[str, str], now: datetime, staleness_seconds: int
    ) -> ProcessingJob | None:
        """Single-winner transition to ``in-progress`` with attempt++ (BR-021/BR-027).

        Acquires a fresh ``seen`` job, or reclaims an ``in-progress`` job only once its
        lease is stale (``>= staleness_seconds``). Returns the updated job if this caller
        won, else ``None`` (a competing worker won, or a live lease is held).
        """
        ...

    def transition(
        self, identity: tuple[str, str], target: JobStatus, now: datetime
    ) -> ProcessingJob:
        """Apply a terminal/intermediate state transition (FSM-validated)."""
        ...

    def stamp_answer_ts(self, identity: tuple[str, str], answer_message_ts: str) -> None:
        """Stamp the posted answer's ts on the job for F8 reaction resolution."""
        ...

    def mark_post_intent(self, identity: tuple[str, str], now: datetime) -> None:
        """Stamp the BR-027 pre-post intent marker immediately before posting the answer.

        Closes the repost window: if the worker crashes after the Slack post but before
        ``stamp_answer_ts``, a recovery-spawned worker sees this marker and resolves the job
        WITHOUT reposting (at-most-once-*completed*). Idempotent — only the first marker for
        a job is retained.
        """
        ...

    def resolve_answer_ts(self, answer_message_ts: str) -> UUID | None:
        """Resolve an answer message ts → correlation-id via the GSI (F8/BR-018)."""
        ...

    def find_stale_jobs(self, now: datetime, staleness_seconds: int) -> list[ProcessingJob]:
        """Return jobs whose in-flight lease is stale and reclaimable (BR-021)."""
        ...


class SafetyScanner(Protocol):
    """API-INT-003 — pre-send secret-detection gate (CS-4)."""

    def scan(self, assembled_input: str) -> SafetyVerdict:
        """Judge ``assembled_input`` for secrets. Fail-safe to ``refuse`` on error."""
        ...


class GroundingClient(Protocol):
    """API-INT-004 — MCP grounding wrapper."""

    def ground(self, query: str) -> list[GroundingSource]:
        """Return zero-or-more citable sources for ``query`` (BR-009)."""
        ...


class SlackGateway(Protocol):
    """API-INT-005 — all Slack I/O routes through the adapter."""

    def fetch_thread(self, channel_id: str, thread_ts: str) -> list[ThreadMessage]:
        """Fetch prior thread messages in chronological order (BR-005)."""
        ...

    def post_message(self, ref: OriginatingMessageRef, text: str) -> str:
        """Post a message in the originating thread; returns the posted message ts."""
        ...

    def download_file_text(self, download_url: str, max_bytes: int) -> str:
        """Download a private Slack file as UTF-8 text, truncated to ``max_bytes``."""
        ...


class OperationalDataService(Protocol):
    """API-INT-006/007 — cost guardrail, usage/adoption recording, feedback."""

    def within_budget(self, guardrail: GuardrailConfig) -> bool:
        """BR-008 — whether the current period is within the cost budget."""
        ...

    def record_usage(self, token_usage: int) -> None:
        """BR-019 — atomically increment the per-period usage counter."""
        ...

    def record_adoption(self, author_id: str) -> None:
        """BR-019 — record a resolved question for the period's adoption metric."""
        ...

    def record_feedback(self, signal: FeedbackSignal) -> None:
        """API-INT-007 — append an immutable feedback row (BR-020)."""
        ...


class ConfigStore(Protocol):
    """API-INT-008 — read-only operator configuration."""

    def get_allowlist(self) -> ChannelAllowlist:
        """Read the channel allowlist (BR-001)."""
        ...

    def get_usage_policy(self) -> UsagePolicy:
        """Read the published usage policy (NFR-3/BR-025)."""
        ...

    def get_guardrail(self) -> GuardrailConfig:
        """Read the cost-guardrail thresholds (BR-008/NFR-8)."""
        ...


class WorkQueue(Protocol):
    """API-INT-009 — the C-1 intake→worker enqueue seam."""

    def enqueue(
        self, job_id: UUID, identity: tuple[str, str], correlation_id: UUID, author_id: str
    ) -> None:
        """Enqueue a job reference for async processing (BR-004).

        ``author_id`` (ENT-001.author-id) rides the message so the worker can attribute the
        resolved question to a distinct developer for AdoptionMetric (FR-18/BR-019).
        """
        ...
