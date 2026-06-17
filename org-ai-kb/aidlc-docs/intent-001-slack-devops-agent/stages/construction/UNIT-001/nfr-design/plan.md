# NFR Design — Plan

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `nfr-design` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-systems-architect-agent · Reviewer: aidlc-architecture-reviewer-agent ·
> No contributors assigned (per workflow.json).

## Goal

Turn the deferred quality concerns into **measurable, verifiable NFR targets** and fix the
**tech stack and cross-cutting patterns** for UNIT-001. Convert every "set in nfr-design"
placeholder (A-3, A-6, A-7, A-9; NFR-8/9/10) into concrete numbers + verification methods,
and specify the patterns (async worker, idempotency, retry/backoff, circuit-breaker,
secret-detection, observability) the agent service is built on. Preserve every stable ID
from upstream artifacts (NFR-1..10, FR-1..21, CS-1..6, CMP-001..008, A-1..9) — expand in
place, never rename.

## Inputs Used & Artifact Resolution (fallbacks documented)

| Concern | Artifact used | Notes |
|---|---|---|
| NFRs + deferred placeholders (source of truth) | `requirements-analysis/requirements.md` | NFR-1..10, A-3/A-6/A-7/A-9, CS-1..6, NFR-3..6 security baseline |
| Unit definition + 2-role runtime + C-1 seam | `functional-design/unit.md`, `units-generation/units.md` | Intake (NFR-1) vs worker (NFR-2/NFR-10) split; internal durable queue |
| Component blueprint + budget/job ownership | `functional-design/components.yaml` | CMP-007 owns within-budget decision (CS-1/NFR-8); CMP-006 owns job lifecycle/de-dup |
| Job lifecycle + terminals (failed path) | `functional-design/functional-spec.md`, `entities.yaml` | ProcessingJob `seen→in-progress→(resolved\|failed)`; timeout/budget/oversize → `failed` |
| External + internal interfaces | `functional-design/api-specification.md` | Slack/inference/MCP surfaces (rate limits, retries land here); CMP-003 swap seam |
| Grounding + citation behaviour | `functional-design/rules.yaml` (BR-*) | CS-5 grounding cap feeds the per-request cost cap |
| **reverse-engineering** | **skipped** (greenfield) | No existing code; targets derived from requirements + Slack/AWS platform constraints |
| **contract-design** | **skipped** (single unit) | No cross-unit NFRs; rate-limit/retry NFRs attach to external surfaces only |
| Tech stack baseline | repo context (`devops-agent-python`) + functional artifacts | Strongly signals Python; confirmed as a recommendation below, not a blocking question |

## Open Decisions (block full artifact production until answered)

Five product/business forks in `questions.md` (numeric targets + postures):

- **Q1** — Full-answer latency target (NFR-2/A-3). *Recommend: keep p95 ≤ 30s + 15s heartbeat.*
- **Q2** — Cost guardrail thresholds + exceed behaviour (NFR-8/A-7). *Recommend: per-request cap + per-period soft budget.*
- **Q3** — Availability target (NFR-9). *Recommend: business-hours best-effort ~99%, dependency-bounded.*
- **Q4** — Secret-detection posture (FR-15/NFR-4/A-6). *Recommend: hard-refuse-and-re-ask, named pattern class.*
- **Q5** — Max input size + oversize behaviour (FR-21/A-9/C-2). *Recommend: hybrid trim-with-notice / reject-when-question-alone-overflows.*

The five change specific numbers and three behaviours; the step structure below is stable
regardless of the answers.

## Recommendations Under My Architectural Authority (not human questions)

Recorded here for transparency; will be specified in the artifacts unless the human overrides.

- **R-1 Tech stack — Python 3.12+.** Matches the repo (`devops-agent-python`) and the AWS/MCP
  ecosystem. Slack ingress via **Slack Bolt for Python** (Events API; handles signature
  verification + the 3s ack). Async worker via the runtime chosen in infrastructure-design
  (this stage fixes the *pattern*, not Lambda-vs-container). HTTP/MCP client with explicit
  timeouts. Validation with **pydantic** for inbound Slack payloads and config.
- **R-2 Async / idempotency pattern.** Accept-and-enqueue across the C-1 durable queue
  (mandatory per C-1); worker drains concurrently (NFR-10, no head-of-line blocking).
  De-dup key = `channel-id + message-ts` (functional-design Q3) enforced at the job store
  (CMP-006) for at-most-once-*completed* (CS-3).
- **R-3 Resilience pattern.** Bounded retry with exponential backoff + jitter on Slack/MCP/
  inference calls (NFR-7); a **circuit breaker** per external dependency so a sustained
  outage fails fast to the FR-17 message instead of burning the latency budget; a per-job
  **total time budget** that, when exhausted, resolves `failed` (ties to NFR-2 / Q1). Retry
  counts/backoff curve are my call; I will state concrete starting values.
- **R-4 Observability.** Structured JSON logs (no secrets/PII — NFR-6) with a correlation-id
  per job (DA-1 from components.yaml); metrics for the FR-18 adoption counters, latency
  histograms (NFR-1/NFR-2 percentiles), failure-by-cause counts (timeout/budget/oversize/
  dependency), and cost-counter (NFR-8). These are the verification instruments for the NFRs.
- **R-5 Concurrency mechanism (shared with infrastructure-design).** This stage fixes the
  *target* (≥ N concurrent in-flight questions, no head-of-line blocking — NFR-10) and the
  *pattern* (horizontally-scalable worker draining the queue). The concrete instance/conc-
  urrency count is an infrastructure-design decision; documented as a hand-off.
- **R-6 Rate-limit handling.** Respect Slack `Retry-After` / 429 and MCP backpressure with
  the R-3 backoff; never drop a question silently (NFR-7) — a question that cannot be
  serviced within budget resolves `failed` with an FR-17 message.

## Steps

### Phase 0 — Clarify (this step)
- [x] Read upstream artifacts (requirements NFRs/constraints, functional-design unit/spec/
      api-spec/components, units packaging).
- [x] Write `questions.md` — 5 product/business forks (latency, cost, availability, secret
      posture, input-size), each with options + trade-offs + recommendation.
- [x] Write `plan.md` (this file) with artifact-resolution fallbacks and authority-level
      recommendations (R-1..R-6).
- [ ] Set stage status to `clarification-asked` in `state/state.json`; register `questions.md`
      and `plan.md` in the stage `outputs` array.
- [ ] **Yield for human answers** (supervised stage — Row 3 hard stop).

### Phase 1 — Incorporate answers
- [ ] Read answered `questions.md`. If any answer is ambiguous, append follow-ups and set
      `further-clarification`; else proceed.
- [ ] Lock the five numeric/posture decisions into the artifact inputs.

### Phase 2 — Produce `nfr.yaml` (machine-readable, source of truth for targets)
- [ ] Expand NFR-1..10 in place with **concrete numbers + measure + verification method +
      source trace**, preserving IDs.
- [ ] Add new NFR rows for the gaps surfaced here, e.g. input-size budget (from FR-21/A-9),
      per-request + per-period cost caps (NFR-8/A-7), retry/backoff + circuit-breaker budget
      (NFR-7), latency heartbeat (NFR-2/Q1) — each with a stable new ID continuing the NFR-*
      sequence and an explicit source.
- [ ] Mark anything finalised downstream (exact token budget, concurrency count) as
      `deferred-to: infrastructure-design` with the *policy* fixed here.

### Phase 3 — Produce `nfr-spec.md` (narrative + patterns + tech stack)
- [ ] Quality-attribute scenarios for each NFR (stimulus → response → measure).
- [ ] **Tech stack & rationale** (R-1) with trade-offs.
- [ ] **Cross-cutting patterns** (R-2..R-6): async/idempotency, resilience (retry/backoff/
      circuit-breaker/time-budget), secret-detection approach + starting rule set + known
      best-effort limits (A-6), observability signals as NFR verification instruments,
      rate-limit handling.
- [ ] **Traceability matrix** NFR-id ↔ FR/CS/A-source ↔ owning component (CMP-*) ↔
      verification method.
- [ ] **Infrastructure-design hand-off list** — every decision intentionally left to the
      runtime choice, with the policy/target already fixed here.

### Phase 4 — Self-check & register
- [ ] Verify every requirements-stage "set in nfr-design" placeholder (A-3, A-6, A-7, A-9,
      NFR-8/9/10) is now resolved or explicitly handed off — no silent gaps.
- [ ] Verify no stable ID was renamed; all expansions are in place and traceable.
- [ ] Register all outputs in `state/state.json`; set status `artifact-generated`.

## Artifacts To Be Produced

| Artifact | Role |
|---|---|
| `questions.md` | The 5 clarification forks (this phase) |
| `plan.md` | This plan |
| `nfr.yaml` | Machine-readable, measurable NFR targets (IDs, numbers, measure, verification, source) — source of truth |
| `nfr-spec.md` | Narrative: quality scenarios, tech stack, cross-cutting patterns, traceability matrix, infra hand-off |

## Definition of Done

- All five forks answered (or recommendations accepted).
- Every deferred placeholder resolved with a concrete, **verifiable** target or an explicit
  infrastructure-design hand-off that fixes the policy.
- `nfr.yaml` + `nfr-spec.md` written; IDs preserved; full traceability to NFR/FR/CS/A sources.
- Reviewer (aidlc-architecture-reviewer-agent) verdict "ready".
