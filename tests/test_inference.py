"""Tests for CMP-003 inference backends (Slice 4). No live calls — respx + stubs."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from botocore.exceptions import ClientError

from slack_devops_agent.components.inference.bedrock import BedrockBackend
from slack_devops_agent.components.inference.kiro_gateway import KiroGatewayBackend
from slack_devops_agent.components.inference.provider import (
    InferenceFailureError,
    build_inference_provider,
)
from slack_devops_agent.config.settings import Settings
from slack_devops_agent.resilience.backoff import RetryableError

BASE = "http://kiro-gateway.test"


def _kiro() -> KiroGatewayBackend:
    return KiroGatewayBackend(base_url=BASE, api_key="k", model="m")


@respx.mock
def test_kiro_happy_path_normalises_output_and_usage() -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "use 3 AZs"}}],
                "usage": {"total_tokens": 123},
            },
        )
    )
    exchange = _kiro().run_inference("how many AZs?")
    assert exchange.model_output == "use 3 AZs"
    assert exchange.token_usage == 123
    assert exchange.backend_id == "kiro"


@respx.mock
def test_kiro_system_prompt_is_sent_first() -> None:
    route = respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}}
        )
    )
    _kiro().run_inference("how many AZs?", system="GUARDRAIL")
    body = json.loads(route.calls.last.request.content)
    assert body["messages"][0] == {"role": "system", "content": "GUARDRAIL"}
    assert body["messages"][1] == {"role": "user", "content": "how many AZs?"}


@respx.mock
def test_kiro_no_system_omits_system_message() -> None:
    route = respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}}
        )
    )
    _kiro().run_inference("q")
    body = json.loads(route.calls.last.request.content)
    assert [m["role"] for m in body["messages"]] == ["user"]


@respx.mock
def test_kiro_429_is_retryable_with_retry_after() -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "2"})
    )
    with pytest.raises(RetryableError) as exc:
        _kiro().run_inference("q")
    assert exc.value.retry_after_seconds == 2.0


@respx.mock
def test_kiro_400_is_typed_failure() -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(return_value=httpx.Response(400))
    with pytest.raises(InferenceFailureError):
        _kiro().run_inference("q")


@respx.mock
def test_kiro_missing_content_is_typed_failure() -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": []})
    )
    with pytest.raises(InferenceFailureError):
        _kiro().run_inference("q")


class _StubBedrockClient:
    """Minimal stub of the boto3 bedrock-runtime client's converse method."""

    def __init__(self, response: dict[str, Any] | None = None, error: ClientError | None = None):
        self._response = response
        self._error = error

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.last_kwargs = kwargs
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def test_bedrock_happy_path() -> None:
    client = _StubBedrockClient(
        response={
            "output": {"message": {"content": [{"text": "prefer Fargate"}]}},
            "usage": {"totalTokens": 77},
        }
    )
    backend = BedrockBackend(client=client, model_id="model")  # type: ignore[arg-type]
    exchange = backend.run_inference("ecs or eks?")
    assert exchange.model_output == "prefer Fargate"
    assert exchange.token_usage == 77
    assert exchange.backend_id == "bedrock"


def test_bedrock_system_prompt_passed_to_converse() -> None:
    client = _StubBedrockClient(
        response={
            "output": {"message": {"content": [{"text": "ok"}]}},
            "usage": {"totalTokens": 1},
        }
    )
    BedrockBackend(client=client, model_id="m").run_inference("q", system="GUARDRAIL")  # type: ignore[arg-type]
    assert client.last_kwargs["system"] == [{"text": "GUARDRAIL"}]


def test_bedrock_throttle_is_retryable() -> None:
    err = ClientError({"Error": {"Code": "ThrottlingException"}}, "Converse")
    backend = BedrockBackend(client=_StubBedrockClient(error=err), model_id="m")  # type: ignore[arg-type]
    with pytest.raises(RetryableError):
        backend.run_inference("q")


def test_bedrock_other_error_is_typed_failure() -> None:
    err = ClientError({"Error": {"Code": "AccessDeniedException"}}, "Converse")
    backend = BedrockBackend(client=_StubBedrockClient(error=err), model_id="m")  # type: ignore[arg-type]
    with pytest.raises(InferenceFailureError):
        backend.run_inference("q")


def test_factory_selects_backend_behind_the_seam() -> None:
    kiro = build_inference_provider(
        Settings(INFERENCE_BACKEND="kiro", KIRO_GATEWAY_BASE_URL=BASE, PROXY_API_KEY="k")  # type: ignore[call-arg]
    )
    assert kiro.backend_id == "kiro"
    with pytest.raises(ValueError):
        build_inference_provider(Settings(INFERENCE_BACKEND="unknown"))  # type: ignore[call-arg]
