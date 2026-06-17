# Units of Work

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `units-generation` (inception) · Owner: aidlc-app-architect-agent.
> Source of truth for building blocks: `components.yaml` (copied forward from
> domain-design with `Unit:` ownership added). This stage decides **packaging only** —
> the 8 components (CMP-001..CMP-008) and their boundaries are unchanged.

## Packaging Decision (and why)

**One deployable unit — UNIT-001 (single deployable artifact, multi-role runtime).**
All 8 components ship as a single buildable/deployable artifact; the C-1 intake→worker
async boundary is an **internal** seam — a **durable, out-of-process queue that is
internal to the unit** (not a cross-unit contract), distinct from the in-process calls
between modules within a single role. "Internal" means "not a cross-unit contract," **not**
"in-memory": the queue must survive a worker crash (CS-2 in-flight recovery) and lets the
worker role scale independently of intake (Q3=b / NFR-10).

Traced to the human answers (`questions.md`, 2026-06-17T11:39:24+08:00) and the
domain-design drivers:

| Driver | Answer / source | Effect on packaging |
|---|---|---|
| Packaging shape (Q1) | **a** — single deployable unit, queue boundary internal | One unit, UNIT-001; matches the A-4/C-4 working assumption |
| Team / ownership (Q2) | **a** — one team/dev owns it end-to-end, one release cadence | No unit-per-team driver → no split |
| Independent scaling (Q3) | **b** — worker bursts (NFR-10) vs cheap always-on intake (NFR-1) | Reconciled *within* one unit (see below), **not** by splitting |
| Inference seam (Q4) | **a** — distinct buildable library/module, stable interface | CMP-003 is an internal **library module**, not a separate unit |
| C-1 async boundary | requirements / domain-design | Lives inside UNIT-001 as an internal queue seam |
| `contract-design` | single-unit ⇒ no cross-unit contracts | **Stays skipped** (confirmed) |

**Why not split (units-decomposition principle "fewer units until complexity
justifies more"):** the only technical argument for a split is the divergent
intake/worker latency-and-scaling profile (NFR-1 vs NFR-2/NFR-10). Q2 confirms a
single owner and single release cadence, so a cross-unit contract, an operable
network/queue hop, and doubled deployment/observability surface would be cost without
a matching benefit for a single-workspace internal tool (A-5). The component
boundaries already sit on the C-1 seam, so the worker remains cleanly extractable
later if a real multi-team or independent-deploy signal appears.

### Reconciling Q1 (one unit) with Q3 (independent worker scaling)

The human wants **one deployable unit** *and* **the worker sized/scaled
independently of intake**. These are not in conflict — independent *scaling* does
not require a separate *deployable unit*:

- UNIT-001 ships as one artifact but runs in **two roles off one codebase**: an
  **intake role** (CMP-001 path — always-on, cheap, must ack within NFR-1 p95 < 3s)
  and a **worker role** (CMP-002 + CMP-003/004/005 path — long-running NFR-2 p95 ≤ 30s,
  concurrency-sensitive NFR-10).
- The internal C-1 queue decouples the two roles, so the **worker role can be scaled
  horizontally (N concurrent worker instances draining the queue) independently of the
  intake role**, satisfying S-24 (no head-of-line blocking) and NFR-10.
- The C-1 boundary is preserved as a **clean future extraction seam**: if the worker
  ever needs its own deploy cadence or runtime, it lifts out along this seam into a
  second unit with minimal disturbance (at which point `contract-design` is reinstated
  for the queue contract).
- The concrete runtime mechanism that delivers independent scaling (e.g. separate
  process pools, autoscaling worker consumers, function concurrency) is an
  **infrastructure-design** decision, not this stage's. This stage records the
  *requirement* and the *seam*; infrastructure-design picks the mechanism.

## Unit Inventory

| Unit ID | Unit | Purpose | Packaging Assumption | Components Owned |
|---|---|---|---|---|
| UNIT-001 | Slack DevOps Agent | Deliver the entire Slack DevOps assistant — intake, async agent reasoning, grounding, safety, job lifecycle, operational data, and configuration — as one buildable/deployable artifact | Modular monolith: one deployable unit with an internal C-1 async queue seam separating an always-on intake role from an independently-scalable worker role; an internal inference-provider library module isolates the A-1 backend | CMP-001, CMP-002, CMP-003, CMP-004, CMP-005, CMP-006, CMP-007, CMP-008 |

## Unit Details

### Slack DevOps Agent

- **ID:** UNIT-001
- **Purpose:** The single buildable/deployable piece that *is* the bot — it owns the
  complete capability from Slack `@mention` to grounded, cited, in-thread answer, plus
  the safety gate, job de-dup/recovery, cost guardrail, operational metrics, and
  operator configuration.
- **Responsibilities:**
  - Own the Slack boundary in both directions and ack within NFR-1 (CMP-001).
  - Run the async agent loop — context reconstruction, safety gate (CS-4), budget
    check, inference + MCP grounding under the CS-5 cap, answer composition, job
    resolution (CMP-002).
  - Provide a backend-agnostic inference abstraction so the engine can be swapped
    Kiro↔Bedrock without touching agent-core logic (CMP-003, A-1).
  - Ground answers in AWS Knowledge MCP sources and cite them, marking ungrounded
    rather than fabricating (CMP-004, A-2).
  - Gate input for secrets/credentials before any external send (CMP-005, NFR-4/CS-4).
  - Own the ProcessingJob state machine: at-most-once-completed de-dup and in-flight
    recovery across the internal C-1 seam (CMP-006, CS-2/CS-3).
  - Own the durable aggregate operational data (adoption, feedback, usage counter) and
    the within-budget decision (CMP-007, CS-1/NFR-8).
  - Own operator-set configuration: channel allowlist, usage policy, guardrail
    thresholds (CMP-008).
- **Boundaries (what UNIT-001 is NOT):**
  - Does **not** own its external dependencies — Slack API, the message queue, the
    Kiro/Bedrock inference endpoint, `aws-knowledge-mcp-server`, and the durable
    datastore are infrastructure consumed by the unit, not part of it.
  - Does **not** span workspaces/tenants (A-5/OOS-5) and does **not** execute or deploy
    generated IaC (OOS-3).
  - Does **not** persist cross-session conversation memory (A-8/OOS-4) — thread context
    is fetch-not-store (CS-6).
  - Because there is exactly one unit, there is **no cross-unit contract** in this
    release; `contract-design` stays skipped.
- **Packaging assumption:** A single deployable artifact with a multi-role runtime
  (a "modular monolith" by code structure, **not** a single process). One codebase, one
  build, **one release cadence** — but deployed in 2+ runtime roles that share that one
  artifact version (always-on intake role + horizontally-scaled worker role). "One unit"
  is a property of the *artifact version*, not of co-deployment: infrastructure-design is
  free to scale (and even deploy) the worker role independently of intake. Internally
  organised into enforced modules (below) with the C-1 **durable, out-of-process** queue
  as the internal seam between the intake and worker roles. Conceptual only — Lambda vs
  container, which queue, and which datastore are infrastructure-design choices.
- **Build independence:** Builds and unit-tests stand alone — no other *unit* must be
  running to build or test it (there is only one unit). External dependencies are
  mocked/stubbed for test: the inference-provider library module (CMP-003) is built and
  tested in isolation behind its stable interface (Q4), and the MCP client (CMP-004),
  Slack adapter (CMP-001), and durable stores (CMP-006/007) are exercised against test
  doubles so the agent loop is testable without live backends.
- **Change rate:** Single overall cadence (one team, Q2). Relative internal churn:
  CMP-001 tracks the Slack API; CMP-003 is the highest-risk, most-likely-to-change
  module (A-1 backend swap) — its library boundary localises that churn; CMP-005
  detection rules evolve on their own cadence (A-6); CMP-008 is low-churn/read-mostly;
  CMP-002 carries the core agent-loop logic.

## Internal Module Structure (within UNIT-001)

Not separate units — these are the enforced internal module boundaries that keep the
single artifact a *modular* monolith and preserve future extraction seams. Each maps
1:1 to its owning component(s); the inference module is called out per Q4.

| Internal module | Role | Components | Notes |
|---|---|---|---|
| Intake / Adapter | Always-on intake role | CMP-001 | Acks within NFR-1; enqueues across the C-1 internal seam |
| Agent Worker | Independently-scalable worker role | CMP-002, CMP-004, CMP-005 | Drains the internal queue; runs the CS-4-ordered pipeline under the CS-5 cap |
| **Inference Provider (library)** | A-1 swap seam | CMP-003 | **Q4: distinct buildable library module with a stable interface**, consumed by the worker; backend (Kiro/Bedrock) selected in infrastructure-design; built/tested in isolation. Module boundary only — *not* a separate deployable unit |
| Job / State | Job lifecycle & de-dup | CMP-006 | Owns ProcessingJob (CS-1/CS-2/CS-3); durable store is infra |
| Operational Data | Durable aggregates & budget | CMP-007 | Owns adoption/feedback/usage + within-budget decision (CS-1) |
| Configuration & Policy | Operator settings | CMP-008 | Read-mostly; allowlist/policy/guardrail thresholds |

> The internal C-1 queue seam sits between **Intake/Adapter** and **Agent Worker**.
> It is the single boundary along which the worker would extract into its own unit if
> a future signal justifies it.

## Validation (units-decomposition skill)

- **Understandable independently:** one unit; its internal modules each map to a
  single domain component with a single responsibility. ✓
- **No circular *unit* dependencies:** a single unit has no inter-unit graph; the
  internal component dependency graph remains the acyclic DAG validated in
  domain-design. ✓
- **Dependency directions explicit:** unchanged from domain-design; the only async
  edge (intake→worker) is the internal C-1 queue seam, deliberately not a synchronous
  call. ✓
- **Supports the stated NFRs:** intake (NFR-1) and worker (NFR-2/NFR-10) have divergent
  profiles served by the two-role design and independent worker scaling *within* the
  unit — no split required now, extraction seam preserved. ✓
- **Fewer units until justified:** Q2 (one team) + A-5 (single-workspace internal
  tool) give no current driver to split; decomposition stays minimal. ✓
- **Every component assigned to exactly one unit:** all of CMP-001..CMP-008 → UNIT-001
  (see `components.yaml` `Unit:` fields). ✓

---

## Functional-Design Expansion (appended 2026-06-17, construction/UNIT-001)

> Owner: aidlc-systems-architect-agent. The unit definition above is copied forward
> from units-generation UNCHANGED (boundaries, packaging, internal modules preserved).
> This section adds references to the functional artifacts produced this stage. No
> boundary or packaging decision is changed.

### Functional artifacts for UNIT-001

| Artifact | Role |
|---|---|
| `entities.yaml` | ENT-001..ENT-014 full schemas (source of truth) |
| `rules.yaml` | BR-001..BR-026 business rules (source of truth) |
| `functional-spec.md` | ER diagram, ProcessingJob state machine, workflows W1..W5, rules summary |
| `api-specification.md` | External integration surfaces (API-EXT-001..006) + internal module interfaces (API-INT-001..009) |
| `components.yaml` | Copied-forward blueprint + `Functional-Design-Refs` appendix |

### Design decisions applied (human-answered 2026-06-17)

- **Q1=c** — `api-specification.md` documents both the external integration surfaces and
  the internal module seams (notably the CMP-003 inference swap seam API-INT-001 and the
  C-1 enqueue API-INT-009).
- **Q2=b** — ProcessingJob (ENT-008) uses distinct terminals `resolved | failed`
  (refinement R-1; enum expanded in place).
- **Q3=a** — de-dup identity = channel-id + message-ts (refinement R-2).
- **Q4=b** — FeedbackSignal (ENT-010) is an append-only log; success metric reads
  latest-per-(answer, reactor, signal) (refinement R-3, refined per PM F-1).

### Internal module → functional coverage

| Internal module → component(s) | Workflows | Provided interface(s) |
|---|---|---|
| Intake/Adapter → CMP-001 | W1, W4 (capture), W5 | API-INT-005 |
| Agent Worker → CMP-002 (+CMP-004, CMP-005) | W2, W3 | API-INT-003 (CMP-005), API-INT-004 (CMP-004) |
| Inference Provider library → CMP-003 | W2 | **API-INT-001 (A-1/Q4 stable swap seam)** |
| Job/State → CMP-006 | W1, W3 | API-INT-002 (+ ProcessingJob state machine) |
| Operational Data → CMP-007 | W2, W4 | API-INT-006, API-INT-007 |
| Configuration & Policy → CMP-008 | W5 | API-INT-008 |

The C-1 internal async seam is API-INT-009 (intake→worker queue), the preserved future
extraction boundary — unchanged from units-generation.

### Boundaries retained (unchanged)

OOS-3 (never executes/deploys IaC — BR-017), OOS-4/A-8 (no durable conversation memory;
fetch-not-store — BR-005), A-5/OOS-5 (single workspace), NFR-5 (least-privilege creds at
every external surface). Concrete numeric thresholds remain deferred to nfr-design (A-7/A-9).
