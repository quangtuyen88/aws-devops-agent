"""Bounded retry with exponential backoff + full jitter (NFR-15).

Base 500ms, ×2 per attempt, max 3 retries, cap 8s. Honours an explicit
``retry_after`` hint (Slack 429 / MCP backpressure, BR-023). All retries live *inside*
the per-request time budget (NFR-17) — the caller owns that outer bound.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from .clock import Clock


class RetryableError(Exception):
    """Raised by an operation to signal a transient failure worth retrying.

    ``retry_after_seconds`` carries a server backpressure hint (e.g. Slack 429).
    """

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class BackoffPolicy:
    """Exponential-backoff parameters (NFR-15)."""

    base_ms: int = 500
    max_attempts: int = 3
    cap_ms: int = 8000

    def delay_seconds(self, attempt: int, retry_after: float | None = None) -> float:
        """Full-jitter delay for a zero-based ``attempt`` index, honouring ``retry_after``."""
        exp_ms = min(self.cap_ms, self.base_ms * (2**attempt))
        # Jitter only — not used for any security/crypto decision (B311/S311 intentional).
        jittered = random.uniform(0, exp_ms) / 1000.0  # noqa: S311  # nosec B311
        if retry_after is not None:
            return max(jittered, retry_after)
        return jittered


def retry_call[T](
    operation: Callable[[], T],
    *,
    policy: BackoffPolicy,
    clock: Clock,
) -> T:
    """Invoke ``operation`` with bounded retry on :class:`RetryableError`.

    Re-raises the last :class:`RetryableError` once ``max_attempts`` retries are
    exhausted (BR-023: surface via the failure path, never silently drop). Non-retryable
    exceptions propagate immediately.
    """
    last_error: RetryableError | None = None
    for attempt in range(policy.max_attempts + 1):
        try:
            return operation()
        except RetryableError as err:
            last_error = err
            if attempt == policy.max_attempts:
                break
            clock.sleep(policy.delay_seconds(attempt, err.retry_after_seconds))
    if last_error is None:  # unreachable: the loop body runs at least once
        raise RuntimeError("retry_call completed without a result or error")
    raise last_error
