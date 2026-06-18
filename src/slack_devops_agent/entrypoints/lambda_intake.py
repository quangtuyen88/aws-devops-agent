"""Intake Lambda (CMP-001 role) — API Gateway → Slack Events ingress (W1/W4).

Verifies the Slack request signature, answers the url_verification challenge, then routes
mention/reaction events to the intake handler. Returns HTTP 200 fast (NFR-1); the heavy
work is enqueued for the worker. Slack at-least-once redelivery is absorbed by de-dup
(BR-010), so we always 200 once the signature is valid.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from slack_sdk.signature import SignatureVerifier

from ..config.settings import get_settings
from ..observability.logging import configure_logging, get_logger
from .dispatch import dispatch_slack_event
from .wiring import build_intake_handler

configure_logging()
_log = get_logger(__name__)


def _response(status: int, body: str = "") -> dict[str, Any]:
    return {"statusCode": status, "body": body}


def lambda_handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    """API Gateway proxy entrypoint for the Slack Events API."""
    settings = get_settings()
    raw_body = event.get("body") or ""
    # API Gateway HTTP API may base64-encode the body; Slack signs the raw bytes, so decode
    # before verifying or the HMAC never matches (BR-: signature over the exact payload).
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    verifier = SignatureVerifier(signing_secret=settings.slack_signing_secret)
    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")
    if not verifier.is_valid(raw_body, timestamp, signature):
        _log.warning(
            "rejected Slack request with invalid signature",
            extra={
                "is_base64": bool(event.get("isBase64Encoded")),
                "body_len": len(raw_body),
                "ts": timestamp,
                "sig_recv_prefix": signature[:10],
                "sig_calc_prefix": (
                    verifier.generate_signature(timestamp=timestamp, body=raw_body) or ""
                )[:10],
                "secret_len": len(settings.slack_signing_secret),
            },
        )
        return _response(401, "invalid signature")

    envelope = json.loads(raw_body) if raw_body else {}

    # Slack URL verification handshake.
    if envelope.get("type") == "url_verification":
        return _response(200, json.dumps({"challenge": envelope.get("challenge", "")}))

    retry_num = int(headers.get("x-slack-retry-num", "0") or "0")
    handler = build_intake_handler(settings)
    try:
        outcome = dispatch_slack_event(
            envelope, handler, settings.slack_bot_user_id, retry_num=retry_num
        )
        _log.info("intake dispatched", extra={"outcome": outcome.value if outcome else "none"})
    except Exception:
        # Always 200 to Slack once verified; redelivery would just re-dedup. Log for ops.
        _log.exception("intake handler error")
    return _response(200)
