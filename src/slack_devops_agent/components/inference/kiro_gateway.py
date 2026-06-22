"""CMP-003 — Kiro-gateway inference backend (HTTP-client-only, A-1 primary).

IMPORTANT (AGPL boundary, Q3=a): this module is an OpenAI-compatible HTTP **client** to
the kiro-gateway's ``POST /v1/chat/completions`` (bearer ``PROXY_API_KEY``). The gateway
itself is an external, **unmodified** third-party AGPL-3.0 container operated separately —
it is **never** vendored, forked, or imported into this codebase. Do not add the gateway's
source here; doing so would extend AGPL source-disclosure obligations to this repo. Keep
this strictly a client integration behind the CMP-003 seam.
"""

from __future__ import annotations

import httpx

from ...domain.entities import InferenceExchange
from ...resilience.backoff import RetryableError
from .provider import InferenceFailureError

_BACKEND_ID = "kiro"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class KiroGatewayBackend:
    """OpenAI-compatible HTTP client for the external kiro-gateway."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 25.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._client = client

    @property
    def backend_id(self) -> str:
        return _BACKEND_ID

    def run_inference(self, prompt_input: str, system: str | None = None) -> InferenceExchange:
        """POST one chat completion. Maps 429/5xx to retryable; others to typed failure.

        ``system`` is sent as a leading ``system`` message (outranks user content) so the
        operator guardrail cannot be overridden by instructions inside ``prompt_input``.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt_input})
        payload = {"model": self._model, "messages": messages}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            response = client.post(
                f"{self._base_url}/v1/chat/completions", json=payload, headers=headers
            )
        except httpx.HTTPError as err:  # network/timeout
            raise RetryableError(f"kiro-gateway transport error: {err}") from err
        finally:
            if self._client is None:
                client.close()

        if response.status_code in _RETRYABLE_STATUS:
            retry_after = response.headers.get("Retry-After")
            raise RetryableError(
                f"kiro-gateway {response.status_code}",
                retry_after_seconds=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 400:
            raise InferenceFailureError(
                f"kiro-gateway returned {response.status_code}", backend_id=_BACKEND_ID
            )

        return self._normalise(response.json())

    def _normalise(self, body: dict[str, object]) -> InferenceExchange:
        """Normalise an OpenAI-shaped response into an :class:`InferenceExchange`."""
        choices = body.get("choices")
        output: str | None = None
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    output = content if isinstance(content, str) else None
        usage_obj = body.get("usage")
        tokens = 0
        if isinstance(usage_obj, dict):
            total = usage_obj.get("total_tokens")
            tokens = int(total) if isinstance(total, int) else 0
        if output is None or not output.strip():
            # Empty/whitespace content (e.g. a reasoning-only response, or an unknown model id)
            # must never post a blank answer — route to the FR-17 failure path instead.
            raise InferenceFailureError(
                "kiro-gateway response had empty message content", backend_id=_BACKEND_ID
            )
        return InferenceExchange(
            prompt_input="",  # never echo the raw prompt back into the transient exchange log
            model_output=output,
            token_usage=tokens,
            backend_id=_BACKEND_ID,
        )
