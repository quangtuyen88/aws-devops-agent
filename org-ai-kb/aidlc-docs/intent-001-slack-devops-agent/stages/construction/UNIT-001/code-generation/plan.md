# Code-Generation Plan — UNIT-001 (Slack DevOps Agent)

> Stage: `code-generation` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-sw-dev-engineer-agent · Status: plan-and-clarify.
>
> Production code lives at the **workspace root** (`/Users/tuyen/vnbnode/devops-agent-python`),
> **never** inside `org-ai-kb/`. This file (and the other stage artifacts) is the only thing
> written under `aidlc-docs/`.

## Artifact resolution (per work-method)

| Concern | Source artifact used | Notes |
|---|---|---|
| Entities | `functional-design/entities.yaml` (ENT-001..014) | source of truth for schemas |
| Business rules | `functional-design/rules.yaml` (BR-001..027) | source of truth |
| Workflows / state machine | `functional-design/functional-spec.md` (W1..W5) | ProcessingJob FSM |
| Interfaces / seams | `functional-design/api-specification.md` (API-EXT-001..006, API-INT-001..009) | port definitions |
| NFR targets & patterns | `nfr-design/nfr-spec.md` + `nfr.yaml` | concrete numbers (NFR-1..21) |
| Physical mapping | `infrastructure-design/infrastructure-specification.md` + `unit.md` | AWS services, IAM, timing invariant, F1–F8 |
| Packaging | `infrastructure-design/unit.md` | one artifact, two Lambda roles + reaper |

No upstream stage was skipped; nothing material had to be inferred. Two carry-forward items
from the infra-review gate are tracked below (AGPL boundary; **F8** answer-ts mapping).

## Decisions pending human answers (`questions.md`)

- **Q1** scope: application+tests first vs +Terraform IaC in this pass. _(plan below assumes
  the recommended (a); the IaC slice is listed but gated on the answer.)_
- **Q2** F8 mapping persistence (recommended: GSI on `ProcessingJob` keyed by `answer-message-ts`).
- **Q3** AGPL `kiro-gateway` boundary (recommended: HTTP-client-only, gateway never vendored).
- **Q4** test strategy for AWS deps (recommended: `moto` + port fakes, injected clocks).

> The plan steps are written to the recommendations; if an answer differs, the affected
> step(s) are revised before that slice is built.

## Proposed repository layout (workspace root)

```
pyproject.toml                  # uv-managed; Python 3.12; ruff, mypy, pytest, moto
src/slack_devops_agent/
  domain/                       # entities (pydantic) + business rules — no I/O
  ports/                        # abstract interfaces (the API-INT-* seams)
  components/
    intake/                     # CMP-001 intake path (W1) + reactions (W4)
    worker/                     # CMP-002 agent loop (W2/W3)
    inference/                  # CMP-003 provider: kiro_gateway + bedrock backends
    mcp/                        # CMP-004 AWS Knowledge MCP client
    safety/                     # CMP-005 secret scanner
    jobs/                       # CMP-006 job coordinator (DynamoDB adapter)
    opdata/                     # CMP-007 operational data (DynamoDB adapter)
    config/                     # CMP-008 configuration & policy (DynamoDB adapter)
  resilience/                   # backoff (NFR-15), circuit breaker (NFR-16), time budget (NFR-17)
  observability/                # structured JSON logging, EMF metrics, correlation-id
  entrypoints/
    lambda_intake.py            # API GW → Bolt handler (events + reactions)
    lambda_worker.py            # SQS → worker
    lambda_reaper.py            # EventBridge → recovery reaper (F3)
tests/                          # unit + bounded-context (moto) tests, mirroring src/
infra/terraform/                # 9 modules (Q1=b only)
```
_(Exact package name `slack_devops_agent` is a default; will confirm if the human prefers
another.)_

## Implementation slices (write-test-verify; each slice verified before the next)

### Slice 0 — Project scaffold
- [x] `pyproject.toml` via `uv` (Python 3.12; deps: `slack-bolt`, `pydantic`, `boto3` +
      `boto3-stubs`, `httpx`; dev: `pytest`, `pytest-cov`, `moto`, `ruff`, `mypy`)
- [x] tooling config (ruff, mypy strict, pytest), `.env.example`, `.gitignore`
- [x] verify: clean install, `ruff check`, `mypy`, empty `pytest` all green

### Slice 1 — Domain layer (entities + rules)
- [x] pydantic models for ENT-001..014 (logical types, constraints, defaults incl. F-1/F-2/F-3)
- [x] ProcessingJob state machine (ENT-008; Q2=b terminals `resolved`/`failed`)
- [x] pure business-rule functions BR-001..027 (no I/O)
- [x] unit tests for every rule + FSM transition (incl. terminal-no-exit, dedup invariants)
- [x] verify: tests green, types clean

### Slice 2 — Ports + cross-cutting
- [x] abstract ports for API-INT-001..009 (inference, job, safety, grounding, slack, opdata,
      feedback, config, queue)
- [x] resilience: bounded retry+jitter (NFR-15), per-dependency circuit breaker (NFR-16),
      per-request time budget (NFR-17) with **injected clock**
- [x] structured JSON logger keyed by correlation-id, class-only redaction (NFR-6/BR-026); EMF metrics
- [x] unit tests (backoff caps, breaker open/half-open, budget trip, log-scrub corpus)
- [x] verify

### Slice 3 — CMP-005 safety scanner (built first; CS-4 gate is the NFR-4 invariant)
- [x] curated regex ruleset (AWS keys, PEM, bearer/OAuth, Slack tokens, conn-strings, high-entropy)
- [x] `SafetyVerdict` producer; refuse-or-allow under Q4=b (no warn path from secret hits)
- [x] tests: known-secret corpus asserts `refuse`; benign corpus; fail-safe on scanner error
- [x] verify

### Slice 4 — CMP-003 inference provider (the A-1 seam, Q4)
- [x] backend-agnostic `InferenceProvider` (API-INT-001); `InferenceExchange` normalisation + usage
- [x] **kiro-gateway** backend: `httpx` client to `POST /v1/chat/completions`, bearer
      `PROXY_API_KEY` (HTTP-client-only per Q3 — gateway not vendored)
- [x] **bedrock** backend: boto3 `Converse`; backend selected by `Config.backend-id`
- [x] tests: backend-swap behind the interface; both via typed fakes/`respx`/stubbed boto3;
      breaker integration; **no live call in CI**
- [x] verify

### Slice 5 — CMP-004 MCP client + CMP-006 jobs + CMP-007 opdata + CMP-008 config (adapters)
- [x] CMP-004 grounding client (API-INT-004) → `GroundingSource`; "no source" signal (BR-009)
- [x] CMP-006 DynamoDB job coordinator: conditional `PutItem` dedup on `slack-event-identity`
      (F1), single-winner lease via conditional `UpdateItem` (BR-027), recovery scan with
      **inclusive `>=` 90s** reclaim (F5), heartbeat-as-lease-refresh off critical path (F6)
- [x] **F8 mapping** (pending Q2): stamp `answer-message-ts` on ProcessingJob + GSI for
      intake resolution
- [x] CMP-007 opdata: atomic `ADD` usage counter (BR-019), append-only `FeedbackSignal`
      (BR-020/F-1), adoption metrics; within-budget decision (BR-008)
- [x] CMP-008 config: read-only allowlist / usage-policy / guardrail (BR-024); fail-safe defaults
- [x] bounded-context tests against **`moto`** (dedup race, lost-update, lease boundary)
- [x] verify

### Slice 6 — CMP-001 intake (W1) + reactions (W4)
- [x] Slack Bolt signature verify, parse `InboundMention`; BR-002/BR-003/BR-001 filters
- [x] dedup-register (CMP-006), in-thread ack within NFR-1, enqueue across C-1 (API-INT-009)
- [x] reaction path (F2): synchronous 👍/👎 capture → resolve answer-ts→correlation-id (F8)
      → append `FeedbackSignal` (no SQS/worker hop)
- [x] tests (mention/non-mention/bot-author/non-allowlisted; redelivery dedup; reaction filter)
- [x] verify

### Slice 7 — CMP-002 worker agent loop (W2/W3)
- [x] dequeue + completion re-check (BR-011) → `in-progress` lease (BR-021)
- [x] context fetch (BR-005 fetch-not-store), size check trim/reject (NFR-14 hybrid, 12k/4k tunable F7)
- [x] **CS-4 ordering**: safety gate → within-budget → agent loop under CS-5 cap
      (≤2 inf/≤5 MCP, NFR-12) + 30s budget (NFR-17)
- [x] answer-type classify (F-2) → compose Answer (BR-015/016/017) → idempotent post (BR-027)
      → record adoption → `resolved`
- [x] failure/recovery (W3): FR-17 messages, budget-deny re-ask (M-1), bounded retries→`failed`
- [x] heartbeat every 15s (NFR-11)
- [x] tests: full pipeline with fakes; cap/timeout/oversize/budget-deny; kill-worker recovery
      asserting the **90s inclusive boundary** (F5)
- [x] verify

### Slice 8 — Lambda entrypoints
- [x] `lambda_intake` (API GW + Bolt; events + reactions), `lambda_worker` (SQS, batch=1),
      `lambda_reaper` (EventBridge; DLQ drain → `failed` + FR-17 post)
- [x] thin adapters delegating to core; correlation-id propagated as SQS message attribute
- [x] handler tests with synthetic events; verify

### Slice 9 — Terraform IaC  _(follow-on increment — DONE)_
- [x] 9 modules per infra-spec §6 (`networking`, `messaging`, `data`, `compute-intake`,
      `compute-worker`, `recovery`, `gateway`, `security`, `observability`) under
      `infra/terraform/`; remote state S3+DynamoDB lock (partial backend, `-backend-config`);
      region/account parameterised; provider pinned (`hashicorp/aws ~> 5.100`, lock file committed)
- [x] timing invariant in lock-step (budget 30s / Lambda 45s / visibility 90s / staleness 90s
      `>=` / maxReceiveCount 3); least-privilege IAM per role (§4.2, ARNs constructed from the
      name prefix to break the KMS↔ARN module cycle)
- [x] DynamoDB `ProcessingJob` table includes the **`answer-ts-index` GSI projecting `job_id`**
      (F8); customer-managed KMS at rest on all 3 tables + SQS + secrets + log groups
- [x] verify: `terraform fmt -check -recursive` ✅, `terraform init -backend=false` ✅,
      `terraform validate` ✅ — **no `apply`, no plan-with-backend** (OOS-3)

### Slice 10 — Traceability artifacts
- [x] `implementation-map.md` (CMP/ENT/BR/API/NFR/infra IDs → files + tests; coverage gaps)
- [x] copy-forward + expand `components.yaml` and `unit.md` with implementation refs
      (preserve all stable IDs)
- [x] full-suite verify: `ruff check`, `ruff format --check`, `mypy`, `pytest` (coverage),
      `bandit -r src/`
- [x] set stage status → `artifact-generated`

## Follow-on increment (this pass) — NFR-11 + BR-027 hardening (DONE)

Alongside Slice 9, two residual items flagged in `implementation-map.md` were closed:

- **NFR-11 heartbeat runtime wiring** — `components/worker/heartbeat.py::HeartbeatEmitter`
  posts the periodic "still working…" message on a daemon background timer (cadence
  `HEARTBEAT_SECONDS`, default 15s), kept off the critical CPU path (infra-spec §2.4/F6). The
  worker wraps `_run_pipeline` in the emitter as a context manager so it stops on both the
  success and failure paths. Tests: `tests/test_heartbeat.py` (emitter beat/stop/fast-block +
  worker start/stop wiring).
- **BR-027 repost-window hardening (MINOR-b)** — `ProcessingJob.post_intent_at` is a pre-post
  intent marker stamped (idempotently) immediately **before** the Slack post; the worker's
  early idempotency check now uses `ProcessingJob.post_attempted` (intent OR answer-ts), so a
  crash between the Slack post and the answer-ts stamp can no longer repost on recovery —
  closing the window to **at-most-once-completed**. Tests: `tests/test_worker.py`
  (`test_reclaim_with_only_post_intent_does_not_repost_br027`,
  `test_happy_path_stamps_post_intent_before_resolving_br027`) and `tests/test_adapters.py`
  (`test_mark_post_intent_is_idempotent`, moto).


`ruff check` + `ruff format --check` + `mypy` (strict) + `pytest` green before proceeding;
`bandit` on the full suite at the end. No slice leaves a red build behind it.

## Carry-forward / watch-items
- **AGPL `kiro-gateway`** (Q3): integrate by HTTP client only; never vendor/fork the gateway.
- **F8** answer-ts→correlation-id durable mapping (Q2): implement once approach is confirmed;
  record as in-place ENT-008 expansion, flag for systems-architect contributor.
- **Timing invariant (F5/F6)** must move in lock-step if any value is tuned.
- **F7** 4,000 reserved-output tokens is a tunable `Config` default, not a requirement.

## Outputs this stage will produce
Production source + tests at the workspace root; `pyproject.toml` and tooling config;
(optionally) Terraform under `infra/terraform/`; `implementation-map.md`, expanded
`components.yaml`, expanded `unit.md` in this stage directory.
