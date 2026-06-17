"""Per-request wall-clock time budget (NFR-17).

The outer 30s bound on a single request, aligned to NFR-2. On exhaustion the job
resolves ``failed`` with ``failure-by-cause=timeout`` (BR-013). All retries and tool
calls run *inside* this budget. Uses the injected monotonic clock so the trip is
deterministically testable.
"""

from __future__ import annotations

from .clock import Clock


class TimeBudgetExceededError(Exception):
    """Raised when the per-request time budget is exhausted."""


class TimeBudget:
    """A monotonic countdown started at construction."""

    def __init__(self, clock: Clock, budget_seconds: float) -> None:
        self._clock = clock
        self._budget_seconds = budget_seconds
        self._start = clock.monotonic()

    @property
    def elapsed_seconds(self) -> float:
        """Seconds elapsed since the budget started."""
        return self._clock.monotonic() - self._start

    @property
    def remaining_seconds(self) -> float:
        """Seconds left before the budget trips (clamped at 0)."""
        return max(0.0, self._budget_seconds - self.elapsed_seconds)

    @property
    def is_exhausted(self) -> bool:
        """True once no budget remains."""
        return self.remaining_seconds <= 0.0

    def check(self) -> None:
        """Raise :class:`TimeBudgetExceededError` if the budget is exhausted."""
        if self.is_exhausted:
            raise TimeBudgetExceededError(
                f"per-request time budget of {self._budget_seconds}s exhausted"
            )
