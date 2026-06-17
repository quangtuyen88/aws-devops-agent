# Functional Design — Product Manager Contribution

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `functional-design` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-systems-architect-agent · Contributor: **aidlc-product-manager-agent**.
>
> Role: voice of the customer/business. I checked that every design element traces back
> to a stated requirement (FR/NFR/CS/A/OOS), that no design element exists without a
> requirement basis, and that the modelled behaviour reflects real user value and the
> persona pain points in `story-generation/personas.md`. Source-of-truth artifacts read:
> `entities.yaml`, `rules.yaml`, `api-specification.md`, `functional-spec.md`,
> `unit.md`, `unit-story-map.md`; upstream `requirements.md`, `stories.md`, `personas.md`.

---

## Verdict

**Strong, traceable artifact set — contribute with findings.** Every FR-1..FR-21 and
NFR-1..NFR-10 maps to ≥1 entity/rule/workflow, the four design forks (Q1–Q4) were
resolved coherently, and no rule or entity was found that lacks a requirement basis
(no scope creep). The findings below are **3 substantive** items that affect a stated
requirement or a persona pain point, plus **5 minor** notes. None blocks the stage; F-1,
F-2, F-3 should be resolved (or explicitly accepted) before code-generation.

---

## Traceability check (positive confirmation)

- **FR → rule/entity/workflow coverage:** confirmed complete via the `unit-story-map.md`
  "Functional Coverage Expansion" table cross-referenced against `requirements.md`. Each
  of FR-1..FR-21 resolves to a concrete BR-* + workflow; NFR-1..NFR-10 are carried as the
  cross-cutting table (NFR-1→BR-004, NFR-4→BR-012 hard gate, NFR-6→BR-026, NFR-8→BR-008/019, etc.).
- **No orphan design elements:** every entity (ENT-001..014) and rule (BR-001..026) carries
  a `source:` block tracing to FR/NFR + stories. Spot-checked ENT-010, ENT-014, BR-012,
  BR-020 — all grounded. No invented capability.
- **OOS boundaries preserved:** OOS-3 (BR-017 advice-only), OOS-4/A-8 (BR-005 fetch-not-store,
  ENT-003 "MUST NOT be written to durable store"), OOS-5 (single workspace) all retained in
  `unit.md` boundaries. ✓
- **Refinements (Q2/Q3/Q4) flagged, not silent:** ENT-008.status and ENT-010 changes are
  explicitly marked `REFINEMENT vs blueprint`. Good discipline — no blueprint drift.

---

## Substantive findings

### F-1 (Medium) — Success-metric correctness: feedback aggregation key cannot represent a developer holding both 👍 and 👎

**Where:** `entities.yaml` ENT-010 (FeedbackSignal), `rules.yaml` BR-020, `functional-spec.md` W4.4.
**Requirements touched:** FR-16 (capture helpfulness), FR-18 (success metric).

BR-020 aggregates "latest row per **(answer-ref, reactor-id)** by recorded-at; a latest
`removed` row = withdrawn." The aggregation key collapses both emoji into a single
per-reactor signal. But Slack lets one user place **both** 👍 and 👎 on the same message
simultaneously, and remove them independently. Concrete failure:

1. Dev adds 👍 → append `(added, positive)`.
2. Dev adds 👎 → append `(added, negative)`; latest row = negative.
3. Dev removes 👎 → append `(removed, negative)`; **latest row = removed ⇒ signal withdrawn** —
   even though the 👍 is still present in Slack.

The metric reports "no signal" when the true state is 👍. This misreports the FR-18 success
metric — the bot's primary value KPI for the team.

**Recommendation (product intent):** key the latest-per aggregation on
**(answer-ref, reactor-id, signal)** so an `added/removed` pair is resolved per emoji, then
derive the reactor's net signal (e.g. positive-and-not-withdrawn). This is a one-field change
to BR-020's aggregation logic; ENT-010 already carries `signal` + `event-action` to support it.
If the team prefers to keep the simpler key, state the accepted limitation explicitly
("a dev's mixed/removed reactions may under-count signal") so the metric is read honestly.

---

### F-2 (Medium) — Question-type classification is unmodelled, yet BR-015 branches on it

**Where:** `rules.yaml` BR-015; `entities.yaml` ENT-004 (Answer).
**Requirements touched:** FR-8 (structured answer), FR-9/FR-10 (arch-review / solution-design),
FR-11 (cost), FR-12 (troubleshooting).

BR-015 reads: "IF the question is **architecture-review or solution-design** THEN Answer MUST
include recommendation + rationale + trade-offs + alternative … ELSE recommendation + rationale
required." This rule depends on classifying the inbound question into a type, but **nothing in
the functional model captures that classification** — ENT-001 (InboundMention) and ENT-004
(Answer) have no `question-type` / `answer-type` attribute, and no workflow step assigns one.
As written, BR-015 is not mechanically verifiable: a reviewer/implementer cannot tell when the
"MUST include trade-offs + alternative" branch fires.

This also leaves FR-11 (cost) and FR-12 (troubleshooting) covered only by the generic ELSE
branch (recommendation + rationale). That is an acceptable v1 product decision — but it should be
a **decision**, not an accident of an unmodelled field.

**Recommendation:** either (a) add an `answer-type` (or `question-intent`) enum attribute to
ENT-004 — values e.g. `architecture-review | solution-design | cost | troubleshooting | factual` —
and have W2 set it before composition so BR-015 keys on a real field; or (b) restate BR-015 so
the trade-offs/alternative requirement is conditioned on the *content* of the request in a way
the inference step can self-assess, and document that FR-9/FR-10 detection is best-effort. (a) is
cleaner for traceability and downstream test design.

---

### F-3 (Medium, user empathy) — Default `non-allowlisted-behaviour = silent` contradicts the Developer's stated pain point

**Where:** `entities.yaml` ENT-012.non-allowlisted-behaviour `default: "silent"`; BR-001; W1.5; S-14.
**Requirements touched:** FR-2; persona pain point.

`personas.md` (Developer) lists as an explicit pain point: *"A request that hangs with no
response (silent failure) is worse than a clear error."* S-14 exists precisely to give a
developer *"a clear signal that it only operates in designated channels, so that I'm not left
waiting."* Yet the modelled **default** for an out-of-allowlist mention is `silent`, which
reproduces exactly the "left waiting / is it broken?" experience the persona wants to avoid.

FR-2 permits silent *or* a not-designated reply, so `silent` is in-scope — this is not a
requirements violation. It is a **default-choice** product concern: the safer default for user
trust is `reply-not-designated` (one ephemeral/in-thread line: "I only answer in designated
channels"). Silent should be the opt-in for noise-sensitive channels, not the out-of-box default.

**Recommendation:** flip ENT-012.non-allowlisted-behaviour `default` to `reply-not-designated`,
or record an explicit rationale for defaulting to silent. Low cost, directly serves the S-14
intent and the persona.

---

## Minor notes (non-blocking)

- **M-1 — `failed` is permanently terminal, including budget-deny (BR-011/BR-013).** A question
  denied by the cost guardrail (NFR-8) becomes `failed` forever; even after the budget period
  resets or Slack redelivers, BR-011 (`status IN {resolved, failed} → do nothing`) means the dev
  must re-ask. Reasonable for v1, but the in-thread failure message (BR-013) should tell the dev
  to **re-ask later** so the dead-end is not silent-by-another-name. Suggest noting the required
  message intent for budget-deny in W3 / BR-008.

- **M-2 — Adoption "questions-handled" counts only `resolved` (ENT-009 constraint, BR-019).**
  Failed/denied questions are excluded from the FR-18 adoption count. This under-reports *demand*
  (a developer who asked and got a failure still adopted the bot). Acceptable against FR-18's
  literal "served" wording, but flag it so the metric is read as "successfully answered," not
  "total asks." A separate attempt counter is cheap if demand visibility matters later.

- **M-3 — FR-16 "(or equivalent control)" narrowed to reactions only.** The functional model
  captures only 👍/👎 reactions (ENT-002, API-EXT-005); the requirement's "or equivalent control"
  (e.g. buttons) is dropped. Reactions satisfy FR-16, so this is fine — just confirm the narrowing
  is intentional for v1 and not an oversight.

- **M-4 — BR-003 trigger wording vs W1 ordering.** BR-003's trigger says "a Slack message event is
  received **in an allowlisted channel**," but W1 evaluates the @mention check (BR-003, step 4)
  *before* the allowlist check (BR-001, step 5). Behaviourally harmless (non-allowlisted mentions
  are stopped at step 5), but the trigger text implies allowlist-first. Align the wording to avoid
  confusing code-generation about the gate order.

- **M-5 — Top-level mention context fetch (ENT-001.thread-ts nullable).** When a mention is a
  top-level channel message, `thread-ts` is null and W2.3 fetches "thread replies." Confirm the
  intended behaviour is "fetch just the originating message as its own context" so there is no
  ambiguity for the implementer (no functional gap, just an explicit note).

---

## Items confirmed as correctly out of scope / deferred (no action)

- Numeric thresholds (NFR-1 ack window, NFR-2 timeout, CS-5 cap, max-attempts, size limit,
  budget limits) correctly deferred to nfr-design (A-7/A-9) — functional design fixed *shape*,
  not numbers. ✓
- Concrete inference backend (Kiro vs Bedrock) correctly behind API-INT-001 (A-1 swap seam),
  deferred to infrastructure-design. The pluggable-provider product requirement (FR-5/S-3) is
  honoured. ✓
- Viewing/reporting of feedback & adoption correctly capture-only this release (Q2=a) — the
  durable aggregate store (A-8) leaves the door open without rework. ✓

---

## Summary for the owner

The artifacts are requirements-complete and traceable with no scope creep. Please address
**F-1** (feedback metric correctness — affects the bot's headline KPI), **F-2** (model the
question/answer type that BR-015 branches on, so the structured-answer requirement is
verifiable), and **F-3** (reconsider the `silent` default against the Developer pain point), or
record an explicit decision for each. M-1..M-5 are polish. With F-1/F-2/F-3 resolved or
consciously accepted, this stage is ready from a product standpoint.
