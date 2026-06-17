"""Per-dependency circuit breaker (NFR-16).

Opens after a threshold of consecutive failures so a sustained-down dependency
fails fast (<1s) to the FR-17 message instead of burning the 30s budget. A half-open
probe is allowed after the reset window; a success closes the breaker.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from .clock import Clock


class BreakerState(StrEnum):
    """Circuit-breaker states (exposed as the NFR-20 breaker gauge)."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the breaker is open (fail fast)."""


class CircuitBreaker:
    """A single dependency's breaker. Not thread-safe; one per worker invocation."""

    def __init__(
        self,
        name: str,
        clock: Clock,
        *,
        failure_threshold: int = 5,
        reset_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self._clock = clock
        self._failure_threshold = failure_threshold
        self._reset_seconds = reset_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._state = BreakerState.CLOSED

    @property
    def state(self) -> BreakerState:
        """Current state, transitioning OPEN→HALF_OPEN once the reset window elapses."""
        if (
            self._state == BreakerState.OPEN
            and self._opened_at is not None
            and self._clock.monotonic() - self._opened_at >= self._reset_seconds
        ):
            self._state = BreakerState.HALF_OPEN
        return self._state

    def call[T](self, operation: Callable[[], T]) -> T:
        """Run ``operation`` through the breaker.

        Raises :class:`CircuitOpenError` immediately when open. On success the breaker
        closes; on failure it records the failure and may open.
        """
        if self.state == BreakerState.OPEN:
            raise CircuitOpenError(f"circuit '{self.name}' is open")
        try:
            result = operation()
        except Exception:
            self._record_failure()
            raise
        self._record_success()
        return result

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None
        self._state = BreakerState.CLOSED

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._state = BreakerState.OPEN
            self._opened_at = self._clock.monotonic()
