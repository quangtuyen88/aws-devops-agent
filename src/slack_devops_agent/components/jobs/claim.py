"""The at-most-once-*completed* decision (BR-011/BR-021/BR-022/BR-027).

Concentrates the invariant "a recovery-spawned worker must never double-post an answer"
behind one call, composing the existing :class:`JobCoordinator` primitives with the
existing pure rules — no new persistence, no new adapter surface. See
``docs/adr/0001-claim-and-guard.md`` for why this is a free function over the port
rather than a new port method, and why the reaper does not route through it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ...domain import rules
from ...domain.entities import ProcessingJob
from ...ports import JobCoordinator


class ClaimDecision(StrEnum):
    """What the caller must do next, per the at-most-once-completed invariant."""

    PROCEED = "proceed"
    SKIP_COMPLETED = "skip-completed"
    SKIP_ALREADY_POSTED = "skip-already-posted"
    LEASE_LOST = "lease-lost"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class ClaimResult:
    decision: ClaimDecision
    job: ProcessingJob | None = None


def claim_and_guard(
    jobs: JobCoordinator,
    identity: tuple[str, str],
    now: datetime,
    *,
    staleness_seconds: int,
    max_attempts: int,
) -> ClaimResult:
    """The single "may I process this job?" gate — read this top to bottom.

    1. A job already ``resolved``/``failed`` is skipped before any lease attempt
       (BR-011).
    2. The lease CAS (:meth:`JobCoordinator.acquire_lease`) picks exactly one winner
       across live and recovery-spawned workers (BR-021/BR-027).
    3. A job whose post was already attempted — the pre-post intent marker is stamped,
       or the answer landed — resolves without reposting (BR-027).
    4. A job past its attempt bound is surfaced for abandonment instead of another
       pipeline run (BR-022).
    """
    existing = jobs.get(identity)
    if existing is not None and not rules.should_process_existing(existing):
        return ClaimResult(ClaimDecision.SKIP_COMPLETED)

    job = jobs.acquire_lease(identity, now, staleness_seconds)
    if job is None:
        return ClaimResult(ClaimDecision.LEASE_LOST)

    if job.post_attempted:
        return ClaimResult(ClaimDecision.SKIP_ALREADY_POSTED, job)

    if rules.attempts_exhausted(job, max_attempts):
        return ClaimResult(ClaimDecision.EXHAUSTED, job)

    return ClaimResult(ClaimDecision.PROCEED, job)
