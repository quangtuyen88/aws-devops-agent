"""Reaper Lambda (F3) — EventBridge-scheduled in-flight recovery + DLQ drain (W3).

Builds the recovery reaper and runs the stale-lease scan plus a best-effort DLQ drain.
No VPC; least-privilege access to the job table, the work queue, the DLQ, and the Slack
bot token (infra-spec §4).
"""

from __future__ import annotations

from typing import Any

import boto3
from pydantic import ValidationError
from slack_sdk import WebClient

from ..components.intake import SlackGatewayAdapter
from ..components.jobs import DynamoJobCoordinator
from ..components.queue import SqsWorkQueue, WorkMessage
from ..components.recovery import Reaper
from ..config.settings import Settings, get_settings
from ..observability.logging import configure_logging, get_logger
from ..observability.metrics import Metrics
from ..resilience.clock import SystemClock

configure_logging()
_log = get_logger(__name__)


def _build_reaper(settings: Settings) -> Reaper:
    dynamo = boto3.resource("dynamodb", region_name=settings.aws_region)
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    return Reaper(
        jobs=DynamoJobCoordinator(
            dynamo.Table(settings.processing_job_table), settings.answer_ts_gsi
        ),
        slack=SlackGatewayAdapter(WebClient(token=settings.slack_bot_token)),
        queue=SqsWorkQueue(sqs, settings.work_queue_url),
        clock=SystemClock(),
        metrics=Metrics(),
        staleness_seconds=settings.lease_staleness_seconds,
        max_attempts=settings.max_attempts,
    )


def _drain_dlq(settings: Settings) -> list[tuple[str, str]]:
    """Receive and delete DLQ messages, returning their job identities."""
    if not settings.dlq_url:
        return []
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    identities: list[tuple[str, str]] = []
    response = sqs.receive_message(QueueUrl=settings.dlq_url, MaxNumberOfMessages=10)
    for message in response.get("Messages", []):
        try:
            work_message = WorkMessage.from_json(message.get("Body") or "{}")
            identities.append((work_message.channel_id, work_message.message_ts))
        except (ValueError, ValidationError):
            _log.warning("skipping malformed DLQ message")
            continue
        sqs.delete_message(QueueUrl=settings.dlq_url, ReceiptHandle=message["ReceiptHandle"])
    return identities


def lambda_handler(_event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    """EventBridge entrypoint. Runs stale-lease recovery and DLQ drain."""
    settings = get_settings()
    reaper = _build_reaper(settings)
    recovered = reaper.recover_stale()
    drained = reaper.drain_dead_letters(_drain_dlq(settings))
    _log.info("reaper run complete", extra={"recovered": len(recovered), "drained": len(drained)})
    return {"recovered": len(recovered), "drained": len(drained)}
