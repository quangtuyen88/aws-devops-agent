"""Structured JSON logging keyed by correlation-id, with redaction (NFR-6/BR-026).

Logs carry the correlation-id (DA-1) and redacted descriptors only — never raw secrets,
credentials, or user-pasted content. The :func:`redact` helper scrubs known secret
shapes before anything reaches a log sink, so even an accidental ``raw_text`` log is safe.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

# Coarse redaction patterns — defence in depth on top of never-logging raw content.
_REDACTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),  # Slack tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),  # bearer tokens
)
_REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Scrub known secret shapes from ``text`` before it can reach a log sink."""
    scrubbed = text
    for pattern in _REDACTION_PATTERNS:
        scrubbed = pattern.sub(_REDACTED, scrubbed)
    return scrubbed


class _JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON with structured ``extra`` fields."""

    _RESERVED = frozenset(
        vars(logging.makeLogRecord({})).keys() | {"message", "asctime", "taskName"}
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = redact(value) if isinstance(value, str) else value
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        handler.setFormatter(_JsonFormatter())
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        root.addHandler(handler)


def get_logger(
    name: str, correlation_id: str | None = None
) -> logging.LoggerAdapter[logging.Logger]:
    """Return a logger adapter that stamps ``correlation_id`` (DA-1) on every record."""
    extra = {"correlation_id": correlation_id} if correlation_id else {}
    return logging.LoggerAdapter(logging.getLogger(name), extra)
