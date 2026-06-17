# Plan — Story Generation

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Owner: aidlc-product-manager-agent
Output artifacts:
- `personas.md` (template at `.kiro/stages/story-generation/templates/personas.md`)
- `stories.md` (template at `.kiro/stages/story-generation/templates/stories.md`)

## Inputs used

- `requirements.md` (primary source) — 21 FRs, 10 NFRs, 9 assumptions (A-1..A-9),
  6 out-of-scope (OOS-1..OOS-6), and design constraints C-1..C-4. Every story traces back here.
- `intent.md` — verbatim prompt and user framing (the "Developer" actor).
- `workflow.json` — confirms greenfield, single deployable unit, supervised autonomy.
- Clarification answers to Q1–Q2 in `questions.md` (pending human response).
- `aidlc-systems-architect-agent` contribution — expected **after** artifact-generated
  (per the workflow order), so produced without it; will refine if it raises gaps.

### Artifact resolution / fallbacks

- `reverse-engineering` **skipped** (fully greenfield) — no prior stories to copy forward.
- `wireframe-design` **skipped** — Slack is the interface; no screen-flow stories. Slack
  message/interaction shaping folds into functional-design, so stories stay at the
  behaviour level (what the user/system does), not screen level.
- This is the first stage to produce stories; nothing to copy-forward. Stories are built
  fresh from `requirements.md`, preserving FR/NFR IDs for traceability.

## Decomposition method (decisions I make per the story-decomposition skill — not asked)

- **Granularity:** one story per distinct, separately-testable capability. The in-scope
  question types (FR-9 architecture review, FR-10 solution design, FR-11 cost, FR-12
  troubleshooting, FR-13 IaC snippets) become **separate user stories** — each has distinct
  acceptance criteria — rather than one "ask anything" story.
- **System stories** (As the [service], when [trigger], it must [behaviour]) for the
  architectural/behavioural requirements with no human actor: FR-3 ack, FR-4 thread memory,
  FR-5 inference routing, FR-6/FR-7 MCP grounding+citations, FR-17 failure handling,
  FR-19 event de-dup (C-1), FR-20 bot-loop ignore, FR-21 input bound (C-2). C-1/C-4 async
  intake→worker boundary surfaces as system-story acceptance criteria.
- **NFRs** become cross-cutting acceptance criteria attached to the relevant stories, plus a
  small number of dedicated system stories where an NFR is itself a behaviour (e.g. NFR-7
  rate-limit handling, NFR-10 concurrency / no head-of-line blocking).
- **Ordering / prioritisation (prioritisation skill):** all 21 FRs are v1 (per requirements
  audit), so no story is deferred. Within v1, stories are ordered **risk-first / core-first**:
  the thin vertical slice (mention → ack → ground via MCP → infer → cited answer → post)
  comes first as the highest value+risk path; capability variants and feedback/metrics follow.
  This ordering is guidance for design/build, not a scope cut.
- **Edge/error cases** (oversized input, inference/MCP failure, secret-laden input, duplicate
  events) are their own stories, not buried in happy-path stories.

## Steps

- [x] 1. Received human answers — Q1=a (add lightweight Platform Operator), Q2=a (capture-only).
        Both clear; proceeded without follow-ups.
- [x] 2. Wrote `personas.md`: **Developer** + **Platform Operator** (Q1=a). Each lists its S-ids.
- [x] 3. Wrote `stories.md` from `requirements.md`:
        - [x] 3a. Developer user stories: S-1 (FR-1 intake), S-7..S-11 (FR-9..FR-13),
              S-13 (FR-4 follow-up), S-14 (FR-2 reject), S-6 (FR-14 receive), S-25 (FR-16 give).
        - [x] 3b. System stories: S-2 (FR-3), S-3 (FR-5), S-4 (FR-6), S-5 (FR-7), S-12 (FR-8),
              S-16 (FR-15), S-19 (FR-17), S-20 (FR-19), S-21 (FR-20), S-22 (FR-21),
              S-23 (NFR-7), S-24 (NFR-10), S-26 (FR-16 capture), S-27 (FR-18 capture).
        - [x] 3c. Operator stories: S-15 (FR-2), S-17 (NFR-3), S-18 (NFR-8). (Q1=a)
        - [x] 3d. N/A — Q2=a (capture-only). No consumption story; deferred, not deleted.
        - [x] 3e. Cross-cutting NFR section: NFR-2 latency, NFR-5/NFR-6 secrets; NFR-1→S-2,
              NFR-3→S-17/S-16, NFR-4→S-16, NFR-8→S-18, NFR-9→S-19 attached in-story.
        - [x] 3f. Given/When/Then acceptance criteria written for every story.
        - [x] 3g. Stories ordered core-first (thin slice → variants → safety → feedback).
- [x] 4. Coverage matrix built: all FR-1..FR-21 and NFR-1..NFR-10 mapped; no orphan stories.
- [x] 5. OOS-1..OOS-6 guard section: no story introduces out-of-scope behaviour.
- [x] 6. INVEST self-check done; assumptions A-1/A-2/A-6/A-7/A-8/A-9 referenced where depended on.
- [x] 7. Both files written; outputs registered in `state.json`; status set `artifact-generated`.
- [x] 8. Refined against `aidlc-systems-architect-agent-contribution.md`; status set `refined`.
        - [x] 8a. **CS-2 (accepted, story edit):** widened **S-19** to cover an acked-but-not-
              completed job lost to a worker restart (the S-2→S-6 silent-failure gap from the C-1
              async split). Added an AC for detect→retry-or-resolve and added C-1 to its
              constraints. Stays traced to FR-17/NFR-9, so the coverage matrix is unchanged.
        - [x] 8b. **CS-1, CS-3, CS-4, CS-5, CS-6 (accepted as downstream notes, no story change):**
              recorded in `stories.md` → "Cross-story architectural interactions" so functional-/
              units-/nfr-/infra-design carry them forward. Per the architect, these are shared-
              boundary design concerns, not backlog-granularity changes.
        - [x] 8c. **Not changed (with reasoning):** no new mandatory story added — architect
              requested none and CS-2 was the only finding warranting a story edit, handled by
              extending S-19 (lighter touch than a new story, keeps story count/IDs stable per the
              decomposition skill's traceability aim). Coverage matrix, OOS guard, INVEST self-
              check, persona set, and committed scope (Q1=a, Q2=a) left intact — architect
              confirmed all sound. S-20's AC unchanged (CS-3 is a functional-design state-semantics
              concern, not a story-text change, per the architect).
- [ ] 9. (Later) Finalise against `aidlc-product-lead-agent-review.md`; set `finalised`.

## Notes

- Inference stays a pluggable abstraction (A-1) — stories reference "the inference provider",
  never a specific Kiro API, so the highest-risk assumption can be de-risked in design without
  rewriting stories.
- Grounding+citation (FR-6/FR-7) and the A-2 "no source → state ungrounded, don't fabricate"
  behaviour are captured as explicit acceptance criteria, since fabricated citations are the
  key correctness risk for this bot.
