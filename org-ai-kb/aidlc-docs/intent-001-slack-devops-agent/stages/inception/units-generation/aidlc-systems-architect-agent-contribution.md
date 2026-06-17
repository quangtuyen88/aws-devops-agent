# Systems Architect Contribution — Units Generation

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Contributor: aidlc-systems-architect-agent
Role: systems thinking and architectural soundness of the **packaging** decision —
unit boundaries, dependency directions, the intake/worker scaling reconciliation, and a
clean hand-off into the design stages I own downstream (functional-design, nfr-design,
infrastructure-design).
Reviewed artifacts: `units.md`, `unit-dependencies.md`, `unit-story-map.md`,
`components.yaml` (Unit ownership added); cross-checked against `questions.md` (human
answers Q1=a/Q2=a/Q3=b/Q4=a, 2026-06-17T11:39:24+08:00), domain-design
`components.yaml`/`components.md`, the domain-design architecture review, my own
domain-design contribution (DA-1..DA-7), and `requirements.md` (NFR-1/2/8/10, C-1, A-1/A-5).

## Verdict

**Packaging decision is architecturally sound, traceable, and ready to advance.** One
deployable unit (UNIT-001, single artifact) with the C-1 intake→worker boundary as an
*internal* seam is the correct call for a single-team (Q2=a), single-workspace internal
tool (A-5): it keeps build/deploy/ops cost minimal while leaving the worker cleanly
extractable along a boundary that is already drawn. The Q1=a vs Q3=b tension (one unit,
independently-scaled worker) is real and the owner reconciled it correctly — independent
*scaling* does not require a separate *deployable* unit. Component IDs, behaviours,
dependencies, and entities are preserved verbatim; story coverage (S-1..S-27) is
complete and S-23/NFR-7 is now correctly placed as cross-cutting within the unit
(closing the domain-design F-1 traceability gap at the unit level).

The findings below are **not blockers** and do not change the unit count. One (UG-1,
the C-1 seam wording) is a small in-place precision fix worth making **now** because the
current phrasing could mislead infrastructure-design into a choice that breaks NFR-10
and CS-2. The rest are systems consequences of the Q3=b decision that I will carry into
the stages I own — recorded here so they are not discovered late.

---

## 1. What the packaging gets right (validation)

- **Fewer-units-until-justified, applied correctly.** Q2=a (one team, one cadence) and
  A-5 (single workspace) give no team-ownership or independent-deploy driver, so the only
  technical argument for a split — the divergent NFR-1 intake vs NFR-2/NFR-10 worker
  profile — is reconciled *within* the unit rather than paid for with a cross-unit
  contract, a network hop, and doubled observability surface. Right trade-off, made
  explicit. ✓
- **The C-1 boundary is preserved as a real extraction seam, not erased.** Folding the
  async boundary inside UNIT-001 does not collapse it — the component boundaries still sit
  on the seam, and FUT-1/FUT-3 in `unit-dependencies.md` are the correct trigger list to
  reinstate `contract-design` if the worker is later lifted out. This keeps today's
  simplicity without foreclosing tomorrow's split. ✓
- **A-1 inference seam handled at the right granularity (Q4=a).** CMP-003 as a distinct
  buildable *library module* with a stable interface — not a separate deployable unit — is
  exactly the de-risking shape I asked for at domain-design: swappable Kiro↔Bedrock,
  testable in isolation, zero deployment ceremony. The single build-time edge (INT-6)
  is correctly the only compile-order constraint among the internal modules. ✓
- **State is externalised; workers stay stateless.** CMP-002/003/004/005 hold no durable
  state; all shared state is CMP-006/007. This is the correct shape for NFR-10 horizontal
  worker scaling — confirmed it survived the packaging step. ✓
- **Story coverage complete and S-23 resolved.** All 27 stories map to UNIT-001 with
  internal-module traceability; S-23 (NFR-7) is placed cross-cutting on Intake/Adapter +
  MCP Client, which is the fix the domain-design reviewer (F-1) asked for. ✓

---

## 2. Systems findings (UG-1 in-place now; UG-2..UG-4 carry into design stages)

### UG-1 — The C-1 seam is *internal* but must NOT be *in-process* (recommend in-place wording fix)
`units.md` (Packaging Decision) describes the C-1 boundary as "an **in-process**/in-artifact
queue handoff." This conflates two different things and, if read literally by
infrastructure-design, breaks the design:
- An **in-process / in-memory** queue cannot survive a worker crash → it defeats **CS-2
  in-flight recovery** (a lost worker would silently lose the job — the exact pain point
  the personas call out).
- An in-process queue also forces intake and worker into one process → it defeats **Q3=b /
  NFR-10 independent worker scaling**, the very thing this stage committed to.

"Internal" here must mean **"not a cross-unit contract,"** *not* "in-memory." The C-1 queue
must be a **durable, out-of-process queue** (infrastructure consumed by the unit) even
though both roles ship from one artifact. Note `unit-dependencies.md` already gets this
right — INT-4 says "internal queue seam (… not a synchronous call)" and the boundaries
list calls the queue "infrastructure consumed by the unit." Only the `units.md`
parenthetical is imprecise, and it contradicts that boundaries line.
- **Recommendation (one-line, owner, now):** reword the `units.md` parenthetical to e.g.
  "an internal seam — a durable out-of-process queue that is internal to the unit (not a
  cross-unit contract), distinct from the in-process calls between modules within a role."
  This removes the only statement that could send infra-design toward an in-memory queue.

### UG-2 — "Single deployable unit" ≠ "single running process" (pin for infrastructure-design)
The Q1=a + Q3=b reconciliation means UNIT-001 is **one buildable/releasable artifact
deployed in 2+ runtime roles** (always-on intake role + horizontally-scaled worker role),
not one process. "One release cadence" (Q2=a) is a property of the *artifact version*, not
of *co-deployment*. This is sound and `units.md` states the two-role intent — but the
"modular monolith" label invites a single-process reading.
- **Recommendation:** infrastructure-design must treat UNIT-001 as **one artifact, multiple
  role deployments sharing a version**, and is free to scale (and even deploy) the worker
  role independently of intake. Recording so "one unit" is not silently read as "one
  Lambda / one process," which would re-break Q3=b.

### UG-3 — Independent worker scaling makes DA-2 and DA-3 correctness-critical, not optional
The packaging makes the shared durable state (CMP-006 `ProcessingJob`, CMP-007
`UsageCounter`) the **single contention point** between N concurrent worker instances —
`unit-dependencies.md` FUT-3 flags this correctly. The systems consequence: the
domain-design concerns I raised are no longer "nice to pin later" — committing to Q3=b
*requires* them:
- **DA-2 (cost guardrail TOCTOU):** read-then-act "within budget?" cannot hold under
  concurrent workers; needs reserve-then-settle on `UsageCounter`, or NFR-8 is explicitly
  declared a soft/best-effort bound.
- **DA-3 (job claim race):** seen→in-progress must be a **compare-and-set / conditional
  write** on `ProcessingJob.status`, or two workers double-process one job (CS-3 violated).
- **Recommendation:** functional-design + nfr-design must resolve DA-2/DA-3 with a stated
  consistency model on the shared store; "scale workers independently" is not safe without
  it. No unit change — this is a hand-off note the Q3=b decision now makes mandatory.

### UG-4 — Terminology: prefer "single deployable artifact, multi-role runtime" over "modular monolith" (minor)
The artifact's substance is right; only the label is slightly misleading given the
two-role/independent-scaling reality (see UG-2). A true modular monolith is usually one
process. Optional clarity improvement; no decision changes.

---

## 3. Hand-off summary for the stages I own next

- **functional-design:** DA-3 (CAS on `ProcessingJob.status`; intake register/ack/enqueue
  ordering), DA-6 (distinct reason codes: guardrail-denied vs dependency-failed vs
  oversized), the CS-4/CS-5 pipeline contract, and the UG-1 correlation-id (already on
  ENT-001/ENT-004) propagated across the C-1 queue for end-to-end tracing.
- **nfr-design:** DA-2 (hard reserve-then-settle vs explicit soft cap, A-7 thresholds),
  DA-5 (cache CMP-008 config reads in the NFR-1 3s ack path), DA-7 (agent-loop iteration
  + timeout budget must *include* retries), and the worker concurrency model for NFR-10.
- **infrastructure-design:** UG-1 (durable out-of-process C-1 queue — not in-memory),
  UG-2 (one artifact / multiple role deployments / independent worker scaling mechanism),
  DA-4 (CS-2 recovery trigger: queue visibility timeout and/or reaper), the CMP-006/007
  shared store + consistency model (DA-2/DA-3 enforcement point, two CMP-007 access
  profiles), and A-1 backend selection behind the CMP-003 library interface.

---

## 4. Items explicitly NOT changing

- No objection to the unit count, boundaries, dependency directions, internal-module
  structure, or component/entity ownership — single-unit (UNIT-001) is the correct
  packaging and I endorse it. `contract-design` correctly stays skipped.
- UG-1 is the only suggested **in-place** edit (a one-line wording precision fix in
  `units.md`); UG-2..UG-4 are downstream design notes for stages I own and do not require
  reworking `units.md`, `unit-dependencies.md`, `unit-story-map.md`, or `components.yaml`.
- `components.yaml` faithfully copies domain-design forward with `Unit:` ownership only —
  IDs/behaviours/dependencies/entities preserved verbatim, no domain drift. Do not rework.
- Story coverage matrix and the FUT-* extraction-trigger list are sound as written.
