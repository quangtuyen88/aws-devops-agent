"""CMP-003 — Amazon Bedrock inference backend (A-1 config-switchable alternate).

Uses the boto3 ``bedrock-runtime`` ``Converse`` API behind the same CMP-003 interface as
the Kiro-gateway backend, so the agent core is invariant to which backend serves a
request (selected by ``INFERENCE_BACKEND``). Carries no AGPL obligation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError

from ...domain.entities import InferenceExchange
from ...resilience.backoff import RetryableError
from .provider import InferenceFailureError

if TYPE_CHECKING:
    from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

_BACKEND_ID = "bedrock"
_THROTTLE_CODES = {"ThrottlingException", "TooManyRequestsException", "ServiceUnavailable"}


class BedrockBackend:
    """Bedrock ``Converse`` client implementing the CMP-003 inference seam."""

    def __init__(self, client: BedrockRuntimeClient, model_id: str) -> None:
        self._client = client
        self._model_id = model_id

    @property
    def backend_id(self) -> str:
        return _BACKEND_ID

    def run_inference(self, prompt_input: str) -> InferenceExchange:
        """Invoke Bedrock Converse; map throttling to retryable, else typed failure."""
        try:
            response = self._client.converse(
                modelId=self._model_id,
                messages=[{"role": "user", "content": [{"text": prompt_input}]}],
            )
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            if code in _THROTTLE_CODES:
                raise RetryableError(f"bedrock throttled: {code}") from err
            raise InferenceFailureError(
                f"bedrock ClientError: {code}", backend_id=_BACKEND_ID
            ) from err
        return self._normalise(dict(response))

    def _normalise(self, response: dict[str, Any]) -> InferenceExchange:
        """Normalise a Converse response into an :class:`InferenceExchange`."""
        output = None
        content = response.get("output", {}).get("message", {}).get("content", [])
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text")
                output = text if isinstance(text, str) else None
        usage = response.get("usage", {})
        tokens = int(usage.get("totalTokens", 0)) if isinstance(usage, dict) else 0
        if output is None:
            raise InferenceFailureError(
                "bedrock response missing message content", backend_id=_BACKEND_ID
            )
        return InferenceExchange(
            prompt_input="",
            model_output=output,
            token_usage=tokens,
            backend_id=_BACKEND_ID,
        )
