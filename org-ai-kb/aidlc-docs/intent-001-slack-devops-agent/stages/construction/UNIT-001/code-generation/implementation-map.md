# Implementation Map — UNIT-001 (Slack DevOps Agent)

> Stage: `code-generation` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-sw-dev-engineer-agent · Status: artifact-generated.
>
> Traceability from design IDs (CMP / ENT / BR / API / NFR / infra F-items) to the
> production code and tests that realise them. Production code lives at the **workspace
> root** under `src/slack_devops_agent/`; tests under `tests/`. Nothing in this map lives
> inside `org-ai-kb/` except this document and the copied-forward `components.yaml` /
> `unit.md`.
>
> Scope this pass (Q1=a): **application code + tests only**. Terraform IaC (9 modules) is a
> deferred follow-on slice. Inference = **Kiro-gateway primary (HTTP-client-only) + Bedrock
> alternate** behind CMP-003 (Q3=a). Bounded-context tests use **moto**; live
> Slack/Kiro/Bedrock/MCP stay behind typed fakes/respx (Q4=a).

## Verification status

| Gate | Command | Result |
|---|---|---|
| Lint | `uv run ruff check src tests` | ✅ all checks passed |
| Format | `uv run ruff format --check src tests` | ✅ 65 files formatted |
| Types | `uv run mypy` (strict) | ✅ no issues, 51 source files |
| Tests | `uv run pytest` | ✅ 105 passed |
| Security | `uv run bandit -r src/` | ✅ 0 issues (2,716 LoC) |
| Coverage | `uv run pytest --cov` | 88% overall (gaps = thin AWS-wiring Lambda handlers, deferred per Q4=a) |
| IaC format | `terraform fmt -check -recursive` (`infra/terraform/`) | ✅ all formatted (re-validated this pass) |
| IaC validate | `terraform init -backend=false` + `terraform validate` | ✅ configuration valid (no `apply`, OOS-3; re-validated this pass) |
| Deploy script lint | `shellcheck scripts/deploy.sh` | ✅ clean (0 warnings) |
| Deploy script syntax | `bash -n scripts/deploy.sh` | ✅ syntax OK |

## Components (CMP-001..008)

| CMP | Component | Production code | Tests |
|---|---|---|---|
| CMP-001 | Slack Interaction Adapter | `components/intake/{handler,parsing,slack_gateway}.py` | `tests/test_intake.py`, `tests/test_glue.py` |
| CMP-002 | Agent Orchestrator (worker) | `components/worker/{orchestrator,composer,rendering}.py` | `tests/test_worker.py` |
| CMP-003 | Inference Provider (A-1 seam) | `components/inference/{provider,kiro_gateway,bedrock}.py` | `tests/test_inference.py` |
| CMP-004 | AWS Knowledge MCP Client | `components/mcp/client.py` | `tests/test_mcp.py` |
| CMP-005 | Input Safety Scanner | `components/safety/scanner.py` | `tests/test_safety.py` |
| CMP-006 | Job Coordinator | `components/jobs/coordinator.py` | `tests/test_adapters.py` |
| CMP-007 | Operational Data Service | `components/opdata/service.py` | `tests/test_adapters.py` |
| CMP-008 | Configuration & Policy | `components/config/store.py` | `tests/test_adapters.py` |
| (recovery) | Recovery reaper (F3 / W3) | `components/recovery/reaper.py` | `tests/test_entrypoints.py` |
| (runtime) | Lambda roles (intake/worker/reaper) | `entrypoints/{lambda_intake,lambda_worker,lambda_reaper,dispatch,wiring}.py` | `tests/test_entrypoints.py`, `tests/test_glue.py` |

## Entities (ENT-001..014)

| ENT | Entity | Realised as | Notes |
|---|---|---|---|
| ENT-001 | InboundMention | `domain/entities.py::InboundMention` | `slack_event_identity` property (Q3=a); `author-id` threaded → SQS body → durable job → `record_adoption` (DEFECT-1) |
| ENT-002 | ReactionEvent | `domain/entities.py::ReactionEvent` | add/remove (Q4) |
| ENT-003 | ConversationContext | `domain/entities.py::ConversationContext` | fetch-not-store; assembled in worker |
| ENT-004 | Answer | `domain/entities.py::Answer` | model validator enforces BR-015/BR-016 |
| ENT-005 | InferenceExchange | `domain/entities.py::InferenceExchange` | `backend_id` is the A-1 detail |
| ENT-006 | GroundingSource | `domain/entities.py::GroundingSource` | never fabricated (BR-009) |
| ENT-007 | SafetyVerdict | `domain/entities.py::{SafetyVerdict,SafetyFinding}` | redacted findings only (NFR-6) |
| ENT-008 | ProcessingJob | `domain/entities.py::ProcessingJob` + `domain/state_machine.py` | **F8 expansion (Q2=a):** `answer_message_ts` attribute + GSI; **BR-027 hardening:** `post_intent_at` pre-post intent marker + `post_attempted` property; see note below |
| ENT-009 | AdoptionMetric | `domain/entities.py::AdoptionMetric` / `opdata/service.py` | distinct devs via DynamoDB string set; keyed on **author-id** (developer), not channel (DEFECT-1) |
| ENT-010 | FeedbackSignal | `domain/entities.py::FeedbackSignal` / `opdata/service.py` | append-only (Q4); F-1 aggregation in `rules.net_reactor_signal` |
| ENT-011 | UsageCounter | `domain/entities.py::UsageCounter` / `opdata/service.py` | atomic `ADD` (BR-019) |
| ENT-012 | ChannelAllowlist | `domain/entities.py::ChannelAllowlist` / `config/store.py` | F-3 default `reply-not-designated` |
| ENT-013 | UsagePolicy | `domain/entities.py::UsagePolicy` / `config/store.py` | fail-safe default text |
| ENT-014 | GuardrailConfig | `domain/entities.py::GuardrailConfig` / `config/store.py` | validator: ≥1 limit (A-7) |

### F8 — ENT-008 in-place expansion (Q2=a, recorded for systems-architect confirmation)

`ProcessingJob` gains a nullable `answer_message_ts` attribute (stamped by the worker at
answer-post, W2 step 10) and the `processing-job` DynamoDB table gains a GSI
(`answer-ts-index`, partition key `answer_message_ts`). Intake resolves a reaction
(`ReactionEvent.answer_message_ts`) → `job_id` (== `correlation_id` == `Answer.correlation_id`,
DA-1) via `DynamoJobCoordinator.resolve_answer_ts`. **No new entity, stable ENT-008 ID
preserved** — this is the in-place expansion promised in `code-generation/questions.md` Q2.

## Business rules (BR-001..027)

| BR | Where enforced |
|---|---|
| BR-001 allowlist | `rules.is_channel_allowed` + `intake/handler.py` |
| BR-002 ignore bot/self | `rules.is_bot_authored` + `intake/parsing.py` |
| BR-003 must @mention | `intake/parsing.py::mentions_bot` + handler |
| BR-004 ack + enqueue | `intake/handler.py::handle_mention` (ack-failure degrade covered) |
| BR-005 thread-scoped fetch-not-store | `worker/orchestrator.py::_run_pipeline` (fetch) |
| BR-006 shared latency budget | `resilience/time_budget.py` used across the loop |
| BR-007 oversize trim/reject | `worker/orchestrator.py::_enforce_size` + `rules.within_size_budget` — trim path posts an in-thread notice (`_TRIM_NOTICE_TEXT`), never silent (DEFECT-2) |
| BR-008 within budget before spend | `rules.is_within_budget` + `opdata/service.py::within_budget` — positive per-request limit enforced on the hot path (NFR-14 size gate + CS-5 caps); non-positive = kill-switch (MINOR-a) |
| BR-009 ground-or-mark-ungrounded | `worker/composer.py` + `mcp/client.py` (empty ⇒ ungrounded) |
| BR-010 at-most-once per identity | `jobs/coordinator.py::register_or_get` (conditional PutItem) |
| BR-011 at-most-once-completed | `rules.should_process_existing` + worker completion re-check |
| BR-012 safety gate before inference/MCP | `worker/orchestrator.py::_run_pipeline` (CS-4 ordering) |
| BR-013 failures resolve the ack | `worker/orchestrator.py::_fail` + `worker/rendering.py::render_failure` |
| BR-014 tool-call cap + timeout | `rules.loop_cap_reached` + `_agent_loop` + `TimeBudget` |
| BR-015 structured answer by type | `Answer` validator + `rules.classify_answer_type` + composer |
| BR-016 citation/grounding consistency | `Answer` model validator |
| BR-017 code advice-only | `worker/composer.py` (code_snippets) + `rendering.py` (code block) |
| BR-018 capture 👍/👎 on bot answers | `intake/parsing.py::parse_reaction` + `handler.handle_reaction` |
| BR-019 record usage + adoption (atomic) | `opdata/service.py::{record_usage,record_adoption}` — adoption keyed on author-id threaded from intake (DEFECT-1) |
| BR-020 append-only + F-1 aggregation | `opdata/service.py::record_feedback` + `rules.{net_reactor_signal,aggregate_feedback}` |
| BR-021 detect lost in-flight | `rules.is_lease_stale` (inclusive ≥) + `coordinator.find_stale_jobs` + reaper |
| BR-022 bounded retries → failed | `rules.attempts_exhausted` + worker + reaper |
| BR-023 rate-limit backoff | `resilience/backoff.py` + adapter 429 → `RetryableError` |
| BR-024 config read-only | `config/store.py` (read-only methods) |
| BR-025 policy + safety gate | `config/store.py::get_usage_policy` + `safety/scanner.py` |
| BR-026 log hygiene | `observability/logging.py` (redaction + correlation-id) |
| BR-027 single-winner lease + idempotent post | `coordinator.acquire_lease` (optimistic CAS + staleness) + worker idempotent post **hardened** with the `ProcessingJob.post_intent_at` pre-post intent marker (`coordinator.mark_post_intent`, stamped before the Slack post) + early `post_attempted` check — closes the repost window (MINOR-b), at-most-once-*completed* |

## API seams (API-INT-001..009, API-EXT-001..006)

| API | Port (Protocol) | Adapter |
|---|---|---|
| API-INT-001 | `ports.InferenceProvider` | `inference/{kiro_gateway,bedrock}.py` (A-1) |
| API-INT-002 | `ports.JobCoordinator` | `jobs/coordinator.py` |
| API-INT-003 | `ports.SafetyScanner` | `safety/scanner.py` |
| API-INT-004 | `ports.GroundingClient` | `mcp/client.py` (wraps API-EXT-004) |
| API-INT-005 | `ports.SlackGateway` | `intake/slack_gateway.py` (wraps API-EXT-002/003) |
| API-INT-006 | `ports.OperationalDataService` | `opdata/service.py` |
| API-INT-007 | `ports.OperationalDataService.record_feedback` | `opdata/service.py` |
| API-INT-008 | `ports.ConfigStore` | `config/store.py` |
| API-INT-009 | `ports.WorkQueue` | `queue/sqs.py` (C-1 seam) |
| API-EXT-001/005 | inbound Slack events | `entrypoints/lambda_intake.py` + `dispatch.py` |
| API-EXT-006 | inference endpoint | `inference/kiro_gateway.py` (HTTP), `inference/bedrock.py` (Converse) |

## NFR coverage (NFR-1..21)

| NFR | Realised / verified by |
|---|---|
| NFR-1 ack window | intake posts ack + returns 200 before enqueue (`lambda_intake`, `handler`) |
| NFR-2 / NFR-17 budget | `resilience/time_budget.py` (30s); `tests/test_resilience.py` |
| NFR-4 / NFR-21 secrets | `safety/scanner.py` refuse-or-allow; `tests/test_safety.py`, `tests/test_worker.py::test_safety_refuse_blocks_inference_and_fails` |
| NFR-6 log hygiene | `observability/logging.py` redaction; `tests/test_glue.py` |
| NFR-7 / NFR-15 rate-limit/backoff | `resilience/backoff.py`; adapter 429 mapping; `tests/test_resilience.py`, `tests/test_mcp.py` |
| NFR-8 / NFR-12 / NFR-13 cost | `rules.{is_within_budget,loop_cap_reached}` + `opdata`; `tests/test_worker.py`, `tests/test_adapters.py` |
| NFR-11 heartbeat | `worker/heartbeat.py::HeartbeatEmitter` (periodic ~15s post on a daemon timer, off the critical path per F6) wired into `worker/orchestrator.py` around the pipeline; `tests/test_heartbeat.py` |
| NFR-14 oversize hybrid | `worker/orchestrator.py::_enforce_size` (trim/reject); `tests/test_worker.py` |
| NFR-16 breaker | `resilience/circuit_breaker.py`; `tests/test_resilience.py` |
| NFR-19 recovery (90s inclusive) | `rules.is_lease_stale` + `coordinator`; `tests/test_adapters.py::test_recovery_uses_inclusive_90s_boundary`, `tests/test_worker.py::test_stale_in_progress_job_is_recovered_then_resolved` |
| NFR-20 observability | `observability/metrics.py` (EMF) emitted across intake/worker/reaper |

## AGPL boundary (Q3=a) — watch-item closed for this pass

`components/inference/kiro_gateway.py` is an **HTTP client only** to the external gateway's
`POST /v1/chat/completions` (bearer `PROXY_API_KEY`). The gateway is **not** vendored,
forked, or imported — an explicit module docstring states it must stay unmodified and
external. Bedrock (`bedrock.py`) is one `INFERENCE_BACKEND` flip away (no AGPL).

## Known gaps / deferred

- **Lambda handler bodies** (`lambda_intake/worker/reaper`, `wiring.py`) are thin AWS
  construction wrappers exercised only on their non-AWS branches (signature/challenge,
  dispatch, batch shaping); full live wiring is post-deployment integration (Q4=a).
- **F8 ENT-008 expansion** — flagged below for systems-architect confirmation against
  functional-design (stable ID preserved, no new entity).

## Resolved in the follow-on increment (this pass)

- **Terraform IaC** (9 modules) — **DONE**, see the Terraform section below.
- **NFR-11 periodic heartbeat** — **DONE**: `worker/heartbeat.py::HeartbeatEmitter` emits the
  "still working…" message on a daemon background timer (cadence `HEARTBEAT_SECONDS`, default
  15s), wired into the worker around the pipeline as a context manager (stops on success and
  failure). Off the critical CPU path per infra-spec §2.4/F6. Tests in `tests/test_heartbeat.py`.
- **BR-027 repost-window residual (MINOR-b)** — **CLOSED**: a `ProcessingJob.post_intent_at`
  pre-post intent marker is stamped (idempotently) immediately **before** the Slack answer
  post (`DynamoJobCoordinator.mark_post_intent`, conditional `attribute_not_exists`). The
  worker's early idempotency check now uses `ProcessingJob.post_attempted` (intent marker OR
  answer-ts), so a crash in the narrow window **between** the successful Slack post and the
  `stamp_answer_ts` write can no longer cause a recovery-spawned worker to repost — the
  invariant is now full **at-most-once-completed**. Accepted tradeoff: if the very first post
  *itself* failed and then crashed after the marker was stamped, recovery resolves without
  reposting (favours no-duplicate over a possible no-answer, which the normal retry/FR-17
  path already covers). Tests: `tests/test_worker.py` (post-intent reclaim + happy-path
  ordering) and `tests/test_adapters.py` (`test_mark_post_intent_is_idempotent`, moto).

## Terraform IaC (SLICE 9 — `infra/terraform/`)

Authored and validated with `terraform fmt -check` + `terraform init -backend=false` +
`terraform validate` only — **never** `apply` or plan-with-backend (OOS-3). Provider pinned
(`hashicorp/aws ~> 5.100`, `.terraform.lock.hcl` committed); remote state is an S3 backend
with DynamoDB locking via a partial `backend "s3" {}` block configured at init time
(`-backend-config=backend.hcl`) — no live state in the repo.

| infra-spec §6 module | Path | Realises |
|---|---|---|
| networking | `modules/networking` | VPC, public/private subnets (Multi-AZ, F4), NAT, **DynamoDB + S3 free gateway endpoints**, **per-endpoint-toggleable SQS/Secrets/Logs/ECR-api/ECR-dkr/Bedrock interface endpoints** (`count = var.X ? 1 : 0`; Bedrock default OFF), worker SG; **destroy-safe existing-VPC mode** (`use_existing_network` consumes VPC/subnets/SG/route-tables via data sources only) (§3) |
| messaging | `modules/messaging` | C-1 SQS work queue (visibility 90s) + DLQ, redrive `maxReceiveCount=3` (§2.4/BR-022), KMS SSE |
| data | `modules/data` | 3 DynamoDB tables (KMS + PITR); **ProcessingJob `answer-ts-index` GSI projecting `job_id`** (F8) |
| compute-intake | `modules/compute-intake` | API Gateway HTTP API + intake Lambda (no VPC), published version/alias, provisioned concurrency 2 (§2.1) |
| compute-worker | `modules/compute-worker` | worker Lambda in-VPC, SQS event source `batch_size=1`, reserved conc. 15, event-source max conc. 12, timeout 45s (§2.2) |
| recovery | `modules/recovery` | EventBridge Scheduler → reaper Lambda (no VPC) + scheduler-invoke role (§1/F3) |
| gateway | `modules/gateway` | ECS Fargate kiro-gateway (baseline 2, Multi-AZ) on **container port 8000** + internal ALB w/ TLS listener; **Application Auto Scaling target-tracking 2→4 on `ECSServiceAverageCPUUtilization`** (§2.3/§1, F4); **destroy-safe existing-ALB mode** (`use_existing_alb` adds an `aws_lb_listener_rule` to a borrowed listener via data sources); **credentials init-sidecar** (stock pinned image writes the Kiro OIDC creds JSON from Secrets Manager to a task-local shared volume → unmodified gateway reads it via `KIRO_CREDS_FILE`); unmodified upstream image (AGPL boundary §0) |
| security | `modules/security` | customer-managed KMS CMK, 5 Secrets Manager containers, **least-privilege IAM per runtime role** (intake/worker/reaper/gateway, §4.2) |
| observability | `modules/observability` | KMS-encrypted log groups, dashboard, alarms (DLQ depth, worker errors, ack/answer p95) (§5) |

> **IAM cycle-break:** the `security` module scopes its IAM policies to ARNs *constructed
> from the name prefix* (`data.aws_caller_identity` + region + partition) rather than
> consuming the data/messaging module outputs, so it stays a dependency-free foundation
> module (KMS + secrets + roles) that the other modules can depend on without a Terraform
> module cycle.

> **Timing invariant in lock-step (§2.4):** budget 30s (`request_time_budget_seconds`) <
> Lambda 45s (`worker_lambda_timeout_seconds`) ≤ SQS visibility 90s
> (`queue_visibility_timeout_seconds`) == lease staleness 90s; `maxReceiveCount` 3 ==
> `max_attempts`. All are root variables so they move together if tuned.


## Existing-VPC / per-endpoint-toggle increment (this pass)

Follow-on to SLICE 9, authored and **validated only** (`terraform fmt -check -recursive` +
`terraform init -backend=false` + `terraform validate`; `shellcheck` + `bash -n` for the
script) — **never** `apply`, never plan-with-backend, never destroy (OOS-3). Existing module
structure and stable IDs preserved.

- **Per-endpoint interface VPC endpoint toggles** (`modules/networking`) — the former
  `for_each` interface-endpoint block is now one `aws_vpc_endpoint` resource per service with
  `count = var.X ? 1 : 0`: `create_sqs_endpoint`, `create_secretsmanager_endpoint`,
  `create_logs_endpoint`, `create_ecr_api_endpoint`, `create_ecr_dkr_endpoint` (default
  `true`) and `create_bedrock_endpoint` (**default `false`** — Bedrock failover egresses via
  NAT unless compliance requires PrivateLink). Root passthrough vars + `terraform.tfvars.example`
  wired. **DynamoDB + S3 remain free gateway endpoints** (S3 added this pass).
  > **Endpoint-set change (flagged):** the prior set was SQS/Secrets/**KMS**/Bedrock. The
  > requested toggle set replaces the standalone **KMS** interface endpoint with **Logs +
  > ECR-api + ECR-dkr** (matching the §10 cost model's 6-endpoint list). KMS API traffic now
  > egresses via NAT (or an endpoint can be re-added if required).
- **Destroy-safe existing-VPC mode** (`modules/networking`) — `use_existing_network` (default
  `false`) consumes an existing VPC/subnets/SG/route-tables via **data sources / by-ID only**
  (`data.aws_vpc`, `data.aws_subnet`, `data.aws_security_group`, `data.aws_route_tables`);
  `existing_nat_gateway` skips NAT creation. All managed network resources are `count`-gated on
  `!use_existing_network`, so `terraform destroy` can never delete borrowed infra. Explicit
  guarantee comment block at the top of `modules/networking/main.tf` and root `variables.tf`.
- **Destroy-safe existing-ALB mode** (`modules/gateway`) — `use_existing_alb` +
  `existing_alb_listener_arn` add an `aws_lb_listener_rule` onto a borrowed listener (read via
  `data.aws_lb_listener` / `data.aws_lb`) instead of creating an ALB; the created ALB / listener
  / ALB-SG are `count`-gated off in that mode. Target group + service stay app-created.
- **Deploy script** — `scripts/deploy.sh` (`set -euo pipefail`, `usage()`, `[[ ]]`, quoted
  expansions, shellcheck-clean) sources a gitignored `./deploy.env` (override `-e`), maps
  values to `TF_VAR_*`, runs `terraform init -backend-config=...` then **`plan` by default**;
  `apply` only with explicit `--apply`. **No destroy command.** `scripts/deploy.env.example`
  documents every variable; `deploy.env` added to `.gitignore`.
- **Docs** — `docs/DEPLOYMENT.md` §5.1 (existing-VPC/ALB mode + per-endpoint toggles +
  destroy-safety guarantee), §5.2 (`deploy.sh`/`deploy.env`), §6.1 ('Build & push the
  kiro-gateway image (Docker)' — pull pinned tag or build upstream UNMODIFIED, ECR
  login/create/tag/push, runtime secret injection, AGPL boundary), and refreshed cost numbers
  (§8/§10) for the Bedrock endpoint dropped by default (5 interface endpoints).


## Kiro credentials injection increment (this pass)

Follow-on to the existing-VPC slice; authored and **validated only** (`terraform fmt -check` +
`init -backend=false` + `validate`; `shellcheck` + `bash -n` for scripts). The credential flow
was **empirically verified** against the real upstream image (`ghcr.io/jwadow/kiro-gateway`)
with local Docker smoke tests before finalizing.

- **Problem found:** the gateway's Kiro API rejects requests with `400 profileArn is required`
  for Builder-ID/desktop accounts; the JSON-credentials path alone (even with
  `clientId`/`clientSecret`) does **not** supply it. The `profileArn` lives in the kiro-cli DB
  `state` table (`api.codewhisperer.profile`), not in `auth_kv`.
- **Solution (proven OK end-to-end):** `scripts/kiro-creds-to-secret.sh` extracts
  `accessToken`/`refreshToken`/`expiresAt`/`region` (`auth_kv` token row),
  `clientId`/`clientSecret` (`auth_kv` device-registration row), and `profileArn` (`state`
  table) from the local kiro-cli SQLite DB, reshapes snake_case→camelCase into the gateway's
  "Option 1" JSON, and pushes it to Secrets Manager (`-p`/`-s`) or a local 0600 file (`-o`).
  Secret values are never printed; the JSON is piped to `aws` / written `umask 077`.
- **`modules/gateway`:** task definition now mounts a task-local shared volume (`kiro-creds`)
  and runs an **init container** (pinned `busybox`) that writes the injected secret JSON to
  `/creds/kiro-auth-token.json`; the unmodified gateway reads it via `KIRO_CREDS_FILE`
  (`dependsOn` SUCCESS). The bogus `KIRO_SSO_CREDENTIALS` env was removed (the upstream image
  has no such variable). **`container_port` corrected 8080 → 8000** (verified the image's
  listener), aligning the ALB target group + `/health` check. No IAM change needed — the
  existing execution-role policy already grants `GetSecretValue` on `kiro_sso` + `kms:Decrypt`.
- **`scripts/deploy.sh`:** added `--load-kiro-creds` (post-`--apply` only; runs the extractor
  against the deployed secret). Plan path stays read-only.
- **Docs:** `docs/DEPLOYMENT.md` §4 (secret name/content), §6.2 (credential extraction + the
  profileArn rationale + init-sidecar mechanism + token-refresh caveat + port-8000 note).
- **`.gitignore`:** `kiro-auth-token.json`, `*.sqlite3`.
