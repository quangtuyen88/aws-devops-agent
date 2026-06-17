# Infrastructure Specification — Slack DevOps Agent (UNIT-001)

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `infrastructure-design` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-systems-architect-agent · Reviewer: aidlc-architecture-reviewer-agent ·
> Autonomy: **supervised**.
>
> This stage maps the 8 logical components (CMP-001..008) and the two-role runtime
> (always-on **intake** + horizontally-scalable **worker**, split by the internal durable
> **C-1** queue seam) onto concrete AWS services, and resolves the 5 deferred items from
> `nfr-design/nfr-spec.md §5`. The NFR stage fixed all **policies and targets**; this stage
> chooses the **concrete services and mechanisms**, then verifies the mapping against each NFR.
>
> **Human decisions applied** (`questions.md`, recorded 2026-06-17T14:13:37+08:00):
> **Q1=a · Q2=both-backends-behind-CMP-003 (Kiro primary via self-hosted kiro-gateway + Bedrock alternate) · Q3=a (+kiro-gateway container) · Q4=a · Q5=a · Q6=a.**
>
> No stable ID (CMP-001..008, ENT-001..014, UNIT-001, NFR-*, FR-*, CS-*, A-*, BR-*) is renamed.

---

## 0. Decisions Resolved (the 5 NFR hand-off items + A-1)

| # | Hand-off item (`nfr-spec.md §5`) | Policy fixed in nfr-design | **Concrete decision (this stage)** |
|---|---|---|---|
| 1 | Exact input-token budget (NFR-14) | hybrid trim/reject + 12k default | **12,000 input tokens / 4,000 reserved output** (Claude family via Kiro/Bedrock; chosen for latency+cost, not model capacity — the 200k Claude window is far larger). Tunable in `Config`. **(F7)** The **4,000 reserved-output** value is an **infrastructure-introduced default**, NOT an nfr-design requirement (NFR-14 governs the *input* budget only). It is a tunable `Config` parameter — code-generation MUST treat it as configurable, not a fixed requirement. |
| 2 | Worker concurrency + scaling mechanism (NFR-10) | queue-draining pattern, ≥10 target | **SQS → Lambda event-source with `batch_size=1`**, worker **reserved concurrency = 15**, SQS event-source **maximum concurrency = 12** (backs the ≥10 target with headroom; one job per invocation ⇒ no head-of-line blocking). |
| 3 | Metrics/log sink + dashboards (NFR-20) | required signal set + correlation-id keying | **Amazon CloudWatch** — structured JSON logs (correlation-id = `job-id`), metrics via **EMF**, one dashboard + alarms. |
| 4 | Secret-manager + per-integration IAM scopes (NFR-5) | secret-manager-stored, least-privilege | **AWS Secrets Manager** (one secret per integration) + **one least-privilege IAM role per runtime role**, scoped to specific secret/resource ARNs (see §4). |
| 5 | Concrete queue + datastore + inference backend (A-1) | dependency-bounded SLO + per-dependency breaker | **SQS** (C-1 queue) + **DynamoDB** (jobs/opdata/config) + **inference = Kiro primary** (self-hosted `kiro-gateway` container) **/ Bedrock alternate** (boto3 Converse), both behind the CMP-003 seam (API-INT-001). |

**A-1 resolution detail:** CMP-003 ships with **two interchangeable backends** behind its
stable interface (API-INT-001):

- **Primary — Kiro** via a self-hosted **`kiro-gateway`** (FastAPI, OpenAI-compatible
  `POST /v1/chat/completions` + Anthropic-compatible `POST /v1/messages`, bearer-auth via
  `PROXY_API_KEY`), serving Claude models from the Kiro subscription. It is **stateful**
  (holds/refreshes Kiro SSO tokens) ⇒ it runs as an **always-on container**, not a Lambda.
- **Alternate — Amazon Bedrock** (`Converse`/`InvokeModel`) via boto3, selected by config
  through the same CMP-003 interface — no agent-core change to switch.

> **Failover semantics (F4) — config/deploy-time, NOT automatic per-request.** The
> Kiro→Bedrock switch is an **operator-flipped configuration/deploy-time** change (the
> `backend-id` selected in `Config`), **not** an automatic per-request failover. When the
> `kiro-gateway` circuit breaker (CMP-003, NFR-16) opens, in-flight jobs **fail gracefully**
> (FR-17 in-thread failure message, abandon-to-`failed` after `maxReceiveCount`), and they
> keep failing until an operator flips `backend-id` to `bedrock` and the change is rolled
> out. The Bedrock alternate therefore provides **disaster-recovery / business-continuity**
> resilience, **not** in-request resilience. In-request / in-band resilience for the primary
> path comes instead from the **Multi-AZ baseline of the `kiro-gateway` Fargate service**
> (§2.3) — see F4 availability classification in §7 (NFR-9).

> ⚠️ **LICENSING WATCH-ITEM (open — must be confirmed before code-generation):**
> `kiro-gateway` (github.com/jwadow/kiro-gateway) is **AGPL-3.0**. Under AGPL, *network use is
> distribution* — operating it as a service can trigger source-disclosure obligations to
> users who interact with it over a network. This is **NOT silently accepted**. Mitigations:
> (a) deploy it as a **separate, unmodified** container artifact (do not fork into our
> codebase) to bound copyleft scope; (b) if modified, publish the modified source; (c) the
> CMP-003 seam means **Bedrock can be made primary** to avoid AGPL entirely if legal review
> rejects it. Surface again at the code-generation gate. (Cross-ref: `components.yaml`
> CMP-003 physical mapping, `unit.md` infra appendix.)

---

## 1. Service Mapping — CMP-001..008 → AWS services

| CMP | Component | Runtime role | Concrete AWS service(s) | NFR satisfied |
|---|---|---|---|---|
| CMP-001 | Slack Interaction Adapter | intake **and** outbound | **API Gateway (HTTP API)** + **intake Lambda** (Slack Bolt, signature verify, dedup-register, ack, enqueue). **Inbound `reaction_added`/`reaction_removed` events (W4/FR-16) also arrive here** — the same API Gateway routes them to the **intake** Lambda, which handles them **synchronously** (W4: filter 👍/👎 on bot answers, normalise, resolve `answer-message-ts`→`Answer.correlation-id` per BR-018, append `FeedbackSignal` to `OperationalData` via CMP-007/API-INT-007). **Reactions never enter SQS or the worker** (they are not agent-loop work). Outbound (answer/failure/heartbeat posts) runs **inside the worker Lambda** using the Slack Web API. | NFR-1, NFR-6, NFR-7 |
| CMP-002 | Agent Orchestrator | worker | **worker Lambda** (SQS-triggered), reserved concurrency 15 | NFR-2, NFR-9, NFR-10, NFR-11, NFR-12, NFR-16, NFR-17 |
| CMP-003 | Inference Provider (library) | worker (in-proc) | calls **`kiro-gateway`** (ECS Fargate) over internal HTTPS (primary) / **Bedrock Converse** via boto3 (alternate) | NFR-9, NFR-16, NFR-5 |
| CMP-004 | AWS Knowledge MCP Client | worker (in-proc) | outbound **HTTPS → hosted `aws-knowledge-mcp-server`** (via NAT) | NFR-7, NFR-16, NFR-17 |
| CMP-005 | Input Safety Scanner | worker (in-proc) | in-process library; runs **before any egress** (CS-4) | NFR-4, NFR-6, NFR-21 |
| CMP-006 | Job Coordinator | intake + worker | **DynamoDB `ProcessingJob`** (conditional writes for dedup + single-winner lease) + **SQS** redelivery | NFR-19 |
| CMP-007 | Operational Data Service | worker | **DynamoDB `OperationalData`** (atomic-`ADD` usage counter, append feedback, adoption) | NFR-13, NFR-20 |
| CMP-008 | Configuration & Policy | all (read) | **DynamoDB `Config`** (allowlist, usage policy, guardrail thresholds) | NFR-3, NFR-5 |
| — (C-1 seam) | intake→worker queue (API-INT-009) | infra | **Amazon SQS** (Standard) + **SQS DLQ** | NFR-10, NFR-19 |
| — (recovery reaper) | NFR-19 backstop / FR-17 | infra | **EventBridge Scheduler → reaper Lambda** (no VPC; periodic). Drains the **DLQ**, marks abandoned jobs `failed` in `ProcessingJob`, and **posts the FR-17 failure message in-thread** using `ProcessingJob.originating-message-ref` + `slack/bot-token`; emits recovery/abandon counters. | NFR-19, NFR-20, FR-17 |
| — (inference backend) | A-1 dependency | infra | **`kiro-gateway` on ECS Fargate** (+ internal ALB) / **Bedrock** | A-1, NFR-9, NFR-16 |

> The queue, the inference endpoints, the MCP server, and the datastores are **dependencies
> of** the components (per `components.yaml`), not components themselves — consistent with the
> domain/units blueprint.

> **ProcessingJob key design (F1) — dedup keys on `slack-event-identity`, not `job-id`.**
> Reconciled with ENT-008 (`entities.yaml`): the two identity attributes are **distinct** and
> are kept distinct here.
> - **Table partition key = `slack-event-identity`** = `channel-id#message-ts` (ENT-008,
>   `unique:true`). This is the **canonical at-most-once-completed dedup key (CS-3/NFR-19)**.
>   Intake performs a **conditional `PutItem` with `attribute_not_exists(slack-event-identity)`**
>   so a Slack at-least-once redelivery (`slack-retry-num`) or an intake re-enqueue of the same
>   `(channel-id, message-ts)` attaches to the existing job rather than creating a second — "at
>   most ONE ProcessingJob per `slack-event-identity`."
> - **`job-id`** is a **stamped, immutable `uuid` attribute** (== `InboundMention.correlation-id`
>   == `Answer.correlation-id`, DA-1), assigned at intake. It is **NOT** derived from
>   `channel-id#message-ts` and is **NOT** the dedup mechanism. It remains the correlation-id
>   used for log keying (§5), cross-seam tracing (SQS message attribute), and the **idempotent
>   answer-post key (BR-027)**. (A GSI on `job-id` is available if a job must be fetched by
>   correlation-id; the hot dedup/lease path uses the `slack-event-identity` PK directly.)
> - **Single-winner lease (CS-2/BR-027):** a conditional `UpdateItem` on the **same item**
>   (compare-and-set on `status` + `attempt-count` + `last-transition-at`) guarantees one winner
>   enters `in-progress`. This corrects the prior text that made `job-id` the PK and conditioned
>   dedup on it — that contradicted ENT-008 and the "correlation-id stamped/immutable at intake"
>   invariant. `components.yaml` CMP-006 mapping is updated to match.

---

## 2. Compute

### 2.1 Intake role (always-on, NFR-1)

| Property | Value | Rationale |
|---|---|---|
| Service | API Gateway **HTTP API** + Lambda | Bolt handles Slack signature verify + 3s ack out of the box (C-1). |
| VPC | **No VPC** | Only touches public AWS endpoints (SQS, DynamoDB) + Slack HTTPS; staying out of VPC removes ENI cold-start penalty → protects p95 < 3s. |
| Memory / timeout | 512 MB / **10 s** | Ack work is light (verify, conditional dedup write, enqueue, ack). |
| Provisioned concurrency | **2** (tunable) | Bounds cold-start tail against NFR-1. **Residual risk:** burst beyond 2 may cold-start; monitored via the ack-latency histogram. |
| Responsibilities | FR-1/2/3/4 intake, dedup register (CMP-006), enqueue (API-INT-009), ack (NFR-1) | — |

### 2.2 Worker role (horizontally scalable, NFR-2/10)

| Property | Value | Rationale |
|---|---|---|
| Service | **SQS → Lambda** event-source mapping | Queue-draining horizontal scale "for free"; 30s pipeline sits well inside Lambda limits. |
| VPC | **In VPC** (private subnets) | Needs private reach to `kiro-gateway`; external egress via NAT + interface endpoints (see §3). |
| Memory / timeout | 1024 MB / **45 s** | I/O-bound (inference + MCP); 45s is a hard ceiling *above* the soft 30s NFR-17 budget so the app resolves `failed` gracefully before Lambda kills it. |
| `batch_size` | **1** | One job per invocation ⇒ a slow job cannot block others (**NFR-10, no head-of-line blocking**). |
| Reserved concurrency | **15** | Backs the ≥10 NFR-10 target with headroom. |
| Event-source max concurrency | **12** | Caps SQS-driven fan-out; ≥10 target preserved. |
| Provisioned concurrency | 2 (optional, tunable) | Optional warm pool to trim p95 on the NFR-2 path. |

### 2.3 Inference gateway (kiro-gateway, always-on)

| Property | Value | Rationale |
|---|---|---|
| Service | **ECS Fargate** service (**baseline 2 tasks across 2 AZs**, autoscale **2→4** on CPU/req) behind an **internal ALB** | Stateful (Kiro SSO token refresh) ⇒ must be long-running; private-only. **(F4)** Raised from a single baseline task: `kiro-gateway` is the **primary** inference path and is **our own** infrastructure (§7 NFR-9), so a single baseline task is a single point of failure for the core capability. A **Multi-AZ baseline of 2** gives in-band resilience to a task crash or single-AZ event without depending on the (manual, config-time) Bedrock failover. Each task independently holds/refreshes its own Kiro SSO token. |
| Image | upstream `kiro-gateway` (AGPL — see §0 watch-item), unmodified | Bounds copyleft scope. |
| Secrets | Kiro SSO creds + `PROXY_API_KEY` in **Secrets Manager** | NFR-5. |
| Network | private subnets, internal ALB only (no public ingress) | Reachable only from the worker Lambda inside the VPC. |
| TLS | TLS on the internal ALB listener | NFR-5 in-transit. |

### 2.4 Timing reconciliation (NFR-17 ↔ NFR-19 ↔ SQS) — **critical invariant**

| Knob | Value | Constraint it satisfies |
|---|---|---|
| NFR-17 per-request budget | **30 s** (app-enforced soft wall clock) | bounds the W2 pipeline |
| Worker Lambda timeout | **45 s** | ≥ budget; hard safety net |
| SQS visibility timeout | **90 s** | ≥ Lambda timeout (45s); == staleness bound ⇒ redelivery aligns with lease reclaim. **(F5)** boundary resolved by an **inclusive** reclaim check (below) |
| Lease staleness bound (NFR-19) | **90 s** | > budget (30s) + heartbeat margin (15s) ⇒ a **live** job is never reclaimed |
| `maxReceiveCount` → DLQ | **3** (== `max_attempt`) | abandon-to-`failed` after 3 attempts (BR-022) |

Heartbeats (NFR-11, every 15s) refresh `ProcessingJob.last-transition-at`, so a live worker
keeps its lease fresh; a dead worker's lease goes stale at 90s exactly when SQS makes the
message visible again → the redelivered invocation reclaims it (attempt++). The single-winner
lease + idempotent post (BR-027) guarantees **at-most-once *completed*** — no duplicate answer.

> **F5 — boundary-race resolution (visibility 90s == staleness 90s).** Because SQS makes the
> message visible at the **same instant** the lease becomes reclaimable, the reclaim check MUST
> be **inclusive**: a job is reclaimable when `now − last_transition_at >= 90s` (**`>=`, not
> `>`**). With the inclusive comparison, the redelivered worker at the 90s boundary finds the
> lease stale and reclaims it (attempt++), rather than finding it "not-yet-stale" and deferring
> a full visibility cycle. The **NFR-19 kill-worker test MUST assert this exact boundary**
> (a worker killed so its last heartbeat lands at T, redelivered at T+90s, reclaims on the
> first redelivery). Defense-in-depth option if the platform's visibility timer proves coarse:
> set visibility marginally above staleness (e.g. 95s) — but the inclusive `>=` check is the
> primary, sufficient resolution and keeps the invariant table values aligned.

> **F6 — heartbeat-as-lease-refresh is an explicit liveness assumption.** The 15s heartbeat
> (NFR-11) doubles as the lease refresh: it updates `last-transition-at` from an async timer
> **inside the worker invocation**. **Assumption:** the heartbeat timer fires on schedule. If a
> long synchronous / CPU-bound section starves the timer, a **live** worker's lease can go stale
> at 90s and a recovery worker may reclaim the job. This is **tolerated by design** because the
> single-winner lease + **idempotent answer-post (BR-027)** guarantee at-most-once *completed* —
> at worst the job is reprocessed, never double-answered. Code-generation should keep heartbeat
> emission off the critical CPU path (e.g. a separate timer/thread) to minimise the window.

---

## 3. Network Topology

```
Slack ──HTTPS──▶ API Gateway (HTTP API) ──▶ intake Lambda (no VPC)
                                                  │ PutItem(cond)         SendMessage
                                                  ▼                        ▼
                                            DynamoDB:ProcessingJob     SQS (C-1) ──▶ DLQ
                                                                            │ trigger (batch=1)
                                                                            ▼
                                              ┌──────────  worker Lambda (VPC, private subnets) ──────────┐
                                              │  CMP-002 orchestrator + CMP-003/004/005 in-process libs    │
                                              └───┬───────────────┬───────────────┬───────────────┬───────┘
                          internal ALB (TLS) ◀───┘ kiro-gateway   │ NAT GW        │ VPC endpoints │
                          ECS Fargate (Kiro)                       ▼               ▼               ▼
                                                       Slack Web API +     Bedrock (iface),   DynamoDB (gw),
                                                       aws-knowledge-mcp    Secrets Mgr,       SQS, CloudWatch,
                                                       (public HTTPS)       (iface)            KMS (iface)
```

- **Public ingress:** only the API Gateway HTTPS endpoint (Slack Events). Slack request
  signature verified at the intake Lambda (boundary validation).
- **intake Lambda:** no VPC; uses public AWS API endpoints for SQS/DynamoDB + Slack HTTPS.
  **(F2)** also receives inbound `reaction_added`/`reaction_removed` via the same API Gateway
  and writes `FeedbackSignal` to `OperationalData` synchronously (no SQS/worker hop).
- **recovery reaper Lambda (F3):** no VPC; EventBridge-scheduled; reaches DLQ (SQS),
  `ProcessingJob` (DynamoDB), `slack/bot-token` (Secrets Manager) and Slack Web API over
  public AWS + Slack HTTPS endpoints. Does not touch `kiro-gateway`/MCP.
- **worker Lambda:** in **private subnets**. External HTTPS egress (Slack Web API, MCP) via
  **NAT Gateway**. **Bedrock, Secrets Manager, KMS** via **interface VPC endpoints** (keeps
  that traffic off NAT and IAM-scoped). **DynamoDB** via a (free) **gateway VPC endpoint**;
  **SQS** via interface endpoint. `kiro-gateway` reached over the **internal ALB** (private).
- **Egress posture:** outbound HTTPS only; NAT egress can be restricted to the MCP + Slack
  domains via an egress allowlist (e.g. firewall/route policy). **Residual cost:** the NAT
  Gateway is the main always-on cost item introduced by the VPC posture; acceptable for the
  security benefit (no public inference gateway) on an internal tool.

> **Security note:** the only network-exposed endpoint is the API Gateway, which is
> authenticated by **Slack request-signature verification**. `kiro-gateway` is **never**
> publicly exposed (internal ALB + `PROXY_API_KEY`). No unauthenticated public surface is created.

---

## 4. Security Boundaries

### 4.1 Secrets (AWS Secrets Manager — one per integration, NFR-5)

| Secret | Holder | Consumed by |
|---|---|---|
| `slack/signing-secret` | Slack signature verify | intake Lambda |
| `slack/bot-token` | Slack Web API | intake + worker + reaper Lambda |
| `inference/kiro-gateway-proxy-key` (`PROXY_API_KEY`) | gateway bearer auth | worker Lambda |
| `inference/kiro-sso-credentials` | Kiro token refresh | **kiro-gateway only** |
| `mcp/aws-knowledge-credential` | MCP auth | worker Lambda |

All secrets KMS-encrypted; no credential literals in source/config (verified by CI
`git-secrets`/`bandit`, NFR-5). Bedrock uses IAM (no stored secret).

### 4.2 IAM least-privilege (one role per runtime role, scoped to ARNs)

- **intake-lambda-role:** `sqs:SendMessage` (queue ARN only); `dynamodb:PutItem/GetItem`
  (ProcessingJob table only); **`dynamodb:PutItem` + `dynamodb:Query/GetItem` (OperationalData
  table only) — (F2)** for the inbound reaction path: append the append-only `FeedbackSignal`
  (W4/FR-16, BR-018/BR-020/R-3) and resolve `answer-message-ts`→`Answer.correlation-id`. No
  `UpdateItem` (feedback is append-only, never mutated). `dynamodb:GetItem/Query` (read Config);
  `secretsmanager:GetSecretValue` (slack secrets only); logs.
- **reaper-lambda-role (F3 — recovery reaper, no VPC):** `dynamodb:UpdateItem/Query`
  (ProcessingJob only — mark abandoned jobs `failed`, read `originating-message-ref`);
  `sqs:ReceiveMessage/DeleteMessage/GetQueueAttributes` (**DLQ ARN only**);
  `secretsmanager:GetSecretValue` (`slack/bot-token` only — to post the FR-17 in-thread failure
  message); logs. **No** SQS send, **no** OperationalData, **no** inference/MCP perms. Reaches
  DynamoDB/SQS/Secrets/Slack over public AWS + Slack HTTPS endpoints (no VPC, like intake).
- **worker-lambda-role:** `sqs:ReceiveMessage/DeleteMessage/GetQueueAttributes` (queue);
  `dynamodb:UpdateItem/PutItem/GetItem/Query` (ProcessingJob + OperationalData + read Config);
  `bedrock:InvokeModel`,`bedrock:Converse` (**specific model ARNs only**);
  `secretsmanager:GetSecretValue` (kiro-proxy + mcp + slack-bot secrets only);
  `cloudwatch:PutMetricData` not needed (EMF via logs); logs + VPC-ENI (managed).
- **kiro-gateway-task-role:** `secretsmanager:GetSecretValue` (kiro-sso + proxy-key only);
  logs. **No AWS data-plane permissions** (cannot read jobs/opdata).
- No `*` actions or `*` resources; each granted scope == required scope.

### 4.3 Pre-send secret gate, transit & at-rest

- **CMP-005 gate placement (NFR-4/CS-4):** in-process in the worker, executed **before** any
  call to `kiro-gateway`/Bedrock/MCP. On `refuse` → zero egress; named-class refuse message
  posted via Slack. No override path (Q4=b invariant preserved).
- **In transit (NFR-5):** TLS 1.2+ on every hop — Slack HTTPS, API GW HTTPS, internal ALB
  TLS, Bedrock/MCP/Secrets Manager/DynamoDB over TLS.
- **At rest:** DynamoDB (`ProcessingJob`,`OperationalData`,`Config`) and Secrets Manager use
  **customer-managed KMS keys**; SQS uses SSE (KMS); CloudWatch Logs KMS-encrypted.

---

## 5. Observability (CloudWatch — NFR-20)

- **Logs:** structured JSON, one line per event, **`correlation-id` = `ProcessingJob.job-id`**
  on every line (propagated across the C-1 seam as an SQS message attribute). JSON logger
  redacts; secret findings logged as **class only** (NFR-6/BR-026). Log-group retention 30d,
  KMS-encrypted.
- **Metrics (via EMF, emitted from worker/intake logs):**
  | Signal | Type | Verifies |
  |---|---|---|
  | ack latency | histogram (intake) | NFR-1 |
  | full-answer latency | histogram (worker) | NFR-2 |
  | `failure-by-cause` `{timeout,budget,cap,oversize,dependency,safety-refuse,retries-exhausted}` | counter | NFR-7/12/14/17 |
  | usage count + degrade count | counter | NFR-8/13 |
  | adoption: distinct developers, questions handled | counter | FR-18 |
  | circuit-breaker state per dependency | gauge | NFR-16 |
  | in-flight concurrency + recovery/abandon | gauge + counter | NFR-10/19 |
- **Dashboard:** one CloudWatch dashboard (latency p95 widgets, failure-by-cause, breaker
  states, usage-vs-budget, concurrency, SLO-window availability split own-vs-dependency).
- **Alarms:** ack p95 > 3s; answer p95 > 30s; any breaker open > 5 min; **DLQ depth > 0**;
  usage ≥ 90% of budget; worker error rate. Correlation via Logs Insights queries keyed by
  `correlation-id`. (Optional X-Ray trace intake→SQS→worker, correlation-id propagated.)

---

## 6. Deployment Strategy

- **IaC:** **Terraform**, remote state in **S3 + DynamoDB lock**; **region & account
  parameterised** (variables/workspaces) so promotion to multi-account (Q1 option b) is
  mechanical. `terraform fmt`/`validate` gate; **execution is manual** (org rule: the agent
  writes IaC, never applies it).
- **Modules:** `networking` (VPC, subnets, NAT, endpoints) · `messaging` (SQS + DLQ) ·
  `data` (3 DynamoDB tables + KMS) · `compute-intake` (API GW + Lambda + provisioned conc.) ·
  `compute-worker` (Lambda + SQS event-source) · `recovery` (EventBridge Scheduler + reaper
  Lambda + reaper-lambda-role — F3) · `gateway` (ECS Fargate kiro-gateway + ALB) ·
  `security` (IAM roles, KMS keys, Secrets Manager) · `observability` (log groups, dashboard,
  alarms).
- **Two-role deploy from one artifact:** intake Lambda + worker Lambda built from the **same
  UNIT-001 codebase/image** (one version); `kiro-gateway` is a **separate third-party image**
  (AGPL boundary, §0). Lambda versions + aliases enable blue/green alias shift; ECS uses
  rolling update with deployment-circuit-breaker auto-rollback.
- **Rollback / RTO:** Lambda alias shift or Terraform revert; ECS auto-rollback. In-flight
  jobs survive a deploy because the **SQS queue + DynamoDB job state are durable** (CS-2) — no
  job is lost across a rollout; RTO is bounded by the 90s lease/redelivery cycle, well within
  the business-hours SLO (NFR-9).
- **Recovery scan (NFR-19):** primary = **SQS redelivery** (visibility-timeout-driven) with
  the per-delivery lease-staleness check (inclusive `>=`, F5); backstop = an **EventBridge-scheduled reaper** (mapped in §1, IAM `reaper-lambda-role` in §4.2) that
  drains the DLQ, marks abandoned jobs `failed` (FR-17), **posts the FR-17 in-thread failure
  message** using `ProcessingJob.originating-message-ref` + `slack/bot-token`, and emits the
  recovery/abandon counters (NFR-20).

---

## 7. NFR Cross-Check (every NFR → infrastructure decision + residual risk)

| NFR | Infrastructure decision that satisfies it | Residual risk |
|---|---|---|
| NFR-1 (ack p95<3s) | API GW + no-VPC intake Lambda + provisioned concurrency 2 | Burst beyond provisioned pool may cold-start; watched via ack histogram |
| NFR-2 (answer p95≤30s) | worker Lambda 1024MB/45s; optional provisioned conc. | Inference/MCP latency is dependency-bound (NFR-9) |
| NFR-5 (creds/least-priv) | Secrets Manager (1/integration) + per-role IAM scoped to ARNs; KMS | kiro-gateway holds Kiro SSO creds — isolated task role, no data-plane perms |
| NFR-6 (no secrets/PII in logs) | JSON logger redaction; class-only findings; KMS log groups | heuristic redaction (A-6) — same best-effort limit as CMP-005 |
| NFR-7 (rate limits) | bounded retry in worker; SQS redelivery; never silent drop | — |
| NFR-9 (~99% biz-hours, dep-bounded) | durable SQS+DynamoDB; breaker fast-fail; error-budget split own/dependency. **(F4)** `kiro-gateway` is classified **OWN infrastructure** (self-operated ECS Fargate), so its failures — token-refresh failure, task crash, AZ loss — count against **our** error budget, **not** the dependency exclusion. Resilience instrument: **Multi-AZ baseline of 2 tasks** (§2.3) for in-band availability; Bedrock is a **manual/config-time DR alternate** (not per-request failover). Only the **upstream model services** (Kiro subscription backend, Bedrock service, MCP server) remain on the *dependency* side of the split. | own-side risk now bounded by the Fargate Multi-AZ baseline; the Kiro/Bedrock model backends + MCP remain dependency-bound (C-3); manual Bedrock cutover is the budget backstop if `kiro-gateway` is fully lost |
| NFR-10 (≥10, no HOL block) | SQS→Lambda `batch_size=1`, reserved conc. 15, max conc. 12 | account Lambda concurrency limit must allow 15 (verify in target account) |
| NFR-11 (heartbeat 15s) | in-invocation timer posts via Slack Web API | within single Lambda invocation |
| NFR-12 (per-req cap ≤2 inf/≤5 MCP) | enforced in worker loop; `failure-by-cause=cap` metric | app-level (CMP-002) |
| NFR-13 (soft budget 500/24h) | DynamoDB atomic `ADD` counter; graceful degrade | atomic increment avoids lost-update under concurrency |
| NFR-14 (input budget) | **12,000 input / 4,000 output tokens** (Config-tunable); trim-with-notice / reject | conservative vs 200k model window — intentional for latency/cost. **(F7)** 4,000 output is an infra-introduced tunable default, not an nfr-design requirement |
| NFR-15 (retry/backoff) | in-process backoff lib, all retries inside the 30s budget | — |
| NFR-16 (breaker/dependency) | per-dependency breaker in CMP-003/004; breaker-state gauge | three breakers: Slack, inference, MCP |
| NFR-17 (30s budget) | app soft budget 30s < Lambda 45s < SQS visibility 90s | invariant table §2.4 |
| NFR-19 (recovery, at-most-once-completed) | dedup PK = `slack-event-identity` (cond. `PutItem`, F1); SQS visibility 90s == lease staleness 90s with **inclusive `>=` reclaim** (F5); maxReceiveCount 3→DLQ; EventBridge reaper posts FR-17 (F3) | timing invariant §2.4 must be kept in lock-step if any value is tuned; kill-worker test asserts the 90s boundary |
| NFR-20 (observability) | CloudWatch logs+EMF+dashboard+alarms, correlation-id keyed | EMF metric cardinality on `failure-by-cause` dimension kept bounded |
| NFR-21 (secret detection) | CMP-005 in-process pre-egress; refuse-or-allow | heuristic (A-6) — documented limits |

App-level NFRs not infra-bound (NFR-3 policy text, NFR-4 invariant logic, NFR-8 guardrail
decision) are owned by CMP-008/CMP-005/CMP-007 respectively; infrastructure only provides the
KMS-encrypted `Config`/`OperationalData` stores and the pre-egress placement that let them hold.

---

## 8. Copied Blueprint Expansions

| Copied-forward artifact | Source | Expansion added this stage (no ID renamed) |
|---|---|---|
| `components.yaml` | `functional-design/components.yaml` | `Infrastructure-Design-Refs` appendix: per-CMP physical mapping (compute, storage, network, IAM, observability, deployment). |
| `unit.md` | `functional-design/unit.md` | `Infrastructure-Design Expansion` appendix: deployment topology, Terraform module refs, runtime config, two-role deploy, operational ownership, AGPL watch-item. |

> **Artifact-resolution note (per work-method):** nfr-design emitted no `components.yaml`/
> `unit.md`; the richest upstream copies (NFR+functional-enriched) live in `functional-design/`
> and are copied forward and expanded **in place**, preserving every stable ID.

---

## 9. Review Findings Resolution (aidlc-architecture-reviewer-agent, 2026-06-17)

| ID | Resolution | Where |
|---|---|---|
| **F1** | ProcessingJob **PK = `slack-event-identity`** (`channel-id#message-ts`), conditional `PutItem` on `attribute_not_exists` enforces CS-3 dedup; **`job-id` is a stamped immutable `uuid` attribute** (== correlation-id, DA-1), not the dedup key and not derived from `channel#message-ts`. Single-winner lease = conditional `UpdateItem` on the same item. Now consistent with ENT-008. | §1 key-design note; `components.yaml` CMP-006 |
| **F2** | Reactions modelled as **inbound** events: API Gateway → **intake** Lambda → CMP-007 (synchronous, W4); never enter SQS/worker. `intake-lambda-role` granted **`OperationalData` write** (append-only `FeedbackSignal`) + resolution read. Worker "reaction capture" removed. | §1 CMP-001 row; §4.2 IAM; `components.yaml` CMP-001/CMP-007 |
| **F3** | **EventBridge → reaper Lambda** added to service mapping; `reaper-lambda-role` defined (ProcessingJob write, DLQ SQS, `slack/bot-token`, logs, metrics). Posts FR-17 in-thread via `ProcessingJob.originating-message-ref` — confirmed available on the durable record. | §1 reaper row; §4.1/§4.2; §6; `components.yaml` CMP-006 |
| **F4** | `kiro-gateway` classified **OWN infrastructure** in the NFR-9 split (its failures count against our budget). Failover = **config/deploy-time, manual**, not per-request. Baseline raised **1→2 tasks Multi-AZ** (in-band resilience); Bedrock = manual DR alternate. | §0 failover note; §2.3; §7 NFR-9 |
| **F5** | Lease-reclaim comparison specified **inclusive `>=`** (`now − last_transition_at >= 90s`); kill-worker test asserts the 90s boundary; optional visibility margin noted as defense-in-depth. | §2.4; §7 NFR-19 |
| **F6** | Heartbeat-as-lease-refresh stated as an **explicit liveness assumption**; idempotent post (BR-027) makes a starved-timer reclaim safe (reprocess, never double-answer). | §2.4 |
| **F7** | 4,000 reserved-output tokens flagged as an **infra-introduced tunable default**, not an nfr-design requirement. | §0 item 1; §7 NFR-14 |

---

## 10. Self-Check (Phase 4)

- ✅ All 8 components (CMP-001..008) mapped to concrete AWS services (§1).
- ✅ All 5 deferred hand-off items + A-1 resolved (§0).
- ✅ Every NFR (1,2,5,6,7,9,10,11,12,13,14,15,16,17,19,20,21) traced to an infrastructure
  decision with residual risk (§7).
- ✅ No stable ID renamed; copied-forward artifacts expanded in place (§8).
- ✅ Architecture-review findings F1–F4 resolved (correctness/completeness); F5–F7 addressed/acknowledged (§9).
- ✅ Out-of-scope preserved: OOS-3 (agent never executes/applies IaC — Terraform applied
  manually), A-5 (single workspace), A-8 (no durable conversation memory — only jobs/opdata/config).
- ⚠️ **Open watch-item carried to code-generation:** `kiro-gateway` AGPL-3.0 licensing (§0) —
  not silently accepted; Bedrock-as-primary is the ready fallback via the CMP-003 seam.
