# API Specification — Functional Design

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `functional-design` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-systems-architect-agent.
>
> **Scope (Q1=c, human-answered 2026-06-17):** UNIT-001 exposes no public consumer API —
> it is event-driven from Slack. This document therefore covers **both** (1) the
> **external integration surfaces** the unit consumes/exposes at its outer boundary and
> (2) the **internal module interfaces** — the stable seams inside the unit that matter
> for testing and future extraction (the CMP-003 inference swap seam and the C-1
> intake→worker queue above all). `contract-design` was skipped (single unit), so there
> are no cross-unit contracts; these are integration + internal seams, not unit contracts.
>
> Logical shapes only — no wire formats, no SDK calls, no framework. Auth/least-privilege
> detail (NFR-5) and concrete thresholds are finalised in nfr-/infrastructure-design.

---

## Part A — External Integration Surfaces

The boundaries between UNIT-001 and the outside world. "Direction" is from the unit's
point of view: *inbound* = the unit receives; *outbound* = the unit calls out.

### A.1 Interface Summary

| ID | Type | Direction | Name | Component | Counterparty |
|---|---|---|---|---|---|
| API-EXT-001 | Slack event (subscription) | inbound | Mention / message event intake | CMP-001 | Slack Events API |
| API-EXT-002 | Slack Web API call | outbound | Fetch thread replies | CMP-001 | Slack Web API |
| API-EXT-003 | Slack Web API call | outbound | Post message (ack / answer / failure) | CMP-001 | Slack Web API |
| API-EXT-004 | MCP tool call | outbound | AWS Knowledge documentation / regional-availability tools | CMP-004 | aws-knowledge-mcp-server |
| API-EXT-005 | Slack event (subscription) | inbound | Reaction add/remove event | CMP-001 | Slack Events API |
| API-EXT-006 | Inference endpoint call | outbound | Run inference (backend-specific) | CMP-003 | Kiro / Bedrock endpoint |

### A.2 Operations

#### API-EXT-001 — Mention / message event intake
| Field | Value |
|---|---|
| Purpose | Receive Slack message events so a developer's @mention becomes a captured question |
| Trigger | Slack delivers a message event for a channel the bot is in (at-least-once; may carry X-Slack-Retry-Num) |
| Auth / Permission | Slack request-signature verification; bot granted least-privilege event scopes only (NFR-5) |
| Input | Slack event envelope: channel-id, message-ts, thread-ts?, author-id, is-bot flag, text, retry-num → parsed into `InboundMention` (ENT-001) |
| Output | Synchronous HTTP 200 within the NFR-1 window (BR-004); no answer body returned synchronously |
| Business rules | BR-001 (allowlist), BR-002 (ignore bot/self), BR-003 (must mention), BR-004 (ack + enqueue), BR-010 (de-dup) |
| Entities | ENT-001 InboundMention |
| Errors | Invalid signature → reject; non-mention / bot-author → silently ignore; non-allowlisted → silent or not-designated reply (BR-001) |
| Versioning | Slack Events API contract is external; adapter isolates it so internal entities are stable |

#### API-EXT-002 — Fetch thread replies
| Field | Value |
|---|---|
| Purpose | Reconstruct thread-scoped context at request time (fetch-not-store, CS-6) |
| Trigger | Worker needs prior thread context (BR-005) |
| Auth / Permission | Bot token, least-privilege read scope for the originating channel only (NFR-5) |
| Input | channel-id + thread-ts |
| Output | Ordered prior messages → `ConversationContext.ordered-messages` (ENT-003) |
| Business rules | BR-005 (thread-scoped, fetch-not-store), BR-006 (latency budget), BR-023 (rate-limit backoff) |
| Entities | ENT-003 ConversationContext |
| Errors | Rate limit → backoff/retry (BR-023); persistent failure → failure path (BR-013) |
| Versioning | External Slack contract; isolated by CMP-001 |

#### API-EXT-003 — Post message (ack / answer / failure)
| Field | Value |
|---|---|
| Purpose | Post the acknowledgement, the final answer, and failure/retry messages into the originating thread |
| Trigger | Ack (BR-004); answer ready (W2); failure resolution (BR-013) |
| Auth / Permission | Bot token, least-privilege write scope for allowlisted channels (NFR-5) |
| Input | originating-message-ref + rendered content (Slack-formatted: code blocks for snippets, links for citations) |
| Output | Posted Slack message (answer carries the coordinates later used to resolve reactions, BR-018) |
| Business rules | BR-004, BR-013, BR-016 (citation/grounding consistency), BR-017 (no execution), BR-026 (no secrets/PII) |
| Entities | ENT-004 Answer |
| Errors | Rate limit → backoff (BR-023); post failure on the answer path → retry then failure message |
| Versioning | External Slack contract; isolated by CMP-001 |

#### API-EXT-004 — AWS Knowledge MCP tools
| Field | Value |
|---|---|
| Purpose | Retrieve citable AWS documentation sources to ground answers |
| Trigger | Worker grounds an AWS-fact answer (BR-009) |
| Auth / Permission | MCP credentials from secret manager, least-privilege (NFR-5) |
| Input | Query / tool arguments (documentation-search, regional-availability) — only AFTER the safety gate allows (BR-012) |
| Output | Zero-or-more `GroundingSource` (ENT-006): title, url, snippet, tool-name |
| Business rules | BR-009 (ground-or-mark-ungrounded), BR-012 (post-safety-gate only), BR-014 (tool-call cap), BR-023 (backpressure) |
| Entities | ENT-006 GroundingSource |
| Errors | No source → mark ungrounded (BR-009); failure/timeout → failure path (BR-013); rate limit → backoff (BR-023) |
| Versioning | External MCP tool contract; isolated by CMP-004 |

#### API-EXT-005 — Reaction add/remove event intake
| Field | Value |
|---|---|
| Purpose | Capture 👍/👎 helpfulness feedback on posted answers |
| Trigger | Slack delivers a reaction_added / reaction_removed event |
| Auth / Permission | Slack signature verification; least-privilege reaction event scope (NFR-5) |
| Input | answer-message-ts, reactor-id, emoji, add/remove → `ReactionEvent` (ENT-002) |
| Output | HTTP 200; forwards a normalised reaction to CMP-007 (API-INT-007) |
| Business rules | BR-018 (only 👍/👎 on bot answers), BR-026 |
| Entities | ENT-002 ReactionEvent |
| Errors | Non-👍/👎 or non-answer target → ignore (BR-018) |
| Versioning | External Slack contract; isolated by CMP-001 |

#### API-EXT-006 — Run inference (external endpoint)
| Field | Value |
|---|---|
| Purpose | The backend-specific call to the configured inference endpoint (Kiro, or alternate such as Bedrock) |
| Trigger | CMP-003 fulfils an internal run-inference request (API-INT-001) |
| Auth / Permission | Endpoint credentials from secret manager, least-privilege (NFR-5) |
| Input | Backend-specific prompt payload (translated from the stable internal request) |
| Output | Backend-specific response + usage → normalised into `InferenceExchange` (ENT-005) |
| Business rules | BR-008 (within budget before spend), BR-012 (only post-safety-gate input), BR-014 (cap), BR-019 (usage recorded) |
| Entities | ENT-005 InferenceExchange |
| Errors | Unavailable/error → typed failure surfaced to BR-013 |
| Versioning | **The A-1 swap point.** This external shape is intentionally hidden behind API-INT-001 so the backend can change without touching agent-core logic; concrete backend chosen in infrastructure-design |

---

## Part B — Internal Module Interfaces

The stable seams *inside* UNIT-001 (the modular-monolith boundaries from units.md).
These are not cross-unit contracts; they are the extraction/testing seams.

### B.1 Interface Summary

| ID | Type | Name | Provider | Consumer(s) | Why it is a stable seam |
|---|---|---|---|---|---|
| API-INT-001 | Internal call | Run inference (backend-agnostic) | CMP-003 | CMP-002 | **A-1 swap seam (Q4)** — backend-agnostic; built/tested in isolation |
| API-INT-002 | Internal call | Job register / transition / recover | CMP-006 | CMP-001, CMP-002 | Owns ProcessingJob state machine + de-dup (CS-2/CS-3) |
| API-INT-003 | Internal call | Scan input for secrets | CMP-005 | CMP-002 | The CS-4 pre-send safety gate |
| API-INT-004 | Internal call | Ground + cite | CMP-004 | CMP-002 | Grounding seam; wraps API-EXT-004 |
| API-INT-005 | Internal call | Fetch replies / post message | CMP-001 | CMP-002 | All Slack I/O routes through the adapter |
| API-INT-006 | Internal call | Within-budget? / record usage + adoption | CMP-007 | CMP-002 | Cost guardrail + adoption recording |
| API-INT-007 | Internal call | Record feedback signal | CMP-007 | CMP-001 | Append-only feedback capture (Q4) |
| API-INT-008 | Internal call | Read configuration | CMP-008 | CMP-001, CMP-002, CMP-007 | Read-only operator config |
| API-INT-009 | Internal queue | Intake→worker enqueue / dequeue | (infra queue) | CMP-001 → CMP-002 | **The C-1 future extraction seam** |

### B.2 Operations

#### API-INT-001 — Run inference (the A-1 / Q4 stable seam)
| Field | Value |
|---|---|
| Purpose | Expose a backend-agnostic "run inference" operation so the orchestrator never sees backend specifics |
| Trigger | Worker iteration after the safety gate (BR-012) and within-budget check (BR-008) |
| Auth / Permission | In-process; backend credentials handled inside CMP-003 (NFR-5) |
| Input | Backend-agnostic prompt input (from `ConversationContext.assembled-prompt-input`) |
| Output | `InferenceExchange` (ENT-005): normalised model-output + token-usage + backend-id |
| Business rules | BR-012 (allowed input only), BR-014 (cap), BR-019 (usage reported) |
| Entities | ENT-005 |
| Errors | Typed inference failure (no model-output) → BR-013 |
| Versioning | **Stable interface is the contract; the concrete backend behind it (API-EXT-006) may change without breaking consumers.** This is the single most important internal seam (A-1) |

#### API-INT-002 — Job register / transition / recover
| Field | Value |
|---|---|
| Purpose | Own the ProcessingJob lifecycle: register-or-get by identity, transition state, detect lost in-flight jobs |
| Trigger | Intake registration (BR-010); worker state transitions; recovery scan (BR-021) |
| Auth / Permission | In-process |
| Input | `slack-event-identity` (channel-id, message-ts) for register; job-id + target state for transitions |
| Output | The `ProcessingJob` (ENT-008) and whether processing should start (new vs existing-incomplete vs complete) |
| Business rules | BR-010 (at-most-once), BR-011 (at-most-once-completed), BR-021 (recovery), BR-022 (bounded retries), BR-027 |
| Entities | ENT-008 |
| Errors | Identity already complete (resolved/failed) → signal "do nothing" (BR-011) |
| Versioning | Internal; durable store mechanism chosen in infrastructure-design |

#### API-INT-003 — Scan input for secrets
| Field | Value |
|---|---|
| Purpose | Pre-send safety gate: judge assembled input for secrets/credentials (CS-4) |
| Trigger | Before any inference/MCP call for the request (BR-012) |
| Auth / Permission | In-process |
| Input | `ConversationContext.assembled-prompt-input` |
| Output | `SafetyVerdict` (ENT-007): flagged, redacted findings, recommended-action (allow/warn/refuse) |
| Business rules | BR-012 (ordering + refuse-blocks-forward), BR-025 (policy enforcement), BR-026 (redacted only) |
| Entities | ENT-007 |
| Errors | On scanner error, fail safe (treat as refuse/warn per nfr-design A-6) |
| Versioning | Detection rules evolve on their own cadence (A-6); the verdict shape is stable |

#### API-INT-004 — Ground + cite
| Field | Value |
|---|---|
| Purpose | Internal wrapper over the MCP tools that returns citable sources or signals "no source" |
| Trigger | Worker grounds an AWS-fact answer (BR-009), post-safety-gate |
| Auth / Permission | In-process; MCP creds inside CMP-004 |
| Input | Query / tool arguments |
| Output | Zero-or-more `GroundingSource` (ENT-006); explicit "no source" signal |
| Business rules | BR-009, BR-014, BR-023 |
| Entities | ENT-006 |
| Errors | Failure/timeout → BR-013; no source → mark ungrounded (BR-009) |
| Versioning | Wraps API-EXT-004; internal shape stable |

#### API-INT-005 — Fetch replies / post message
| Field | Value |
|---|---|
| Purpose | Let the worker reconstruct context and post answers/failures without touching Slack directly |
| Trigger | Context assembly (BR-005); answer/failure posting (BR-013, W2) |
| Auth / Permission | In-process; Slack token inside CMP-001 |
| Input | Fetch: channel-id+thread-ts. Post: originating-message-ref + rendered content |
| Output | Fetch: ordered messages. Post: posted message coordinates |
| Business rules | BR-005, BR-013, BR-016, BR-017, BR-023, BR-026 |
| Entities | ENT-003, ENT-004 |
| Errors | Rate limit → backoff (BR-023) |
| Versioning | Wraps API-EXT-002/003; internal shape stable |

#### API-INT-006 — Within-budget? / record usage + adoption
| Field | Value |
|---|---|
| Purpose | The cost-guardrail decision and post-processing recording |
| Trigger | Before spend (BR-008); after each exchange and at terminal state (BR-019) |
| Auth / Permission | In-process |
| Input | Within-budget: current period. Record: token-usage/calls; author-id; outcome |
| Output | Within-budget: permit/deny. Record: updated `UsageCounter` (ENT-011), `AdoptionMetric` (ENT-009) |
| Business rules | BR-008 (within budget), BR-019 (atomic increments), BR-024 (reads threshold from CMP-008) |
| Entities | ENT-009, ENT-011, ENT-014 |
| Errors | Deny → failure path (BR-013); recording failure must not undercount usage (BR-019) |
| Versioning | Internal; store + consistency model in infrastructure-design |

#### API-INT-007 — Record feedback signal (append-only, Q4)
| Field | Value |
|---|---|
| Purpose | Append a 👍/👎 add/remove as an immutable feedback row |
| Trigger | CMP-001 forwards a normalised `ReactionEvent` (BR-018) |
| Auth / Permission | In-process |
| Input | answer-ref (correlation-id), reactor-id, signal, event-action, recorded-at |
| Output | Appended `FeedbackSignal` (ENT-010); success metric reads latest-per-(answer, reactor, signal) — each emoji resolved independently (BR-020) |
| Business rules | BR-018 (capture), BR-020 (append-only + aggregation), BR-026 |
| Entities | ENT-010 |
| Errors | Append failure logged; does not affect the original answer |
| Versioning | Internal; append-only log shape stable |

#### API-INT-008 — Read configuration
| Field | Value |
|---|---|
| Purpose | Read-only access to operator-set configuration |
| Trigger | Intake (allowlist); processing (usage policy / loop limits); budget (threshold) |
| Auth / Permission | In-process; read-only (BR-024) |
| Input | Configuration key (allowlist / usage-policy / guardrail) |
| Output | `ChannelAllowlist` (ENT-012), `UsagePolicy` (ENT-013), `GuardrailConfig` (ENT-014) |
| Business rules | BR-001, BR-008, BR-024, BR-025 |
| Entities | ENT-012, ENT-013, ENT-014 |
| Errors | Missing required config → fail-safe defaults where defined (e.g. non-allowlisted-behaviour=reply-not-designated) |
| Versioning | Internal; read-mostly |

#### API-INT-009 — Intake→worker enqueue / dequeue (the C-1 seam)
| Field | Value |
|---|---|
| Purpose | Decouple the always-on intake role from the independently-scalable worker role across a durable, out-of-process queue (C-1/C-4); the single future extraction seam |
| Trigger | Intake enqueues after ack (BR-004); worker dequeues to process |
| Auth / Permission | In-process producer/consumer to the infra queue (queue is infrastructure, not a component) |
| Input | Enqueue: job reference (job-id / slack-event-identity). Dequeue: next job for a worker |
| Output | A job handed to a worker; the queue must survive a worker crash so recovery (BR-021) can run |
| Business rules | BR-004 (enqueue on ack), BR-010/BR-011 (dequeue re-checks completion), BR-021 (lost-job recovery) |
| Entities | ENT-008 |
| Errors | Worker loss before resolution → in-flight recovery (BR-021/BR-022) |
| Versioning | **Internal now; if the worker extracts into its own unit, `contract-design` is reinstated and this becomes a cross-unit queue contract** |

---

## Open Questions

| Question | Blocks | Disposition |
|---|---|---|
| Concrete backend behind API-INT-001/API-EXT-006 (Kiro vs Bedrock) | Deployment wiring | infrastructure-design (A-1) |
| Auth scopes / secret-manager wiring for all external surfaces (NFR-5) | Credential security | nfr-/infrastructure-design |
| Queue + durable-store mechanism and consistency model for API-INT-002/006/009 | Concurrency & recovery durability | infrastructure-design (CS-1) |
| Numeric values: NFR-1 ack window, NFR-2 timeout, CS-5 cap, max-attempts, size limit, budget limits | Threshold enforcement | nfr-design (A-7/A-9) |
