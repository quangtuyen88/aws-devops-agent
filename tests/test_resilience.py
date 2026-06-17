"""Tests for cross-cutting resilience and observability (Slice 2)."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime

import pytest

from slack_devops_agent.observability.logging import redact
from slack_devops_agent.observability.metrics import Metrics
from slack_devops_agent.resilience.backoff import (
    BackoffPolicy,
    RetryableError,
    retry_call,
)
from slack_devops_agent.resilience.circuit_breaker import (
    BreakerState,
    CircuitBreaker,
    CircuitOpenError,
)
from slack_devops_agent.resilience.time_budget import (
    TimeBudget,
    TimeBudgetExceededError,
)


class FakeClock:
    """Deterministic clock for time-sensitive tests (NFR-19/F5)."""

    def __init__(self, start: float = 1000.0) -> None:
        self._mono = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._mono

    def now(self) -> datetime:
        return datetime(2026, 6, 17, 12, 0, 0, tzinfo=UTC)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._mono += seconds

    def advance(self, seconds: float) -> None:
        self._mono += seconds


# --- Backoff (NFR-15) ------------------------------------------------------


def test_retry_succeeds_after_transient_failures() -> None:
    clock = FakeClock()
    calls = {"n": 0}

    def op() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RetryableError("transient")
        return "ok"

    result = retry_call(op, policy=BackoffPolicy(max_attempts=3), clock=clock)
    assert result == "ok"
    assert calls["n"] == 3
    assert len(clock.sleeps) == 2  # slept before the 2 retries


def test_retry_exhausts_and_reraises() -> None:
    clock = FakeClock()

    def op() -> str:
        raise RetryableError("always")

    with pytest.raises(RetryableError):
        retry_call(op, policy=BackoffPolicy(max_attempts=2), clock=clock)
    assert len(clock.sleeps) == 2


def test_backoff_delay_is_capped_and_honours_retry_after() -> None:
    policy = BackoffPolicy(base_ms=500, cap_ms=8000)
    # cap: attempt 10 would be huge but jitter range is capped at 8s
    assert policy.delay_seconds(10) <= 8.0
    # retry_after floor honoured
    assert policy.delay_seconds(0, retry_after=5.0) >= 5.0


# --- Circuit breaker (NFR-16) ----------------------------------------------


def test_breaker_opens_after_threshold_then_half_opens() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker("dep", clock, failure_threshold=3, reset_seconds=30)

    def failing() -> None:
        raise RuntimeError("down")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call(failing)
    assert breaker.state == BreakerState.OPEN

    # fail fast while open
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "x")

    # half-open after reset window
    clock.advance(30)
    assert breaker.state == BreakerState.HALF_OPEN
    assert breaker.call(lambda: "recovered") == "recovered"
    assert breaker.state == BreakerState.CLOSED


# --- Time budget (NFR-17) --------------------------------------------------


def test_time_budget_trips_when_exhausted() -> None:
    clock = FakeClock()
    budget = TimeBudget(clock, budget_seconds=30)
    assert not budget.is_exhausted
    budget.check()
    clock.advance(30)
    assert budget.is_exhausted
    with pytest.raises(TimeBudgetExceededError):
        budget.check()


# --- Redaction + metrics (NFR-6/NFR-20) ------------------------------------


def test_redact_scrubs_known_secret_shapes() -> None:
    assert "AKIA" not in redact("key AKIAIOSFODNN7EXAMPLE here")
    assert "xoxb" not in redact("token xoxb-12345-abcde")
    assert "[REDACTED]" in redact("Authorization: Bearer abc.def.ghi")


def test_metrics_emit_emf_line() -> None:
    stream = io.StringIO()
    metrics = Metrics(correlation_id="cid-1", stream=stream)
    metrics.count("failure_by_cause", 1.0, cause="timeout")
    line = stream.getvalue().strip()
    payload = json.loads(line)
    assert payload["failure_by_cause"] == 1.0
    assert payload["cause"] == "timeout"
    assert payload["correlation_id"] == "cid-1"
    assert payload["_aws"]["CloudWatchMetrics"][0]["Namespace"].startswith("SlackDevOpsAgent")
