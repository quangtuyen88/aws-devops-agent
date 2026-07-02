"""Tests for claim_and_guard (ADR-0001) — the at-most-once-completed decision.

Targets the decision procedure directly against FakeJobCoordinator, independent of the
full Worker pipeline — the "one module top-to-bottom" success criterion from
docs/adr/0001-claim-and-guard.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from slack_devops_agent.components.jobs import ClaimDecision, claim_and_guard
from slack_devops_agent.domain.entities import OriginatingMessageRef
from slack_devops_agent.domain.enums import JobStatus

from .fakes import FakeJobCoordinator

IDENTITY = ("C1", "111.1")
T0 = datetime(2026, 6, 17, 12, 0, 0, tzinfo=UTC)


def _seed(jobs: FakeJobCoordinator, now: datetime = T0) -> None:
    ref = OriginatingMessageRef(channel_id="C1", thread_ts=None, message_ts="111.1", author_id="U1")
    jobs.register_or_get(IDENTITY, ref, uuid4(), now)


def test_fresh_job_proceeds_and_wins_the_lease() -> None:
    jobs = FakeJobCoordinator()
    _seed(jobs)
    result = claim_and_guard(jobs, IDENTITY, T0, staleness_seconds=90, max_attempts=3)
    assert result.decision == ClaimDecision.PROCEED
    assert result.job is not None
    assert result.job.status == JobStatus.IN_PROGRESS
    assert result.job.attempt_count == 1


def test_completed_job_is_skipped_before_any_lease_attempt() -> None:
    jobs = FakeJobCoordinator()
    _seed(jobs)
    jobs.acquire_lease(IDENTITY, T0, 90)
    jobs.transition(IDENTITY, JobStatus.RESOLVED, T0)
    before = jobs.get(IDENTITY).attempt_count  # type: ignore[union-attr]

    result = claim_and_guard(jobs, IDENTITY, T0, staleness_seconds=90, max_attempts=3)

    assert result.decision == ClaimDecision.SKIP_COMPLETED
    assert jobs.get(IDENTITY).attempt_count == before  # type: ignore[union-attr]


def test_single_winner_lease_a_live_competitor_loses() -> None:
    jobs = FakeJobCoordinator()
    _seed(jobs)
    jobs.acquire_lease(IDENTITY, T0, 90)  # a live worker already holds the lease

    result = claim_and_guard(jobs, IDENTITY, T0, staleness_seconds=90, max_attempts=3)

    assert result.decision == ClaimDecision.LEASE_LOST


def test_stale_lease_takeover_reclaims_and_proceeds() -> None:
    jobs = FakeJobCoordinator()
    _seed(jobs)
    jobs.acquire_lease(IDENTITY, T0, 90)  # first worker takes the lease, then dies
    later = T0 + timedelta(seconds=90)  # lease now stale (inclusive)

    result = claim_and_guard(jobs, IDENTITY, later, staleness_seconds=90, max_attempts=3)

    assert result.decision == ClaimDecision.PROCEED
    assert result.job is not None
    assert result.job.attempt_count == 2  # reclaim increments


def test_repost_after_intent_is_refused_without_reposting() -> None:
    jobs = FakeJobCoordinator()
    _seed(jobs)
    jobs.acquire_lease(IDENTITY, T0, 90)
    jobs.mark_post_intent(IDENTITY, T0)  # crash landed here: intent stamped, ts lost
    later = T0 + timedelta(seconds=90)  # lease now stale -> a recovery worker reclaims

    result = claim_and_guard(jobs, IDENTITY, later, staleness_seconds=90, max_attempts=3)

    assert result.decision == ClaimDecision.SKIP_ALREADY_POSTED
    assert result.job is not None


def test_exhausted_attempts_after_winning_the_lease() -> None:
    jobs = FakeJobCoordinator()
    _seed(jobs)
    t = T0
    for _ in range(3):  # drive attempt_count to the cap via repeated stale reclaims
        t += timedelta(seconds=90)
        jobs.acquire_lease(IDENTITY, t, 90)
    t += timedelta(seconds=90)

    result = claim_and_guard(jobs, IDENTITY, t, staleness_seconds=90, max_attempts=3)

    assert result.decision == ClaimDecision.EXHAUSTED
    assert result.job is not None
