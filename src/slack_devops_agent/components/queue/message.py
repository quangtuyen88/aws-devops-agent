"""API-INT-009 — the C-1 work-queue message contract.

One schema for the SQS work message, owned here and used by all three readers/writers
of the durable boundary: the intake enqueue, the worker's ``dispatch.parse_sqs_record``,
and the reaper's DLQ drain.
"""

from __future__ import annotations

import json
from uuid import UUID

from pydantic import BaseModel


class WorkMessage(BaseModel):
    """The C-1 queue message body (ENT-001 job reference + FR-18 author attribution)."""

    job_id: UUID
    channel_id: str
    message_ts: str
    correlation_id: UUID
    author_id: str

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, body: str) -> WorkMessage:
        """Deserialize a queue message body.

        ``author_id`` falls back to ``""`` rather than failing the whole message; the
        adoption write tolerates it and the gap is observable via the empty developer id
        (FR-18/BR-019).
        """
        payload = json.loads(body)
        payload.setdefault("author_id", "")
        return cls.model_validate(payload)
