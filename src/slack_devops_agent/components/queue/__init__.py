"""API-INT-009 — the C-1 intake→worker queue adapter."""

from __future__ import annotations

from .message import WorkMessage
from .sqs import SqsWorkQueue

__all__ = ["SqsWorkQueue", "WorkMessage"]
