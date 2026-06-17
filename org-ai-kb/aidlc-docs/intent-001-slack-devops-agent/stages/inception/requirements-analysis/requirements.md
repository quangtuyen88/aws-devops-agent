# Requirements

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Owner: aidlc-product-manager-agent
Source: `intent.md`, `workflow.json`, clarification answers Q1–Q8 (`questions.md`)

## Intent Summary

- **Type:** New feature (greenfield system — a new Slack-integrated DevOps assistant service)
- **Scope:** Multi-component service (Slack adapter, agent core, Kiro-backed inference provider, `aws-knowledge-mcp-server` MCP client, feedback/metrics capture)
- **Classification:** Greenfield (confirmed in `intent.md`; reverse-engineering skipped — no existing codebase)
- **Affected repos:** New repo (none existing)

**One-line value:** Developers ask DevOps/AWS questions in dedicated Slack channels by `@mention`ing the bot; the bot answers with detailed, AWS-documentation-grounded guidance routed through the team's Kiro inference subscription.

## Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| FR-1 | Accept developer questions via `@mention` of the bot in a Slack channel or thread | Given the bot is a member of an allowed channel, when a developer posts a message that `@mention`s the bot, then the message text is captured and routed for processing. A message that does not mention the bot is ignored. |
| FR-2 | Restrict operation to a configured allowlist of dedicated channels | Given a channel is not in the configured allowlist, when the bot is mentioned there, then the bot does not produce an answer (it either stays silent or replies that it only operates in designated channels). Only allowlisted channels (e.g. `#devops-help`) trigger answers. |
| FR-3 | Acknowledge each accepted question immediately before processing | When a valid mention is received, then the bot posts an acknowledgement (e.g. "working on it…") in-thread within the latency bound in NFR-1, prior to the full answer. |
| FR-4 | Maintain thread-scoped conversation memory | Given a developer asks a follow-up in the same Slack thread, when the bot processes it, then prior messages in that thread are included as context so the user need not re-paste earlier content. Memory does not persist beyond the originating thread. |
| FR-5 | Route the question to an LLM/SLM via the Kiro-backed inference provider | When a question is processed, then the bot invokes inference through the configured Kiro-backed provider abstraction and obtains a model response. Inference access is treated as a pluggable abstraction (see A-1). |
| FR-6 | Ground answers using `aws-knowledge-mcp-server` MCP tools | When generating an answer to an AWS-related question, then the agent calls the MCP server's tools (e.g. AWS documentation search, regional availability) and incorporates the returned sources into the answer. An answer that requires AWS facts is not produced from model knowledge alone. |
| FR-7 | Cite AWS documentation sources in every grounded answer | When an answer is produced using MCP-returned content, then the answer includes citations/links to the specific AWS documentation sources used. Citations are mandatory, not optional (see A-2 if MCP returns no source). |
| FR-8 | Provide detailed answers including rationale, trade-offs, and alternatives | When answering an architecture-review or solution-design question, then the response contains (a) a direct recommendation, (b) the rationale, (c) relevant trade-offs, and (d) at least one alternative where applicable. |
| FR-9 | Support architecture review questions | Given a developer submits an architecture for review, when processed, then the bot returns an assessment covering strengths, risks/concerns, and improvement recommendations grounded in AWS guidance. |
| FR-10 | Support solution-design guidance | Given a developer asks how to build a solution (e.g. Lambda + API Gateway + DynamoDB), when processed, then the bot returns a recommended design approach grounded in AWS guidance. |
| FR-11 | Support cost estimation / right-sizing guidance | Given a developer asks about cost or sizing, when processed, then the bot returns cost/right-sizing guidance for the relevant AWS services. (In scope per Q4.) |
| FR-12 | Support operational troubleshooting questions | Given a developer asks an operational question (e.g. "why is my Lambda throttling?"), when processed, then the bot returns troubleshooting guidance grounded in AWS documentation. (In scope per Q4.) |
| FR-13 | Generate ready-to-use IaC / code snippets | Given a developer requests buildable output, when processed, then the bot can return IaC/code snippets in Terraform, AWS CDK, or AWS SAM appropriate to the requested solution. The bot does not execute or deploy them (see OOS-3). |
| FR-14 | Post the full answer back into the originating Slack thread | When the answer is ready, then the bot posts it as a reply in the same thread/channel where the question was asked, formatted for readability in Slack (e.g. code blocks for snippets, links for citations). |
| FR-15 | Detect secrets/credentials in user input and warn or refuse | Given input appears to contain secrets, credentials, keys, or tokens, when detected, then the bot warns the user and/or refuses to forward that input to inference/MCP, rather than processing it normally. (Per Q7; detection depth assessed in nfr-design — see A-6.) |
| FR-16 | Capture per-answer helpfulness feedback (👍 / 👎) | When an answer is posted, then the developer can signal helpfulness via a 👍/👎 reaction (or equivalent control), and the bot records the signal against that answer for the success metric in FR-18. |
| FR-17 | Handle inference/MCP failures gracefully with a user-facing message | Given inference or an MCP call fails or times out, when processing a question, then the bot posts a clear failure/retry message in-thread instead of going silent or leaving the acknowledgement unresolved. |
| FR-18 | Capture adoption metrics | The system records, at minimum, the number of distinct developers served and the number of questions handled per week, sufficient to report adoption. (Per Q8a.) |
| FR-19 | Process duplicate Slack event deliveries at most once | Given Slack re-delivers the same event (identified by event/message identity, e.g. on `X-Slack-Retry-Num` after a missed 3s ack), when the bot receives a duplicate, then it does not start a second processing pass or post a second answer for the same originating message. (Per contributor G-1; caused by the async ack constraint C-1.) |
| FR-20 | Ignore the bot's own and other bots' messages | Given a message originates from the bot itself or from another bot/app, when received, then the bot does not treat it as a question — even if it contains an `@mention` of the bot. Prevents answer→re-trigger loops. (Per contributor G-3.) |
| FR-21 | Bound input size and handle oversized input gracefully | Given a question plus accumulated thread context (FR-4) exceeds the configured maximum input size, when processed, then the bot does not silently truncate without notice: it either truncates with an in-thread notice or returns a clear "input too large" message (ties to FR-17). The specific size limit and truncation strategy are set in nfr-design (see A-9). (Per contributor G-2 / constraint C-2.) |

## Non-Functional Requirements

| ID | Requirement | Measure |
|---|---|---|
| NFR-1 | Acknowledgement latency | The acknowledgement (FR-3) is posted within Slack's synchronous response window — target p95 < 3s from receipt of the mention. |
| NFR-2 | Full-answer latency | The complete grounded answer is delivered within p95 ≤ 30s of the question (assumed default — see A-3; revisit in nfr-design). |
| NFR-3 | Data-sensitivity policy | Documented usage policy: only internal/non-production content may be shared with the bot — no secrets, credentials, PII, or customer data. Policy is published to users and enforced in part by FR-15. |
| NFR-4 | Secret non-propagation | Input flagged by FR-15 as containing secrets/credentials is not forwarded to the inference provider or MCP server. Verified by test inputs containing known secret patterns. |
| NFR-5 | Credential security & least privilege | Slack, Kiro, and MCP credentials are stored in a secret manager (never hardcoded or committed), and each integration is granted least-privilege scopes only. Verified by config review. |
| NFR-6 | No secrets/PII in logs | Operational logs and metrics contain no secrets, credentials, or user-pasted PII. Verified by log inspection against test inputs. |
| NFR-7 | External rate-limit handling | The bot handles Slack and MCP rate limits/backpressure (e.g. retry with backoff) without crashing or dropping a question silently. Verified by simulated rate-limit responses. |
| NFR-8 | Inference/MCP cost guardrail | A bound on inference/MCP usage exists (e.g. per-request and/or per-period limit) to prevent runaway cost. Specific thresholds set in nfr-design (see A-7). |
| NFR-9 | Availability | The bot service availability target is defined and monitored. The target is **dependency-bounded** — overall availability cannot exceed that of the external Kiro inference and `aws-knowledge-mcp-server` dependencies (per contributor C-3). Specific target (e.g. business-hours availability) set in nfr-design. |
| NFR-10 | Concurrency | The service handles multiple simultaneous in-flight questions (from different developers/channels) without head-of-line blocking — one slow question must not stall others. The concurrency target and async-worker sizing are set in nfr-design/infrastructure-design. (Per contributor G-5; relates to async constraint C-1.) |

## Assumptions

- **A-1:** The team's Kiro subscription exposes a programmatic interface usable for LLM/SLM inference; the exact API surface is treated as a pluggable abstraction and resolved in infrastructure-design (per workflow-composition decision Q2:c). **Known fork (per contributor):** Kiro is primarily an interactive surface and a headless server-to-server inference endpoint is not confirmed; the provider abstraction (FR-5) must therefore be designed so an alternate inference backend (e.g. Amazon Bedrock) can drop in without changing agent-core logic. This is the highest-risk assumption and should be de-risked **before functional-design commits**. Flagged for validation.
- **A-2:** `aws-knowledge-mcp-server` is reachable from the bot's runtime and provides documentation search and regional-availability tooling that returns citable sources. If the MCP returns no source for a query, the bot states that the answer is ungrounded rather than fabricating a citation. Flagged for validation.
- **A-3:** The full-answer latency target of p95 ≤ 30s (NFR-2) is a working default chosen during clarification; to be confirmed/adjusted in nfr-design. Flagged for validation.
- **A-4:** The solution is a single deployable unit (per workflow-composition; contract-design skipped). Revisited at units-generation if the design splits.
- **A-5:** A single Slack workspace is in scope; access is limited to members of that workspace and the allowlisted channels.
- **A-6:** Secret/credential detection (FR-15) is best-effort/heuristic; its precision/recall and exact behaviour (warn vs hard refuse) are assessed in nfr-design.
- **A-7:** Cost-guardrail thresholds (NFR-8) and availability targets (NFR-9) are set during nfr-design; this stage records only that they must exist.
- **A-8:** Thread-scoped memory (FR-4) lives only for the active thread context and is not persisted in a durable cross-session store. **Clarification (per contributor G-4):** "ephemeral" applies to *conversation* memory only. A minimal durable store for *aggregate operational data* — adoption counts (FR-18) and helpfulness feedback signals (FR-16) — is permitted and required; it is not conversation memory and does not violate OOS-4.
- **A-9:** A maximum input size / context-window budget exists for FR-21 (question + accumulated thread context must fit the inference model's context window). The exact size limit and truncation-vs-reject strategy are set in nfr-design. Flagged for validation. (Per contributor C-2/G-2.)

## Out of Scope

- **OOS-1:** Audiences beyond developers (e.g. PMs, non-engineering staff) and workspace-wide open access — operation is limited to developers in the allowlisted channels (Q1:a).
- **OOS-2:** Invocation via slash command or direct message — `@mention` only for this release (Q2:a). Deferred, not deleted.
- **OOS-3:** Executing, applying, or deploying generated IaC/code, or otherwise mutating any AWS resources — the bot provides advice and snippets only.
- **OOS-4:** Persistent cross-session or per-user memory beyond the originating thread (Q3:b).
- **OOS-5:** Multi-workspace / multi-tenant support.
- **OOS-6:** Guidance for non-AWS cloud providers — scope is AWS, grounded in `aws-knowledge-mcp-server`.

## Design Constraints to Carry Forward

Recorded here from the systems-architect contribution. These are not solved at requirements
stage; they are binding inputs for functional-design / nfr-design / infrastructure-design.

- **C-1 (Slack 3s ack is architectural, not just UX):** Slack requires HTTP 200 within ~3s or
  it retries delivery. The agent loop (NFR-2 ≤ 30s) cannot finish in that window, so an
  accept-and-enqueue / async-worker pattern is **mandatory**. Backs FR-3, NFR-1, FR-19.
  → functional-design + infrastructure-design.
- **C-2 (Token/context budget):** Thread context (FR-4) + pasted architecture can exceed the
  model's context window; a max-input / truncation policy is required. Backs FR-21, A-9.
  → nfr-design.
- **C-3 (Dependency-bounded availability):** Kiro inference and the MCP server are external;
  bot availability (NFR-9) is bounded by theirs. → nfr-design.
- **C-4 (Single deployable, internal async boundary):** The ack-then-answer split implies an
  intake path + async worker path *within* the single deployable unit (A-4). Functional-design
  must show this internal async boundary. → functional-design.

## Traceability Notes

- FR-1, FR-2 ← Q1 (dedicated channels), Q2 (@mention).
- FR-3 ← Q6 (acknowledge then answer). FR-4 ← Q3 (thread-scoped memory).
- FR-5 ← intent (Kiro inference). FR-6, FR-7 ← intent (MCP grounding) + Q5 (mandatory citations).
- FR-8 ← Q5 (detailed answers). FR-9–FR-13 ← Q4 (all question types, including IaC snippets).
- FR-14 ← intent (post answers to Slack). FR-15 ← Q7 (secret detection/refusal).
- FR-16, FR-18 ← Q8 (thumbs feedback + adoption metrics). FR-17 ← user-empathy (error states are real users).
- NFR-1, NFR-2 ← Q6. NFR-3, NFR-4 ← Q7. NFR-5, NFR-6 ← security baseline. NFR-7–NFR-9 ← operating an external-dependency service.
- FR-19 ← contributor G-1 (Slack retry de-dup). FR-20 ← contributor G-3 (bot-loop prevention).
  FR-21 ← contributor G-2 / C-2 (input size bound). NFR-10 ← contributor G-5 (concurrency).
- A-1 fork ← contributor §1 (Kiro inference risk). A-8 clarification ← contributor G-4.
  A-9 ← contributor C-2/G-2. NFR-9 dependency-bound ← contributor C-3. C-1..C-4 ← contributor §2.

## Refinement Log (contributor feedback addressed)

Round 1 — `aidlc-systems-architect-agent-contribution.md`:
- **G-1 → FR-19** (Slack event idempotency / at-most-once processing).
- **G-2/C-2 → FR-21 + A-9** (input size bound, truncation behaviour, user-facing message).
- **G-3 → FR-20** (ignore own/other bot messages to prevent answer loops).
- **G-4 → A-8 clarified** (metrics/feedback store is aggregate operational data, not conversation memory; permitted/required).
- **G-5 → NFR-10** (concurrency without head-of-line blocking).
- **A-1 recommendation → A-1 expanded** (pluggable inference must support a fallback backend e.g. Bedrock; flagged as highest-risk, de-risk before functional-design).
- **C-1..C-4 → new "Design Constraints to Carry Forward" section**; **C-3 → NFR-9 updated** to dependency-bounded availability.
- No committed scope (Q1–Q8) changed; all additions are additive and traceable. The contributor raised no objections to scope, so nothing was rejected.
