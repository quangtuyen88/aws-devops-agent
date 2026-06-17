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
