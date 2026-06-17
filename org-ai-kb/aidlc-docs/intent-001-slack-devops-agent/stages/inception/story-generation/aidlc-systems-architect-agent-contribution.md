# Systems Architect Contribution — Story Generation

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Contributor: aidlc-systems-architect-agent
Role: systems thinking, architectural soundness of the decomposition, cross-story
interaction risk, NFR placement, traceability into design stages.
Reviewed artifacts: `stories.md` (S-1..S-27 + cross-cutting NFRs + coverage matrix),
`personas.md`, `plan.md`, `questions.md`; cross-checked against `requirements.md`
(FR-1..FR-21, NFR-1..NFR-10, A-1..A-9, C-1..C-4) and my requirements-stage contribution.

## Verdict

The decomposition is **architecturally sound, complete, and traceable**. Every requirement
maps to a story, the INVEST self-check holds, and the design constraints I raised at
requirements stage (C-1..C-4, G-1..G-5, A-1 fork) are faithfully encoded as stories or
cross-cutting criteria. The thin-vertical-slice ordering is the right risk-first sequence
and correctly front-loads the highest-risk assumption.

Stories operate at the right (behaviour) level and correctly defer screen/transport shaping
to functional/infra design. I have **no scope objections** and recommend **no new stories**
as a hard requirement. The findings below are *cross-story interaction risks* — places where
individually-correct stories share a hidden architectural boundary that functional-design
must treat as a unit. They are additive design guidance, not story rewrites. None block exit
from this stage.

---

## 1. What the decomposition gets right (validation)

- **Risk-first ordering front-loads A-1.** Putting S-3 (inference routing) in the first
  vertical slice is correct: A-1 (Kiro programmatic inference) is the single assumption that
  can force a redesign, and S-3's AC already encodes the pluggable-fallback hedge ("backend
  changed e.g. to Bedrock → agent-core unchanged"). The thin slice S-1→S-2→S-3→S-4→S-5→S-6
  is exactly the path that exercises every external dependency once. Good de-risking shape.
- **C-1/C-4 async boundary is visible.** S-2 (ack + enqueue), S-20 (de-dup), S-24 (no
  head-of-line blocking) collectively surface the mandatory intake→async-worker split inside
  the single deployable unit (A-4). Notes-for-downstream calls this out explicitly. Correct.
- **Fabricated-citation risk is encoded as behaviour, not prose.** S-4/S-5 make the A-2
  "no source → state ungrounded, never fabricate" rule a testable AC. This is the key
  correctness control and it is in the right place.
- **OOS-3 preserved in S-11.** Keeping "bot does not execute/apply/deploy" as an explicit AC
  preserves the NFR-5 simplification I flagged at requirements stage — no AWS *write*
  credentials enter the system at all. Keep this guard.

---

## 2. Cross-story architectural interactions (functional/infra-design must carry forward)

These are the substantive findings. Each is a place where the stories are individually
correct but share a boundary that must be designed once, coherently.

### CS-1 — Shared durable state spans four stories; it is the only stateful surface
S-20 (de-dup identity), S-18 (per-period cost guardrail counter), S-26 (feedback signals)
and S-27 (adoption counts) all require state that **must be consistent across concurrent
worker instances** demanded by S-24. The stories present these independently, which is fine
for backlog granularity, but architecturally they are one concern: the service is otherwise
stateless and this is its **single durable/shared-state boundary** (the A-8 aggregate-
operational-data store).
- Implication: de-dup and per-period guardrail state **cannot live in process memory** if
  S-24 implies more than one worker instance — an in-memory set would let duplicates and
  over-budget requests slip through on a second instance.
- Recommendation (design, not story): treat S-18/S-20/S-26/S-27 as backed by the same A-8
  store, and decide its consistency model in units-generation/infrastructure-design. No story
  change needed; add a downstream note so this is not discovered late.

### CS-2 — In-flight work durability gap between S-2 (ack) and S-6 (answer)
S-19 resolves a dangling acknowledgement when **inference/MCP fails or times out**. It does
**not** cover the worker process itself crashing/restarting after S-2 acked but before S-6
posted. In that case the developer gets "working on it…" and then silence — the exact silent-
failure pain point the personas call out.
- This is a real reliability gap created by the C-1 async split. S-19's AC ("acknowledgement
  is not left dangling") implicitly promises resolution, but its triggers are only dependency
  failures, not loss of the in-flight job.
- Recommendation: extend S-19's scope (or add one system story) so that **a job that is acked
  but not completed is either retried or resolved with a failure message** — i.e. the in-flight
  work item survives a worker restart, or its loss is detected and surfaced. This is the
  difference between "handles dependency errors" and "never leaves an ack unresolved."

### CS-3 — Idempotency (S-20) vs Slack retry-as-recovery tension
S-20 says re-delivered events start no second processing pass. Slack retries are *also* the
natural recovery path if the first attempt died before acking/answering (relates to CS-2).
De-duping purely on "event seen" would permanently lose a question whose first attempt
crashed.
- Recommendation: define de-dup semantics in functional-design as **at-most-once *completed*
  processing**, keyed so that an event whose prior attempt neither answered nor posted a
  failure may still be (re)processed. S-20's AC is correct as written; the *state semantics*
  (seen vs in-progress vs resolved) need pinning down so it doesn't conflict with CS-2's
  recovery requirement.

### CS-4 — S-16 secret detection is a fixed pre-inference gate, independent of build order
The reading-order places S-16 in the later "safety/governance" band, but NFR-4 (non-
propagation) makes secret detection a **runtime data-flow gate that must sit upstream of S-3
(inference) and S-4 (MCP)** — input is screened *before* it can reach either dependency.
- No story change needed (ordering is explicitly build guidance, not data flow), but flag for
  functional-design: in the pipeline, S-16 executes between intake (S-1/S-2) and inference
  (S-3), not "after" the answer path. Building S-16 late is fine; *placing* it late in the
  request pipeline would violate NFR-4.

### CS-5 — NFR-2 is a shared 30s budget consumed by S-13 + S-4 + S-3; bound the agent loop
The cross-cutting NFR-2 (p95 ≤ 30s) is one budget spent across, per request: a Slack thread-
history fetch (S-13, see CS-6), one *or more* MCP round-trips (S-4), and inference that may
run multiple agent-loop turns (S-3). A multi-step agentic loop routinely consumes tens of
seconds, so 30s is achievable but not generous.
- Recommendation (nfr-design, already the right home): in addition to the latency target,
  define a **hard cap on agent tool-call iterations and a per-request timeout** that routes to
  S-19 rather than running unbounded. S-19's AC includes "times out" — good — but no story or
  AC currently bounds *iteration count*, which is the more likely runaway. Capture in nfr-design.

### CS-6 — S-13 "memory" is reconstructed from Slack, not stored — confirm and budget it
Because OOS-4/A-8 forbid durable conversation memory, S-13's "prior messages included as
context" can only be satisfied by **re-fetching thread history from Slack (`conversations.replies`)
at request time**. This is the correct model given the constraints, but it has two architectural
consequences worth recording:
- It adds a Slack API call to every threaded question → contributes to the NFR-2 budget (CS-5)
  and adds to the NFR-7 (S-23) rate-limit surface.
- It feeds directly into S-22's input-size bound (accumulated thread context). S-13↔S-22 are
  already linked in the stories — good; just confirm the fetch-not-store model so functional-
  design doesn't introduce an unintended durable conversation store and trip OOS-4.

---

## 3. Minor notes

- **S-3 fallback backend has no standalone AC for the abstraction's *shape*.** S-3's "pluggable"
  AC is sufficient at story level; the actual abstraction contract (so Bedrock can drop in) is
  correctly an infrastructure-design artifact. Just ensure A-1 stays flagged [VALIDATE-NOW]
  through to functional-design as the stories' notes already state.
- **Transport choice (Events API vs Socket Mode) is correctly absent** from stories — it is an
  infra-design decision. No action; recording that I checked and agree it does not belong here.
- **NFR-5 (credential security)** as a cross-cutting criterion rather than an operator story is
  the right call (consistent with Q1); it is verified by config review, not a behaviour.

---

## 4. Prioritization view (risk-first, for build sequencing)

1. **S-1→S-2→S-3 with CS-2/CS-3 resolved** — the async ack/enqueue/worker/de-dup core. Highest
   architectural risk after A-1; get the in-flight durability + idempotency semantics right here
   or every downstream story inherits a silent-failure mode.
2. **S-3 + A-1 validation** — de-risk Kiro programmatic inference before functional-design commits.
3. **S-4/S-5 MCP grounding + citations** — core value; medium effort.
4. **S-19/S-23 failure + rate-limit handling** — reliability backbone; CS-2 widens S-19's scope.
5. **Capability variants (S-7..S-11), safety (S-16), metrics (S-25..S-27)** — high value, lower
   architectural risk, layered on the core; CS-1 ties the stateful ones together.

## 5. Items explicitly NOT changing

- No objection to any committed scope (Q1=a, Q2=a) or to the persona set.
- No new mandatory story requested; CS-2 is the only finding that *may* warrant a story edit
  (extend S-19) — the rest are downstream design notes that the stories' own
  "Notes for downstream stages" section can absorb.
- Coverage matrix, OOS guard, and INVEST self-check are sound as written; do not rework them.
