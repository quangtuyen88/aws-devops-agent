# Units Generation — Clarification Questions

> Stage: `units-generation` (inception) · Owner: aidlc-app-architect-agent ·
> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`).
>
> Purpose: the 8 logical components (CMP-001..CMP-008) from domain-design are fixed.
> This stage decides only **how they are packaged into deployable units**. The
> domain-design carried a working assumption of a *single* deployable unit with the
> intake→worker async boundary living *inside* it (A-4 / C-4). units-generation is
> where that assumption is confirmed against your real constraints — team,
> deployment, scaling, and operational maturity. These questions resolve that.
>
> Note on scope: concrete runtime/cloud choices (Lambda vs container, which queue,
> which datastore) are **infrastructure-design**, not this stage. Here we decide
> *conceptual packaging* (how many independently buildable/deployable units and
> where the boundaries sit). If the answer splits into 2+ units, `contract-design`
> is added back before construction (per workflow rationale).

---

### Q1 of 4: How should the 8 components be packaged into deployable units?

This is the central decision of the stage. The architecturally significant fact is
that the intake path (CMP-001 — must ack within **NFR-1 p95 < 3s**, always-on,
event-driven) and the worker path (CMP-002 + the inference/MCP/safety/grounding
components — long-running **NFR-2 p95 ≤ 30s**, concurrency-sensitive NFR-10) already
sit on opposite sides of a mandatory async queue boundary (C-1). They have different
latency, scaling, and failure profiles — a classic reason a single component group
could be split into two units.

a) **Single deployable unit (modular monolith).** All 8 components ship as one
   buildable/deployable artifact; the queue boundary is internal. Matches the A-4/C-4
   working assumption. `contract-design` stays skipped.
b) **Two units split on the existing async boundary** — an *Intake/Adapter* unit
   (CMP-001 + the de-dup/registration touchpoint) and an *Agent Worker* unit (CMP-002,
   CMP-003, CMP-004, CMP-005) — with the shared-state components (CMP-006, CMP-007,
   CMP-008) placed by Q-follow-up. The queue becomes a unit-to-unit integration point;
   `contract-design` is reinstated.
c) **Finer-grained split** (e.g. also isolating CMP-003 Inference Provider and/or
   CMP-007 Operational Data Service as their own units).
d) Other / let me describe a different grouping.

**Trade Offs:** (a) is simplest to build, deploy, test, and operate, and keeps one
codebase and one release — best when one team owns it and load is modest; the cost is
that intake and worker scale and deploy together. (b) lets the fast always-on intake
and the bursty long-running worker scale and fail independently (directly serving
NFR-1 vs NFR-2/NFR-10), at the cost of a real cross-unit contract, a network/queue hop
to operate, and added deployment/observability overhead. (c) maximises independent
evolvability (notably the high-risk A-1 inference seam) but multiplies operational
surface well beyond what an internal-tool bot likely warrants.

**Recommendation:** (a) **Single deployable unit**, unless Q2–Q3 surface a real
multi-team or independent-scaling need. The async boundary is genuine but can live
*inside* one unit (queue as an internal seam). For a single-workspace internal tool
(A-5) owned by one team, a modular monolith with clean internal module boundaries
keeps build/deploy/ops cost lowest while preserving the option to extract the worker
later — the boundaries are already drawn at the component level. I lean (a) but want
Q2–Q3 to confirm before committing.

[Answer]:

---

### Q2 of 4: Who builds and operates this — team structure and ownership?

Unit boundaries that don't match team boundaries create friction; splitting into
units only pays off when separate teams (or separate release cadences) own the pieces.

a) **One team / one developer** owns the entire bot end-to-end, one release cadence.
b) **Two+ teams** — e.g. one owns the Slack/platform integration, another owns the
   agent/inference logic — with independent release cadences.
c) Other / not yet decided.

**Trade Offs:** (a) favours a single unit — internal module boundaries give all the
separation needed without cross-unit contract overhead. (b) is the strongest argument
for the Q1(b) split, since unit-per-team enables parallel, independently-released work.

**Recommendation:** (a) for a greenfield internal tool. If (b), it materially
strengthens the case for the Q1(b) two-unit split.

[Answer]:

---

### Q3 of 4: Do intake and worker need to scale (and deploy) independently in the near term?

a) **No / not yet** — expected volume is modest (internal, single-workspace, A-5),
   intake and worker can scale together for now.
b) **Yes** — we anticipate question bursts where many long-running agent loops run
   concurrently (NFR-10) while intake stays cheap and always-on, and we want them sized
   and released separately from day one.
c) Other / unknown.

**Trade Offs:** (a) supports the single-unit choice (Q1a) and defers the split until a
real scaling signal appears — cheaper now, and the worker can be extracted later along
the boundary that's already drawn. (b) supports Q1(b): independent scaling is the main
technical payoff of splitting on the queue boundary.

**Recommendation:** (a) unless you already have evidence of bursty concurrent load.
Independent scaling of the *worker* is the kind of thing best done when the signal is
real; the component boundaries preserve that option without paying for it now.

[Answer]:

---

### Q4 of 4: Should the Inference Provider (CMP-003, the A-1 seam) be packaged as a separately buildable library/module, regardless of the Q1 outcome?

A-1 is flagged the highest-risk assumption: the Kiro inference surface may not be
usable headless, so the abstraction must let an alternate backend (e.g. Bedrock) drop
in without touching agent-core logic. Packaging influences how cleanly that swap and
its isolated testing happen.

a) **Yes — a distinct buildable library/module** with a stable interface, consumed by
   the worker, so the backend can be swapped and tested in isolation. (Inside a single
   unit this is just an internal module with an enforced interface; it does not require
   a separate *deployable* unit.)
b) **No — keep it an ordinary internal module** of whichever unit owns the worker; the
   interface boundary from domain-design is enough.
c) Other.

**Trade Offs:** (a) makes the A-1 seam explicit and independently testable/mockable,
de-risking the swap, at the cost of a little packaging ceremony. (b) is simpler and
relies on discipline to keep the seam clean. Note (a) can be satisfied as a *module/
library* boundary without making CMP-003 its own deployable unit.

**Recommendation:** (a) as a **module/library boundary, not a separate deployable
unit** — it directly serves the de-risking the requirements call for (validate A-1
before functional-design) while keeping the deployment footprint per Q1.

[Answer]:

---

## Human Answers (recorded 2026-06-17T11:39:24+08:00)

- **Q1: a** — Single deployable unit (modular monolith); async queue boundary is internal.
  `contract-design` stays skipped.
- **Q2: a** — One team / one developer owns the bot end-to-end, single release cadence.
- **Q3: b** — Yes: anticipate bursty concurrent agent loads (NFR-10), want intake vs worker
  sized independently. **NOTE — tension with Q1(a):** the human wants ONE deployable unit but
  ALSO independent scaling of the worker. Owner to reconcile explicitly: keep a single unit
  but design the worker path for independent horizontal scaling within it (concurrent workers
  off the internal queue), and preserve the C-1 boundary as a clean future extraction seam.
  Record how independent scaling is achieved without a second deployable unit (infra-design
  will detail the runtime mechanism).
- **Q4: a** — Inference Provider (CMP-003, A-1 seam) packaged as a distinct buildable
  library/module with a stable interface (swap Kiro↔Bedrock, test in isolation) — a module/
  library boundary, NOT a separate deployable unit.
