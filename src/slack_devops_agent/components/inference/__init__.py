"""CMP-003 — Inference Provider (A-1 backend-agnostic seam)."""

from __future__ import annotations

from .provider import InferenceFailureError, build_inference_provider

__all__ = ["InferenceFailureError", "build_inference_provider"]
