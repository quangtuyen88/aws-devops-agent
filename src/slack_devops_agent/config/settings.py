"""Runtime configuration loaded from the environment (pydantic-settings).

Validated at startup — fail fast with a clear error if a required var is missing
(design-principles: validate at boundaries). Secrets (tokens, API keys) are injected
from AWS Secrets Manager into the environment at runtime (NFR-5); never hardcoded.

The timing invariant (NFR-17 budget / lease staleness / max attempts) MUST move in
lock-step with the infrastructure (SQS visibility, Lambda timeout) if tuned — see
infrastructure-design/unit.md.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration. Field names map to UPPER_SNAKE env vars."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # --- Slack (CMP-001) ---
    slack_bot_token: str = Field(default="", alias="SLACK_BOT_TOKEN")
    slack_signing_secret: str = Field(default="", alias="SLACK_SIGNING_SECRET")
    slack_bot_user_id: str = Field(default="", alias="SLACK_BOT_USER_ID")

    # --- Inference backend (CMP-003) ---
    inference_backend: str = Field(default="kiro", alias="INFERENCE_BACKEND")
    kiro_gateway_base_url: str = Field(default="", alias="KIRO_GATEWAY_BASE_URL")
    proxy_api_key: str = Field(default="", alias="PROXY_API_KEY")
    kiro_model: str = Field(default="claude-3-5-sonnet", alias="KIRO_MODEL")
    kiro_timeout_seconds: float = Field(default=70.0, alias="KIRO_TIMEOUT_SECONDS")
    bedrock_region: str = Field(default="us-east-1", alias="BEDROCK_REGION")
    bedrock_model_id: str = Field(
        default="anthropic.claude-3-5-sonnet-20240620-v1:0", alias="BEDROCK_MODEL_ID"
    )

    # --- AWS Knowledge MCP (CMP-004) ---
    mcp_base_url: str = Field(default="", alias="MCP_BASE_URL")
    mcp_api_key: str = Field(default="", alias="MCP_API_KEY")

    # --- AWS resources (CMP-006/007/008 + queue) ---
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    processing_job_table: str = Field(
        default="slack-devops-agent-processing-job", alias="PROCESSING_JOB_TABLE"
    )
    operational_data_table: str = Field(
        default="slack-devops-agent-operational-data", alias="OPERATIONAL_DATA_TABLE"
    )
    config_table: str = Field(default="slack-devops-agent-config", alias="CONFIG_TABLE")
    answer_ts_gsi: str = Field(default="answer-ts-index", alias="ANSWER_TS_GSI")
    work_queue_url: str = Field(default="", alias="WORK_QUEUE_URL")
    dlq_url: str = Field(default="", alias="DLQ_URL")

    # --- Timing invariant (NFR-17 / NFR-19 / BR-022) ---
    request_time_budget_seconds: float = Field(default=30.0, alias="REQUEST_TIME_BUDGET_SECONDS")
    lease_staleness_seconds: int = Field(default=90, alias="LEASE_STALENESS_SECONDS")
    max_attempts: int = Field(default=3, alias="MAX_ATTEMPTS")
    heartbeat_seconds: int = Field(default=45, alias="HEARTBEAT_SECONDS")

    # --- Cost guardrail / input bounds (NFR-8/12/13/14) ---
    max_inference_calls: int = Field(default=2, alias="MAX_INFERENCE_CALLS")
    max_mcp_calls: int = Field(default=5, alias="MAX_MCP_CALLS")
    per_period_limit: int = Field(default=500, alias="PER_PERIOD_LIMIT")
    period_definition: str = Field(default="day", alias="PERIOD_DEFINITION")
    max_input_tokens: int = Field(default=12000, alias="MAX_INPUT_TOKENS")
    reserved_output_tokens: int = Field(default=4000, alias="RESERVED_OUTPUT_TOKENS")

    # --- Resilience (NFR-15/16) ---
    retry_base_ms: int = Field(default=500, alias="RETRY_BASE_MS")
    retry_max_attempts: int = Field(default=2, alias="RETRY_MAX_ATTEMPTS")
    retry_cap_ms: int = Field(default=8000, alias="RETRY_CAP_MS")
    breaker_failure_threshold: int = Field(default=5, alias="BREAKER_FAILURE_THRESHOLD")
    breaker_reset_seconds: int = Field(default=30, alias="BREAKER_RESET_SECONDS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton (parsed once, cached)."""
    return Settings()
