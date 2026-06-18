"""Event dispatch helpers (pure-ish routing, no AWS construction).

Separated from the Lambda handlers so the routing of Slack envelopes and SQS records is
unit-testable with synthetic events and fakes.
"""

from __future__ import annotations

import json
from uuid import UUID

from ..components.intake import IntakeHandler, IntakeOutcome, parse_mention, parse_reaction
from ..components.intake.parsing import pick_reviewable_file

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
    """Parse an SQS body into ``(identity, correlation_id, author_id)`` for the worker.

    ``author_id`` (ENT-001.author-id) feeds AdoptionMetric (FR-18/BR-019). A missing field
    falls back to ``""`` rather than crashing the whole batch; the adoption write tolerates
    it and the gap is observable via the empty developer id.
    """
    payload = json.loads(body)
    identity = (str(payload["channel_id"]), str(payload["message_ts"]))
    correlation_id = UUID(str(payload["correlation_id"]))
    author_id = str(payload.get("author_id") or "")
    return identity, correlation_id, author_id
