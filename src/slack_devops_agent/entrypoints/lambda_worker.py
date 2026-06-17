"""Worker Lambda (CMP-002 role) — SQS → async agent loop (W2/W3).

Configured with ``batch_size=1`` (infra-spec): one job per invocation. On an unhandled
error the record is left to SQS redelivery (visibility timeout) and ultimately the DLQ →
recovery reaper, so a question is never silently dropped (BR-013/BR-021).
"""

from __future__ import annotations

from typing import Any

from ..config.settings import get_settings
from ..observability.logging import configure_logging, get_logger
from .dispatch import parse_sqs_record
from .wiring import build_worker

configure_logging()
_log = get_logger(__name__)


def lambda_handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    """SQS entrypoint. Processes each record; reports partial batch failures to SQS."""
    settings = get_settings()
    failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        message_id = str(record.get("messageId", ""))
        try:
            identity, correlation_id, author_id = parse_sqs_record(str(record.get("body") or "{}"))
            worker = build_worker(settings, correlation_id=str(correlation_id))
            outcome = worker.process(identity, correlation_id, author_id)
            _log.info("worker processed", extra={"outcome": outcome.value})
        except Exception:
            _log.exception(
                "worker error; record will be redelivered", extra={"message_id": message_id}
            )
            failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": failures}
