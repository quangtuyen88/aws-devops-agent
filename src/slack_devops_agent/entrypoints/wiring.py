"""Composition root — build the intake handler, worker, and reaper from configuration.

Keeps all concrete-adapter construction (DynamoDB resources, SQS/Slack clients, the
selected inference backend) in one place so the Lambda entrypoints stay thin. Each
builder reads :class:`Settings` and wires the ports to their adapters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from slack_sdk import WebClient

from ..components.config import DynamoConfigStore
from ..components.inference import build_inference_provider
from ..components.intake import IntakeHandler, SlackGatewayAdapter
from ..components.jobs import DynamoJobCoordinator
from ..components.mcp import McpGroundingClient
from ..components.opdata import DynamoOperationalData
from ..components.queue import SqsWorkQueue
from ..components.recovery import Reaper
from ..components.safety import SecretScanner
from ..components.worker import DefaultAnswerComposer, Worker, WorkerConfig
from ..config.settings import Settings
from ..observability.metrics import Metrics
from ..resilience.clock import SystemClock

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource


def _shared(
    settings: Settings,
) -> tuple[DynamoDBServiceResource, DynamoJobCoordinator, SlackGatewayAdapter, SystemClock]:
    """Build the dynamo resource, job coordinator, Slack gateway, and clock every builder needs."""
    dynamo = boto3.resource("dynamodb", region_name=settings.aws_region)
    jobs = DynamoJobCoordinator(dynamo.Table(settings.processing_job_table), settings.answer_ts_gsi)
    slack = SlackGatewayAdapter(WebClient(token=settings.slack_bot_token))
    return dynamo, jobs, slack, SystemClock()


def build_intake_handler(settings: Settings, *, correlation_id: str | None = None) -> IntakeHandler:
    """Construct the CMP-001 intake handler with its DynamoDB/SQS/Slack adapters."""
    dynamo, jobs, slack, clock = _shared(settings)
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    return IntakeHandler(
        config=DynamoConfigStore(
            dynamo.Table(settings.config_table), default_per_period_limit=settings.per_period_limit
        ),
        jobs=jobs,
        slack=slack,
        queue=SqsWorkQueue(sqs, settings.work_queue_url),
        opdata=DynamoOperationalData(
            dynamo.Table(settings.operational_data_table),
            clock,
            period_definition=settings.period_definition,
        ),
        clock=clock,
        bot_user_id=settings.slack_bot_user_id,
        metrics=Metrics(correlation_id=correlation_id),
    )


def build_worker(settings: Settings, *, correlation_id: str | None = None) -> Worker:
    """Construct the CMP-002 worker with its adapters and the configured inference backend."""
    dynamo, jobs, slack, clock = _shared(settings)
    return Worker(
        jobs=jobs,
        slack=slack,
        safety=SecretScanner(),
        inference=build_inference_provider(settings),
        grounding=McpGroundingClient(settings.mcp_base_url, settings.mcp_api_key),
        opdata=DynamoOperationalData(
            dynamo.Table(settings.operational_data_table),
            clock,
            period_definition=settings.period_definition,
        ),
        config_store=DynamoConfigStore(
            dynamo.Table(settings.config_table), default_per_period_limit=settings.per_period_limit
        ),
        composer=DefaultAnswerComposer(),
        clock=clock,
        metrics=Metrics(correlation_id=correlation_id),
        config=WorkerConfig(
            time_budget_seconds=settings.request_time_budget_seconds,
            lease_staleness_seconds=settings.lease_staleness_seconds,
            max_attempts=settings.max_attempts,
            max_inference_calls=settings.max_inference_calls,
            max_mcp_calls=settings.max_mcp_calls,
            max_input_tokens=settings.max_input_tokens,
            heartbeat_seconds=settings.heartbeat_seconds,
            retry_base_ms=settings.retry_base_ms,
            retry_max_attempts=settings.retry_max_attempts,
            retry_cap_ms=settings.retry_cap_ms,
            breaker_failure_threshold=settings.breaker_failure_threshold,
            breaker_reset_seconds=settings.breaker_reset_seconds,
        ),
    )


def build_reaper(settings: Settings) -> Reaper:
    """Construct the F3 recovery reaper (stale-lease scan; the DLQ drain stays Lambda-side)."""
    _dynamo, jobs, slack, clock = _shared(settings)
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    return Reaper(
        jobs=jobs,
        slack=slack,
        queue=SqsWorkQueue(sqs, settings.work_queue_url),
        clock=clock,
        metrics=Metrics(),
        staleness_seconds=settings.lease_staleness_seconds,
        max_attempts=settings.max_attempts,
    )
