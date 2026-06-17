"""Domain entities ENT-001..ENT-014 (source of truth: functional-design/entities.yaml).

Pydantic v2 models. Logical types only — no storage engine, no framework coupling.
Transient entities live for one request; durable entities (ProcessingJob, AdoptionMetric,
FeedbackSignal, UsageCounter, config entities) are the CS-1 shared-state boundary and are
persisted by the CMP-006/007/008 adapters.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from .enums import (
    AnswerType,
    EventAction,
    JobStatus,
    NonAllowlistedBehaviour,
    ReactionKind,
    SafetyAction,
)

# ---------------------------------------------------------------------------
# CMP-001 — Slack Interaction Adapter (transient boundary entities)
# ---------------------------------------------------------------------------


class InboundMention(BaseModel):
    """ENT-001 — a parsed, accepted mention of the bot. Transient."""

    correlation_id: UUID
    channel_id: str
    thread_ts: str | None = None
    message_ts: str
    author_id: str
    is_bot_author: bool = False
    raw_text: str
    slack_retry_num: int = Field(default=0, ge=0)

    @property
    def slack_event_identity(self) -> tuple[str, str]:
        """De-dup identity (ENT-008, Q3=a): (channel-id, message-ts)."""
        return (self.channel_id, self.message_ts)

    @property
    def context_thread_ts(self) -> str:
        """Thread to fetch context from; a top-level mention threads on its own ts (M-5)."""
        return self.thread_ts or self.message_ts


class ReactionEvent(BaseModel):
    """ENT-002 — a captured 👍/👎 add/remove on a posted answer. Transient."""

    answer_message_ts: str
    reactor_id: str
    reaction_kind: ReactionKind
    event_action: EventAction


# ---------------------------------------------------------------------------
# CMP-002 — Agent Orchestrator (transient working entities)
# ---------------------------------------------------------------------------


class ThreadMessage(BaseModel):
    """One prior thread message used to reconstruct context (ENT-003 element)."""

    author_id: str
    text: str
    ts: str


class ConversationContext(BaseModel):
    """ENT-003 — thread-scoped working memory. Never persisted (A-8/OOS-4/CS-6)."""

    thread_ts: str
    ordered_messages: list[ThreadMessage] = Field(default_factory=list)
    assembled_prompt_input: str
    within_size_budget: bool


class GroundingSource(BaseModel):
    """ENT-006 — a citable AWS documentation source from an MCP tool. Transient."""

    title: str
    url: str
    snippet: str | None = None
    tool_name: str


class Answer(BaseModel):
    """ENT-004 — the composed response. Transient (posted via CMP-001)."""

    correlation_id: UUID
    answer_type: AnswerType = AnswerType.FACTUAL
    recommendation: str
    rationale: str
    trade_offs: str | None = None
    alternatives: str | None = None
    citations: list[GroundingSource] = Field(default_factory=list)
    is_grounded: bool = False
    code_snippets: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_grounding_and_structure(self) -> Answer:
        """Enforce BR-016 (citation/grounding consistency) and BR-015 (structure)."""
        if self.is_grounded and not self.citations:
            raise ValueError("BR-016: a grounded answer MUST carry >=1 citation")
        if not self.is_grounded and self.citations:
            raise ValueError("BR-016: an ungrounded answer MUST carry zero citations")
        if self.answer_type.requires_trade_offs and not (self.trade_offs or "").strip():
            raise ValueError(
                "BR-015: architecture-review / solution-design answers MUST include trade-offs"
            )
        return self


# ---------------------------------------------------------------------------
# CMP-003 — Inference Provider (transient exchange entity)
# ---------------------------------------------------------------------------


class InferenceExchange(BaseModel):
    """ENT-005 — one inference round-trip. Transient."""

    prompt_input: str
    model_output: str | None = None
    token_usage: int = Field(default=0, ge=0)
    backend_id: str


# ---------------------------------------------------------------------------
# CMP-005 — Input Safety Scanner (transient verdict entity)
# ---------------------------------------------------------------------------


class SafetyFinding(BaseModel):
    """A redacted match descriptor — never a raw secret value (NFR-6/BR-026)."""

    kind: str
    location: str


class SafetyVerdict(BaseModel):
    """ENT-007 — outcome of scanning one input. Transient."""

    flagged: bool
    findings: list[SafetyFinding] = Field(default_factory=list)
    recommended_action: SafetyAction


# ---------------------------------------------------------------------------
# CMP-006 — Job Coordinator (durable)
# ---------------------------------------------------------------------------


class OriginatingMessageRef(BaseModel):
    """Slack coordinates + asker needed to post back and attribute adoption (ENT-008).

    Carries the originating developer's ``author_id`` (ENT-001.author-id) so the worker can
    attribute the resolved question to a *distinct developer* for AdoptionMetric
    (FR-18 / ENT-009 / BR-019) — the metric counts people, not channels.
    """

    channel_id: str
    thread_ts: str | None = None
    message_ts: str
    author_id: str


class ProcessingJob(BaseModel):
    """ENT-008 — a unit of async work with de-dup identity + state machine. Durable."""

    job_id: UUID
    channel_id: str
    message_ts: str
    originating_message_ref: OriginatingMessageRef
    status: JobStatus = JobStatus.SEEN
    attempt_count: int = Field(default=0, ge=0)
    last_transition_at: datetime
    # BR-027 pre-post intent marker: stamped immediately BEFORE the Slack answer post so a
    # crash in the narrow window between posting and stamping ``answer_message_ts`` is still
    # detectable on recovery — a reclaiming worker that sees this set MUST NOT repost.
    post_intent_at: datetime | None = None
    answer_message_ts: str | None = None  # F8: stamped at answer-post; GSI key

    @property
    def post_attempted(self) -> bool:
        """True once an answer post has been initiated or completed (BR-027).

        Either the pre-post intent marker is stamped (a post may already have reached Slack)
        or the answer ts is durably recorded (the post definitely landed). In both cases a
        recovery-spawned worker must resolve WITHOUT reposting to guarantee
        at-most-once-*completed*.
        """
        return self.post_intent_at is not None or self.answer_message_ts is not None

    @property
    def slack_event_identity(self) -> tuple[str, str]:
        """De-dup key (ENT-008, Q3=a)."""
        return (self.channel_id, self.message_ts)


# ---------------------------------------------------------------------------
# CMP-007 — Operational Data Service (durable)
# ---------------------------------------------------------------------------


class AdoptionMetric(BaseModel):
    """ENT-009 — aggregate adoption counters. Durable."""

    period: str
    distinct_developers: int = Field(default=0, ge=0)
    questions_handled: int = Field(default=0, ge=0)


class FeedbackSignal(BaseModel):
    """ENT-010 — append-only helpfulness signal (Q4)."""

    answer_ref: UUID
    signal: ReactionKind
    recorded_at: datetime
    reactor_id: str
    event_action: EventAction


class UsageCounter(BaseModel):
    """ENT-011 — per-period usage tally read on the hot path (NFR-8). Durable."""

    period: str
    usage_count: int = Field(default=0, ge=0)
    last_updated_at: datetime


# ---------------------------------------------------------------------------
# CMP-008 — Configuration & Policy (operator-set, read-mostly)
# ---------------------------------------------------------------------------


class ChannelAllowlist(BaseModel):
    """ENT-012 — channels the bot may answer in (FR-2)."""

    allowed_channel_ids: list[str] = Field(default_factory=list)
    non_allowlisted_behaviour: NonAllowlistedBehaviour = (
        NonAllowlistedBehaviour.REPLY_NOT_DESIGNATED
    )

    def is_allowed(self, channel_id: str) -> bool:
        """True when the bot is permitted to answer in ``channel_id`` (BR-001)."""
        return channel_id in self.allowed_channel_ids


class UsagePolicy(BaseModel):
    """ENT-013 — published data-sensitivity policy (NFR-3)."""

    policy_text: str
    published_location_ref: str | None = None


class GuardrailConfig(BaseModel):
    """ENT-014 — operator-set cost-guardrail thresholds (NFR-8)."""

    per_request_limit: int | None = Field(default=None, ge=0)
    per_period_limit: int | None = Field(default=None, ge=0)
    period_definition: str = "week"

    @model_validator(mode="after")
    def _at_least_one_limit(self) -> GuardrailConfig:
        """At least one limit MUST be set so the NFR-8 guardrail is enforceable (A-7)."""
        if self.per_request_limit is None and self.per_period_limit is None:
            raise ValueError("GuardrailConfig MUST set per-request-limit or per-period-limit")
        return self
