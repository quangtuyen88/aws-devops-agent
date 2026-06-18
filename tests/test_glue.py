"""Tests for adapter glue: Slack gateway, intake Lambda edges, JSON log redaction."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest
import respx
from slack_sdk.errors import SlackApiError

from slack_devops_agent.components.intake.slack_gateway import SlackGatewayAdapter
from slack_devops_agent.domain.entities import OriginatingMessageRef
from slack_devops_agent.entrypoints import lambda_intake
from slack_devops_agent.observability.logging import configure_logging, get_logger
from slack_devops_agent.resilience.backoff import RetryableError


class _FakeResponse:
    def __init__(self, data: dict[str, Any], status_code: int = 200, headers: dict | None = None):
        self._data = data
        self.status_code = status_code
        self.headers = headers or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class _FakeWebClient:
    def __init__(self, replies: dict[str, Any] | None = None, error: SlackApiError | None = None):
        self._replies = replies or {"messages": []}
        self._error = error
        self.posted: list[dict[str, Any]] = []
        self.token = "xoxb-fake-token"  # noqa: S105  # test-only placeholder, not a real secret

    def conversations_replies(self, **kwargs: Any) -> _FakeResponse:
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._replies)

    # Mirrors the slack_sdk WebClient method name exactly (camelCase is the SDK's API).
    def chat_postMessage(self, **kwargs: Any) -> _FakeResponse:  # noqa: N802
        self.posted.append(kwargs)
        return _FakeResponse({"ts": "posted-ts-1"})


def test_slack_gateway_fetch_and_post() -> None:
    client = _FakeWebClient(replies={"messages": [{"user": "U1", "text": "hi", "ts": "1.1"}]})
    gw = SlackGatewayAdapter(client)  # type: ignore[arg-type]
    thread = gw.fetch_thread("C1", "1.1")
    assert thread[0].text == "hi"
    ref = OriginatingMessageRef(channel_id="C1", thread_ts="1.1", message_ts="1.1", author_id="U1")
    assert gw.post_message(ref, "answer") == "posted-ts-1"
    assert client.posted[0]["channel"] == "C1"


@respx.mock
def test_slack_gateway_download_file_text_sends_bearer_and_truncates() -> None:
    url = "https://files.slack.com/private/explore-s3.yaml"
    route = respx.get(url).mock(
        return_value=httpx.Response(200, content=b"AWSTemplateFormatVersion: 2010-09-09\nmore")
    )
    gw = SlackGatewayAdapter(_FakeWebClient())  # type: ignore[arg-type]
    text = gw.download_file_text(url, max_bytes=10)
    assert text == "AWSTemplat"  # truncated to max_bytes
    assert route.calls.last.request.headers["Authorization"] == "Bearer xoxb-fake-token"


@respx.mock
def test_slack_gateway_download_403_is_retryable() -> None:
    url = "https://files.slack.com/private/x.yaml"
    respx.get(url).mock(return_value=httpx.Response(403))
    gw = SlackGatewayAdapter(_FakeWebClient())  # type: ignore[arg-type]
    with pytest.raises(RetryableError):
        gw.download_file_text(url, max_bytes=1000)


def test_slack_gateway_maps_rate_limit_to_retryable() -> None:
    response = _FakeResponse({}, status_code=429, headers={"Retry-After": "3"})
    err = SlackApiError("ratelimited", response)  # type: ignore[arg-type]
    gw = SlackGatewayAdapter(_FakeWebClient(error=err))  # type: ignore[arg-type]
    with pytest.raises(RetryableError) as exc:
        gw.fetch_thread("C1", "1.1")
    assert exc.value.retry_after_seconds == 3.0


# --- intake Lambda edges (no AWS construction on these paths) --------------


def test_intake_lambda_rejects_invalid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lambda_intake.SignatureVerifier, "is_valid", lambda *a, **k: False)
    result = lambda_intake.lambda_handler({"body": "{}", "headers": {}})
    assert result["statusCode"] == 401


def test_intake_lambda_answers_url_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lambda_intake.SignatureVerifier, "is_valid", lambda *a, **k: True)
    body = json.dumps({"type": "url_verification", "challenge": "abc123"})
    result = lambda_intake.lambda_handler({"body": body, "headers": {}})
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["challenge"] == "abc123"


# --- JSON log redaction (NFR-6/BR-026) -------------------------------------


def test_json_logging_redacts_secrets() -> None:
    from slack_devops_agent.observability.logging import _JsonFormatter

    record = logging.LogRecord(
        name="test.redaction",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="user pasted AKIAIOSFODNN7EXAMPLE in the thread",
        args=(),
        exc_info=None,
    )
    record.correlation_id = "cid-9"
    payload = json.loads(_JsonFormatter().format(record))
    assert "AKIA" not in payload["message"]
    assert payload["correlation_id"] == "cid-9"
    # configure_logging must be installable without raising (idempotent install path).
    configure_logging(level=logging.INFO)
    assert get_logger("x", correlation_id="c").extra == {"correlation_id": "c"}
