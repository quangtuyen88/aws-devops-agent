# Functional Design — Plan

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `functional-design` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-systems-architect-agent · Reviewer: aidlc-architecture-reviewer-agent ·
> Contributor: aidlc-product-manager-agent.

## Goal

Detail the **business logic** for all 8 components of UNIT-001 — full entity schemas,
numbered business rules, workflows as step sequences, and the `ProcessingJob` state
machine — technology-agnostic, no code/SQL/framework references. Expand the
copied-forward blueprint in place, preserving every stable ID.

## Inputs Used & Artifact Resolution (fallbacks documented)

| Concern | Artifact used | Notes |
|---|---|---|
| Unit definition | `units-generation/units.md` (UNIT-001) | Single deployable unit, 2-role runtime, internal C-1 seam |
| Component blueprint (copy-forward, source of truth) | `units-generation/components.yaml` | CMP-001..008, ENT-001..014, all dependencies + DA-1 correlation-id refinement |
| Story assignment | `units-generation/unit-story-map.md` | All 27 stories (S-1..S-27) owned by UNIT-001 |
| Requirements / NFRs / constraints | `requirements-analysis/requirements.md` | FR-1..21, NFR-1..10, CS-1..6, A-1..9, OOS-1..5 — re-read during artifact production |
| Detailed story acceptance criteria | `story-generation/stories.md` | Drives workflow steps + rule violation behaviour |
| **contract-design** | **skipped** (single unit) | No cross-unit contracts. `api-specification.md` reinterpreted per Q1 — see questions.md |
| **reverse-engineering** | **skipped** (greenfield) | No existing code to mine; all logic derived from requirements/stories |
| **wireframe-design** | **skipped** | Slack message/interaction shaping folds into the CMP-001 workflows + `api-specification.md` outbound section |

## Open Decisions (block full artifact production until answered)

- **Q1** — `api-specification.md` scope (external surfaces / internal seams / both). *Recommend: both.*
- **Q2** — `ProcessingJob` terminal-state + retry modeling. *Recommend: distinct `resolved`/`failed` terminals, expand enum in place.*
- **Q3** — De-dup identity composition. *Recommend: `channel-id + message-ts`.*
- **Q4** — Feedback signal mutability. *Recommend: append-only, latest-per-reactor aggregation.*

These four are non-blocking for the *structure* of the plan (steps below are stable);
they change specific enum values, one rule, and the api-spec table of contents.

## Steps

### Phase 0 — Clarify
- [x] Read all upstream artifacts (units, components.yaml, unit-story-map, requirements, stories).
- [x] Write `questions.md` (4 design forks) and this `plan.md`.
- [x] Set this stage's status to `clarification-asked` and hand back for human answers.
- [x] On answers: if clear, proceed to Phase 1; if ambiguous, append follow-ups and set `further-clarification`.

### Phase 1 — Entities (`entities.yaml`, source of truth)
- [x] Copy ENT-001..014 forward; for each, add full attribute schema: `type`, `required`, `unique`, `references`, `values` (enums), `default`, constraints — preserving names verbatim.
- [x] Mark durability explicitly (transient vs durable) per the blueprint descriptions; emphasise constraints on the 6 durable entities (ENT-008 ProcessingJob, ENT-009 AdoptionMetric, ENT-010 FeedbackSignal, ENT-011 UsageCounter, ENT-012..014 config).
- [x] Encode the DA-1 `correlation-id` linkage (ENT-001 ↔ ENT-004 ↔ ENT-008.job-id) as a cross-entity constraint/relationship.
- [x] Apply Q2 outcome to `ENT-008.status` enum and Q3 outcome to `slack-event-identity` definition; apply Q4 outcome to ENT-010 cardinality.
- [x] Add relationships (cardinality + direction) where entities reference each other.

### Phase 2 — Business rules (`rules.yaml`, source of truth)
- [x] Number rules BR-001.. with `statement / category / applies-to (CMP+ENT+API) / trigger / logic / violation / source (FR+S)`.
- [x] Cover the constraint-driven rules: CS-4 safety-gate-before-any-send ordering; CS-5 tool-call/timeout cap; CS-3 at-most-once-completed de-dup; CS-2 in-flight recovery + retry/abandon (shape only, count → nfr); CS-6 fetch-not-store; A-8/OOS-4 no cross-session memory; A-2 ground-or-mark-ungrounded; OOS-3 never execute IaC; NFR-6 redacted findings only; NFR-3 usage-policy; NFR-8 within-budget-before-spend; FR-21/A-9 input-size bound.
- [x] Cover the intake rules: FR-2/S-14 allowlist filter (silent vs not-designated per ENT-012), FR-20/S-21 ignore bot/self, FR-3/NFR-1 ack-within-window.
- [x] Cover answer-composition rules: FR-8 required answer fields, FR-13 code-snippets-where-requested, citation presence vs `is-grounded=false`.
- [x] Cover feedback aggregation rule per Q4.

### Phase 3 — State machine + workflows (feed into `functional-spec.md`)
- [x] `ProcessingJob` state machine table (states, events, transitions, guards) per Q2.
- [x] Workflow W1 — Intake & ack (CMP-001): validate → ignore bot/self → allowlist → register/de-dup (CMP-006) → ack → enqueue (C-1).
- [x] Workflow W2 — Async agent processing (CMP-002 worker): dequeue → in-progress → reconstruct context (CMP-001 fetch) → size check → safety gate (CMP-005, CS-4) → within-budget (CMP-007) → inference (CMP-003) + MCP grounding (CMP-004) loop under CS-5 cap → compose answer → post (CMP-001) → record usage/adoption (CMP-007) → resolve.
- [x] Workflow W3 — Failure resolution & in-flight recovery (CMP-002/CMP-006): failure/oversize/budget-deny/worker-loss → failure message → terminal; recovery detects acked-but-incomplete → retry-or-abandon.
- [x] Workflow W4 — Feedback capture (CMP-001 → CMP-007): reaction add/remove → forward → record signal.
- [x] Workflow W5 — Configuration reads (CMP-008): allowlist / usage-policy / guardrail thresholds (read-only consumers).

### Phase 4 — Interface specification (`api-specification.md`, per Q1)
- [x] Per Q1 outcome, document the chosen interface set (recommend: external integration surfaces — Slack inbound event, Slack outbound Web API, inference endpoint, MCP tools — *and* internal module interfaces — CMP-003 stable inference interface, C-1 enqueue, CMP-004/005/006/007 operations).
- [x] For each: purpose, trigger, auth/permission, logical input/output, business rules, entities, errors, versioning. Cross-reference BR/ENT IDs.

### Phase 5 — Human-readable view (`functional-spec.md`)
- [x] Scope table (UNIT-001, CMP-001..008, source stories).
- [x] Mermaid ER diagram reflecting `entities.yaml` (YAML remains source of truth).
- [x] State machine table(s) from Phase 3; workflow step lists W1..W5; rules summary table.

### Phase 6 — Copy-forward expansions (preserve all stable IDs)
- [x] `components.yaml` — expand each CMP with entity-schema refs, rule IDs, workflow/state-machine refs, API refs; **preserve** original IDs/names/dependencies/Unit ownership.
- [x] `unit.md` — copy UNIT-001 definition forward, expand with references to functional artifacts; retain boundaries.
- [x] `unit-story-map.md` — copy forward, expand each story row with functional coverage refs (workflow/rule/entity IDs).

### Phase 7 — Close out
- [x] Verify every FR/NFR/CS and every story S-1..S-27 traces to ≥1 entity/rule/workflow (no coverage regression vs unit-story-map).
- [x] Register every produced file in `state.json` `outputs`; set status to `artifact-generated`.

## Traceability discipline

- Preserve verbatim: all CMP/ENT IDs and names, dependency directions, Unit ownership.
- Any expansion of a blueprint value (e.g. ENT-008 status enum per Q2) is recorded as an explicit **refinement note**, not a silent change.
- Numeric NFR values (timeouts, retry max, CS-5 cap, budget limits) are referenced as named parameters and **deferred to nfr-design (A-7)** — functional-design fixes shape, not numbers.

## Phase 8 — Refinement pass (PM contribution applied) — status `refined`

Addressed `aidlc-product-manager-agent-contribution.md`. All substantive findings resolved
in place; minor notes resolved or documented as conscious decisions.

- [x] **F-1 (feedback metric correctness)** — refined the aggregation key from
  `(answer, reactor)` to `(answer, reactor, signal)` so each emoji is resolved
  independently; a withdrawn 👎 no longer collapses a still-present 👍. Updated `BR-020`,
  `ENT-010` (constraints + reactor-id/event-action/recorded-at notes), `functional-spec.md`
  W4.4 + rules table, `api-specification.md` feedback interface, `unit.md` R-3,
  `components.yaml` refinement log (R-4).
- [x] **F-2 (unmodelled question type)** — added `Answer.answer-type` enum
  (`architecture-review | solution-design | cost | troubleshooting | factual`, default
  `factual`), set in W2 before composition; rewrote `BR-015` to branch on it (verifiable).
  Updated `ENT-004` (+attribute, +FR-9..FR-12 source), `functional-spec.md` W2 step 8 +
  ER diagram + rules table, `components.yaml` ENT-004 attributes + refinement log (R-5).
- [x] **F-3 (silent default vs persona)** — flipped `ENT-012.non-allowlisted-behaviour`
  default `silent → reply-not-designated` (Developer "left waiting" pain, S-14); both values
  remain FR-2-compliant, `silent` is now the operator opt-in. Updated `entities.yaml`,
  `api-specification.md` fail-safe-default example, `components.yaml` refinement log (R-6).
- [x] **M-1** — budget-deny failure message now invites re-asking after the period resets
  (`BR-008`, W3.2).
- [x] **M-2** — documented that `AdoptionMetric.questions-handled` counts answered-not-demand;
  a separate demand counter is deferred (no FR requires it) (`ENT-009`).
- [x] **M-3** — recorded the intentional v1 narrowing of FR-16 "(or equivalent control)" to
  👍/👎 reactions (`ENT-002`).
- [x] **M-4** — aligned `BR-003` trigger wording with the W1 order (mention check precedes
  allowlist).
- [x] **M-5** — clarified that a top-level mention (`thread-ts` null) uses the originating
  message as its own single-message context (`BR-005`).

All stable IDs preserved; every change recorded as an explicit refinement note (R-4..R-6).
No numeric NFR values introduced (still deferred to nfr-design).

### Phase 8.1 — Architecture-review repairs (status `final-review-needed` → final)

Applied after `aidlc-architecture-reviewer-agent` returned NOT READY (see
`aidlc-architecture-reviewer-agent-review.md`):

- [x] **A-1** — repaired `entities.yaml` ENT-004: the F-2 insertion had collapsed
  `answer-type` and `recommendation` into one block with duplicate `type`/`required`/
  `constraints` keys. Restored `answer-type` as a single clean `enum` (with its F-2
  constraints) and re-added `recommendation` (`string`, required, FR-8a) as its own
  attribute.
- [x] **A-2** — re-confirmed `functional-spec.md` ER diagram / W2 step 9 and `rules.yaml`
  BR-015 match the repaired ENT-004 (both `recommendation` and `answer-type` present);
  source-of-truth and derived view are now consistent.
- [x] **B-1** — named the single-writer/idempotent-post requirement at the functional level:
  added `BR-027` and an ENT-008 constraint requiring single-winner entry into `in-progress`
  (lease / compare-and-set) and idempotent answer posting per job identity; concrete
  mechanism remains deferred to infrastructure-design. `functional-spec.md` W2 step 10 and
  the BR table updated.

`entities.yaml`, `rules.yaml`, and `components.yaml` (multi-document) re-validated with a
**strict, duplicate-key-rejecting** YAML loader (PyYAML SafeLoader subclass that raises on
duplicate mapping keys) — all parse clean with zero duplicate keys; BR ids are unique (27,
no duplicates, BR-027 present). `state.json` re-validated as well-formed JSON. No numeric
NFR values introduced (still deferred to nfr-design).
