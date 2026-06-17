# NFR Spec — Slack DevOps Agent (UNIT-001)

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `nfr-design` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-systems-architect-agent · Reviewer: aidlc-architecture-reviewer-agent.
>
> **`nfr.yaml` is the source of truth** for measurable targets, numbers, and verification
> methods. This file is the narrative: quality-attribute scenarios, the tech-stack
> decision, the cross-cutting patterns the service is built on, the full traceability
> matrix, and the infrastructure-design hand-off. Every stable ID (NFR-1..21, FR-*, CS-*,
> A-*, CMP-*) is preserved; nothing renamed.
>
> Human decisions (questions.md, 2026-06-17T13:38:12+08:00 — "go with recommendations"):
> **Q1=a · Q2=b · Q3=a · Q4=b · Q5=c**, plus the plan.md R-1..R-6 architecture-authority
> choices.

---

## 1. Quality-Attribute Scenarios

Each scenario: **stimulus → response → measure** (the measure is the verifiable NFR).

### Performance / Latency

- **S/NFR-1 (ack):** A developer `@mention`s the bot in an allowlisted channel → CMP-001
  validates, registers the job, posts the ack and returns HTTP 200 → **p95 < 3s**
  (Slack's retry window, C-1). *Verified by the intake latency histogram (NFR-20).*
- **S/NFR-2 (full answer):** An accepted question runs the W2 pipeline (context fetch →
  safety gate → budget check → inference+MCP loop → composition → post) → the grounded,
  cited answer lands in-thread → **p95 ≤ 30s** (A-3 confirmed, Q1=a). *Full-answer
  histogram, with a dedicated scenario for the heavy FR-9 architecture-review path.*
- **S/NFR-11 (heartbeat):** A grounded answer takes longer than 15s → a "still working…"
  update is posted in-thread at 15s and every 15s thereafter → user never stares at a
  bare ack. *Worker-timer unit test + manual check.* Additive UX; does not move the SLO.
- **S/NFR-17 (time budget):** Inference or MCP stalls → the 30s per-request wall-clock
  budget trips → the job resolves `failed` with an FR-17 message and `failure-by-cause=
  timeout`. *Fault-injection test.*

### Reliability / Resilience

- **S/NFR-7 (rate limits):** Slack/MCP return 429 / backpressure → bounded retry with
  backoff (NFR-15) honouring `Retry-After` → no crash, **no silent drop**; if the budget
  is exhausted the question fails gracefully (FR-17). *Simulated 429 responses.*
- **S/NFR-16 (breaker):** A dependency is sustained-down → its circuit breaker opens after
  5 consecutive failures (or ≥50% over 20 calls) → subsequent requests **fail fast (<1s)**
  to the FR-17 message instead of burning the 30s budget; half-open probe after 30s.
  *Sustained-outage fault injection; breaker-state gauge.*
- **S/NFR-19 (recovery):** A worker dies mid-job → the job's `in-progress` lease goes stale
  after 90s → a recovery scan re-enters `in-progress` (attempt++) up to `max_attempt=3`,
  then abandons to `failed`. The single-winner lease + idempotent post (BR-027) guarantee
  **at-most-once *completed*** — no duplicate answer. *Kill-worker test.*
- **S/NFR-9 (availability):** During business hours the service targets **~99%**, explicitly
  **dependency-bounded** (C-3): outages of Kiro/Bedrock or the MCP server are reported as
  graceful FR-17 failures and excluded from the error budget. *Error-budget report split by
  cause (own vs dependency).*

### Scalability

- **S/NFR-10 (concurrency):** Many developers ask at once and one question is slow → the
  horizontally-scalable worker role drains the internal C-1 queue so the slow question
  **does not stall others** (no head-of-line blocking); starting target ≥ 10 concurrent
  in-flight. *Inject one 25s question among many fast ones; assert isolation.* Concrete
  worker count/mechanism → infrastructure-design.

### Cost

- **S/NFR-12 (per-request cap):** The agent loop would exceed **≤ 2 inference / ≤ 5 MCP**
  calls for one question → the loop halts → the job fails with `failure-by-cause=cap`.
  *Loop-cap unit test.*
- **S/NFR-13 (per-period soft budget):** Workspace question volume crosses the rolling
  24h budget (default 500) → the bot **degrades gracefully** ("daily capacity reached, try
  later", invites re-ask after reset) — never a silent hard-stop. *Budget-cross test +
  atomic-increment concurrency test.*

### Security / Safety

- **S/NFR-4 + S/NFR-21 (secrets):** Input contains a secret pattern (e.g. an `AKIA…` key) →
  CMP-005 runs **before any external send** (CS-4) and returns `refuse` → the bot
  **hard-refuses and re-asks**, naming the matched *class* (not the value), with **no
  override** → **zero** forwarding to inference/MCP (NFR-4 invariant). *Known-secret corpus
  asserts no external send + named-class message.*
- **S/NFR-3 (policy):** Operators publish the data-sensitivity policy (ENT-013) consumed by
  the safety gate (BR-025). *Config review.*
- **S/NFR-6 (log hygiene):** Any input (incl. flagged) flows through processing → logs
  contain only the correlation-id + redacted descriptors, **no secrets/PII**. *Log-scrub
  test against the secret corpus.*

### Reliability / Input bounds

- **S/NFR-14 (oversize, Q5=c hybrid):** Question + thread context exceeds the input budget →
  **trim-with-notice** (drop oldest context, keep recent + current question, post a notice —
  never silent, FR-21) for normal overflow; **reject-and-ask** only when the current
  question *alone* still overflows. *Two-path test.*

### Operability

- **S/NFR-20 (observability):** Every job emits structured JSON keyed by correlation-id plus
  the metric set (latency histograms, failure-by-cause, usage/degrade counters, breaker
  gauge, concurrency/recovery counters). These are the **verification instruments** for all
  other NFRs. *End-to-end signal-presence check.*

---

## 2. Tech Stack & Rationale (R-1)

| Concern | Decision | Rationale | Trade-off acknowledged |
|---|---|---|---|
| Language | **Python 3.12+** | Matches the repo (`devops-agent-python`) and the AWS/MCP ecosystem; strong async + typing. | Per-request latency is dominated by inference/MCP I/O, not CPU, so Python's GIL is not the bottleneck here. |
| Slack ingress | **Slack Bolt for Python** (Events API) | Handles signature verification and the 3s ack (NFR-1/C-1) out of the box; well-maintained first-party SDK. | Bolt's built-in concurrency is for intake only — the heavy work is deliberately pushed across the C-1 queue to the worker role. |
| Inbound validation | **pydantic** | Schema-first validation of Slack payloads + config; fail-fast at the boundary (design-principles). | — |
| Inference seam | **CMP-003 backend-agnostic library module** (API-INT-001) | A-1 is the highest-risk assumption; the stable interface lets Kiro↔Bedrock swap without touching agent-core. | Backend confirmation (headless Kiro vs Bedrock) is an infrastructure-design decision; module is built/tested in isolation behind the seam. |
| HTTP/MCP client | explicit-timeout client + bounded retry (NFR-15) | Every external call must be time-bounded to honour NFR-17. | — |
| Async worker runtime | **pattern fixed here** (queue-draining, horizontally scalable); **mechanism deferred** | This stage fixes the *pattern* (NFR-10), not Lambda-vs-container. | Concrete runtime → infrastructure-design. |

> The worker runtime choice (Lambda concurrency vs container autoscaling vs process pool),
> the concrete queue, the datastore, and the inference backend are **infrastructure-design**
> decisions. This stage fixes the *patterns and targets* they must satisfy.

---

## 3. Cross-Cutting Patterns

### 3.1 Async / idempotency (R-2)
Accept-and-enqueue across the **mandatory C-1 durable queue** (API-INT-009): intake (NFR-1)
acks fast and enqueues; the worker role drains concurrently (NFR-10, no head-of-line
blocking). **De-dup identity = `channel-id + message-ts`** (functional-design Q3=a) enforced
at CMP-006 for **at-most-once-*completed*** (CS-3). A **single-winner `in-progress` lease +
idempotent answer post** (BR-027) guarantees a recovery-spawned worker never double-posts.

### 3.2 Resilience (R-3) — three nested guards
1. **Bounded retry with exponential backoff + full jitter** (NFR-15: base 500ms, ×2, max 3
   retries, cap 8s) on every Slack/MCP/inference call; honours Slack `Retry-After`/429.
2. **Circuit breaker per external dependency** (NFR-16): opens on sustained failure and
   fails fast to the FR-17 message instead of burning the latency budget.
3. **Per-request total time budget** (NFR-17: 30s, aligned to NFR-2): the outer wall clock;
   on exhaustion the job resolves `failed`. All retries live *inside* this budget.

Recovery (NFR-19): `max_attempt=3`, `staleness_bound=90s` — chosen so the staleness bound
(90s) safely exceeds the per-request budget (30s) and never reclaims a live job.

### 3.3 Secret detection (R-bound to Q4=b) — NFR-4 / NFR-21
Pre-send gate (CMP-005, CS-4) runs **before any external send**. Posture: **best-effort
heuristic** (A-6), **hard-refuse-and-re-ask**, naming the matched **class** (never the value,
NFR-6), **no override** → NFR-4 invariant intact. The detector is **refuse-or-allow only**
under Q4=b — a positive detection always returns `refuse` and never `warn`, so the BR
`warn ⇒ post-and-proceed` path is never exercised by secret detection. Starting rule set (curated regex for AWS
access keys, secret keys, PEM private keys, bearer/OAuth tokens, Slack tokens, credential
connection strings, high-entropy assignments) is documented in `nfr.yaml` with its known
best-effort precision/recall limits — it will miss novel/obfuscated secrets and may flag
benign high-entropy strings. Rules evolve on their own cadence inside CMP-005.

### 3.4 Cost guardrail (Q2=b) — NFR-8 / NFR-12 / NFR-13
Two levers, both owned by CMP-007 (the CS-1 budget owner): a **per-request cap** (≤ 2
inference / ≤ 5 MCP — also the CS-5 tool-call cap) that stops per-question fan-out, and a
**per-period rolling soft budget** (default 500/24h) that **degrades gracefully** on volume
runaway. Thresholds are operator-set (ENT-014); the usage counter (ENT-011) uses atomic
increments (BR-019).

### 3.5 Observability as NFR verification (R-4) — NFR-20
Structured JSON logs (no secrets/PII, BR-026) with a **correlation-id per job** (DA-1 ==
ProcessingJob.job-id), plus latency histograms, failure-by-cause counters, usage/degrade
counters, breaker-state gauge, and concurrency/recovery counters. **These signals are the
instruments by which every other NFR is verified** — they are not optional telemetry.

### 3.6 Rate-limit handling (R-6) — NFR-7
Respect Slack `Retry-After`/429 and MCP backpressure via the §3.2 backoff; **never drop a
question silently** — an un-serviceable question resolves `failed` with an FR-17 message.

---

## 4. Traceability Matrix

| NFR | Resolves / Source | Owning CMP | Verification method |
|---|---|---|---|
| NFR-1 | FR-3, C-1 | CMP-001 | intake latency histogram; load test p95<3s |
| NFR-2 | FR-14, **A-3** (Q1=a) | CMP-002 | full-answer histogram; FR-9 path scenario |
| NFR-11 | FR-3/FR-14, Q1=a | CMP-002 | worker-timer test; manual heartbeat check |
| NFR-17 | FR-17, NFR-2, BR-013/14 | CMP-002 | stalled-call fault injection |
| NFR-3 | FR-15, BR-025 | CMP-008 | config review |
| NFR-4 | FR-15, CS-4, Q4=b | CMP-005 | known-secret corpus: zero external send |
| NFR-21 | FR-15, **A-6** (Q4=b) | CMP-005 | precision/recall vs labelled corpus |
| NFR-5 | security baseline | CMP-008 | config review + CI secret scan *(value→infra)* |
| NFR-6 | BR-026 | CMP-001/002/005/007 | log-scrub test |
| NFR-7 | FR-17, BR-023 | CMP-001/004/002 | simulated 429/backpressure |
| NFR-15 | FR-17, NFR-7 | CMP-002/004/001 | backoff unit + injected-failure integration |
| NFR-16 | FR-17, C-3, NFR-9/17 | CMP-002 | sustained-outage injection; breaker gauge |
| NFR-8 | **A-7** (Q2=b), CS-1/CS-5 | CMP-007 | via NFR-12 + NFR-13 |
| NFR-12 | CS-5, A-7, BR-014 | CMP-002 | loop-cap unit test |
| NFR-13 | A-7, CS-1, BR-008/19 (Q2=b) | CMP-007 | budget-cross + atomic-increment test |
| NFR-9 | **A-7** (Q3=a), C-3 | CMP-002 | error-budget report split by cause |
| NFR-10 | C-1, S-24 (R-5 authority) | CMP-002 | HOL-blocking isolation test *(count→infra)* |
| NFR-14 | FR-21, **A-9** (Q5=c), C-2, BR-007 | CMP-002 | trim/reject two-path test *(token#→infra)* |
| NFR-19 | FR-19, CS-2/CS-3, BR-021/22/27 | CMP-006/002 | kill-worker recovery test |
| NFR-20 | FR-18, BR-026 | all (CMP-007 counters) | end-to-end signal-presence *(sink→infra)* |

Bold A-* = a requirements-stage "set in nfr-design" placeholder now **resolved here**.

---

## 5. Infrastructure-Design Hand-off

Each item below has its **policy/target fixed here**; only the concrete value/mechanism is
left to infrastructure-design (see `nfr.yaml: infrastructure_design_handoff`).

1. **Exact input-token budget** (NFR-14) — hybrid trim/reject behaviour + conservative 12k
   default fixed; exact number finalised against the chosen model.
2. **Worker concurrency/instance count + scaling mechanism** (NFR-10) — queue-draining,
   horizontally-scalable pattern + ≥10 starting target fixed; count/mechanism (Lambda
   concurrency / container autoscaling / process pool) chosen there.
3. **Metrics/log sink + dashboards** (NFR-20) — required signal set + correlation-id keying
   fixed; the concrete observability backend chosen there.
4. **Secret-manager + per-integration IAM scopes** (NFR-5) — secret-manager-stored,
   least-privilege requirement fixed; concrete manager + scopes chosen there.
5. **Concrete queue, datastore, and inference backend** (Kiro/Bedrock — A-1) — the
   dependency-bounded SLO (NFR-9) and per-dependency breaker policy (NFR-16) fixed; the
   concrete services chosen there.

---

## 6. Self-Check (Phase 4)

- ✅ Every requirements-stage "set in nfr-design" placeholder resolved: **A-3**→NFR-2/11,
  **A-6**→NFR-21/4, **A-7**→NFR-8/12/13 + NFR-9, **A-9**→NFR-14; **NFR-8/9/10** targets
  set. No silent gaps (see `nfr.yaml: placeholder_resolution`).
- ✅ No stable ID renamed — NFR-1..10 expanded in place; NFR-11..21 are new sequence rows.
  **NFR-18 is intentionally unused** (adoption-metric concern folded into NFR-20), so the
  new block is NFR-11..17, 19, 20, 21 — a deliberate gap, not a dropped NFR (see
  `nfr.yaml: id_sequence_note`).
- ✅ Every NFR has a concrete target + measure + verification method + source trace + owning
  CMP. Items genuinely model/runtime-bound are `policy-fixed-value-handed-off` with the
  policy fixed here (NFR-5, NFR-10, NFR-14 token#, NFR-20 sink).
- ✅ NFR-4 invariant preserved (no override path under Q4=b).
- ✅ Patterns (async/idempotency, resilience, secret-detection, cost guardrail,
  observability, rate-limit) all specified with concrete starting values.
