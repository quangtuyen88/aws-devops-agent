"""Tests for the C-1 work-queue message contract (Phase 3)."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from slack_devops_agent.components.queue import WorkMessage


def test_round_trip() -> None:
    message = WorkMessage(
        job_id=uuid4(),
        channel_id="C1",
        message_ts="111.1",
        correlation_id=uuid4(),
        author_id="U1",
    )
    assert WorkMessage.from_json(message.to_json()) == message


def test_missing_author_id_falls_back_to_empty_string() -> None:
    body = json.dumps(
        {
            "job_id": str(uuid4()),
            "channel_id": "C1",
            "message_ts": "111.1",
            "correlation_id": str(uuid4()),
        }
    )
    assert WorkMessage.from_json(body).author_id == ""


def test_malformed_body_raises() -> None:
    with pytest.raises(ValidationError):
        WorkMessage.from_json(json.dumps({"channel_id": "C1"}))
