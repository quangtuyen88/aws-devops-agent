"""CMP-001 — Slack event parsing (API-EXT-001/005).

Translates raw Slack Events API envelopes into the unit's transient boundary entities
(:class:`InboundMention`, :class:`ReactionEvent`), isolating the external Slack contract
so internal entities stay stable. Pure parsing — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from ...domain.entities import InboundMention, ReactionEvent
from ...domain.enums import EventAction, ReactionKind

_POSITIVE_EMOJI = {"+1", "thumbsup", "thumbsup_all"}
_NEGATIVE_EMOJI = {"-1", "thumbsdown"}

# Reviewable text/IaC attachments only — never binaries/images/archives (which would feed junk
# bytes into the prompt). Matched on the file name suffix and Slack's filetype.
_REVIEWABLE_SUFFIXES = (".yaml", ".yml", ".json", ".tf", ".hcl", ".txt", ".md", ".template", ".csv")
_REVIEWABLE_FILETYPES = {"yaml", "yml", "json", "tf", "hcl", "text", "markdown", "template", "csv"}
# 256 KB cap so a large upload can't blow the prompt budget or Lambda memory.
MAX_ATTACHED_FILE_BYTES = 262144


class FileReject(StrEnum):
    """Why a candidate attachment was not accepted (drives the user-facing notice)."""

    WRONG_TYPE = "wrong-type"
    OVERSIZE = "oversize"


@dataclass(frozen=True)
class ReviewableFile:
    """A validated, downloadable attachment reference (no content yet)."""

    name: str
    download_url: str
    size: int


def pick_reviewable_file(
    event: dict[str, object], max_bytes: int = MAX_ATTACHED_FILE_BYTES
) -> ReviewableFile | FileReject | None:
    """Select the first attachment worth reviewing, or a rejection reason, or None.

    Pure (no IO): validates the file's type (allowlist) and size against ``max_bytes`` so the
    handler can download only safe, bounded files. Returns ``None`` when the message carries no
    files at all; a :class:`FileReject` when a file is present but unsupported/oversize.
    """
    files = event.get("files")
    if not isinstance(files, list) or not files:
        return None
    oversize = False
    for entry in files:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        filetype = str(entry.get("filetype") or "").lower()
        if not (name.lower().endswith(_REVIEWABLE_SUFFIXES) or filetype in _REVIEWABLE_FILETYPES):
            continue
        url = str(entry.get("url_private_download") or entry.get("url_private") or "")
        size = int(entry["size"]) if str(entry.get("size") or "").isdigit() else 0
        if size > max_bytes:
            oversize = True
            continue
        if url:
            return ReviewableFile(name=name, download_url=url, size=size)
    if oversize:
        return FileReject.OVERSIZE
    return FileReject.WRONG_TYPE


def parse_mention(event: dict[str, object], bot_user_id: str, retry_num: int = 0) -> InboundMention:
    """Parse a Slack ``app_mention`` / ``message`` event into an :class:`InboundMention`.

    ``is_bot_author`` is set when the event carries a ``bot_id``/bot subtype or the author
    is the bot itself (BR-002). The mention check itself is applied by the handler (BR-003).
    """
    text = str(event.get("text") or "")
    author_id = str(event.get("user") or "")
    is_bot = (
        bool(event.get("bot_id"))
        or event.get("subtype") == "bot_message"
        or (author_id == bot_user_id and bot_user_id != "")
    )
    thread_ts_raw = event.get("thread_ts")
    return InboundMention(
        correlation_id=uuid4(),
        channel_id=str(event.get("channel") or ""),
        thread_ts=str(thread_ts_raw) if thread_ts_raw else None,
        message_ts=str(event.get("ts") or ""),
        author_id=author_id,
        is_bot_author=is_bot,
        raw_text=text,
        slack_retry_num=retry_num,
    )


def mentions_bot(text: str, bot_user_id: str) -> bool:
    """BR-003 — whether ``text`` contains a valid @mention of the bot."""
    return f"<@{bot_user_id}>" in text


def parse_reaction(event: dict[str, object]) -> ReactionEvent | None:
    """Parse a ``reaction_added`` / ``reaction_removed`` event (BR-018).

    Returns ``None`` for non-👍/👎 reactions or events without a message target — those
    are silently ignored.
    """
    emoji = str(event.get("reaction") or "")
    if emoji in _POSITIVE_EMOJI:
        kind = ReactionKind.POSITIVE
    elif emoji in _NEGATIVE_EMOJI:
        kind = ReactionKind.NEGATIVE
    else:
        return None

    item = event.get("item")
    if not isinstance(item, dict) or item.get("type") != "message":
        return None
    answer_ts = item.get("ts")
    if not answer_ts:
        return None

    action = EventAction.ADDED if event.get("type") == "reaction_added" else EventAction.REMOVED
    return ReactionEvent(
        answer_message_ts=str(answer_ts),
        reactor_id=str(event.get("user") or ""),
        reaction_kind=kind,
        event_action=action,
    )
