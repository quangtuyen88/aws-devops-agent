"""Shared test fixtures: a deterministic clock and moto-backed DynamoDB tables.

Bounded-context dependencies (the unit's own DynamoDB tables) are tested against ``moto``
(Q4=a); timing races use the injected :class:`FakeClock` rather than real waits.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws


class FakeClock:
    """Deterministic, advanceable clock for time-sensitive tests (NFR-19/F5)."""

    def __init__(self, start_mono: float = 1000.0, start_wall: datetime | None = None) -> None:
        self._mono = start_mono
        self._wall = start_wall or datetime(2026, 6, 17, 12, 0, 0, tzinfo=UTC)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._mono

    def now(self) -> datetime:
        return self._wall

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._mono += seconds
        self._wall += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self._mono += seconds
        self._wall += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def dynamo() -> Iterator[boto3.resources.base.ServiceResource]:
    """Yield a moto-backed DynamoDB resource with the unit's three tables created."""
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
            TableName="processing-job",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "answer_message_ts", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "answer-ts-index",
                    "KeySchema": [{"AttributeName": "answer_message_ts", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.create_table(
            TableName="operational-data",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.create_table(
            TableName="config",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield resource


@pytest.fixture
def job_table(dynamo: boto3.resources.base.ServiceResource):  # type: ignore[no-untyped-def]
    return dynamo.Table("processing-job")


@pytest.fixture
def opdata_table(dynamo: boto3.resources.base.ServiceResource):  # type: ignore[no-untyped-def]
    return dynamo.Table("operational-data")


@pytest.fixture
def config_table(dynamo: boto3.resources.base.ServiceResource):  # type: ignore[no-untyped-def]
    return dynamo.Table("config")
