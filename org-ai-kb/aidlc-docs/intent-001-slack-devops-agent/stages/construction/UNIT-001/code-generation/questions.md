# Code-Generation Clarifications — UNIT-001 (Slack DevOps Agent)

> Stage: `code-generation` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-sw-dev-engineer-agent · Status: plan-and-clarify.
>
> Inputs read: `functional-design/{entities.yaml, rules.yaml, functional-spec.md,
> api-specification.md, unit.md}`, `nfr-design/nfr-spec.md`,
> `infrastructure-design/{infrastructure-specification.md, unit.md,
> aidlc-architecture-reviewer-agent-review.md}`. Two carry-forward items from the infra
> review gate (AGPL `kiro-gateway`, **F8** answer-ts→correlation-id mapping) are surfaced
> below as required by that review.
>
> Tech stack is fixed by the orchestrator brief: **Python 3.12 + Slack Bolt + pydantic,
> `uv` for packaging**; inference = **Kiro-gateway primary** (OpenAI-compatible
> `POST /v1/chat/completions`, bearer `PROXY_API_KEY`) **+ Bedrock alternate**, both behind
> CMP-003. Those are not re-asked.

---

### Q1 of 4: What is the scope of this code-generation pass — application code only, or application code **plus** the Terraform IaC?

a) **Application code + tests only.** Implement the 8 components (CMP-001..008) as a
   modular-monolith Python package at the workspace root, with the 3 Lambda entrypoints
   (intake, worker, reaper), all external dependencies behind ports/adapters, and full
   unit + bounded-context tests. Terraform IaC (the 9 modules in infra-spec §6) is deferred
   to a later code-generation slice/PR.
b) **Application code + tests + Terraform IaC**, all in this pass — author the 9 Terraform
   modules (`networking`, `messaging`, `data`, `compute-intake`, `compute-worker`,
   `recovery`, `gateway`, `security`, `observability`) alongside the application, validated
   with `terraform fmt`/`validate` (manual `apply`, per OOS-3).
c) Other.

**Trade Offs:** UNIT-001 is large (8 components, 3 runtime roles, 5 cross-cutting NFR
patterns). Option (a) gets verified, testable business logic landing fastest and keeps the
first review reviewable; IaC then layers on with the app contract already stable. Option (b)
delivers a deployable slice in one pass but is a very large artifact set to review at once,
and the IaC cannot be executed here anyway (OOS-3 — manual apply).

**Recommendation:** **(a)** — implement and verify the application + tests first
(write-test-verify per the full-stack skill), then produce Terraform IaC as a clearly
separated follow-on slice. This keeps each verifiable increment small and reviewable and
front-loads the highest-value, highest-risk logic (the agent loop, safety gate, job
dedup/recovery).

[Answer]:

---

### Q2 of 4: How should the durable **`answer-message-ts → correlation-id`** mapping (infra-review **F8**) be persisted so the intake Lambda can key feedback reactions (W4/BR-018)?

a) **GSI on the `ProcessingJob` (CMP-006) table** keyed by `answer-message-ts`. The worker,
   when it posts the answer (W2 step 10), stamps `answer-message-ts` onto the existing
   ProcessingJob item (it already updates that item on resolve); intake resolves the
   reaction via `Query` on the GSI → `job-id` (== `correlation-id`, DA-1).
b) **A dedicated mapping record** written to the `OperationalData` (CMP-007) table
   (e.g. PK `answer-ts#<ts>` → `correlation-id`) at answer-post time; intake `GetItem`s it.
   Models the mapping as a new durable entity (≈ ENT-015).
c) Other.

**Trade Offs:** (a) reuses an item the worker already writes and an ID the dedup record
already owns — no new entity, no extra write, mapping lives with the job it belongs to; the
cost is one GSI and a stamped attribute on ENT-008. (b) keeps CMP-006 untouched and puts the
feedback-support data in CMP-007 (which already owns `FeedbackSignal`), at the cost of a new
entity and an extra durable write on the answer path. The infra IAM surface already granted
covers **both** (worker `PutItem`/`UpdateItem`, intake `Query/GetItem`).

**Recommendation:** **(a)** — stamp `answer-message-ts` on `ProcessingJob` and add a GSI.
It adds no new entity, reuses the existing resolve-time write, and the GSI→`job-id` lookup
is exactly the `correlation-id` the `FeedbackSignal.answer-ref` needs (DA-1). I will record
this as an in-place expansion of ENT-008 in `implementation-map.md`, preserving the stable
ID, and flag it for the systems-architect contributor to confirm against functional-design.

[Answer]:

---

### Q3 of 4: Confirm the AGPL-3.0 `kiro-gateway` boundary for the CMP-003 primary backend.

a) **Confirm Kiro-gateway primary, integrate by HTTP client only.** This repo implements
   only an OpenAI-compatible HTTP **client** to the gateway's `POST /v1/chat/completions`
   (bearer `PROXY_API_KEY`) behind the CMP-003 interface. The gateway itself is **not**
   vendored, forked, or imported into this codebase (it is operated as a separate, unmodified
   third-party container per infra-spec §0/§2.3), so no AGPL source-disclosure obligation
   attaches to UNIT-001's code. Bedrock remains the config-switchable alternate behind the
   same interface (no AGPL).
b) **Make Bedrock the primary** backend instead and treat Kiro-gateway as the alternate, to
   avoid the AGPL service-operation question entirely.
c) Other / route to legal review first.

**Trade Offs:** (a) matches the orchestrator brief and the infra design and carries no
copyleft risk **to our code** as long as we never fork the gateway — but it does mean
*operating* an AGPL service (an ops/legal consideration outside this repo). (b) sidesteps
AGPL fully but diverges from the stated "Kiro primary" decision and loses the Kiro
subscription cost profile.

**Recommendation:** **(a)** — proceed Kiro-primary via an HTTP-client-only integration; the
CMP-003 seam keeps Bedrock one config flip away if legal later rejects operating the gateway.
I will add an explicit note in code/docs that the gateway must stay unmodified and external.

[Answer]:

---

### Q4 of 4: What test strategy for the unit's own AWS-backed bounded-context dependencies (DynamoDB tables, SQS queue)?

a) **`moto` (in-process AWS mocks) for bounded-context integration tests + port fakes for
   unit tests.** Domain/rule logic is unit-tested against in-memory port fakes; the
   DynamoDB dedup/lease/atomic-counter and SQS enqueue/redelivery paths are integration-tested
   against `moto`. Live Slack / Kiro-gateway / Bedrock / MCP calls are exercised only through
   typed fakes; real cross-dependency integration is deferred to post-deployment (per the
   full-stack skill — cross-unit/live deps are out of scope here).
b) **LocalStack** (containerised AWS) for the integration tests instead of `moto`.
c) Other.

**Trade Offs:** `moto` runs in-process with no Docker dependency — fast, CI-friendly, and
sufficient to verify conditional writes, atomic `ADD`, and SQS semantics for this unit.
LocalStack is higher-fidelity (closer to real service behaviour, esp. for edge SQS/DynamoDB
semantics) but needs Docker and is slower. Neither reaches the genuinely external deps
(Slack/Kiro/Bedrock/MCP), which stay behind fakes regardless.

**Recommendation:** **(a)** — `moto` + port fakes. It keeps the write-test-verify loop fast
and dependency-light while still testing the unit's own stores realistically; the timing-race
behaviours that need exact wall-clock semantics (NFR-19 inclusive `>=` reclaim, F5) are tested
with injected clocks rather than relying on a queue emulator.

[Answer]:

---

## Human Answer (recorded 2026-06-17T15:03:36+08:00)

**"go with recommendations"** — accept all four:
- **Q1: a** — Application code + tests only this pass (8 components as a modular-monolith
  Python package at workspace root + 3 Lambda entrypoints, deps behind ports/adapters, full
  unit + bounded-context tests). Terraform IaC (9 modules) deferred to a separate follow-on slice.
- **Q2: a** — Persist the F8 mapping as a GSI on the ProcessingJob (CMP-006) table keyed by
  `answer-message-ts`; worker stamps it at answer-post (W2 step 10); intake Querys the GSI →
  job-id (== correlation-id) for feedback. In-place expansion of ENT-008, stable ID preserved.
- **Q3: a** — Kiro-gateway primary via HTTP-client-only integration (OpenAI-compatible
  `/v1/chat/completions`, bearer PROXY_API_KEY) behind CMP-003; gateway NOT vendored/forked/
  imported — operated as a separate unmodified external container (bounds AGPL). Bedrock alternate
  one config flip away. Add explicit code/docs note that the gateway must stay unmodified & external.
- **Q4: a** — `moto` (in-process AWS mocks) for bounded-context integration tests + port fakes
  for unit tests + injected clocks for NFR-19/F5 timing races. Live Slack/Kiro/Bedrock/MCP stay
  behind typed fakes; real cross-dependency integration deferred to post-deployment.
