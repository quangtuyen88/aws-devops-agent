"""CMP-003 — inference provider error type + backend factory (API-INT-001).

The backend-agnostic seam (A-1): the worker depends only on the :class:`InferenceProvider`
port. ``build_inference_provider`` selects the concrete backend from configuration
(Kiro-gateway primary, Bedrock alternate) without the agent core ever seeing backend
specifics beyond ``backend_id``.
"""

from __future__ import annotations

from ...config.settings import Settings
from ...ports import InferenceProvider


class InferenceFailureError(Exception):
    """Typed, non-retryable inference failure → routes to the FR-17 failure path (BR-013).

    ``model_output`` is absent on this path; the worker resolves the job ``failed`` with
    ``failure-by-cause=dependency``.
    """

    def __init__(self, message: str, backend_id: str) -> None:
        super().__init__(message)
        self.backend_id = backend_id


def build_inference_provider(settings: Settings) -> InferenceProvider:
    """Build the configured inference backend (Kiro primary / Bedrock alternate).

    Imports are local so selecting one backend never requires the other's SDK at import
    time (e.g. a Kiro-only deployment does not import boto3 bedrock-runtime).
    """
    backend = settings.inference_backend.lower()
    if backend == "kiro":
        from .kiro_gateway import KiroGatewayBackend

        return KiroGatewayBackend(
            base_url=settings.kiro_gateway_base_url,
            api_key=settings.proxy_api_key,
            model=settings.kiro_model,
            timeout_seconds=settings.kiro_timeout_seconds,
        )
    if backend == "bedrock":
        import boto3

        from .bedrock import BedrockBackend

        client = boto3.client("bedrock-runtime", region_name=settings.bedrock_region)
        return BedrockBackend(client=client, model_id=settings.bedrock_model_id)
    raise ValueError(f"unknown INFERENCE_BACKEND: {settings.inference_backend!r}")
