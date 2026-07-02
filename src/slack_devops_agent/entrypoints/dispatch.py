"""Event dispatch helpers (pure-ish routing, no AWS construction).

Separated from the Lambda handlers so the routing of Slack envelopes and SQS records is
unit-testable with synthetic events and fakes.
"""

from __future__ import annotations

from uuid import UUID

from ..components.intake import IntakeHandler, IntakeOutcome, parse_mention, parse_reaction
from ..components.intake.parsing import pick_reviewable_file
from ..components.queue import WorkMessage

_MENTION_EVENT_TYPES = {"app_mention", "message"}
_REACTION_EVENT_TYPES = {"reaction_added", "reaction_removed"}


def dispatch_slack_event(
    envelope: dict[str, object], handler: IntakeHandler, bot_user_id: str, retry_num: int = 0
) -> IntakeOutcome | None:
    """Route a parsed Slack Events API envelope to the intake handler (W1/W4).

    Returns the :class:`IntakeOutcome`, or ``None`` for an event type the unit ignores.
    """
    event = envelope.get("event")
    if not isinstance(event, dict):
        return None
    event_type = str(event.get("type") or "")

    if event_type in _MENTION_EVENT_TYPES:
        mention = parse_mention(event, bot_user_id, retry_num=retry_num)
        return handler.handle_mention(mention, pick_reviewable_file(event))

    if event_type in _REACTION_EVENT_TYPES:
        reaction = parse_reaction(event)
        if reaction is None:
            return IntakeOutcome.FEEDBACK_IGNORED
        return handler.handle_reaction(reaction)

    return None


def parse_sqs_record(body: str) -> tuple[tuple[str, str], UUID, str]:
    """Parse an SQS body into ``(identity, correlation_id, author_id)`` for the worker."""
    message = WorkMessage.from_json(body)
    return (message.channel_id, message.message_ts), message.correlation_id, message.author_id
