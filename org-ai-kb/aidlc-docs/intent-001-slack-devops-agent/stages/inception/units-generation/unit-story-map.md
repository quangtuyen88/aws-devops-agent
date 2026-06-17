# Unit Story Map

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `units-generation` (inception) · Owner: aidlc-app-architect-agent.
>
> All 27 stories (S-1..S-27) belong to the single unit **UNIT-001**. Every story is
> therefore "fully implemented (UNIT-001)" — no story is split across units. The
> *internal module* column carries the component→story traceability from
> domain-design (`components.md`) so build planning still knows where each story lives
> inside the unit.

## Coverage Matrix

| Story | Unit(s) | Coverage type | Implementing internal module(s) → component(s) |
|---|---|---|---|
| S-1 | UNIT-001 | fully implemented | Intake/Adapter → CMP-001 |
| S-2 | UNIT-001 | fully implemented | Intake/Adapter → CMP-001 (ack); internal C-1 enqueue to Agent Worker → CMP-002 |
| S-3 | UNIT-001 | fully implemented | Agent Worker → CMP-002 via Inference Provider library → CMP-003 |
| S-4 | UNIT-001 | fully implemented | Agent Worker → CMP-002 + AWS Knowledge MCP Client → CMP-004 |
| S-5 | UNIT-001 | fully implemented | Agent Worker → CMP-002 + AWS Knowledge MCP Client → CMP-004 |
| S-6 | UNIT-001 | fully implemented | Intake/Adapter → CMP-001 (posts); Agent Worker → CMP-002 (composes) |
| S-7 | UNIT-001 | fully implemented | Agent Worker → CMP-002 |
| S-8 | UNIT-001 | fully implemented | Agent Worker → CMP-002 |
| S-9 | UNIT-001 | fully implemented | Agent Worker → CMP-002 |
| S-10 | UNIT-001 | fully implemented | Agent Worker → CMP-002 |
| S-11 | UNIT-001 | fully implemented | Agent Worker → CMP-002 (OOS-3: never executes IaC) |
| S-12 | UNIT-001 | fully implemented | Agent Worker → CMP-002 |
| S-13 | UNIT-001 | fully implemented | Agent Worker → CMP-002 (fetch-not-store via CMP-001, CS-6) |
| S-14 | UNIT-001 | fully implemented | Intake/Adapter → CMP-001 (enforces); reads allowlist from CMP-008 |
| S-15 | UNIT-001 | fully implemented | Configuration & Policy → CMP-008 |
| S-16 | UNIT-001 | fully implemented | Agent Worker → CMP-002 invokes Input Safety Scanner → CMP-005 (CS-4, before any send) |
| S-17 | UNIT-001 | fully implemented | Configuration & Policy → CMP-008 |
| S-18 | UNIT-001 | fully implemented | Operational Data → CMP-007 (counter + within-budget) + Configuration & Policy → CMP-008 (threshold) |
| S-19 | UNIT-001 | fully implemented | Agent Worker → CMP-002 (failure msg) + Job/State → CMP-006 (in-flight recovery, CS-2) |
| S-20 | UNIT-001 | fully implemented | Job/State → CMP-006 (at-most-once-completed de-dup, CS-3) |
| S-21 | UNIT-001 | fully implemented | Intake/Adapter → CMP-001 |
| S-22 | UNIT-001 | fully implemented | Agent Worker → CMP-002 (input-size bound, FR-21/A-9) |
| S-23 | UNIT-001 | fully implemented | cross-cutting inside the unit: Intake/Adapter → CMP-001 (Slack rate limits) + AWS Knowledge MCP Client → CMP-004 (MCP backpressure) |
| S-24 | UNIT-001 | fully implemented | Job/State → CMP-006 + Agent Worker → CMP-002 (independently-scaled worker role, Q3/NFR-10) |
| S-25 | UNIT-001 | fully implemented | Intake/Adapter → CMP-001 (captures 👍/👎) |
| S-26 | UNIT-001 | fully implemented | Operational Data → CMP-007 (records signal) |
| S-27 | UNIT-001 | fully implemented | Operational Data → CMP-007 + Agent Worker → CMP-002 (records after processing) |

## Per-Unit Story Assignment

### Slack DevOps Agent (UNIT-001)

Owns all 27 stories. Grouped by the internal module primarily responsible (a story may
touch more than one module — see the coverage matrix for the full mapping).

| Internal module → component(s) | Stories | What the unit implements |
|---|---|---|
| Intake/Adapter → CMP-001 | S-1, S-2, S-6, S-14, S-21, S-25 (+S-23 Slack side) | Mention capture, immediate ack within NFR-1, posting answers/failures, allowlist filtering, bot-message ignore, reaction capture, Slack rate-limit handling |
| Agent Worker → CMP-002 (+ CMP-004, CMP-005) | S-3, S-4, S-5, S-7..S-13, S-16, S-19, S-22, S-27 (+S-23 MCP side) | The agent loop: inference, MCP grounding + citations, the four answer capability variants, detailed answer composition, thread follow-up, pre-send safety gate, graceful failure, input-size bound, usage recording |
| Inference Provider library → CMP-003 | S-3 | Backend-agnostic inference behind a stable interface (A-1 swap), built/tested in isolation (Q4) |
| Job/State → CMP-006 | S-19, S-20, S-24 | ProcessingJob state machine, at-most-once-completed de-dup, in-flight recovery, concurrency without head-of-line blocking |
| Operational Data → CMP-007 | S-18, S-26, S-27 | Cost-usage counter + within-budget decision, feedback-signal capture, adoption metrics |
| Configuration & Policy → CMP-008 | S-15, S-17, S-18 | Channel allowlist, published usage policy, cost-guardrail thresholds |

## Coverage Gaps

None — every story S-1..S-27 is owned by UNIT-001 (the single unit), and every story
traces to at least one internal module/component. The domain-design coverage matrix
already confirmed every FR-1..FR-21 and the NFR placements map to ≥1 component; since
all components are in UNIT-001, that coverage is preserved at the unit level.

| Story/Requirement | Gap | Resolution |
|---|---|---|
| — | — | — |

> Cross-cutting NFRs handled as acceptance criteria across stories (NFR-2, NFR-5,
> NFR-6 per `stories.md`) remain cross-cutting *within* UNIT-001 — they are unit-wide
> qualities, not unowned work.
