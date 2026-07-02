"""Pure business-rule logic (source of truth: functional-design/rules.yaml).

Every function here is side-effect-free: it takes domain values and returns a decision.
The orchestration components (CMP-001/002) call these to keep policy verifiable and
testable in isolation. I/O (Slack, inference, MCP, stores) lives in the adapters.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from .entities import (
    ChannelAllowlist,
    FeedbackSignal,
    InboundMention,
    ProcessingJob,
    SafetyVerdict,
)
from .enums import (
    AnswerType,
    EventAction,
    JobStatus,
    NonAllowlistedBehaviour,
    ReactionKind,
    SafetyAction,
)

# --- Intake & filtering (CMP-001) -----------------------------------------


def is_bot_authored(mention: InboundMention) -> bool:
    """BR-002 — messages authored by the bot/another app are never questions."""
    return mention.is_bot_author


def is_channel_allowed(mention: InboundMention, allowlist: ChannelAllowlist) -> bool:
    """BR-001 — the bot answers only in operator-allowlisted channels."""
    return allowlist.is_allowed(mention.channel_id)


def should_reply_not_designated(allowlist: ChannelAllowlist) -> bool:
    """BR-001/F-3 — whether to post the 'only designated channels' notice."""
    return allowlist.non_allowlisted_behaviour == NonAllowlistedBehaviour.REPLY_NOT_DESIGNATED


# --- Job de-dup & lifecycle (CMP-006) -------------------------------------


def should_process_existing(job: ProcessingJob) -> bool:
    """BR-010/BR-011 — at-most-once-*completed*.

    A redelivered/known identity is re-eligible only when not yet complete
    (status in {seen, in-progress}); terminal jobs do nothing further.
    """
    return not job.status.is_terminal


def is_lease_stale(job: ProcessingJob, now: datetime, staleness_seconds: int) -> bool:
    """BR-021/NFR-19/F5 — a lost in-flight job is reclaimable.

    The reclaim check is **inclusive** (``>=``): a job whose last transition is at
    least ``staleness_seconds`` old is presumed lost. The staleness bound (90s) is
    chosen to exceed the per-request budget (30s) so a live job is never reclaimed.
    """
    if job.status not in {JobStatus.SEEN, JobStatus.IN_PROGRESS}:
        return False
    age = now - job.last_transition_at
    return age >= timedelta(seconds=staleness_seconds)


def attempts_exhausted(job: ProcessingJob, max_attempts: int) -> bool:
    """BR-022 — retries are bounded; >= max abandons to failed."""
    return job.attempt_count >= max_attempts


# --- Input size (CMP-002) -------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Conservative token estimate (~4 chars/token). Used for the NFR-14 size gate."""
    return (len(text) + 3) // 4


def within_size_budget(assembled_input: str, max_input_tokens: int) -> bool:
    """BR-007/NFR-14 — whether assembled input fits the configured budget."""
    return estimate_tokens(assembled_input) <= max_input_tokens


def question_alone_overflows(question: str, max_input_tokens: int) -> bool:
    """NFR-14 (Q5=c hybrid) — reject-and-ask only when the question alone overflows."""
    return estimate_tokens(question) > max_input_tokens


# --- Cost guardrail (CMP-007/008) -----------------------------------------


def is_within_budget(
    usage_count: int, per_period_limit: int | None, per_request_limit: int | None = None
) -> bool:
    """BR-008 — a request must be within the cost budget before any spend.

    Two ENT-014 guardrails compose here:

    * ``per_period_limit`` — the period-level spend ceiling. The request is denied once
      cumulative ``usage_count`` reaches it (``>=``), halting further spend for the period.
    * ``per_request_limit`` — the per-request token ceiling. A *positive* value is not
      enforced at this period-level gate (``usage_count`` is cumulative, not per-request);
      it is enforced downstream on the hot path by the NFR-14 input-size gate and the CS-5
      tool-call/token caps in the agent loop, which bound a single request's spend before
      it lands. A non-positive value (``<= 0``) is treated here as an explicit operator
      kill-switch that blocks every request before any spend.

    Returns ``True`` when the request may proceed.
    """
    over_period = per_period_limit is not None and usage_count >= per_period_limit
    request_blocked = per_request_limit is not None and per_request_limit <= 0
    return not (over_period or request_blocked)


# --- Safety gate (CMP-005) — CS-4 -----------------------------------------


def safety_blocks_forward(verdict: SafetyVerdict) -> bool:
    """BR-012 — a ``refuse`` verdict blocks forwarding to inference/MCP."""
    return verdict.recommended_action == SafetyAction.REFUSE


def safety_requires_warning(verdict: SafetyVerdict) -> bool:
    """BR-012 — a ``warn`` verdict proceeds but posts a user notice."""
    return verdict.recommended_action == SafetyAction.WARN


# --- Agent loop cap (CMP-002) — CS-5 --------------------------------------


def loop_cap_reached(inference_calls: int, mcp_calls: int, max_inf: int, max_mcp: int) -> bool:
    """BR-014/NFR-12 — hard per-request tool-call cap."""
    return inference_calls >= max_inf or mcp_calls >= max_mcp


# --- Answer composition (CMP-002) -----------------------------------------


_ARCH_KEYWORDS = ("architecture review", "review my architecture", "well-architected")
_DESIGN_KEYWORDS = ("design", "should i use", "which service", "approach")
_COST_KEYWORDS = ("cost", "price", "pricing", "cheaper", "budget")
_TROUBLESHOOT_KEYWORDS = (
    "error",
    "failing",
    "broken",
    "debug",
    "not working",
    "troubleshoot",
)


def classify_answer_type(text: str) -> AnswerType:
    """BR-015/F-2 — best-effort heuristic classification; falls back to factual.

    Heuristic by keyword; FR-9/FR-10 detection is explicitly best-effort. When
    uncertain the worker MUST fall back to ``factual`` (no under-specified structured
    answer is forced).
    """
    lowered = text.lower()
    if any(k in lowered for k in _ARCH_KEYWORDS):
        return AnswerType.ARCHITECTURE_REVIEW
    if any(k in lowered for k in _DESIGN_KEYWORDS):
        return AnswerType.SOLUTION_DESIGN
    if any(k in lowered for k in _COST_KEYWORDS):
        return AnswerType.COST
    if any(k in lowered for k in _TROUBLESHOOT_KEYWORDS):
        return AnswerType.TROUBLESHOOTING
    return AnswerType.FACTUAL


# --- Feedback aggregation (CMP-007) — Q4/F-1 ------------------------------


def net_reactor_signal(rows: list[FeedbackSignal]) -> ReactionKind | None:
    """BR-020/F-1 — resolve a single reactor's net signal for one answer.

    Each emoji (signal) is resolved independently: the latest row per
    ``(reactor, signal)`` is PRESENT iff its latest ``event_action`` is ``added``.
    A withdrawn 👎 does not erase a still-present 👍. When both are present the most
    recently added one wins; when neither is present the result is ``None``.
    """
    latest: dict[ReactionKind, FeedbackSignal] = {}
    for row in rows:
        cur = latest.get(row.signal)
        if cur is None or row.recorded_at >= cur.recorded_at:
            latest[row.signal] = row
    present = {sig: r for sig, r in latest.items() if r.event_action == EventAction.ADDED}
    if not present:
        return None
    # Most-recently-added present signal wins for the reactor's net stance.
    winner = max(present.values(), key=lambda r: r.recorded_at)
    return winner.signal


def aggregate_feedback(rows: list[FeedbackSignal]) -> dict[ReactionKind, int]:
    """BR-020 — tally net positive/negative reactors across an answer's feedback rows."""
    by_reactor: dict[str, list[FeedbackSignal]] = defaultdict(list)
    for row in rows:
        by_reactor[row.reactor_id].append(row)
    tally: dict[ReactionKind, int] = {ReactionKind.POSITIVE: 0, ReactionKind.NEGATIVE: 0}
    for reactor_rows in by_reactor.values():
        net = net_reactor_signal(reactor_rows)
        if net is not None:
            tally[net] += 1
    return tally
