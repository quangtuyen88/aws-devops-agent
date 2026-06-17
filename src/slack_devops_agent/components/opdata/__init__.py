"""CMP-007 — Operational Data Service."""

from __future__ import annotations

from .service import DynamoOperationalData, period_key

__all__ = ["DynamoOperationalData", "period_key"]
