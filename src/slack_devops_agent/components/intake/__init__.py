"""CMP-001 — Slack Interaction Adapter (intake, gateway, parsing)."""

from __future__ import annotations

from .handler import IntakeHandler, IntakeOutcome
from .parsing import mentions_bot, parse_mention, parse_reaction
from .slack_gateway import SlackGatewayAdapter

__all__ = [
    "IntakeHandler",
    "IntakeOutcome",
    "mentions_bot",
    "parse_mention",
    "parse_reaction",
    "SlackGatewayAdapter",
]
