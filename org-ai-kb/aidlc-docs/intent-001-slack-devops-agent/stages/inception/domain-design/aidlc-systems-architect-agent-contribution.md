# Systems Architect Contribution — Domain Design

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Contributor: aidlc-systems-architect-agent
Role: systems thinking, architectural soundness of the decomposition, entity/data
ownership, reliability/operational/performance/scalability/observability consequences,
and clean hand-off into the design stages I own downstream (functional-design,
nfr-design, infrastructure-design).
Reviewed artifacts: `components.yaml` (CMP-001..CMP-008, ENT-001..ENT-014),
`components.md`, `plan.md`, `questions.md`; cross-checked against `requirements.md`
(FR-1..FR-21, NFR-1..NFR-10, A-1..A-9, C-1..C-4), `stories.md` (S-1..S-27), and my
story-generation contribution (CS-1..CS-6).

## Verdict

**Architecturally sound, complete, traceable — ready to advance.** The 8-component
decomposition maps one component to each distinct reason-to-change the requirements
identified, the CS-1..CS-6 constraints I raised at story stage are faithfully encoded
(single-owner entities, acyclic DAG, CS-4 safety-gate ordering, at-most-once-*completed*
de-dup, fetch-not-store context), and no infrastructure is modelled as a component. The
FR→component coverage matrix is complete.

The findings below are **not blockers**. They are cross-component data-flow and
quality-attribute consequences that the *static* component view leaves implicit and that
I will need pinned down when I own functional-design / nfr-design / infrastructure-design.
One (DA-1, correlation identity) is worth a small in-place entity-model addition now;
the rest are downstream design notes to record so they are not discovered late.

---

## 1. What the decomposition gets right (validation)

- **CS-1 shared state is single-owned and split correctly.** De-dup identity lives in
  `ProcessingJob` (CMP-006); the append-mostly analytics + hot-path cost counter live in
  CMP-007. Separating hot per-request job-control state from append-mostly analytics is the
  right call even if they later share a physical store — different access patterns and
  consistency needs. Exactly the CS-1 boundary I flagged.
- **CS-4 ordering is expressible in the dependency graph.** CMP-002→CMP-005 (safety) precedes
  CMP-002→CMP-003 (inference) and CMP-002→CMP-004 (MCP); the numbered edges encode it. NFR-4
  non-propagation is structurally enforceable.
- **The C-1/C-4 async boundary is modelled honestly.** The queue is infrastructure, not a
  component, so there is no synchronous CMP-001→CMP-002 edge — this keeps the graph acyclic
  and makes the intake→worker split a real boundary rather than a hidden coupling. Good.
- **A-1 seam is isolated as its own component (CMP-003).** The highest-risk assumption is
  behind a backend-agnostic abstraction with no synchronous dependents other than CMP-002.
  This is the de-risking shape I asked for; keep CMP-003's surface free of Kiro-specifics.
- **CS-6 fetch-not-store is preserved.** `ConversationContext` is explicitly ephemeral and
  owned by CMP-002; no durable conversation store sneaks in. OOS-4/A-8 intact.

---

## 2. Cross-component findings (carry into design stages)

### DA-1 — No end-to-end correlation identity across the async boundary (recommend in-place fix)
The entity model links request artifacts only through Slack message timestamps:
`InboundMention` (channel/thread/message-ts) → `ProcessingJob` (job-id, slack-event-identity,
originating-message-ref) → `Answer` (no id) → `FeedbackSignal.answer-ref` /
`ReactionEvent.answer-message-ts`. There is **no single correlation id that threads a logical
request from intake (CMP-001) across the queue into the worker (CMP-002) and its leaf calls**
(CMP-003/004/005/007). Because C-1 splits the request across a process boundary, this is the
one identifier needed to (a) trace a request end-to-end for debugging and (b) satisfy NFR-6
log hygiene without leaking Slack/user identifiers as the join key.
- **Recommendation (small, domain-level):** add a `correlation-id` (or reuse `job-id` as the
  canonical request id) as an attribute on `InboundMention` and `Answer`, so every component
  on the path can stamp it. This is a data-modelling addition the owner can make now; it
  prevents observability being retrofitted in infrastructure-design. Cheap, high leverage.

### DA-2 — Cost-guardrail correctness under concurrency is a TOCTOU race (nfr/functional-design)
CMP-002's flow is "ask CMP-007 *is this within budget?*" **before** processing, and CMP-007's
responsibility records usage **after** processing (`UsageCounter` updated post-call;
CMP-002 "record … usage after processing"). Under NFR-10 concurrency / S-24 multiple workers,
N requests can all read under-budget before any of them records usage → the bound is breached.
The component boundaries are correct (CMP-007 owns the counter and the decision); the **data-flow
semantics are not**. The "within-budget" decision as a plain read-then-act cannot enforce a hard
cap.
- **Recommendation:** in nfr-design/functional-design, define the guardrail as a
  **reserve-then-settle** (atomic increment/conditional check on `UsageCounter` at admission,
  reconcile actual usage on completion), or accept it explicitly as a *soft/best-effort* bound
  per period. No component change; this pins the consistency model behind CMP-007's decision.
  Flag NFR-8 as "soft unless atomic" so it isn't assumed to be a hard cap.

### DA-3 — De-dup register vs ack vs enqueue ordering is unspecified (functional-design)
CMP-001 "register + de-dup (CMP-006)", "ack Slack", and "enqueue (queue)" are three steps whose
**ordering determines correctness** under crash:
- ack/enqueue before the `ProcessingJob` "seen" write → a Slack retry can start a second pass
  (CS-3 violated);
- "seen" write succeeds but enqueue fails → an orphan job that is registered but never processed
  (silent failure — the exact pain point the personas call out).
The at-most-once-*completed* semantics (CS-3) and in-flight recovery (CS-2) require this to be a
designed sequence, plus a **conditional/atomic write** on `ProcessingJob.status` (compare-and-set
on seen→in-progress) so two workers can't both claim the same job.
- **Recommendation:** functional-design must specify the intake write/ack/enqueue order and the
  conditional-write semantics on `ProcessingJob`. Domain model is fine; the ordering contract is
  the gap.

### DA-4 — Nothing *drives* in-flight recovery; CMP-006 needs a trigger (functional/infra-design)
CMP-006 lists "detect acked-but-incomplete jobs (worker loss/restart) for retry-or-resolve
(CS-2)" as a responsibility, but **no edge or mechanism triggers that detection** — recovery is a
behaviour with no actor. In practice this is either queue redelivery (visibility-timeout
re-drive) or a scheduled sweep over `ProcessingJob` for stale `in-progress` rows
(`last-transition-at` + `attempt-count` are already present — good, they support exactly this).
- **Recommendation:** record in notes-for-downstream that CS-2 recovery requires a concrete
  trigger (queue visibility timeout and/or a reaper) to be chosen in infrastructure-design. The
  entity already carries the fields; only the driver is undecided.

### DA-5 — Config reads sit on the NFR-1 (3s ack) hot path (performance — nfr/infra-design)
CMP-001 depends on CMP-008 to read the `ChannelAllowlist` **at intake, inside the NFR-1
synchronous-ack window**. Likewise CMP-002 reads CMP-008 usage-policy/limits and CMP-007 the
within-budget decision on the per-request path (NFR-2 budget, CS-5). These are read-mostly,
low-churn values (CMP-008 by design), but a synchronous datastore round-trip in the 3s ack path
is a latency risk.
- **Recommendation:** nfr/infrastructure-design should allow CMP-008 reads to be cached
  in-process with bounded staleness (config is read-mostly per the component's own rationale).
  No domain change — recording so the 3s ack budget (NFR-1) isn't quietly spent on a config read.

### DA-6 — Over-budget denial is folded into the FR-17 failure path; keep it operationally distinct (functional-design)
CMP-002 routes an over-budget denial to "the failure path (S-19)". FR-17 is specifically
inference/MCP *failure*; a guardrail denial is a *deliberate* outcome, not a fault. Conflating
them is fine for the user-facing "couldn't complete" message but harms operability — over-budget
events must be distinguishable in metrics/logs from genuine dependency failures (otherwise the
NFR-8 guardrail looks like an availability incident).
- **Recommendation:** functional-design should keep the *reason code* distinct
  (guardrail-denied vs dependency-failed vs oversized-input/FR-21) even if the user message is
  similar. Ties to DA-1 (correlation id) and NFR-9 monitoring.

### DA-7 — NFR-7 backoff/retry consumes the NFR-2 budget and isn't owned anywhere (nfr-design)
Rate-limit/backpressure handling (NFR-7) touches CMP-001 (Slack post + `conversations.replies`
fetch for context, CS-6) and CMP-004 (MCP). It's correctly a per-component implementation concern
rather than a component, but two interactions must be designed once: (a) retries with backoff are
spent *inside* the shared NFR-2 30s budget (CS-5) — unbounded retry can blow the per-request
timeout; (b) the CS-6 context re-fetch adds a Slack call to every threaded question, widening the
NFR-7 surface.
- **Recommendation:** nfr-design defines the agent-loop hard iteration cap + per-request timeout
  (CS-5) to *include* retry attempts, so backoff and the loop share one bounded budget.

---

## 3. Minor notes

- **`Answer` has no own identifier.** Feedback/reactions key off the Slack message ts, which works,
  but giving `Answer` an explicit id (or adopting DA-1's correlation id) makes `FeedbackSignal.answer-ref`
  unambiguous and decouples analytics from Slack ts formatting. Optional, low cost.
- **CMP-007 mixes two access profiles under one owner.** `AdoptionMetric`/`FeedbackSignal`
  (append-mostly, read-rarely) vs `UsageCounter` (hot-path read+write, correctness-critical).
  Single ownership is right (CS-1), but flag for infrastructure-design that these may want
  different storage/throughput treatment behind the one component.
- **Stateless-worker scaling is preserved.** CMP-002/003/004/005 hold no durable state; all shared
  state is externalised to CMP-006/007. This is the correct shape for NFR-10 horizontal scaling —
  the CMP-006/007 store becomes the contention point, to be sized in infrastructure-design. No
  action; recording that I checked.
- **NFR-5 (credential security) correctly absent as a component.** Secret-manager storage for
  Slack/Kiro/MCP creds is an infrastructure concern consumed by CMP-003/004/001; right to keep it
  out of the domain model.

---

## 4. Items explicitly NOT changing

- No objection to the component count, boundaries, dependency directions, or entity ownership —
  the balanced 8-component catalogue is correct and I endorse it.
- No new component requested. DA-1 is the only suggested *in-place* edit (add a correlation/request
  id to the entity model); everything else is a downstream design note for stages I own and does
  not require reworking `components.yaml`.
- components.md ↔ components.yaml consistency, the FR/story coverage matrix, and the validation
  section are sound as written; do not rework them.

## 5. Hand-off summary for the stages I own next

- **functional-design:** carries DA-2 (reserve-then-settle guardrail), DA-3 (intake ordering +
  conditional `ProcessingJob` write), DA-6 (distinct reason codes), and the existing CS-4/CS-5
  pipeline contract.
- **nfr-design:** carries DA-2 (hard vs soft cap decision, A-7 thresholds), DA-5 (config caching in
  the NFR-1 path), DA-7 (loop/timeout budget includes retries), plus A-3/A-9 confirmations.
- **infrastructure-design:** carries DA-4 (recovery trigger: visibility timeout and/or reaper),
  DA-1 observability/correlation propagation, CMP-006/007 store sizing and consistency model, and
  the A-1 backend selection (de-risk before functional-design commits).
