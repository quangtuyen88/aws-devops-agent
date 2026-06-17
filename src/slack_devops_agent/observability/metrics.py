"""Metrics emission (NFR-20) — the verification instruments for every other NFR.

Emits CloudWatch EMF-style structured metric lines to stdout (picked up by the Lambda
log → CloudWatch metric-filter pipeline). Kept dependency-free and side-effect-light so
the worker hot path is not slowed. Never carries secrets/PII (BR-026).
"""

from __future__ import annotations

import json
import sys
from typing import Literal, TextIO

Unit = Literal["Count", "Milliseconds", "Seconds", "None"]

_NAMESPACE = "SlackDevOpsAgent/UNIT-001"


class Metrics:
    """Thin EMF metric emitter. One instance per request, keyed by correlation-id."""

    def __init__(self, correlation_id: str | None = None, stream: TextIO | None = None) -> None:
        self._correlation_id = correlation_id
        self._stream = stream if stream is not None else sys.stdout

    def emit(self, name: str, value: float, unit: Unit = "Count", **dimensions: str) -> None:
        """Emit one metric value with optional dimensions in EMF format."""
        payload = {
            "_aws": {
                "CloudWatchMetrics": [
                    {
                        "Namespace": _NAMESPACE,
                        "Dimensions": [list(dimensions.keys())] if dimensions else [[]],
                        "Metrics": [{"Name": name, "Unit": unit}],
                    }
                ],
            },
            name: value,
            **dimensions,
        }
        if self._correlation_id:
            payload["correlation_id"] = self._correlation_id
        self._stream.write(json.dumps(payload, separators=(",", ":")) + "\n")

    def count(self, name: str, value: float = 1.0, **dimensions: str) -> None:
        """Emit a counter metric (e.g. failure-by-cause, degrade, recovery)."""
        self.emit(name, value, "Count", **dimensions)

    def latency_ms(self, name: str, millis: float, **dimensions: str) -> None:
        """Emit a latency metric in milliseconds (e.g. intake/full-answer histograms)."""
        self.emit(name, millis, "Milliseconds", **dimensions)
