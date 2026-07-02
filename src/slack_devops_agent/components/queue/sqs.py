"""API-INT-009 — the C-1 intake→worker enqueue adapter (Amazon SQS).

The durable, out-of-process boundary between the always-on intake role and the
independently-scalable worker role. The message body carries the job reference plus the
originating ``author_id`` (ENT-001.author-id) for adoption attribution (FR-18/BR-019); the
correlation-id is propagated as a message attribute for end-to-end tracing (NFR-20/DA-1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from .message import WorkMessage

if TYPE_CHECKING:
    from mypy_boto3_sqs.client import SQSClient


class SqsWorkQueue:
    """SQS-backed :class:`WorkQueue` producer."""

    def __init__(self, client: SQSClient, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def enqueue(
        self, job_id: UUID, identity: tuple[str, str], correlation_id: UUID, author_id: str
    ) -> None:
        """Enqueue a job reference for async processing (BR-004)."""
        message = WorkMessage(
            job_id=job_id,
            channel_id=identity[0],
            message_ts=identity[1],
            correlation_id=correlation_id,
            author_id=author_id,
        )
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=message.to_json(),
            MessageAttributes={
                "correlation_id": {
                    "DataType": "String",
                    "StringValue": str(correlation_id),
                }
            },
        )
