# Slack DevOps Agent — UNIT-001

A Slack bot that answers AWS/DevOps questions in allowlisted channels: it acknowledges
fast, processes asynchronously, grounds answers in AWS Knowledge MCP sources, reviews
attached IaC files, gates input for secrets, enforces an architecture-only content
guardrail, and records adoption/feedback/usage metrics.

This package is a **modular monolith** (one artifact, three Lambda roles):

- **intake** (`entrypoints/lambda_intake.py`) — Slack Events API ingress (mentions +
  reactions), fast ack, enqueue.
- **worker** (`entrypoints/lambda_worker.py`) — SQS-driven async agent loop.
- **reaper** (`entrypoints/lambda_reaper.py`) — EventBridge-scheduled in-flight recovery.

External dependencies (Slack, the inference backend, AWS Knowledge MCP, DynamoDB, SQS) sit
behind ports/adapters so the agent core is testable without live backends.

> **How "running" works:** there is no standalone server process — the three entrypoints are
> AWS Lambda handlers. Locally you **develop and test** the code (§ Quick start); to actually
> **run** the bot you **deploy** it to AWS (§ Run / deploy). Jump to
> [Quick start](#quick-start) or [Run / deploy](#run--deploy).

## Capabilities

- **Q&A** — `@devops-agent <question>` in an allowlisted channel; the bot acks, processes
  asynchronously, and answers in-thread, grounded where possible in AWS Knowledge MCP sources.
- **File review** — attach a text/IaC file (`.yaml/.yml/.json/.tf/.hcl/.txt/.md/.template`,
  ≤256 KB) and the bot includes its content in the review. Other types/oversize files are
  declined with a notice; requires the Slack app's **`files:read`** scope.
- **Content guardrail** — an operator system prompt restricts answers to AWS architecture /
  DevOps, resists prompt-injection, and declines off-topic or PII/secret-disclosure requests
  (`components/inference/system_prompt.py`).
- **Input safety gate** — assembled input (including any attached file) is scanned for secrets
  before it reaches an inference backend; a positive detection refuses the request
  (`components/safety/scanner.py`).
- **Feedback** — 👍/👎 reactions on a bot answer are captured as adoption/feedback signals.

## Quick start

### 1. Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.12+ | runtime |
| [uv](https://docs.astral.sh/uv/) | latest | dependency + venv management |

Cloud deploy additionally needs the AWS CLI v2, Terraform ≥ 1.6, Docker, and a logged-in
`kiro-cli` — see [Run / deploy](#run--deploy).

### 2. Install

```bash
# clone, then from the repo root:
uv sync --extra dev
```

`uv sync` creates the `.venv` and installs runtime + dev dependencies pinned in `uv.lock`.
Prefix commands with `uv run` to use that environment (no manual `activate` needed).

### 3. Develop & test

```bash
uv run pytest                  # full test suite
uv run ruff check .            # lint
uv run ruff format --check .   # format check
uv run mypy                    # type check (strict)
uv run bandit -r src/          # security lint
```

The agent core is fully testable without any AWS/Slack credentials — adapters are faked
behind ports. The test suite is the local "does it work" signal; there is no local server to
start.

### 4. Run / deploy

Running the bot = deploying it to AWS (Lambda + Fargate). The full step-by-step runbook
(existing VPC, secrets from `.env`, one-command apply) lives in
**[docs/DEPLOY-EXISTING-VPC.md](docs/DEPLOY-EXISTING-VPC.md)**; architecture/cost detail is in
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The short version:

```bash
cp .env.example .env && $EDITOR .env          # Slack tokens, PROXY_API_KEY, SLACK_BOT_USER_ID
cp scripts/deploy.env.example deploy.env && $EDITOR deploy.env   # VPC/subnet/SG IDs + backend

scripts/bootstrap-backend.sh -b <state-bucket> -t <lock-table> -r us-east-1   # one-time
scripts/build-lambda.sh -b <artifacts-bucket> -r us-east-1                    # build Lambda zip

scripts/deploy.sh                              # plan (safe, read-only)
scripts/deploy.sh --apply --load-kiro-creds    # apply + load secrets from .env + Kiro creds
```

`scripts/deploy.sh` plans by default; `--apply` is the only thing that mutates AWS. Secrets
are read from `.env` and pushed to Secrets Manager automatically — never committed.

### Operational notes

- **Slack scopes** — file review needs the **`files:read`** bot scope (reinstall after adding);
  the bot user id (`SLACK_BOT_USER_ID`) gates self-mentions. Without `files:read`, Slack omits
  the file from the event and the bot reviews text only.
- **Intake Lambda alias** — API Gateway invokes the intake function via a published-version
  **alias** (`live`), not `$LATEST`. After updating intake code you must publish a new version
  **and** move the alias, or the new code never serves traffic. The worker/reaper run `$LATEST`
  (SQS/EventBridge invoke the bare function), so a code update is enough for them.
- **Inference reachability** — the worker reaches the kiro-gateway over the internal ALB; the
  channel allowlist, usage guardrail, MCP base URL, and inference timeout are runtime config
  (DynamoDB `Config` items / Lambda env), not code.

## Architecture & Infrastructure

### Runtime topology (AWS)

How a request flows through the deployed infrastructure. The system splits at the durable
**C-1 queue seam** into an always-on **intake** role and a horizontally-scalable **worker**
role; a scheduled **reaper** recovers abandoned jobs.

```mermaid
flowchart TB
    Slack(["Slack<br/>mentions + reactions"])

    subgraph public["Public ingress (auth = Slack signature)"]
        APIGW["API Gateway<br/>HTTP API"]
    end

    subgraph intakeRole["Intake role — no VPC, always-on"]
        Intake["intake Lambda<br/>verify · dedup · ack · enqueue<br/>(reactions handled inline)"]
    end

    subgraph messaging["Messaging seam (C-1)"]
        SQS["SQS Standard"]
        DLQ["SQS DLQ"]
    end

    subgraph workerRole["Worker role — in VPC, private subnets, batch_size=1"]
        Worker["worker Lambda<br/>CMP-002 orchestrator<br/>+ CMP-003 inference<br/>+ CMP-004 MCP<br/>+ CMP-005 safety gate"]
    end

    subgraph gateway["Inference (behind CMP-003 seam)"]
        Kiro["kiro-gateway<br/>ECS Fargate · internal ALB<br/>2 tasks Multi-AZ — PRIMARY"]
        Bedrock["Amazon Bedrock<br/>Converse — ALTERNATE<br/>(config/deploy-time switch)"]
    end

    subgraph data["State (DynamoDB, KMS-encrypted)"]
        PJ[("ProcessingJob<br/>dedup + lease")]
        OD[("OperationalData<br/>usage · feedback")]
        CFG[("Config<br/>allowlist · policy")]
    end

    subgraph recovery["Recovery (NFR-19 backstop)"]
        EB["EventBridge<br/>Scheduler"]
        Reaper["reaper Lambda<br/>no VPC"]
    end

    MCP(["aws-knowledge-mcp-server<br/>public HTTPS via NAT"])

    Slack -->|HTTPS events| APIGW --> Intake
    Intake -->|"PutItem (cond dedup)"| PJ
    Intake -->|"reaction → FeedbackSignal"| OD
    Intake -->|SendMessage| SQS
    SQS -->|"trigger (batch=1)"| Worker
    SQS -.->|maxReceiveCount=3| DLQ
    Worker -->|"safety pass → infer"| Kiro
    Worker -.->|operator switch| Bedrock
    Worker -->|grounding| MCP
    Worker -->|lease · heartbeat · result| PJ
    Worker -->|usage counters| OD
    Worker -->|read policy| CFG
    Worker -->|answer / failure / heartbeat| Slack
    EB --> Reaper
    Reaper -->|drain| DLQ
    Reaper -->|mark failed| PJ
    Reaper -->|FR-17 in-thread failure| Slack
```

### Code architecture (ports & adapters)

One artifact, three Lambda entrypoints. The domain core never imports an adapter — all
external systems are reached through ports, so the agent loop is unit-testable without live
backends.

```mermaid
flowchart LR
    subgraph entry["entrypoints/"]
        LI["lambda_intake"]
        LW["lambda_worker"]
        LR["lambda_reaper"]
        WIRE["wiring · dispatch"]
    end

    subgraph core["domain/ (pure core)"]
        ENT["entities"]
        RULES["rules"]
        SM["state_machine"]
    end

    subgraph comps["components/ (CMP-001..008)"]
        C["intake · worker · queue · jobs<br/>inference · mcp · safety · opdata<br/>config · recovery"]
    end

    PORTS["ports/<br/>(interfaces)"]

    subgraph cross["cross-cutting"]
        RES["resilience<br/>breaker · backoff · budget"]
        OBS["observability<br/>JSON logs · EMF metrics"]
        CONF["config/settings"]
    end

    EXT(["Slack · kiro-gateway / Bedrock<br/>AWS Knowledge MCP · DynamoDB · SQS"])

    entry --> comps
    comps --> core
    comps --> PORTS
    PORTS -.->|adapters implement| EXT
    comps --> RES
    comps --> OBS
    entry --> CONF
```

## Inference backend (CMP-003)

Kiro-gateway is the **primary** backend, integrated **HTTP-client-only** against an
OpenAI-compatible `POST /v1/chat/completions` (bearer `PROXY_API_KEY`). The gateway is
operated as a **separate, unmodified, external** AGPL-3.0 container — it is **never**
vendored, forked, or imported into this codebase, which bounds AGPL source-disclosure
obligations. Amazon Bedrock is the config-switchable alternate behind the same interface.

## Design artifacts

See `org-ai-kb/aidlc-docs/intent-001-slack-devops-agent/stages/construction/UNIT-001/`
for the design artifacts (entities, rules, NFR, infrastructure) and `implementation-map.md`
in the `code-generation/` stage directory for the ID → file/test traceability. Day-to-day
commands (install, test, lint) are in [Quick start](#quick-start).
