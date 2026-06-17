"""CMP-001 — Intake handler (W1 intake/ack + W4 feedback capture).

The always-on intake role. It applies the BR-002/BR-003/BR-001 filters, registers the
de-dup job (BR-010), posts the in-thread ack and enqueues across the C-1 seam (BR-004),
and synchronously captures 👍/👎 feedback on bot answers (W4/BR-018). It does the minimum
on the synchronous path so it can ack within the NFR-1 window; the heavy work is the
worker's.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ...domain import rules
from ...domain.entities import (
    FeedbackSignal,
    InboundMention,
    OriginatingMessageRef,
    ReactionEvent,
)
from ...domain.enums import NonAllowlistedBehaviour
from ...observability.logging import get_logger
from ...observability.metrics import Metrics
from ...ports import (
    ConfigStore,
    JobCoordinator,
    OperationalDataService,
    SlackGateway,
    WorkQueue,
)
from ...resilience.clock import Clock
from .parsing import mentions_bot

_ACK_TEXT = "On it — looking into your question now. :hourglass_flowing_sand:"
_NOT_DESIGNATED_TEXT = (
    "I only operate in designated DevOps channels. Please ask in an allowlisted channel."
)


class IntakeOutcome(StrEnum):
    """Observable result of handling one inbound event (NFR-20)."""

    IGNORED_BOT = "ignored-bot"
    IGNORED_NO_MENTION = "ignored-no-mention"
    NOT_ALLOWLISTED = "not-allowlisted"
    DUPLICATE = "duplicate"
    ACCEPTED = "accepted"
    FEEDBACK_RECORDED = "feedback-recorded"
    FEEDBACK_IGNORED = "feedback-ignored"


@dataclass
class IntakeHandler:
    """Orchestrates the synchronous intake and feedback-capture paths."""

    config: ConfigStore
    jobs: JobCoordinator
    slack: SlackGateway
    queue: WorkQueue
    opdata: OperationalDataService
    clock: Clock
    bot_user_id: str
    metrics: Metrics

    def handle_mention(self, mention: InboundMention) -> IntakeOutcome:
        """W1 — filter, dedup-register, ack, enqueue. Returns the outcome."""
        log = get_logger(__name__, str(mention.correlation_id))

        if rules.is_bot_authored(mention):  # BR-002
            return self._record(IntakeOutcome.IGNORED_BOT)
        if not mentions_bot(mention.raw_text, self.bot_user_id):  # BR-003
            return self._record(IntakeOutcome.IGNORED_NO_MENTION)

        allowlist = self.config.get_allowlist()
        if not rules.is_channel_allowed(mention, allowlist):  # BR-001
            if allowlist.non_allowlisted_behaviour == NonAllowlistedBehaviour.REPLY_NOT_DESIGNATED:
                self.slack.post_message(self._ref(mention), _NOT_DESIGNATED_TEXT)
            return self._record(IntakeOutcome.NOT_ALLOWLISTED)

        # BR-010: register-or-get by identity; a redelivery attaches to the existing job.
        job, created = self.jobs.register_or_get(
            mention.slack_event_identity,
            self._ref(mention),
            mention.correlation_id,
            self.clock.now(),
        )
        if not created:
            log.info(
                "duplicate intake; attaching to existing job", extra={"job_id": str(job.job_id)}
            )
            return self._record(IntakeOutcome.DUPLICATE)

        # BR-004: ack in-thread, then enqueue across the C-1 seam. Ack failure must not
        # block the enqueue (degrade) so the worker can still resolve the job.
        try:
            self.slack.post_message(self._ref(mention), _ACK_TEXT)
        except Exception:
            log.warning("ack post failed; continuing to enqueue (BR-004 degrade)")
        self.queue.enqueue(
            job.job_id,
            mention.slack_event_identity,
            mention.correlation_id,
            mention.author_id,
        )
        return self._record(IntakeOutcome.ACCEPTED)

    def handle_reaction(self, reaction: ReactionEvent) -> IntakeOutcome:
        """W4 — capture 👍/👎 on a bot answer; resolve ts→correlation-id and append (BR-018)."""
        correlation_id = self.jobs.resolve_answer_ts(reaction.answer_message_ts)
        if correlation_id is None:  # reaction not on a known bot answer
            return self._record(IntakeOutcome.FEEDBACK_IGNORED)

        self.opdata.record_feedback(
            FeedbackSignal(
                answer_ref=correlation_id,
                signal=reaction.reaction_kind,
                recorded_at=self.clock.now(),
                reactor_id=reaction.reactor_id,
                event_action=reaction.event_action,
            )
        )
        return self._record(IntakeOutcome.FEEDBACK_RECORDED)

    @staticmethod
    def _ref(mention: InboundMention) -> OriginatingMessageRef:
        return OriginatingMessageRef(
            channel_id=mention.channel_id,
            thread_ts=mention.thread_ts,
            message_ts=mention.message_ts,
            author_id=mention.author_id,
        )

    def _record(self, outcome: IntakeOutcome) -> IntakeOutcome:
        self.metrics.count("intake_outcome", outcome=outcome.value)
        return outcome
