# Unit Dependencies

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `units-generation` (inception) · Owner: aidlc-app-architect-agent.
>
> **Single deployable unit (UNIT-001).** There are no inter-unit dependencies and no
> cross-unit contracts in this release — `contract-design` stays skipped (Q1=a). The
> only architecturally significant boundary, the C-1 intake→worker async seam, is
> **internal** to UNIT-001. This file therefore documents (a) the absent cross-unit
> dependency graph, (b) the internal seam and module dependencies for build/test
> reasoning, and (c) the integration points that would become cross-unit contracts if
> the worker is later extracted.

## Dependency Matrix

### Inter-unit (cross-unit)

| Dependency ID | Unit | Depends on | Dependency type | Integration mechanism |
|---|---|---|---|---|
| — | UNIT-001 | (none) | none | N/A — single deployable unit; all interaction is in-artifact |

There is exactly one unit, so there are no unit-to-unit dependencies to order or
contract.

### Internal (within UNIT-001 — informational, for build/test reasoning)

These are the existing domain-design component dependencies, now all internal to one
unit. They do **not** create unit dependencies; they are listed so the build order and
parallelisation of internal modules are explicit.

| Ref | From module (component) | Depends on (component) | Type | Internal mechanism |
|---|---|---|---|---|
| INT-1 | Intake/Adapter (CMP-001) | Configuration & Policy (CMP-008) | runtime (read) | in-process call (read allowlist) |
| INT-2 | Intake/Adapter (CMP-001) | Job/State (CMP-006) | runtime + data | in-process call (register + de-dup) |
| INT-3 | Intake/Adapter (CMP-001) | Operational Data (CMP-007) | runtime + data | in-process call (record feedback) |
| INT-4 | Intake/Adapter (CMP-001) | Agent Worker (CMP-002) | **async (C-1)** | **internal queue seam** (enqueue; not a synchronous call) |
| INT-5 | Agent Worker (CMP-002) | Input Safety Scanner (CMP-005) | runtime | in-process call BEFORE any external send (CS-4) |
| INT-6 | Agent Worker (CMP-002) | Inference Provider lib (CMP-003) | build-time + runtime | **stable library interface** (Q4 swap seam) |
| INT-7 | Agent Worker (CMP-002) | AWS Knowledge MCP Client (CMP-004) | runtime | in-process call (ground + cite) |
| INT-8 | Agent Worker (CMP-002) | Operational Data (CMP-007) | runtime + data | in-process call (within-budget? + record usage/adoption) |
| INT-9 | Agent Worker (CMP-002) | Job/State (CMP-006) | runtime + data | in-process call (state transitions, recovery) |
| INT-10 | Agent Worker (CMP-002) | Slack Interaction Adapter (CMP-001) | runtime | in-process call (fetch replies, post answer/failure) |
| INT-11 | Agent Worker (CMP-002) | Configuration & Policy (CMP-008) | runtime (read) | in-process call (usage policy / loop limits) |
| INT-12 | Operational Data (CMP-007) | Configuration & Policy (CMP-008) | runtime (read) | in-process call (read guardrail threshold) |

> The internal graph is the same acyclic DAG validated in domain-design. INT-4 is the
> deliberate async seam (not a synchronous edge), which is why CMP-001→CMP-002 does not
> create a cycle with INT-10 (CMP-002→CMP-001).

## Build Order

Only one unit, so the unit-level build order is trivial:

1. **UNIT-001 — Slack DevOps Agent** (no upstream units; build, test, release on its own).

Within UNIT-001, the only build-time (compile/link) dependency among internal modules
is INT-6: the **Inference Provider library module (CMP-003)** exposes the stable
interface the Agent Worker (CMP-002) compiles against, so build it (or at least its
interface) first; the worker then builds against that interface. All other internal
edges are runtime calls, not build-time dependencies, so the remaining modules have no
compile-order constraint among themselves. Deployment order is decided later in
infrastructure-design.

## Parallelisation Opportunities

| Units / modules | Can be built in parallel? | Reason |
|---|---|---|
| UNIT-001 vs other units | N/A | Only one unit exists |
| Inference Provider library (CMP-003) interface vs everything else | Interface first, then parallel | The worker compiles against the CMP-003 interface (INT-6); once the interface is fixed, the provider implementation and the worker can be built/tested in parallel against it (Q4 isolation) |
| Intake/Adapter, Job/State, Operational Data, Configuration, MCP client, Safety scanner | Yes | No build-time dependency among them — only runtime in-process calls; can be developed and unit-tested in parallel behind test doubles |

## Integration Points

There are **no cross-unit runtime integration points** in this release (single unit).
The table below records the points that *would* become cross-unit contracts if the
Agent Worker is later extracted along the C-1 seam — i.e. the agenda `contract-design`
would pick up at that time. For now every "contract" is an enforced **internal**
module interface, not a network contract.

| Dependency ID | From | To | Integration Need | Expected Contract |
|---|---|---|---|---|
| FUT-1 | Intake/Adapter (CMP-001) | Agent Worker (CMP-002) | The C-1 async handoff: enqueue an accepted job (carrying `correlation-id` == `job-id`) for asynchronous processing | N/A this release (internal queue seam). If worker is extracted: queue message contract — owned by a reinstated `contract-design` |
| FUT-2 | Agent Worker (CMP-002) | Inference Provider library (CMP-003) | Backend-agnostic "run inference" + usage reporting; swap Kiro↔Bedrock (A-1) | Internal **library interface** this release (Q4). Stays a library boundary even if the worker is extracted — does not require its own deployable unit |
| FUT-3 | Job/State (CMP-006) + Operational Data (CMP-007) shared durable state | Intake & Worker roles | CS-1 shared state must be consistent across the concurrently-scaled worker instances (Q3/S-24) — not process memory | N/A as a *unit* contract; the store + consistency model is an infrastructure-design decision (carried from domain-design DA-2/DA-3) |

## Notes for downstream stages

- **`contract-design` stays skipped** for this release (single unit, no cross-unit
  boundary). The FUT-* rows are the trigger list to reinstate it if the worker is ever
  extracted along the C-1 seam.
- **infrastructure-design** owns: the runtime mechanism that gives the worker role
  independent horizontal scaling within the single unit (Q3), the concrete internal
  queue, the CS-1 shared-state store + consistency model (DA-2/DA-3), the C-1 in-flight
  recovery trigger (DA-4), and the A-1 backend selection behind the CMP-003 interface.
- **functional-design / nfr-design** inherit all domain-design DA-1..DA-7 notes
  unchanged — packaging does not alter them.
