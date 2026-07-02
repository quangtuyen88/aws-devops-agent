"""In-memory port fakes for orchestration tests (CMP-001/002).

These doubles implement the ports with simple in-memory state so the intake and worker
orchestration can be exercised without live Slack/AWS/MCP backends (full-stack skill:
cross/live deps stay behind fakes; the unit's own stores are tested against moto elsewhere).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from slack_devops_agent.domain.entities import (
    ChannelAllowlist,
    FeedbackSignal,
    GroundingSource,
    GuardrailConfig,
    InferenceExchange,
    OriginatingMessageRef,
    ProcessingJob,
    SafetyVerdict,
    ThreadMessage,
    UsagePolicy,
)
from slack_devops_agent.domain.enums import JobStatus, NonAllowlistedBehaviour, SafetyAction
from slack_devops_agent.domain.rules import is_lease_stale
from slack_devops_agent.domain.state_machine import assert_transition
from slack_devops_agent.resilience.backoff import RetryableError


class FakeConfigStore:
    def __init__(self, allowed: list[str], per_period_limit: int = 500) -> None:
        self._allow = ChannelAllowlist(
            allowed_channel_ids=allowed,
            non_allowlisted_behaviour=NonAllowlistedBehaviour.REPLY_NOT_DESIGNATED,
        )
        self._guardrail = GuardrailConfig(per_period_limit=per_period_limit)

    def get_allowlist(self) -> ChannelAllowlist:
        return self._allow

    def get_usage_policy(self) -> UsagePolicy:
        return UsagePolicy(policy_text="no secrets")

    def get_guardrail(self) -> GuardrailConfig:
        return self._guardrail


class FakeJobCoordinator:
    def __init__(self) -> None:
        self.jobs: dict[tuple[str, str], ProcessingJob] = {}
        self._by_answer_ts: dict[str, UUID] = {}

    def register_or_get(
        self,
        identity: tuple[str, str],
        ref: OriginatingMessageRef,
        job_id: UUID,
        now: datetime,
        attached_file_name: str | None = None,
        attached_file_text: str | None = None,
    ) -> tuple[ProcessingJob, bool]:
        if identity in self.jobs:
            return self.jobs[identity], False
        job = ProcessingJob(
            job_id=job_id,
            channel_id=identity[0],
            message_ts=identity[1],
            originating_message_ref=ref,
            status=JobStatus.SEEN,
            attempt_count=0,
            last_transition_at=now,
            attached_file_name=attached_file_name,
            attached_file_text=attached_file_text,
        )
        self.jobs[identity] = job
        return job, True

    def get(self, identity: tuple[str, str]) -> ProcessingJob | None:
        return self.jobs.get(identity)

    def acquire_lease(
        self, identity: tuple[str, str], now: datetime, staleness_seconds: int
    ) -> ProcessingJob | None:
        job = self.jobs.get(identity)
        if job is None or job.status.is_terminal:
            return None
        if job.status == JobStatus.IN_PROGRESS and not is_lease_stale(job, now, staleness_seconds):
            return None
        updated = job.model_copy(
            update={
                "status": JobStatus.IN_PROGRESS,
                "attempt_count": job.attempt_count + 1,
                "last_transition_at": now,
            }
        )
        self.jobs[identity] = updated
        return updated

    def transition(
        self, identity: tuple[str, str], target: JobStatus, now: datetime
    ) -> ProcessingJob:
        job = self.jobs[identity]
        assert_transition(job.status, target)
        updated = job.model_copy(update={"status": target, "last_transition_at": now})
        self.jobs[identity] = updated
        return updated

    def stamp_answer_ts(self, identity: tuple[str, str], answer_message_ts: str) -> None:
        job = self.jobs[identity]
        self.jobs[identity] = job.model_copy(update={"answer_message_ts": answer_message_ts})
        self._by_answer_ts[answer_message_ts] = job.job_id

    def mark_post_intent(self, identity: tuple[str, str], now: datetime) -> None:
        job = self.jobs[identity]
        if job.post_intent_at is None:  # idempotent: keep the first attempt's marker
            self.jobs[identity] = job.model_copy(update={"post_intent_at": now})

    def resolve_answer_ts(self, answer_message_ts: str) -> UUID | None:
        return self._by_answer_ts.get(answer_message_ts)

    def find_stale_jobs(self, now: datetime, staleness_seconds: int) -> list[ProcessingJob]:
        return [j for j in self.jobs.values() if is_lease_stale(j, now, staleness_seconds)]


class FakeSlackGateway:
    def __init__(
        self, thread: list[ThreadMessage] | None = None, file_text: str = "FILE-CONTENT"
    ) -> None:
        self.posts: list[tuple[OriginatingMessageRef, str]] = []
        self._thread = thread or []
        self.fail_on_post = False
        self.fail_on_download = False
        self._file_text = file_text
        self.download_calls: list[str] = []
        self._counter = 0

    def fetch_thread(self, channel_id: str, thread_ts: str) -> list[ThreadMessage]:
        return self._thread

    def post_message(self, ref: OriginatingMessageRef, text: str) -> str:
        if self.fail_on_post:
            raise RuntimeError("slack down")
        self.posts.append((ref, text))
        self._counter += 1
        return f"answer-ts-{self._counter}"

    def download_file_text(self, download_url: str, max_bytes: int) -> str:
        if self.fail_on_download:
            raise RuntimeError("download failed")
        self.download_calls.append(download_url)
        return self._file_text[:max_bytes]


class FakeWorkQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[UUID, tuple[str, str], UUID, str]] = []

    def enqueue(
        self, job_id: UUID, identity: tuple[str, str], correlation_id: UUID, author_id: str
    ) -> None:
        self.enqueued.append((job_id, identity, correlation_id, author_id))


class FakeOperationalData:
    def __init__(self, within: bool = True) -> None:
        self._within = within
        self.usage = 0
        self.adoptions: list[str] = []
        self.feedback: list[FeedbackSignal] = []

    def within_budget(self, guardrail: GuardrailConfig) -> bool:
        return self._within

    def record_usage(self, token_usage: int) -> None:
        self.usage += token_usage

    def record_adoption(self, author_id: str) -> None:
        self.adoptions.append(author_id)

    def record_feedback(self, signal: FeedbackSignal) -> None:
        self.feedback.append(signal)


class FakeInference:
    def __init__(self, output: str = "Recommendation: use 3 AZs.", tokens: int = 50) -> None:
        self._output = output
        self._tokens = tokens
        self.calls = 0
        self.last_system: str | None = None
        self.last_prompt: str | None = None

    @property
    def backend_id(self) -> str:
        return "fake"

    def run_inference(self, prompt_input: str, system: str | None = None) -> InferenceExchange:
        self.calls += 1
        self.last_system = system
        self.last_prompt = prompt_input
        return InferenceExchange(
            prompt_input="", model_output=self._output, token_usage=self._tokens, backend_id="fake"
        )


class FakeGrounding:
    def __init__(self, sources: list[GroundingSource] | None = None, raises: bool = False) -> None:
        self._sources = sources or []
        self._raises = raises
        self.calls = 0

    def ground(self, query: str) -> list[GroundingSource]:
        self.calls += 1
        if self._raises:
            raise RetryableError("mcp down")
        return self._sources


class FakeSafety:
    def __init__(self, action: SafetyAction = SafetyAction.ALLOW) -> None:
        self._action = action

    def scan(self, assembled_input: str) -> SafetyVerdict:
        return SafetyVerdict(
            flagged=self._action != SafetyAction.ALLOW, recommended_action=self._action
        )


__all__ = [
    "FakeConfigStore",
    "FakeJobCoordinator",
    "FakeSlackGateway",
    "FakeWorkQueue",
    "FakeOperationalData",
    "FakeInference",
    "FakeGrounding",
    "FakeSafety",
]
