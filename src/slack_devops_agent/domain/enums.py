"""Domain enumerations (source of truth: functional-design/entities.yaml).

Logical enums shared across entities and business rules. No I/O here.
"""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    """ProcessingJob lifecycle states (ENT-008, Q2=b distinct terminals)."""

    SEEN = "seen"
    IN_PROGRESS = "in-progress"
    RESOLVED = "resolved"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """``resolved`` and ``failed`` are terminal — no transition leaves them."""
        return self in {JobStatus.RESOLVED, JobStatus.FAILED}


class AnswerType(StrEnum):
    """Classified question intent (ENT-004.answer-type, F-2). Drives BR-015."""

    ARCHITECTURE_REVIEW = "architecture-review"
    SOLUTION_DESIGN = "solution-design"
    COST = "cost"
    TROUBLESHOOTING = "troubleshooting"
    FACTUAL = "factual"

    @property
    def requires_trade_offs(self) -> bool:
        """architecture-review / solution-design MUST carry trade-offs (BR-015)."""
        return self in {AnswerType.ARCHITECTURE_REVIEW, AnswerType.SOLUTION_DESIGN}


class SafetyAction(StrEnum):
    """Recommended action from the safety scan (ENT-007, CS-4/BR-012)."""

    ALLOW = "allow"
    WARN = "warn"
    REFUSE = "refuse"


class ReactionKind(StrEnum):
    """Normalised reaction (ENT-002/ENT-010)."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class EventAction(StrEnum):
    """Reaction add/remove (ENT-002/ENT-010, Q4 append-only support)."""

    ADDED = "added"
    REMOVED = "removed"


class NonAllowlistedBehaviour(StrEnum):
    """Configured behaviour outside the allowlist (ENT-012, F-3 default flip)."""

    SILENT = "silent"
    REPLY_NOT_DESIGNATED = "reply-not-designated"


class FailureCause(StrEnum):
    """Observable failure cause for FR-17 / NFR-20 failure-by-cause counters."""

    TIMEOUT = "timeout"
    CAP = "cap"
    BUDGET_DENY = "budget-deny"
    OVERSIZE = "oversize"
    SAFETY_REFUSE = "safety-refuse"
    DEPENDENCY = "dependency"
    EXHAUSTED_RETRIES = "exhausted-retries"
