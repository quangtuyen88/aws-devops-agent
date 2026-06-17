# Domain Design — Clarification Questions

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Stage: `domain-design` · Owner: aidlc-app-architect-agent

These questions settle the **component decomposition** — how many logical
building blocks exist and which one owns each entity. They do not touch scope,
tech stack, or deployment (that is units-/infrastructure-design). Answers feed
directly into `components.yaml`. See `plan.md` for the baseline catalogue.

Where a question has a clear best answer, a recommendation is given — reply
"agree" to accept it.

---

### Q1 of 6: Overall component granularity

How fine-grained should the component catalogue be? (This frames Q2–Q6.)

a) **Coarse (4):** Slack Adapter, Agent Orchestrator (absorbs safety scan, job coordination, answer composition), Inference Provider, MCP Client. Operational data + config become internal concerns of the orchestrator.
b) **Balanced (8):** the baseline in `plan.md` — Slack Adapter, Agent Orchestrator, Inference Provider, MCP Client, Input Safety Scanner, Job Coordinator, Operational Data Service, Configuration & Policy.
c) **Fine (10+):** balanced, plus split-out Cost Guardrail, Thread-Context Fetcher, Answer Composer, etc.
d) Other.

**Trade Offs:** (a) is simplest and matches the single-deployable-unit assumption (A-4), but hides the CS-1 shared-state boundary and the A-1 pluggability seam inside one large component, making ownership and change-rate reasoning harder. (c) maximises separation of concerns but over-decomposes capabilities that always change together, adding contract overhead with no payoff at this size. (b) isolates exactly the seams the requirements call out as independent: the pluggable inference backend (A-1), the external MCP dependency, the safety gate (CS-4), the async job state (C-1/CS-3), and the single shared-state store (CS-1).

**Recommendation:** (b) Balanced. It maps one component to each distinct reason-to-change the requirements already identified, without splitting things that move together. Components are logical blocks here; grouping into a deployable unit happens later at units-generation, so a balanced count costs nothing now and preserves clarity.

[Answer]:

---

### Q2 of 6: Where does secret/credential detection (FR-15 / S-16 / CS-4) live?

CS-4 states the safety check must run **before** input reaches inference (CMP-003) or MCP (CMP-004).

a) **Its own component (Input Safety Scanner, CMP-005)** that the orchestrator calls first, before any inference/MCP step.
b) A function/module **inside the Agent Orchestrator** (CMP-002) — not a separate component.
c) Part of the **Slack Adapter** (CMP-001), scanning at intake.
d) Other.

**Trade Offs:** Detection rules (heuristics/patterns per A-6) have a distinct change rate from agent-loop logic and from Slack plumbing, and the gate is reused conceptually wherever untrusted text flows outward — that argues for (a). (b) keeps the call graph simpler but couples an evolving rule set to the orchestrator's change cycle. (c) scans too early (it would miss secrets that only appear in fetched thread context per CS-6, and the adapter is about Slack transport, not content inspection).

**Recommendation:** (a) Own component. The distinct change rate (A-6 rule evolution) and the CS-4 "gate before any external send" responsibility justify a separate building block. It depends on nothing external and is cheap to model.

[Answer]:

---

### Q3 of 6: How do we model the async intake→worker split and job lifecycle (C-1 / C-4 / CS-2 / CS-3 / S-19,20,24)?

The Slack 3s ack forces accept-and-enqueue; the queue itself (e.g. SQS) is infrastructure. But the **job state machine** — seen / in-progress / resolved, at-most-once-*completed* de-dup (CS-3), and in-flight recovery (CS-2) — is business logic that needs an owner.

a) **A dedicated Job Coordinator component (CMP-006)** owns the `ProcessingJob` entity and its state transitions; the queue and its datastore are its infrastructure dependencies.
b) The **Agent Orchestrator (CMP-002)** owns job state directly — no separate coordinator.
c) Fold job/de-dup state into the **Operational Data Service (CMP-007)** since CS-1 calls all durable state one boundary.
d) Other.

**Trade Offs:** The de-dup-vs-retry tension (CS-3) and lost-in-flight recovery (CS-2) are subtle state-machine logic that is distinct from the orchestrator's "reason about the answer" job — separating it (a) keeps each understandable alone and gives the `ProcessingJob` entity a single clear owner. (b) is simpler but mixes transport-reliability concerns with answer-generation. (c) conflates job-control state (hot, per-request, correctness-critical) with aggregate analytics state (append-mostly) — different access patterns and consistency needs, even if they happen to share a datastore later.

**Recommendation:** (a) Dedicated Job Coordinator owning `ProcessingJob`. It is the cleanest home for CS-2/CS-3 logic and keeps the orchestrator focused on answer generation. Whether it shares a physical datastore with CMP-007 is an infrastructure-design decision, not a domain one.

[Answer]:

---

### Q4 of 6: Ownership of the shared durable state — adoption metrics, feedback, cost counters (CS-1)

CS-1 names the durable/shared state as: per-period cost counter (S-18), de-dup identity (S-20), feedback signals (S-26), adoption counts (S-27). De-dup identity is handled in Q3. For the **analytics/guardrail** state:

a) **One Operational Data Service (CMP-007)** owns `AdoptionMetric`, `FeedbackSignal`, and `UsageCounter` (cost) together.
b) **Split:** a Metrics & Feedback component vs. a separate Cost Guardrail component (the latter both records and enforces the bound).
c) Other.

**Trade Offs:** Adoption metrics and feedback are pure capture-and-aggregate (write-mostly, read-rarely this release per Q2=a). The cost counter is also a counter, but it is additionally *read on the hot path to enforce a limit* (S-18/NFR-8) — that is an enforcement responsibility, not just storage. Bundling all three (a) gives one clear owner for all aggregate data and a single CS-1 boundary; the enforcement read can still be a method on that component. Splitting (b) cleanly separates "enforce a guardrail" from "record analytics" but creates two owners of very similar counter data.

**Recommendation:** (a) for entity *ownership* (one Operational Data Service owns all three entities), but see Q5 for where the guardrail *enforcement decision* logic sits. This keeps every durable entity single-owned per CS-1 while still allowing enforcement logic to live elsewhere.

[Answer]:

---

### Q5 of 6: Where does cost-guardrail enforcement (NFR-8 / S-18) decide to allow/deny a request?

Given Q4 puts the `UsageCounter` entity in the Operational Data Service:

a) **Operational Data Service (CMP-007)** both stores the counter and exposes an "is the request within budget?" decision; the orchestrator just asks.
b) **Agent Orchestrator (CMP-002)** reads the counter and makes the allow/deny decision itself.
c) A **separate Cost Guardrail component** owns the decision and reads/writes the counter.
d) Other.

**Trade Offs:** (a) keeps the data and the rule that operates on it together (high cohesion — the component that owns the counter knows what "over budget" means), and the orchestrator stays focused. (b) spreads guardrail logic into the orchestrator, coupling cost policy to agent-loop changes. (c) is the most separated but, at this scale, an extra component whose only state is a counter the Operational Data Service already owns is over-decomposition (would split ownership of `UsageCounter` or create a chatty dependency).

**Recommendation:** (a) Operational Data Service owns both the counter and the within-budget decision; thresholds themselves come from Configuration & Policy (Q6). The orchestrator calls "may I proceed?" and routes a denial to the S-19 failure path.

[Answer]:

---

### Q6 of 6: Where do channel allowlist, usage policy, and guardrail thresholds live (FR-2 / NFR-3 / S-15,17,18)?

These are operator-set configuration values, distinct from runtime data.

a) **A dedicated Configuration & Policy component (CMP-008)** owns `ChannelAllowlist`, `UsagePolicy`, and `GuardrailConfig`; the Slack Adapter, Orchestrator, and Operational Data Service read from it.
b) **Distribute:** allowlist into the Slack Adapter (it enforces it), thresholds into the Operational Data Service, policy text as static config — no config component.
c) Other.

**Trade Offs:** A single config owner (a) gives operators one place to manage settings (S-15, S-17, S-18 are all operator stories) and one component to change when a new setting is added; consumers just read. (b) avoids an extra component and puts each setting next to its enforcer, but scatters the operator-facing surface and means "add a new operator setting" touches several components. The values are read-mostly and low-churn either way.

**Recommendation:** (a) Dedicated Configuration & Policy component. The three operator stories (S-15/17/18) make operator configuration a coherent, separately-changing concern with a natural single owner; consumers depend on it read-only.

[Answer]:

---

## Notes

- If you prefer to accept all recommendations, reply "agree to all" and I will
  proceed to produce `components.yaml` / `components.md` with the balanced
  8-component catalogue (CMP-001..CMP-008) as described in `plan.md`.
- These choices affect only the *logical* component boundaries. Whether they
  deploy as one process or several is decided later at units-generation
  (current assumption: single deployable unit, A-4/C-4).

---

## Human Answer (recorded 2026-06-17T10:25:36+08:00)

**"agree to all"** — accept all six recommendations. Produce the balanced 8-component
catalogue CMP-001..CMP-008:
1. Slack Adapter
2. Agent Orchestrator
3. Inference Provider (pluggable backend seam, A-1)
4. MCP Client
5. Input Safety Scanner (CS-4 gate, own component)
6. Job Coordinator (owns `ProcessingJob` state machine — CS-2/CS-3)
7. Operational Data Service (owns `AdoptionMetric`, `FeedbackSignal`, `UsageCounter`;
   exposes within-budget decision for NFR-8/S-18)
8. Configuration & Policy (owns `ChannelAllowlist`, `UsagePolicy`, `GuardrailConfig`; read-only consumers)
