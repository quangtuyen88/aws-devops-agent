"""Recovery reaper (F3 / W3) — in-flight recovery and DLQ drain (BR-021/BR-022).

Scheduled by EventBridge. Two responsibilities:

1. **Stale-lease recovery (BR-021):** find jobs whose ``in-progress`` lease is stale
   (inclusive ``>=`` 90s). Jobs with attempts remaining are re-enqueued for a worker to
   reclaim; jobs that have exhausted ``max_attempts`` are abandoned to ``failed`` with an
   FR-17 message (BR-022).
2. **DLQ drain:** a message that exhausted ``maxReceiveCount`` lands on the DLQ; the reaper
   marks its job ``failed`` and posts the FR-17 message so the ack is never left dangling.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ...domain import rules
from ...domain.enums import FailureCause, JobStatus
from ...observability.logging import get_logger
from ...observability.metrics import Metrics
from ...ports import JobCoordinator, SlackGateway, WorkQueue
from ...resilience.clock import Clock
from ..worker.rendering import render_failure


class ReaperAction(StrEnum):
    """What the reaper did to a recovered job (NFR-20 recovery counters)."""

    REQUEUED = "requeued"
    ABANDONED = "abandoned"


@dataclass
class Reaper:
    """In-flight recovery + DLQ drain (one instance per scheduled invocation)."""

    jobs: JobCoordinator
    slack: SlackGateway
    queue: WorkQueue
    clock: Clock
    metrics: Metrics
    staleness_seconds: int = 90
    max_attempts: int = 3

    def recover_stale(self) -> list[ReaperAction]:
        """Scan stale in-flight jobs; re-enqueue retriable ones, abandon exhausted ones."""
        actions: list[ReaperAction] = []
        for job in self.jobs.find_stale_jobs(self.clock.now(), self.staleness_seconds):
            identity = job.slack_event_identity
            if rules.attempts_exhausted(job, self.max_attempts):
                self._abandon(identity, job, FailureCause.EXHAUSTED_RETRIES)
                actions.append(ReaperAction.ABANDONED)
            else:
                # Re-enqueue; the worker's single-winner lease reclaims it safely (BR-027).
                # Carry the durable author_id so the reclaiming worker still attributes
                # adoption to the developer, not the channel (FR-18/BR-019).
                self.queue.enqueue(
                    job.job_id, identity, job.job_id, job.originating_message_ref.author_id
                )
                self.metrics.count("recovery_requeued")
                actions.append(ReaperAction.REQUEUED)
        return actions

    def drain_dead_letters(self, identities: list[tuple[str, str]]) -> list[ReaperAction]:
        """Abandon jobs whose messages exhausted redelivery and reached the DLQ."""
        actions: list[ReaperAction] = []
        for identity in identities:
            job = self.jobs.get(identity)
            if job is None or job.status.is_terminal:
                continue
            self._abandon(identity, job, FailureCause.EXHAUSTED_RETRIES)
            actions.append(ReaperAction.ABANDONED)
        return actions

    def _abandon(self, identity: tuple[str, str], job: object, cause: FailureCause) -> None:
        ref = job.originating_message_ref  # type: ignore[attr-defined]
        try:
            self.slack.post_message(ref, render_failure(cause))
        except Exception:
            # The FR-17 post is best-effort; the job MUST still be resolved to failed so it
            # is never left dangling. Log rather than swallow silently (BR-026 hygiene).
            get_logger(__name__).warning("reaper could not post FR-17 message; abandoning anyway")
        self.jobs.transition(identity, JobStatus.FAILED, self.clock.now())
        self.metrics.count("recovery_abandoned")
