# Clarification Questions — Requirements Analysis

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Owner: aidlc-product-manager-agent

These questions resolve ambiguity needed to write verifiable requirements. They are
product/scope questions. Deep technical mechanics (Kiro API surface, Slack transport,
hosting runtime) are left to the systems-architect contribution and later design stages.

Greenfield classification is already settled in `intent.md` — not re-asked.

Progress: 8 questions (Q1–Q8).

---

### Q1: Who are the users, and where in Slack can they reach the bot?

a) Developers only, in a small set of dedicated channels (e.g. `#devops-help`)
b) Developers only, anywhere — any channel, DM, or thread they invite the bot into
c) Anyone in the workspace (developers, PMs, ops), anywhere
d) Other

**Trade Offs:** (a) is easiest to control, govern, and measure adoption, but limits
reach. (b) maximises developer convenience but widens the surface for access control
and cost. (c) broadens the audience beyond the stated "Developer" user, risking scope
creep and off-topic load.

**Recommendation:** (b) — the verbatim intent names "Developer" as the user; let them
use the bot wherever they work (channels, DMs, threads), with access scoped to the
workspace. This keeps the audience focused while staying convenient.

[Answer]:

---

### Q2: How does a developer invoke the bot?

a) `@mention` the bot in a channel/thread
b) A slash command (e.g. `/devops <question>`)
c) Direct message (DM) to the bot
d) All of the above (mention + slash command + DM)

**Trade Offs:** A single entry point (a/b/c) is simpler to build and document. (a)
threads naturally into team conversations; (b) is discoverable and structured but
single-shot; (c) is private. (d) is the most flexible but multiplies the interaction
paths each requirement and story must cover.

**Recommendation:** (d) conceptually, but if we must scope for a first release, start
with (a) `@mention in channels/threads` + (c) `DM`, since both naturally support
follow-up conversation. Slash command can be a deferred enhancement.

[Answer]:

---

### Q3: Does the bot need multi-turn conversation memory?

a) Stateless — each question is answered independently, no memory of prior messages
b) Thread-scoped memory — the bot remembers earlier messages within the same Slack thread
c) Per-user persistent memory across threads and sessions
d) Other

**Trade Offs:** (a) is simplest and cheapest, but forces users to re-paste context on
every follow-up — poor experience for "review my architecture" dialogues. (b) matches
how Slack threads already work and supports natural follow-ups at modest cost. (c) adds
storage, privacy, and retention obligations.

**Recommendation:** (b) — thread-scoped memory. Architecture reviews and solution
design are inherently iterative; remembering the thread is the minimum that makes the
experience usable without taking on persistent-storage and privacy burdens.

[Answer]:

---

### Q4: Which question types are in scope for the first release?

a) Architecture review + solution design guidance only (as stated in the intent)
b) (a) plus cost estimation / right-sizing guidance
c) (a) plus operational troubleshooting (e.g. "why is my Lambda throttling?")
d) (a) plus generating ready-to-use IaC / code snippets (Terraform, CDK, SAM)

**Trade Offs:** (a) keeps scope tight and matches the verbatim intent, making success
measurable. (b), (c), (d) each add value but also add distinct flows, grounding needs,
and acceptance criteria. Bundling everything risks a vague, hard-to-verify first release.

**Recommendation:** (a) as the committed scope, with (d) IaC snippets noted as a
likely fast-follow since "help build solutions" implies some buildable output. Treat
(b) and (c) as out-of-scope-for-now (deferred, not deleted).

[Answer]:

---

### Q5: What depth and grounding should answers have?

a) Concise answer only — direct recommendation, no sources
b) Concise answer + citations/links to the AWS docs the MCP server returned
c) Detailed answer (rationale, trade-offs, alternatives) + AWS doc citations
d) Other

**Trade Offs:** (a) is fast but unverifiable and lower-trust for architecture decisions.
(b) adds trust and traceability at little cost. (c) is most useful for genuine
architecture reviews but is slower and more verbose in a chat surface.

**Recommendation:** (c) for architecture-review questions and (b)-style citations as a
baseline everywhere. Grounding answers in `aws-knowledge-mcp-server` sources is the
core value proposition — citing them should be a hard requirement, not optional.

[Answer]:

---

### Q6: What is the acceptable response time, and how should waiting be handled?

a) Synchronous — answer must return within a few seconds, no progress indicator
b) Acknowledge immediately ("working on it…") then post the full answer when ready
c) No latency expectation — answers can take as long as needed
d) Other

**Trade Offs:** Agent loops that call MCP tools and an LLM routinely exceed Slack's
~3s synchronous response window, so (a) is technically risky. (b) sets a realistic UX
and gives us a measurable NFR (ack < 3s; full answer < target). (c) leaves no
verifiable performance criterion.

**Recommendation:** (b) — immediate acknowledgement, then the grounded answer. Please
confirm a target for the full answer (proposed: p95 ≤ 30s) so it becomes a measurable NFR.

[Answer]:

---

### Q7: What may developers share with the bot, and are there data-sensitivity limits?

a) No restriction — developers may paste any architecture, config, code, or identifiers
b) Internal/non-production content only — no secrets, credentials, PII, or customer data
c) Strict — bot must warn or refuse if it detects secrets/credentials in input
d) Other

**Trade Offs:** (a) is frictionless but risks secrets/PII flowing to the inference
provider and MCP calls. (b) sets a clear policy boundary that becomes an NFR and a
usage guideline. (c) adds detection complexity but materially reduces leak risk.

**Recommendation:** (b) as the stated policy (documented usage guideline + NFR), with
(c) secret-detection flagged as a desirable safeguard to assess in nfr-design. This
matters because inputs leave Slack and reach external services (Kiro inference, MCP).

[Answer]:

---

### Q8: How will we judge whether this bot is successful?

a) Adoption — number of developers and questions handled per week
b) Quality — developers rate answers as helpful (e.g. 👍/👎 reaction on each answer)
c) Deflection — reduction in questions routed to senior architects / DevOps team
d) A combination (please indicate which)

**Trade Offs:** Without an explicit success measure, requirements can't be validated as
delivering value. (a) is easy to capture; (b) measures real usefulness but needs a
feedback mechanism (which itself becomes an FR); (c) is the truest business outcome but
hardest to attribute.

**Recommendation:** (d) — combine (a) adoption + (b) a lightweight 👍/👎 helpfulness
signal. If (b) is accepted it adds an FR for capturing reactions; please confirm so I
can include it.

[Answer]:

---

## Human Answers (recorded 2026-06-17T09:33:18+08:00)

- **Q1: a** — Developers only, in a small set of dedicated channels (e.g. `#devops-help`).
- **Q2: a** — Invoked by `@mention` in a channel/thread.
- **Q3: b** — Thread-scoped conversation memory.
- **Q4: a + b + c + d** — ALL question types in scope for v1: architecture review,
  solution design guidance, cost estimation / right-sizing, operational troubleshooting,
  AND ready-to-use IaC/code snippets (Terraform, CDK, SAM). (Scope expansion vs. intent
  minimum — explicitly chosen by the human.)
- **Q5: c** — Detailed answers (rationale, trade-offs, alternatives) WITH AWS doc citations.
  Citations grounded in `aws-knowledge-mcp-server` are a hard requirement.
- **Q6: b** — Acknowledge immediately ("working on it…"), then post the full answer.
  Full-answer target: p95 ≤ 30s assumed as default (flag as assumption; revisit in nfr-design).
- **Q7: b + c** — Internal/non-production content only (no secrets, credentials, PII, customer
  data) AS POLICY, PLUS the bot must warn/refuse when it detects secrets/credentials in input.
- **Q8: a + b** — Success measured by adoption (devs + questions/week) AND a lightweight
  👍/👎 helpfulness signal. (Q8b accepted → add an FR for capturing reaction feedback.)
