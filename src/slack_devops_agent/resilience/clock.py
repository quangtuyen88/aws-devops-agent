"""Injectable clock (NFR-17/NFR-19/F5).

Time-sensitive logic (per-request budget, lease staleness) must be testable without
real wall-clock waits. Components depend on the :class:`Clock` protocol; production wires
:class:`SystemClock`, tests wire :class:`FakeClock`.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """A source of monotonic elapsed time and wall-clock timestamps."""

    def monotonic(self) -> float:
        """Seconds from an arbitrary fixed point; for elapsed-time budgets."""
        ...

    def now(self) -> datetime:
        """Timezone-aware UTC wall-clock time; for durable timestamps."""
        ...

    def sleep(self, seconds: float) -> None:
        """Block for ``seconds`` (no-op-able in tests)."""
        ...


class SystemClock:
    """Real clock backed by :mod:`time`."""

    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
