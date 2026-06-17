# Units Generation — Plan

> Stage: `units-generation` (inception) · Owner: aidlc-app-architect-agent ·
> Reviewer: aidlc-architecture-reviewer-agent · Contributor: aidlc-product-manager-agent
> (state.json lists aidlc-systems-architect-agent as the active contributor for this intent).
> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`).

## Objective

Group the 8 fixed logical components (CMP-001..CMP-008) from domain-design into
deployable **units** with explicit responsibilities, boundaries, dependency
directions, and full story coverage. Components do not change — only their packaging.

## Inputs used (artifact resolution)

| Concern | Artifact used | Notes |
|---|---|---|
| Building blocks (required) | `domain-design/components.yaml` (+ `components.md`) | Source of truth; component IDs/behaviours/deps/entities preserved verbatim. |
| Stories (coverage) | `story-generation/stories.md` | For `unit-story-map.md` (S-1..S-27). |
| Requirements/constraints | `requirements-analysis/requirements.md` | A-4/C-4 (single-unit working assumption), C-1 (mandatory async boundary), NFR-1/2/9/10 (scaling profiles), A-1 (inference seam). |
| Deployment constraints | **human answers to `questions.md`** | Team structure, scaling, ops maturity, packaging — drives the grouping. |

No producing stage was skipped upstream of this one except `contract-design`
(deliberately deferred to here). If the grouping yields 2+ units, contract-design is
reinstated and `unit-dependencies.md` integration points are left for it to fill.

## Steps

- [x] **1. Confirm packaging decision.** Wait for human answers to `questions.md`
      Q1–Q4. Re-read the answers; if ambiguous, append follow-ups and set status
      `further-clarification`. Otherwise record the chosen grouping (single unit vs
      split) and its rationale, tracing to the answers + A-4/C-4/NFR drivers.
- [x] **2. Decide whether `contract-design` is reinstated.** Single unit ⇒ stays
      skipped; 2+ units ⇒ flag for reinstatement and note that integration-point
      contracts are owned by contract-design (leave "Expected Contract" cells pending).
- [x] **3. Produce `units.md`.** Unit inventory table + per-unit details
      (purpose, responsibilities, boundaries, packaging assumption, build
      independence, change rate). Every component CMP-001..CMP-008 assigned to exactly
      one unit; reflect the Q4 decision on the CMP-003 inference seam as a module/library
      boundary within its owning unit.
- [x] **4. Produce `unit-dependencies.md`.** Dependency matrix (build-time / runtime /
      data), build order, parallelisation opportunities, and integration points. For a
      single unit, document the *internal* async boundary (C-1 queue seam) and mark
      cross-unit contracts N/A; for a split, capture the queue + shared-state
      (CMP-006/007/008) integration points.
- [x] **5. Produce `unit-story-map.md`.** Coverage matrix mapping S-1..S-27 to unit(s)
      via the component→story traceability already in components.md; per-unit story
      assignment; confirm the Coverage Gaps table is empty (every story owned).
- [x] **6. Copy forward `components.yaml`.** Copy from domain-design unchanged except
      adding a `unit` ownership reference to each component. Preserve all IDs, names,
      behaviours, dependencies, and entity names verbatim (no domain drift).
- [x] **7. Self-validate** against the units-decomposition skill: each unit
      understandable independently, no circular unit dependencies, dependency
      directions explicit, decomposition supports the stated NFRs (NFR-1 ack vs
      NFR-2/NFR-10 worker), and story coverage complete.
- [x] **8. Register outputs** in `state/state.json` (units-generation `outputs[]`),
      mark these checkboxes done, and set this stage's status to `artifact-generated`.

## Decision drivers carried into this stage

- **C-1 (mandatory async boundary)** — exists regardless of unit count; the only
  question is whether it is *internal* (single unit) or *cross-unit* (split).
- **A-4 / C-4** — prior working assumption is a single deployable unit; this stage
  validates it, it is not binding.
- **NFR-1 (3s ack) vs NFR-2 (30s answer) / NFR-10 (concurrency)** — the divergent
  latency/scaling profiles are the principal technical argument for a possible split.
- **A-1 (inference seam, highest risk)** — must remain a clean swappable boundary
  (Q4); a module/library boundary satisfies this without dictating deployable-unit count.
- **Prioritization:** fewer units until complexity justifies more (units-decomposition
  principle) — split only if team/scaling answers (Q2/Q3) provide a real driver.

## Status

`plan-and-clarify` → after writing `questions.md` + `plan.md`, set
`units-generation.status = clarification-asked` in `state/state.json`.

## Refinement Log — contributor feedback (aidlc-systems-architect-agent)

Contributor verdict: **packaging sound, traceable, ready to advance** — no change to
unit count, boundaries, dependency directions, or component/entity ownership. Findings
addressed:

- [x] **UG-1 (in-place, units.md) — DONE.** Reworded the Packaging Decision so the C-1
      seam reads as a **durable, out-of-process queue internal to the unit** ("internal"
      = not a cross-unit contract, **not** in-memory). Removed the misleading
      "in-process/in-artifact queue handoff" parenthetical that could have steered
      infrastructure-design to an in-memory queue and broken CS-2 recovery + Q3=b/NFR-10
      independent worker scaling. This now aligns `units.md` with INT-4 in
      `unit-dependencies.md` (which already said "internal queue seam … not a synchronous
      call").
- [x] **UG-2 / UG-4 (terminology, units.md) — DONE.** Relabelled UNIT-001 as a "single
      deployable artifact, multi-role runtime" and clarified the Packaging-assumption
      paragraph: one artifact / one release cadence but 2+ runtime roles sharing the
      version, with the worker role independently scalable/deployable. Prevents "one unit"
      being read as "one process / one Lambda," which would re-break Q3=b. "Modular
      monolith" is kept only as a code-structure descriptor with that explicit caveat.
- [ ] **UG-3 (carry-forward, NOT a units.md change) — acknowledged, no edit.** DA-2 (cost
      guardrail TOCTOU → reserve-then-settle or explicit soft cap) and DA-3 (job-claim race
      → compare-and-set on `ProcessingJob.status`) become correctness-critical under
      independent worker scaling. These are resolved in **functional-design / nfr-design**,
      which the contributor owns; `unit-dependencies.md` FUT-3 already flags the shared
      durable state (CMP-006/007) as the contention point and defers the consistency model
      to infrastructure-design. No units-stage artifact change is warranted — packaging
      does not decide consistency models. Left as a downstream hand-off, as the contributor
      intended.

Artifacts changed in refinement: `units.md` only. `unit-dependencies.md`,
`unit-story-map.md`, and `components.yaml` were endorsed verbatim by the contributor and
are unchanged.
