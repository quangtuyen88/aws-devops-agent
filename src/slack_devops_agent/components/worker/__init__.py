"""CMP-002 — Agent Orchestrator (worker role)."""

from __future__ import annotations

from .composer import DefaultAnswerComposer
from .heartbeat import HeartbeatEmitter
from .orchestrator import Worker, WorkerConfig, WorkerOutcome
from .rendering import render_answer, render_failure

__all__ = [
    "DefaultAnswerComposer",
    "HeartbeatEmitter",
    "Worker",
    "WorkerConfig",
    "WorkerOutcome",
    "render_answer",
    "render_failure",
]
