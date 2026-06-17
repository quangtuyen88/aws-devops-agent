"""Tests for CMP-004 MCP grounding client (Slice 5) — respx, no live calls."""

from __future__ import annotations

import httpx
import pytest
import respx

from slack_devops_agent.components.mcp import McpGroundingClient
from slack_devops_agent.resilience.backoff import RetryableError

BASE = "https://mcp.test"


def _client() -> McpGroundingClient:
    return McpGroundingClient(base_url=BASE, api_key="k")


@respx.mock
def test_ground_returns_sources() -> None:
    respx.post(f"{BASE}/tools/documentation-search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"title": "S3 storage classes", "url": "https://docs.aws/s3", "snippet": "..."},
                    {"title": "no-url-entry"},  # skipped — missing url
                ]
            },
        )
    )
    sources = _client().ground("s3 storage classes")
    assert len(sources) == 1
    assert sources[0].title == "S3 storage classes"
    assert sources[0].tool_name == "documentation-search"


@respx.mock
def test_no_source_returns_empty_not_fabricated() -> None:
    respx.post(f"{BASE}/tools/documentation-search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    assert _client().ground("obscure") == []


@respx.mock
def test_hard_error_is_treated_as_no_source() -> None:
    respx.post(f"{BASE}/tools/documentation-search").mock(return_value=httpx.Response(404))
    assert _client().ground("q") == []


@respx.mock
def test_rate_limit_is_retryable() -> None:
    respx.post(f"{BASE}/tools/documentation-search").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"})
    )
    with pytest.raises(RetryableError):
        _client().ground("q")
