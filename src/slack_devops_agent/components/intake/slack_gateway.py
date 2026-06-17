"""CMP-001 — Slack Web API gateway (API-INT-005, wraps API-EXT-002/003).

All Slack I/O routes through this adapter so the worker reconstructs context and posts
answers/failures without touching Slack directly. Rate-limit (429) responses map to
:class:`RetryableError` so the caller backs off (BR-023); the bot token is held here only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from slack_sdk.errors import SlackApiError

from ...domain.entities import OriginatingMessageRef, ThreadMessage
from ...resilience.backoff import RetryableError

if TYPE_CHECKING:
    from slack_sdk import WebClient


class SlackGatewayAdapter:
    """Slack WebClient-backed :class:`SlackGateway`."""

    def __init__(self, client: WebClient) -> None:
        self._client = client

    def fetch_thread(self, channel_id: str, thread_ts: str) -> list[ThreadMessage]:
        """Fetch prior thread replies in chronological order (BR-005, fetch-not-store)."""
        try:
            response = self._client.conversations_replies(channel=channel_id, ts=thread_ts)
        except SlackApiError as err:
            raise self._map_error(err) from err
        messages = response.get("messages") or []
        result: list[ThreadMessage] = []
        for msg in messages:
            result.append(
                ThreadMessage(
                    author_id=str(msg.get("user") or msg.get("bot_id") or ""),
                    text=str(msg.get("text") or ""),
                    ts=str(msg.get("ts") or ""),
                )
            )
        return result

    def post_message(self, ref: OriginatingMessageRef, text: str) -> str:
        """Post a message into the originating thread; return the posted message ts."""
        try:
            response = self._client.chat_postMessage(
                channel=ref.channel_id,
                text=text,
                thread_ts=ref.thread_ts or ref.message_ts,
            )
        except SlackApiError as err:
            raise self._map_error(err) from err
        return str(response.get("ts") or "")

    @staticmethod
    def _map_error(err: SlackApiError) -> Exception:
        """Map a Slack rate-limit to retryable; other errors propagate as-is (BR-023)."""
        response = err.response
        if getattr(response, "status_code", None) == 429:
            retry_after = response.headers.get("Retry-After") if response.headers else None
            return RetryableError(
                "slack rate limited",
                retry_after_seconds=float(retry_after) if retry_after else None,
            )
        return err
