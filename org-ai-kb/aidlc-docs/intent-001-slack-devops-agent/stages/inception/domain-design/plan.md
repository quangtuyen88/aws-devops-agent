# Domain Design — Plan

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Stage: `domain-design` (inception) · Owner: aidlc-app-architect-agent
Status target on completion of this step: `clarification-asked`

## Goal of this stage

Identify the logical building blocks (components) of the system from
`requirements.md` (FR-1..FR-21, NFR-1..NFR-10) and `stories.md` (S-1..S-27),
define their boundaries, dependency directions, and the entities each owns.
This stage does **not** decide deployment topology — that is `units-generation`
(the design is assumed to be a single deployable unit per A-4/C-4, but components
are identified independently of that).

## Inputs used

| Input | Source artifact | Resolution |
|---|---|---|
| Requirements (Required) | `requirements.md` | Present — primary driver |
| Stories (context) | `stories.md` | Present — used for behaviour + the cross-story architectural notes CS-1..CS-6 |
| Contributor architecture notes | `aidlc-systems-architect-agent-contribution.md` (in requirements + story stages) | Present — C-1..C-4 constraints folded into component reasoning |
| RE artifacts | — | Skipped stage (greenfield, A-4). Nothing to infer; no existing code. |

No upstream stage that this stage depends on was skipped in a way that forces
inference: `requirements.md` and `stories.md` both exist and are complete.

## Candidate component catalogue (baseline — to be confirmed via questions.md)

This is the working decomposition the plan will refine after clarification. IDs
are stable for downstream traceability.

| ID | Working name | Core responsibility | Key FRs/stories |
|---|---|---|---|
| CMP-001 | Slack Interaction Adapter | Slack intake + outbound: event validation, mention parse, allowlist filter, bot-message filter, retry de-dup detection, ack + answer posting, reaction capture | FR-1,2,3,14,16,19,20 / S-1,2,6,14,21,25 |
| CMP-002 | Agent Orchestrator (agent core) | Async worker loop: fetch thread context, run safety gate, iterate inference+MCP under a tool-call cap, compose detailed answer, resolve failures | FR-4,5,6,8,17 / S-3,4,12,13,19, CS-5,CS-6 |
| CMP-003 | Inference Provider | Pluggable LLM/SLM abstraction over Kiro (fallback e.g. Bedrock) | FR-5 / S-3 / A-1 |
| CMP-004 | AWS Knowledge MCP Client | Call `aws-knowledge-mcp-server` tools; return citable sources | FR-6,7 / S-4,5 / A-2 |
| CMP-005 | Input Safety Scanner | Detect secrets/credentials; gate before inference/MCP | FR-15 / S-16 / NFR-4 / CS-4 |
| CMP-006 | Job Coordinator | Async job lifecycle (seen/in-progress/resolved), at-most-once-completed de-dup, in-flight recovery, concurrency | FR-19 / S-19,20,24 / C-1,C-4 / CS-2,CS-3 |
| CMP-007 | Operational Data Service | Durable aggregate store: adoption metrics, feedback signals, cost-usage counters | FR-16,18 / NFR-8 / S-18,26,27 / CS-1 |
| CMP-008 | Configuration & Policy | Channel allowlist, usage policy, guardrail thresholds (operator-facing) | FR-2 / NFR-3 / S-15,17,18 |

Infrastructure (NOT components — dependencies of the above): Slack API, the
Kiro/Bedrock endpoint, `aws-knowledge-mcp-server`, the message queue, and the
durable datastore (e.g. DynamoDB) behind CMP-007/CMP-006.

The open decomposition decisions (granularity, where the safety gate / job
state / cost guardrail / config live, how to model the queue) are deferred to
`questions.md` — they materially change which components exist and who owns
which entities.

## Steps

- [x] 1. Confirm decomposition decisions via `questions.md` (granularity, safety-gate placement, async job/queue modeling, shared-state ownership, cost-guardrail placement, config placement). → Human answered "agree to all" (2026-06-17T10:25:36+08:00); balanced 8-component catalogue confirmed.
- [x] 2. Finalise the component list and stable IDs based on answers. → CMP-001..CMP-008 fixed.
- [x] 3. For each component, define: behaviour-summary, responsibilities, explicit boundaries (what it does NOT own), and Source (FR/story refs).
- [x] 4. Map dependencies and dependent-components for each component (direction + interaction reason); verify no circular dependencies and that the CS-4 ordering (safety gate before inference/MCP) is expressible. → Acyclic DAG; intake→worker handoff is async via queue (infra), so no CMP-001→CMP-002 sync edge.
- [x] 5. Identify owned entities per component with attributes; ensure every entity has exactly one owner (resolve CS-1 shared-state ownership explicitly). → ENT-001..ENT-014; de-dup in ProcessingJob (CMP-006), aggregate state in CMP-007.
- [x] 6. Write `components.yaml` (machine-readable source of truth) from the template.
- [x] 7. Derive `components.md` (mermaid component diagram + summary table + rationale) from `components.yaml` — must match the YAML.
- [x] 8. Validate against domain-modeling + units-decomposition skills: each component understandable independently, ownership unambiguous, dependency directions intentional, no infrastructure modeled as a component.
- [x] 9. Register all outputs in `state.json` and set stage status to `artifact-generated`.

## Validation checklist (applied at step 8)

- [x] No database / queue / cache / external service is modeled as a component.
- [x] Every entity has exactly one owning component (CS-1 resolved).
- [x] Dependency directions are explicit; no cycles.
- [x] Secret-scan gate (CS-4) precedes inference (CMP-003) and MCP (CMP-004) in the dependency flow.
- [x] De-dup is expressible as at-most-once *completed* processing, not at-most-once *seen* (CS-3).
- [x] `components.md` is consistent with `components.yaml` (YAML wins on conflict).
- [x] Every component traces to ≥1 FR/story; every FR/story is covered by ≥1 component.

## Refinement pass (contributor feedback — 2026-06-17)

Owner refinement against `aidlc-systems-architect-agent-contribution.md` (status → `refined`).

- [x] R1. Read the systems-architect contribution (DA-1..DA-7 + minor notes).
- [x] R2. Apply DA-1 in place: add `correlation-id` (canonical request id == `ProcessingJob.job-id`) to `InboundMention` (ENT-001) and `Answer` (ENT-004) in `components.yaml`; reflect in `components.md` ownership table.
- [x] R3. Record disposition of DA-2..DA-7 as downstream design notes (no component change — boundaries/ownership endorsed by the contributor) in a new `components.md` "Refinement" section and expand "Notes for downstream stages" so each finding is carried to its owning stage (functional-/nfr-/infrastructure-design).
- [x] R4. Verify components.md ↔ components.yaml still consistent after edits; no new component, no boundary or dependency-direction change.
- [x] R5. Register modified outputs and set stage status to `refined` in `state/state.json`.
