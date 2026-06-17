# Slack DevOps Agent — UNIT-001

A Slack bot that answers AWS/DevOps questions in allowlisted channels: it acknowledges
fast, processes asynchronously, grounds answers in AWS Knowledge MCP sources, gates input
for secrets, and records adoption/feedback/usage metrics.

This package is a **modular monolith** (one artifact, three Lambda roles):

- **intake** (`entrypoints/lambda_intake.py`) — Slack Events API ingress (mentions +
  reactions), fast ack, enqueue.
- **worker** (`entrypoints/lambda_worker.py`) — SQS-driven async agent loop.
- **reaper** (`entrypoints/lambda_reaper.py`) — EventBridge-scheduled in-flight recovery.

External dependencies (Slack, the inference backend, AWS Knowledge MCP, DynamoDB, SQS) sit
behind ports/adapters so the agent core is testable without live backends.

## Inference backend (CMP-003)

Kiro-gateway is the **primary** backend, integrated **HTTP-client-only** against an
OpenAI-compatible `POST /v1/chat/completions` (bearer `PROXY_API_KEY`). The gateway is
operated as a **separate, unmodified, external** AGPL-3.0 container — it is **never**
vendored, forked, or imported into this codebase, which bounds AGPL source-disclosure
obligations. Amazon Bedrock is the config-switchable alternate behind the same interface.

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run bandit -r src/
```

See `org-ai-kb/aidlc-docs/intent-001-slack-devops-agent/stages/construction/UNIT-001/`
for the design artifacts (entities, rules, NFR, infrastructure) and `implementation-map.md`
in the `code-generation/` stage directory for the ID → file/test traceability.
