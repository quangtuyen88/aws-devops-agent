"""CMP-004 — AWS Knowledge MCP Client (API-INT-004).

Wraps the external ``aws-knowledge-mcp-server`` tools (documentation-search,
regional-availability) and returns citable :class:`GroundingSource` results, or an empty
list to signal "no source" (BR-009 → the answer is marked ungrounded, never fabricated).
Rate-limit / backpressure responses map to retryable so the caller can back off (BR-023).
"""

from __future__ import annotations

import httpx

from ...domain.entities import GroundingSource
from ...resilience.backoff import RetryableError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class McpGroundingClient:
    """HTTP client for the AWS Knowledge MCP documentation tools."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        tool_name: str = "documentation-search",
        timeout_seconds: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._tool_name = tool_name
        self._timeout = timeout_seconds
        self._client = client

    def ground(self, query: str) -> list[GroundingSource]:
        """Return zero-or-more citable sources for ``query`` (empty ⇒ ungrounded)."""
        client = self._client or httpx.Client(timeout=self._timeout)
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            response = client.post(
                f"{self._base_url}/tools/{self._tool_name}",
                json={"query": query},
                headers=headers,
            )
        except httpx.HTTPError as err:
            raise RetryableError(f"mcp transport error: {err}") from err
        finally:
            if self._client is None:
                client.close()

        if response.status_code in _RETRYABLE_STATUS:
            retry_after = response.headers.get("Retry-After")
            raise RetryableError(
                f"mcp {response.status_code}",
                retry_after_seconds=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 400:
            # A hard error is treated as "no source" rather than fabricating (BR-009).
            return []
        return self._parse(response.json())

    def _parse(self, body: dict[str, object]) -> list[GroundingSource]:
        """Parse MCP tool results into validated grounding sources."""
        results = body.get("results")
        if not isinstance(results, list):
            return []
        sources: list[GroundingSource] = []
        for entry in results:
            if not isinstance(entry, dict):
                continue
            title = entry.get("title")
            url = entry.get("url")
            if not isinstance(title, str) or not isinstance(url, str):
                continue
            snippet = entry.get("snippet")
            sources.append(
                GroundingSource(
                    title=title,
                    url=url,
                    snippet=snippet if isinstance(snippet, str) else None,
                    tool_name=self._tool_name,
                )
            )
        return sources
