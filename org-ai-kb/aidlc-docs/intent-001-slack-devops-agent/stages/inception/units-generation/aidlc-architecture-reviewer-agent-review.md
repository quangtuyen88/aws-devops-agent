# Architecture Review — Units Generation

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `units-generation` (inception) · Reviewer: aidlc-architecture-reviewer-agent.
> Reviewed (verbatim, from disk): `units.md`, `unit-dependencies.md`,
> `unit-story-map.md`, `components.yaml`, `plan.md`, `questions.md`,
> `aidlc-systems-architect-agent-contribution.md`, and `state/state.json`.
> Cross-checked against domain-design `components.yaml` claims, the human answers
> (Q1=a / Q2=a / Q3=b / Q4=a, 2026-06-17T11:39:24+08:00), and the
> units-decomposition / architecture-review principles.

## Verdict: **READY**

The packaging decision is sound, traceable to the human answers, internally
consistent across all four artifacts, and correctly scoped to a conceptual stage
(no premature runtime/infra decisions). The contributor's one in-place edit (UG-1)
was applied. All findings below are **observations / non-blocking** — none change the
unit count, boundaries, or ownership, and none require rework before advancing.

---

## What I verified (not taken at face value)

1. **Every component is assigned to exactly one unit.** Confirmed in `components.yaml`:
   CMP-001..CMP-008 each carry `Unit: "UNIT-001"`. No component is unassigned or
   double-assigned. ✓
2. **The internal dependency matrix is accurate, not approximated.** I cross-checked
   INT-1..INT-12 against each component's `Dependency` block in `components.yaml`:
   - CMP-001 → CMP-008/006/007 ⇒ INT-1/2/3 ✓
   - CMP-002 → CMP-001/005/007/003/004/006/008 ⇒ INT-10/5/8/6/7/9/11 ✓
   - CMP-007 → CMP-008 ⇒ INT-12 ✓
   - INT-4 (CMP-001→CMP-002) is the **C-1 async enqueue**, correctly represented as the
     queue seam rather than a synchronous edge — matching the components.yaml note that
     no component lists CMP-002 as a synchronous dependency. ✓
   No edge is invented and none is dropped.
3. **The intake↔worker cycle is correctly broken.** INT-4 (async, CMP-001→CMP-002) and
   INT-10 (sync, CMP-002→CMP-001) would be a cycle under synchronous-coupling reasoning;
   the artifact correctly notes INT-4 is the deliberate async seam, so the runtime
   coupling graph stays acyclic. Sound at this abstraction level. ✓
4. **Build order is justified.** Only INT-6 (worker compiles against the CMP-003
   library interface, Q4=a) is a build-time edge; all others are runtime in-process
   calls. The "interface first, then parallel" claim is correct. ✓
5. **UG-1 (the one in-place fix) actually landed.** `units.md` now describes the C-1
   seam as a **durable, out-of-process queue internal to the unit**, with an explicit
   "internal = not a cross-unit contract, **not** in-memory" clarification tied to CS-2
   recovery and Q3=b/NFR-10 scaling. The misleading "in-process/in-artifact queue
   handoff" phrasing is gone; "in-memory" now survives only inside its own negation.
   This aligns `units.md` with INT-4 in `unit-dependencies.md`. ✓
6. **UG-2/UG-4 terminology fix landed.** UNIT-001 is framed as a "single deployable
   artifact, multi-role runtime"; "modular monolith" is retained only as a code-structure
   descriptor with the explicit "**not** a single process" caveat. The one-artifact /
   one-cadence / multi-role-deploy distinction is stated clearly enough that
   infrastructure-design cannot reasonably read "one unit" as "one process." ✓
7. **`contract-design` skip is justified and reversible.** Single unit ⇒ no cross-unit
   contract; the FUT-1/FUT-2/FUT-3 trigger list correctly records what would reinstate
   it if the worker is later extracted along the C-1 seam. ✓
8. **State write contract satisfied.** All 7 stage outputs are registered in
   `state/state.json` with correct `locationRelativeToIntentRoot`; status is `refined`;
   the contribution is recorded. ✓

---

## Findings (non-blocking observations)

### OBS-1 — S-23 traceability lives only in the story map, not in `components.yaml`
S-23 (NFR-7 rate-limit / backpressure) does **not** appear in any component's
`Source.Stories` in `components.yaml` (verified by search), yet `unit-story-map.md`
maps it as cross-cutting onto CMP-001 (Slack rate limits) + CMP-004 (MCP backpressure).
This is the deliberate resolution of the domain-design F-1 traceability gap, and it is
**correctly handled at the unit level** — adding S-23 to a component's `Source` here
would be domain drift, which this stage must not introduce. So the right call was made.
The residual is that `components.yaml` and `unit-story-map.md` disagree on S-23 in
isolation; anyone reading only `components.yaml` would not see S-23 covered.
- **Recommendation (optional, downstream):** functional-design should fold S-23/NFR-7
  into the affected components' acceptance criteria so the gap is closed in a producing
  artifact, not only in the unit story map. No units-stage change warranted.

### OBS-2 — Unit-inventory table cell still leads with "Modular monolith:"
`units.md` line 66 (Unit Inventory → Packaging Assumption cell) leads with
"Modular monolith: …" — the exact label UG-4 cautioned can be misread as single-process.
The same cell immediately clarifies "independently-scalable worker role," and the
surrounding prose carries the full "single deployable artifact, multi-role runtime"
framing, so the risk is low. Cosmetic only.
- **Recommendation (optional):** lead the cell with "Single deployable artifact,
  multi-role runtime (modular monolith by code structure)" for consistency with the
  refined prose. Not required.

### OBS-3 — Stale persona note in `plan.md` header
`plan.md` header lists the contributor as "aidlc-product-manager-agent" then parenthetically
corrects to the systems architect. `state.json` and the actual contribution file both
agree the contributor is `aidlc-systems-architect-agent`, so there is no functional
ambiguity. Cosmetic doc hygiene only.

---

## Concerns correctly deferred (not defects at this stage)

- **UG-3 (DA-2 cost-guardrail TOCTOU; DA-3 job-claim race).** Independent worker
  scaling (Q3=b) makes the shared `UsageCounter`/`ProcessingJob` state a real contention
  point. The owner correctly left this as a functional-/nfr-/infrastructure-design
  hand-off (recorded in `unit-dependencies.md` FUT-3 and the contributor's §3), rather
  than forcing a consistency-model decision into a packaging stage. Per the
  architecture-review principle on early-stage artifacts, this is a deferred concern,
  not a gap. **It must not be lost** — the downstream notes are the safeguard; I confirm
  they are present and specific.
- **Runtime mechanism** (Lambda vs container, which queue, which datastore, the concrete
  worker autoscaling mechanism, A-1 backend selection) — all correctly deferred to
  infrastructure-design. No premature technical commitment was made. ✓

---

## Summary

Single-unit (UNIT-001) packaging is the correct, well-justified call for a single-team
(Q2=a), single-workspace (A-5) internal tool, and the Q1=a vs Q3=b tension is reconciled
soundly (independent *scaling* without a separate *deployable* unit, C-1 preserved as a
clean extraction seam). Component identity, dependency directions, and entities are
preserved verbatim from domain-design with only `Unit:` ownership added — no domain
drift. Story coverage is complete. The three observations above are cosmetic or
downstream and do not gate advancement.

**Stage is ready to advance.**
