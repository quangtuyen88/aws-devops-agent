# Functional Design — Clarification Questions

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `functional-design` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-systems-architect-agent · Status: `plan-and-clarify`.
>
> These resolve genuine design forks that materially change the functional artifacts
> (`entities.yaml`, `rules.yaml`, state machines, `api-specification.md`). Architectural
> items I have authority over are recorded as recommendations in `plan.md`; only the
> forks that need a human/product decision are below. Concrete numeric thresholds
> (timeouts, retry counts, budget limits) are deferred to `nfr-design` (A-7) by design —
> here we only fix the *shape*.

---

### Q1 of 4: What should `api-specification.md` cover, given UNIT-001 is the only unit and `contract-design` was skipped (no cross-unit contracts)?

The bot exposes no public/consumer API — it is event-driven from Slack. So "provider-side
interface" has to be reinterpreted for this unit.

a) **External integration surfaces only** — the inbound Slack event subscription, the
   outbound Slack Web API usage, the inference endpoint interface, and the MCP tool
   interface (the boundaries the unit consumes/exposes to the outside world).
b) **Internal module interfaces only** — the stable seams inside the unit: the CMP-003
   Inference Provider interface (the Q4 swap seam), the C-1 intake→worker enqueue
   contract, and the CMP-004/005/006/007 service operations.
c) **Both** — external integration surfaces *and* the internal module interfaces, in
   clearly separated sections.
d) Other.

**Trade Offs:** (a) documents the real outer boundary but omits the seams that matter
most for testing/extraction (inference swap, queue). (b) captures the future extraction
seams and the Q4 stable interface but leaves the external contract (Slack event shape,
MCP tool shape) undocumented for code-generation. (c) is the most complete and directly
feeds code-generation, at the cost of a longer artifact.

**Recommendation:** **c**. The CMP-003 stable inference interface (Q4) and the C-1
enqueue are the seams the whole design hinges on, and the Slack/MCP/inference external
shapes are what code-generation needs to stub and test against. Separating "consumed
external" from "internal module" keeps it honest about what is and isn't a true API.

[Answer]:

---

### Q2 of 4: How should the `ProcessingJob` lifecycle model terminal states and retry/abandonment?

The blueprint (ENT-008) lists `status: seen | in-progress | resolved` (CS-3), but the unit
also has explicit **failure resolution** (FR-17, S-19), **in-flight recovery** with
`attempt-count` (CS-2), and a **budget-deny** failure path (NFR-8/S-18). The 3-state enum
alone cannot express "answered" vs "failed" vs "gave up after N attempts".

a) **Single `resolved` terminal + outcome attribute** — keep `seen/in-progress/resolved`,
   add an `outcome` field (`answered | failed`); retries loop back to `in-progress` until a
   max-attempt rule fires, then `resolved(failed)`.
b) **Distinct terminal states** — expand the `status` enum to
   `seen → in-progress → (resolved | failed)`, with `failed` reached on unrecoverable
   error, budget-deny, oversize, or exhausted retries; a re-enqueued in-flight job
   re-enters `in-progress` (attempt-count++).
c) **Keep exactly 3 states** — express success/failure and the attempt limit purely as
   business rules, not as states.

**Trade Offs:** (a) preserves the enum verbatim and keeps the metric (answered/failed) as
data, but hides the failure outcome inside an attribute, weakening at-a-glance auditability.
(b) makes the CS-3 at-most-once-*completed* guarantee and CS-2 recovery directly visible
and gives operators clean `answered` vs `failed` counts, but expands the blueprint enum
(a refinement I will flag). (c) is minimal but pushes too much lifecycle meaning into
prose rules, hurting traceability.

**Recommendation:** **b**. Distinct terminals make CS-2/CS-3 verifiable and operational
metrics clean. This expands ENT-008.status **in place** (no rename, no new entity), which I
will record as a refinement against the copied-forward blueprint.

[Answer]:

---

### Q3 of 4: What composes the de-duplication identity (`ProcessingJob.slack-event-identity`, CS-3)?

The de-dup key must be stable across Slack's at-least-once event delivery (ENT-001 carries
`slack-retry-num`) **and** across our own intake→worker re-enqueue, so one mention yields
at most one completed answer.

a) **Originating message coordinates** — `channel-id` + `message-ts` of the triggering
   @mention (one job per mention; coordinates are already in hand for posting back).
b) **Slack `event_id`** — the per-event id Slack keeps stable across its own retries.
c) **Composite** — `channel-id` + `thread-ts` + `message-ts`.

**Trade Offs:** (a) is naturally idempotent across both Slack retries and our re-enqueue,
uses data we already need, and matches "one job per mention". (b) is also retry-stable but
couples our identity to a Slack-internal id we don't otherwise use. (c) adds `thread-ts`,
which is redundant for identity (a `message-ts` is already unique within a channel) and
risks treating the same mention differently if thread context shifts.

**Recommendation:** **a**. `channel-id + message-ts` is the minimal stable key, idempotent
by construction, and reuses coordinates the adapter already holds.

[Answer]:

---

### Q4 of 4: How is helpfulness feedback (`FeedbackSignal`, ENT-010) recorded when a developer changes or removes a reaction?

A developer may react 👍 then switch to 👎, add both, or remove a reaction (FR-16, S-25, S-26).
ENT-010 is described as "append-mostly".

a) **Latest-wins state** — one `FeedbackSignal` per (answer, reactor); a changed reaction
   updates it; removing the reaction marks it withdrawn.
b) **Append-only event log** — every reaction add/remove is an immutable signal row; the
   success metric reads "latest per (answer, reactor)" at aggregation time.
c) **First-wins** — record only the first reaction; ignore later changes.

**Trade Offs:** (a) is simplest to query but is destructive and loses the changed-mind
signal. (b) matches "append-mostly", is non-destructive and auditable, and keeps a clean
event history, at the cost of a read-time aggregation rule. (c) is the simplest but
silently drops real signal and would misreport a 👍→👎 reversal.

**Recommendation:** **b**. Append-only fits the entity's stated nature, avoids destructive
updates on the hot path, and a single "latest per (answer, reactor)" aggregation rule keeps
the success metric correct and auditable.

[Answer]:

---

## Human Answer (recorded 2026-06-17T12:49:23+08:00)

**"go with recommendations"** — accept all four:
- **Q1: c** — `api-specification.md` covers BOTH external integration surfaces (Slack event
  subscription, Slack Web API, inference endpoint interface, MCP tool interface) AND internal
  module interfaces (CMP-003 Inference Provider swap seam, C-1 intake→worker enqueue contract,
  CMP-004/005/006/007 service operations), in clearly separated sections.
- **Q2: b** — `ProcessingJob` uses distinct terminal states: `seen → in-progress → (resolved | failed)`;
  `failed` on unrecoverable error / budget-deny / oversize / exhausted retries; re-enqueued
  in-flight job re-enters `in-progress` (attempt-count++). Expand ENT-008.status enum in place
  (flagged refinement vs blueprint, no rename/new entity).
- **Q3: a** — De-dup identity = `channel-id` + `message-ts` of the triggering @mention.
- **Q4: b** — `FeedbackSignal` is an append-only event log; success metric reads
  "latest per (answer, reactor)" at aggregation time.
