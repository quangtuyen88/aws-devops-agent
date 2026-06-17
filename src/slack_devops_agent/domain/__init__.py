"""Domain layer: entities (ENT-*), enums, the ProcessingJob FSM, and pure rules (BR-*).

No I/O lives here — this layer is fully unit-testable in isolation.
"""

from __future__ import annotations

from . import rules, state_machine
from .entities import (
    AdoptionMetric,
    Answer,
    ChannelAllowlist,
    ConversationContext,
    FeedbackSignal,
    GroundingSource,
    GuardrailConfig,
    InboundMention,
    InferenceExchange,
    OriginatingMessageRef,
    ProcessingJob,
    ReactionEvent,
    SafetyFinding,
    SafetyVerdict,
    ThreadMessage,
    UsageCounter,
    UsagePolicy,
)
from .enums import (
    AnswerType,
    EventAction,
    FailureCause,
    JobStatus,
    NonAllowlistedBehaviour,
    ReactionKind,
    SafetyAction,
)

__all__ = [
    "rules",
    "state_machine",
    "AdoptionMetric",
    "Answer",
    "ChannelAllowlist",
    "ConversationContext",
    "FeedbackSignal",
    "GroundingSource",
    "GuardrailConfig",
    "InboundMention",
    "InferenceExchange",
    "OriginatingMessageRef",
    "ProcessingJob",
    "ReactionEvent",
    "SafetyFinding",
    "SafetyVerdict",
    "ThreadMessage",
    "UsageCounter",
    "UsagePolicy",
    "AnswerType",
    "EventAction",
    "FailureCause",
    "JobStatus",
    "NonAllowlistedBehaviour",
    "ReactionKind",
    "SafetyAction",
]
