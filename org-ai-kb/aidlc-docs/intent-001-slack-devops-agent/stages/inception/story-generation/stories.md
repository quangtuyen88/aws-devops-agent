# Stories

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Owner: aidlc-product-manager-agent
Source: `requirements.md` (FR-1..FR-21, NFR-1..NFR-10, A-1..A-9, OOS-1..OOS-6, C-1..C-4),
clarification answers Q1=a, Q2=a.

**Reading order = priority.** Stories are ordered core-first (thin vertical slice → capability
variants → safety/governance/resilience → feedback & metrics) per the prioritisation skill. All
FRs are v1, so nothing is deferred; ordering is build/de-risk guidance, not a scope cut. Story
IDs are stable for downstream traceability.

Actors: **Developer** and **Platform Operator** (see `personas.md`); **the service** is the actor
for system stories. Cross-cutting NFRs (NFR-2, NFR-5, NFR-6) are listed once in their own section
and referenced from the stories they constrain.

---

## Thin vertical slice — core answer path (highest value + risk; build first)

## S-1: Ask a DevOps question by @mentioning the bot

**Type:** user story

**Statement:** As a **Developer**, I want to ask a question by `@mention`ing the bot in an
allowlisted channel or thread, so that I get DevOps/AWS help without leaving Slack.

**Acceptance Criteria:**
- Given the bot is a member of an allowlisted channel, when I post a message that `@mention`s the bot, then the message text is captured and routed for processing.
- Given a message in an allowlisted channel that does **not** mention the bot, when it is posted, then the bot ignores it (no processing, no reply).
- Given a mention, when it is accepted for processing, then capture occurs within Slack's synchronous window (see NFR-1 via S-2) so Slack does not retry delivery.

**Requirements:** FR-1

---

## S-2: Acknowledge the accepted question immediately

**Type:** system story

**Statement:** As the **service**, when a valid mention is accepted, it must post an in-thread
acknowledgement before the full answer, and return its HTTP 200 to Slack within the ack window.

**Acceptance Criteria:**
- Given a valid mention is received, when it is accepted, then an acknowledgement (e.g. "working on it…") is posted in-thread prior to the full answer.
- Given the Slack 3s delivery window (C-1), when the mention is received, then the service returns HTTP 200 and enqueues the work for an async worker rather than answering synchronously.
- Given normal operation, when measured, then acknowledgement latency meets NFR-1 (p95 < 3s from receipt).

**Requirements:** FR-3, NFR-1 · **Constraints:** C-1 · **Assumptions:** —

---

## S-3: Route the question through the pluggable inference provider

**Type:** system story

**Statement:** As the **service**, when a question is processed, it must obtain a model response
via the configured inference-provider abstraction.

**Acceptance Criteria:**
- Given a processed question, when inference is invoked, then it is called through the configured Kiro-backed provider abstraction and a model response is obtained.
- Given the provider abstraction (A-1), when the inference backend is changed (e.g. to an alternate such as Bedrock), then agent-core logic and other stories do not change — the provider is pluggable.
- Given inference is unavailable or errors, when invoked, then the failure is surfaced to S-19 (graceful failure) rather than swallowed.

**Requirements:** FR-5 · **Assumptions:** A-1 (highest-risk; de-risk before functional-design)

---

## S-4: Ground AWS answers using the AWS Knowledge MCP tools

**Type:** system story

**Statement:** As the **service**, when answering an AWS-related question, it must call
`aws-knowledge-mcp-server` tools and incorporate the returned sources, rather than answering from
model knowledge alone.

**Acceptance Criteria:**
- Given an AWS-related question, when an answer is generated, then the agent calls the MCP server's tools (e.g. documentation search, regional availability) and incorporates the returned content.
- Given an answer that requires AWS facts, when produced, then it is not produced from model knowledge alone.
- Given the MCP returns no source for the query (A-2), when answering, then the bot states the answer is ungrounded rather than fabricating a citation.

**Requirements:** FR-6 · **Assumptions:** A-2

---

## S-5: Cite AWS documentation sources in every grounded answer

**Type:** system story

**Statement:** As the **service**, when an answer uses MCP-returned content, it must include
citations/links to the specific AWS documentation sources used.

**Acceptance Criteria:**
- Given an answer produced using MCP-returned content, when posted, then it includes citations/links to the specific AWS docs used.
- Given an answer drawing on AWS facts, when no citable source is available (A-2), then the answer is explicitly marked ungrounded — citations are never fabricated.
- Given citations exist, when rendered in Slack, then they appear as clickable links (ties to S-6 formatting).

**Requirements:** FR-7 · **Assumptions:** A-2

---

## S-6: Receive the full answer in the originating thread

**Type:** user story

**Statement:** As a **Developer**, I want the full answer posted back in the same thread, formatted
for Slack, so that I can read and act on it in context.

**Acceptance Criteria:**
- Given an answer is ready, when posted, then it appears as a reply in the same thread/channel where I asked.
- Given the answer contains code/IaC, when rendered, then snippets use Slack code blocks and citations render as links.
- Given normal operation, when measured, then full-answer delivery meets NFR-2 (p95 ≤ 30s — see cross-cutting).

**Requirements:** FR-14 · **NFR (cross-cutting):** NFR-2

---

## Capability variants — supported question types (P0)

## S-7: Request an architecture review

**Type:** user story

**Statement:** As a **Developer**, I want to submit an architecture for review, so that I learn its
strengths, risks, and improvements grounded in AWS guidance.

**Acceptance Criteria:**
- Given I submit an architecture, when processed, then the response covers (a) strengths, (b) risks/concerns, and (c) improvement recommendations.
- Given the review (per FR-8), when produced, then it includes a direct recommendation, rationale, relevant trade-offs, and at least one alternative where applicable.
- Given the review makes AWS claims, when produced, then they are grounded and cited (via S-4/S-5).

**Requirements:** FR-9, FR-8

---

## S-8: Request solution-design guidance

**Type:** user story

**Statement:** As a **Developer**, I want a recommended design for a solution (e.g. Lambda + API
Gateway + DynamoDB), so that I can build it correctly.

**Acceptance Criteria:**
- Given I ask how to build a solution, when processed, then the bot returns a recommended design approach grounded in AWS guidance.
- Given the design (per FR-8), when produced, then it includes a recommendation, rationale, trade-offs, and at least one alternative where applicable.
- Given AWS service choices, when recommended, then they are cited (via S-5).

**Requirements:** FR-10, FR-8

---

## S-9: Request cost estimation / right-sizing guidance

**Type:** user story

**Statement:** As a **Developer**, I want cost and right-sizing guidance for relevant AWS services,
so that I can choose cost-effective options.

**Acceptance Criteria:**
- Given I ask about cost or sizing, when processed, then the bot returns cost/right-sizing guidance for the relevant AWS services.
- Given the guidance, when produced, then it is grounded in AWS sources and cited (via S-4/S-5).

**Requirements:** FR-11

---

## S-10: Request operational troubleshooting guidance

**Type:** user story

**Statement:** As a **Developer**, I want troubleshooting help for an operational issue (e.g. "why
is my Lambda throttling?"), so that I can resolve it.

**Acceptance Criteria:**
- Given I ask an operational question, when processed, then the bot returns troubleshooting guidance grounded in AWS documentation.
- Given the guidance, when produced, then it cites the AWS sources used (via S-5).

**Requirements:** FR-12

---

## S-11: Request ready-to-use IaC / code snippets

**Type:** user story

**Statement:** As a **Developer**, I want buildable IaC/code snippets for the recommended solution,
so that I can implement it directly.

**Acceptance Criteria:**
- Given I request buildable output, when processed, then the bot can return snippets in Terraform, AWS CDK, or AWS SAM appropriate to the solution.
- Given a snippet is returned, when posted, then it renders in a Slack code block (via S-6).
- Given any generated IaC/code, when returned, then the bot does **not** execute, apply, or deploy it (OOS-3).

**Requirements:** FR-13 · **OOS guard:** OOS-3

---

## S-12: Compose detailed answers (rationale, trade-offs, alternatives)

**Type:** system story

**Statement:** As the **service**, when answering an architecture-review or solution-design
question, it must structure the response with a recommendation, rationale, trade-offs, and an
alternative where applicable.

**Acceptance Criteria:**
- Given an architecture-review or solution-design answer, when composed, then it contains (a) a direct recommendation, (b) rationale, (c) relevant trade-offs, and (d) at least one alternative where applicable.
- Given a question type where an alternative is not meaningful, when answered, then (d) may be omitted with the other elements still present.

**Requirements:** FR-8 *(applied by S-7, S-8)*

---

## S-13: Continue a conversation via thread follow-up

**Type:** user story

**Statement:** As a **Developer**, I want to ask a follow-up in the same thread without re-pasting
earlier content, so that the conversation stays in context.

**Acceptance Criteria:**
- Given I ask a follow-up in the same thread, when processed, then prior messages in that thread are included as context.
- Given a new thread, when I ask, then context does not carry over from other threads (memory is thread-scoped only).
- Given the thread ends, when memory is considered, then conversation memory does not persist in a durable cross-session store (A-8 / OOS-4).

**Requirements:** FR-4 · **Assumptions:** A-8 · **OOS guard:** OOS-4

---

## Safety, governance & resilience (P0)

## S-14: Be rejected when mentioning the bot outside allowlisted channels

**Type:** user story

**Statement:** As a **Developer**, when I mention the bot in a non-allowlisted channel, I want a
clear signal that it only operates in designated channels, so that I'm not left waiting.

**Acceptance Criteria:**
- Given a channel not in the allowlist, when I mention the bot, then the bot does not produce an answer.
- Given that case, when handled, then the bot either stays silent or replies that it only operates in designated channels (deterministic, configured behaviour).
- Given an allowlisted channel, when I mention the bot, then it proceeds normally (via S-1).

**Requirements:** FR-2

---

## S-15: Configure the channel allowlist

**Type:** user story

**Statement:** As a **Platform Operator**, I want to configure which channels the bot answers in,
so that operation is restricted to dedicated channels.

**Acceptance Criteria:**
- Given I am the operator, when I set the allowlist, then only listed channels (e.g. `#devops-help`) trigger answers.
- Given a channel is removed from the allowlist, when the bot is mentioned there afterwards, then it no longer answers (consistent with S-14).

**Requirements:** FR-2

---

## S-16: Detect secrets/credentials in input and refuse to forward them

**Type:** system story

**Statement:** As the **service**, when input appears to contain secrets/credentials/keys/tokens,
it must warn and/or refuse rather than processing it normally — and must not forward it to
inference or MCP.

**Acceptance Criteria:**
- Given input appears to contain a secret/credential/key/token, when detected, then the bot warns the user and/or refuses to process that input.
- Given flagged input (NFR-4), when handled, then it is **not** forwarded to the inference provider or MCP server.
- Given test inputs with known secret patterns, when run, then they are detected (best-effort/heuristic per A-6; precision/recall and warn-vs-refuse behaviour set in nfr-design).

**Requirements:** FR-15, NFR-4 · **Assumptions:** A-6 · **NFR (cross-cutting):** NFR-3, NFR-6

---

## S-17: Publish the data-sensitivity usage policy

**Type:** user story

**Statement:** As a **Platform Operator**, I want to publish the usage policy to developers, so
that they know only internal/non-production content may be shared — no secrets, PII, or customer
data.

**Acceptance Criteria:**
- Given the service is in use, when an operator publishes the policy, then it is visible to developers (e.g. channel topic/pinned message or equivalent).
- Given the policy, when stated, then it explicitly prohibits secrets, credentials, PII, and customer/production data, and is enforced in part by S-16 (FR-15).

**Requirements:** NFR-3 *(enforcement partly via FR-15/S-16)*

---

## S-18: Set the inference/MCP cost guardrail

**Type:** user story

**Statement:** As a **Platform Operator**, I want to set a bound on inference/MCP usage, so that
runaway cost is prevented.

**Acceptance Criteria:**
- Given I am the operator, when I set the guardrail, then a per-request and/or per-period usage bound is in effect.
- Given the bound is reached, when further usage is attempted, then the service enforces the limit (exact thresholds and enforcement behaviour set in nfr-design per A-7).

**Requirements:** NFR-8 · **Assumptions:** A-7

---

## S-19: Handle inference/MCP failures and lost in-flight work gracefully

**Type:** system story

**Statement:** As the **service**, when inference or an MCP call fails or times out, **or when an
acked job is lost before its answer is posted** (e.g. a worker restart between S-2 and S-6), it
must post a clear in-thread failure/retry message instead of going silent or leaving the
acknowledgement unresolved.

**Acceptance Criteria:**
- Given inference or MCP fails or times out, when processing, then the bot posts a clear failure/retry message in the thread.
- Given the acknowledgement (S-2) was posted, when a failure occurs, then it is not left dangling — the failure message resolves it.
- Given a job was acked (S-2) but neither answered (S-6) nor failure-resolved when its worker is lost/restarted, when the loss is detected, then the job is either retried to completion or resolved with an in-thread failure message — an acked job is never left permanently silent. *(de-dup semantics for the retry path are pinned down with S-20 in functional-design — see CS-3 note.)*
- Given external dependencies are down (C-3), when measured, then availability is understood as dependency-bounded (NFR-9).

**Requirements:** FR-17 · **NFR:** NFR-9 · **Constraints:** C-1 (async ack→worker split), C-3

---

## S-20: Process duplicate Slack event deliveries at most once

**Type:** system story

**Statement:** As the **service**, when Slack re-delivers the same event (e.g. on a retry after a
missed 3s ack), it must not start a second processing pass or post a second answer.

**Acceptance Criteria:**
- Given Slack re-delivers an event identified by event/message identity (e.g. `X-Slack-Retry-Num`), when received, then no second processing pass starts for the same originating message.
- Given a duplicate, when handled, then no second answer or acknowledgement is posted.

**Requirements:** FR-19 · **Constraints:** C-1

---

## S-21: Ignore the bot's own and other bots' messages

**Type:** system story

**Statement:** As the **service**, when a message originates from the bot itself or another
bot/app, it must not treat it as a question — even if it `@mention`s the bot.

**Acceptance Criteria:**
- Given a message from the bot itself or another bot/app, when received, then it is not treated as a question.
- Given such a message contains an `@mention` of the bot, when received, then it is still ignored (prevents answer→re-trigger loops).

**Requirements:** FR-20

---

## S-22: Bound input size and handle oversized input gracefully

**Type:** system story

**Statement:** As the **service**, when a question plus accumulated thread context exceeds the
configured maximum input size, it must not silently truncate — it either truncates with notice or
returns a clear "input too large" message.

**Acceptance Criteria:**
- Given question + accumulated thread context (FR-4) exceeds the configured max input size, when processed, then the bot does not silently truncate without notice.
- Given that case, when handled, then it either truncates with an in-thread notice or returns a clear "input too large" message (ties to S-19).
- Given the limit and truncation strategy, when defined, then they are set in nfr-design (A-9) — this story records that the behaviour must exist.

**Requirements:** FR-21 · **Assumptions:** A-9 · **Constraints:** C-2

---

## S-23: Handle external rate limits and backpressure

**Type:** system story

**Statement:** As the **service**, when Slack or MCP signals rate limits/backpressure, it must
handle them (e.g. retry with backoff) without crashing or silently dropping a question.

**Acceptance Criteria:**
- Given a simulated Slack/MCP rate-limit response, when encountered, then the service retries with backoff rather than crashing.
- Given backpressure, when handled, then no question is dropped silently — it either completes or surfaces a failure message via S-19.

**Requirements:** NFR-7

---

## S-24: Serve concurrent questions without head-of-line blocking

**Type:** system story

**Statement:** As the **service**, when multiple questions are in flight from different
developers/channels, it must process them so that one slow question does not stall others.

**Acceptance Criteria:**
- Given multiple simultaneous in-flight questions, when processed, then one slow question does not block others (no head-of-line blocking).
- Given concurrency targets, when defined, then they and async-worker sizing are set in nfr-design/infrastructure-design (relates to C-1).

**Requirements:** NFR-10 · **Constraints:** C-1

---

## Feedback & metrics (capture-only this release — Q2=a)

## S-25: Give 👍 / 👎 helpfulness feedback on an answer

**Type:** user story

**Statement:** As a **Developer**, I want to signal whether an answer was helpful with a 👍/👎, so
that the team can measure the bot's value.

**Acceptance Criteria:**
- Given an answer is posted, when I react with 👍 or 👎 (or an equivalent control), then I can register the signal.
- Given I signal, when recorded, then it is associated with that specific answer (capture handled by S-26).

**Requirements:** FR-16 *(user-facing part)*

---

## S-26: Capture per-answer helpfulness signals

**Type:** system story

**Statement:** As the **service**, when a developer signals 👍/👎 on an answer, it must record the
signal against that answer for the FR-18 success metric.

**Acceptance Criteria:**
- Given a 👍/👎 signal on an answer, when received, then the signal is recorded against that answer.
- Given the recorded signal, when stored, then it lives in the minimal durable aggregate-operational-data store permitted by A-8 (not conversation memory; does not violate OOS-4).
- *Capture-only this release; viewing/reporting is deferred, not deleted (Q2=a).*

**Requirements:** FR-16 *(capture part)* · **Assumptions:** A-8

---

## S-27: Capture adoption metrics

**Type:** system story

**Statement:** As the **service**, it must record at minimum the number of distinct developers
served and questions handled per week, sufficient to report adoption.

**Acceptance Criteria:**
- Given questions are handled, when recorded, then the system captures at least distinct-developer count and questions-per-week.
- Given the metrics, when stored, then they live in the A-8 aggregate-operational-data store (not conversation memory; does not violate OOS-4).
- *Capture-only this release; a reporting/summary story is deferred, not deleted (Q2=a) — the A-8 store allows it later without rework.*

**Requirements:** FR-18 · **Assumptions:** A-8

---

# Cross-Cutting Acceptance Criteria (NFRs applied across stories)

These NFRs are not standalone stories (no distinct actor/behaviour of their own); they constrain
multiple stories and must be added as acceptance criteria during design/build.

- **NFR-2 — Full-answer latency (p95 ≤ 30s, default per A-3):** applies to every answer-producing
  story — S-6 (delivery), S-7, S-8, S-9, S-10, S-11. Revisited in nfr-design.
- **NFR-5 — Credential security & least privilege:** Slack/Kiro/MCP credentials stored in a secret
  manager (never hardcoded/committed), least-privilege scopes. Applies to all integration points —
  S-1/S-2 (Slack), S-3 (inference), S-4 (MCP). Verified by config review. *(Per Q1, this is a
  cross-cutting criterion, not an operator story.)*
- **NFR-6 — No secrets/PII in logs:** operational logs/metrics contain no secrets, credentials, or
  user-pasted PII. Applies to all stories that log, especially S-16, S-26, S-27. Verified by log
  inspection against test inputs.

---

# Coverage Matrix

Every requirement maps to ≥1 story; every story traces to ≥1 requirement.

## Functional requirements

| Req | Story(ies) |
|---|---|
| FR-1 | S-1 |
| FR-2 | S-14, S-15 |
| FR-3 | S-2 |
| FR-4 | S-13 (context also bounded by S-22) |
| FR-5 | S-3 |
| FR-6 | S-4 |
| FR-7 | S-5 |
| FR-8 | S-12 (applied by S-7, S-8) |
| FR-9 | S-7 |
| FR-10 | S-8 |
| FR-11 | S-9 |
| FR-12 | S-10 |
| FR-13 | S-11 |
| FR-14 | S-6 |
| FR-15 | S-16 |
| FR-16 | S-25 (user), S-26 (capture) |
| FR-17 | S-19 |
| FR-18 | S-27 |
| FR-19 | S-20 |
| FR-20 | S-21 |
| FR-21 | S-22 |

## Non-functional requirements

| Req | Story / placement |
|---|---|
| NFR-1 | S-2 (ack latency) |
| NFR-2 | Cross-cutting → S-6, S-7, S-8, S-9, S-10, S-11 |
| NFR-3 | S-17 (publish), enforced partly by S-16 |
| NFR-4 | S-16 (secret non-propagation) |
| NFR-5 | Cross-cutting (credential security) — not a story per Q1 |
| NFR-6 | Cross-cutting (no secrets/PII in logs) — esp. S-16, S-26, S-27 |
| NFR-7 | S-23 |
| NFR-8 | S-18 |
| NFR-9 | S-19 (dependency-bounded availability) |
| NFR-10 | S-24 |

## Story → requirement (reverse check)

S-1→FR-1 · S-2→FR-3/NFR-1 · S-3→FR-5 · S-4→FR-6 · S-5→FR-7 · S-6→FR-14/NFR-2 ·
S-7→FR-9/FR-8 · S-8→FR-10/FR-8 · S-9→FR-11 · S-10→FR-12 · S-11→FR-13 · S-12→FR-8 ·
S-13→FR-4 · S-14→FR-2 · S-15→FR-2 · S-16→FR-15/NFR-4 · S-17→NFR-3 · S-18→NFR-8 ·
S-19→FR-17/NFR-9 · S-20→FR-19 · S-21→FR-20 · S-22→FR-21 · S-23→NFR-7 · S-24→NFR-10 ·
S-25→FR-16 · S-26→FR-16 · S-27→FR-18. **No orphan stories; no uncovered requirements.**

---

# Out-of-Scope Guard (no story introduces OOS behaviour)

- **OOS-1** (non-developer audiences / open access): stories restricted to Developer in allowlisted channels (S-14, S-15). ✓
- **OOS-2** (slash command / DM): all intake via `@mention` only (S-1). ✓
- **OOS-3** (execute/deploy IaC): explicitly excluded in S-11. ✓
- **OOS-4** (cross-session/per-user memory): S-13 thread-scoped only; S-26/S-27 store is aggregate operational data per A-8, not conversation memory. ✓
- **OOS-5** (multi-workspace/tenant): single workspace assumed (A-5); no story spans workspaces. ✓
- **OOS-6** (non-AWS providers): grounding is AWS-only via `aws-knowledge-mcp-server` (S-4). ✓

---

# INVEST Self-Check

- **Independent:** core-path stories (S-1..S-6) are sequenced but each is separately testable; capability variants (S-7..S-11) are independent of one another.
- **Negotiable:** thresholds/limits (NFR-8/S-18, FR-21/S-22, NFR-2) defer specifics to nfr-design.
- **Valuable:** each user story delivers developer or operator value; system stories enable a correctness/safety behaviour.
- **Estimable:** scoped to one capability/behaviour each.
- **Small:** question types and edge/error cases (S-14, S-16, S-19..S-24) are separate stories, not buried in happy-path.
- **Testable:** all acceptance criteria are Given/When/Then and verifiable as pass/fail.

---

# Notes for downstream stages

- **A-1 (inference provider)** is the highest-risk assumption — S-3 keeps it pluggable; de-risk before functional-design commits.
- **C-1 async boundary** surfaces as acceptance criteria in S-2, S-20, S-24 (intake → async worker within the single deployable unit, A-4/C-4); functional-design must show this internal boundary.
- **Fabricated citations** are the key correctness risk — S-4/S-5 encode the A-2 "no source → state ungrounded, never fabricate" rule explicitly.
- Templates `personas.md` / `stories.md` followed. Wireframe stage skipped (Slack is the interface); message/interaction shaping folds into functional-design, so stories stay at behaviour level.

## Cross-story architectural interactions (from systems-architect contribution)

These are individually-correct stories that share a hidden boundary; functional-/units-/nfr-/infra-design must treat each as one concern. CS-2 was addressed in this stage by widening S-19; the rest are design guidance, not story changes.

- **CS-1 — Single shared-state boundary.** S-18 (per-period cost counter), S-20 (de-dup identity), S-26 (feedback signals), S-27 (adoption counts) are the service's only durable/shared state (the A-8 aggregate-operational-data store) and must be consistent across the concurrent workers implied by S-24 — i.e. **not** process-memory. Decide the store and its consistency model in units-/infrastructure-design.
- **CS-2 — In-flight durability gap (addressed here).** S-19 now covers an acked-but-not-completed job lost to a worker restart, closing the S-2→S-6 silent-failure gap created by the C-1 async split. Functional-design must implement detection + retry-or-resolve.
- **CS-3 — De-dup vs retry-as-recovery semantics.** S-20 ("at-most-once") and S-19's new recovery AC are in tension: de-duping purely on "event seen" would permanently drop a question whose first attempt crashed. Functional-design must define de-dup as **at-most-once *completed* processing**, with state keyed as seen / in-progress / resolved so a crashed-before-answer event can be (re)processed.
- **CS-4 — S-16 is an upstream data-flow gate.** Its late position in the reading order is build-order only; in the request pipeline, secret detection (NFR-4) must run **before** S-3 (inference) and S-4 (MCP) so flagged input never reaches either dependency.
- **CS-5 — NFR-2 (p95 ≤ 30s) is one shared budget** spent across the S-13 thread-history fetch, S-4 MCP round-trips, and a possibly multi-turn S-3 agent loop. nfr-design must add, beyond the latency target, a **hard cap on agent tool-call iterations and a per-request timeout** that routes to S-19 — iteration count, not just dependency timeout, is the likely runaway.
- **CS-6 — S-13 memory is fetch-not-store.** Because OOS-4/A-8 forbid durable conversation memory, thread context is reconstructed via Slack `conversations.replies` at request time. Functional-design must keep this fetch-not-store model (no durable conversation store → no OOS-4 breach); note it adds to the NFR-2 budget (CS-5) and the NFR-7/S-23 rate-limit surface, and feeds the S-22 input-size bound.
