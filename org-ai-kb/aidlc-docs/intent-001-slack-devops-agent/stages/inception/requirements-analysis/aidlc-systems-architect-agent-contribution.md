# Systems Architect Contribution — Requirements Analysis

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Contributor: aidlc-systems-architect-agent
Role: technical feasibility, constraints, NFR soundness, risk surfacing
Reviewed artifact: `requirements.md` (FR-1..FR-18, NFR-1..NFR-9, A-1..A-8, OOS-1..OOS-6)

## Verdict

The requirements are well-formed, traceable, and verifiable. They are **feasible to
build with one material exception**: the Kiro-backed inference path (FR-5 / A-1) is an
unvalidated dependency that could invalidate the core design. Everything else is
standard integration engineering. Below are the specific constraints, risks, and gaps
the design stages must carry forward. Nothing here blocks exiting requirements-analysis;
the items marked **[VALIDATE-NOW]** should be de-risked before functional-design commits.

---

## 1. Feasibility assessment per requirement area

### Kiro inference (FR-5, A-1) — highest risk **[VALIDATE-NOW]**
- The intent assumes the "Kiro subscription" exposes a *programmatic, headless* inference
  API. Kiro is primarily an interactive agent/CLI surface; it is **not confirmed** to
  offer a server-to-server inference endpoint with API-key auth suitable for an
  always-on backend service. This is the single assumption that can force a redesign.
- A-1 correctly treats this as a pluggable abstraction and defers the API surface to
  infrastructure-design. That is the right hedge. **Recommendation:** make the
  provider abstraction (FR-5) explicit enough that a fallback inference backend
  (e.g. Amazon Bedrock) can drop in without touching agent-core logic. Suggest adding a
  note to A-1: "If no Kiro programmatic surface exists, the abstraction must support an
  alternate backend; this is a known fork resolved in infrastructure-design."
- Risk if unaddressed: FR-5, FR-8, FR-9–FR-13 all depend on inference working; a late
  discovery that Kiro has no API stalls the whole construction phase.

### Slack intake & acknowledgement (FR-1, FR-3, NFR-1) — feasible, with a hard constraint
- `@mention` maps to the Slack `app_mention` event (Events API) or Socket Mode.
- **Hard platform constraint:** Slack requires an HTTP 200 to the event callback within
  **3 seconds** or it retries the delivery (up to 3x, with `X-Slack-Retry-Num`). The
  agentic loop (LLM + MCP calls, NFR-2 ≤ 30s) cannot complete inside that window.
  This makes the ack-then-answer pattern (FR-3 / NFR-1) not just a UX choice but an
  **architectural necessity**: the handler must accept-and-enqueue, return 200
  immediately, and process asynchronously. The requirements already imply this; flag it
  explicitly so functional-design provisions an async worker / queue and does not attempt
  synchronous processing.
- Socket Mode removes the public-endpoint requirement and is the lower-friction transport
  for a single-workspace internal tool (A-5). Events API needs a public HTTPS endpoint
  and request-signature verification. Transport choice belongs in infrastructure-design;
  recording the trade-off here.

### MCP grounding & citations (FR-6, FR-7, A-2) — feasible
- `aws-knowledge-mcp-server` is AWS's remote MCP server exposing documentation
  search / read / recommend tooling and returns source URLs, so mandatory citations
  (FR-7) are achievable from real returned sources. A-2's "state ungrounded rather than
  fabricate" rule is the correct failure behaviour and is testable.
- Constraint to carry: it is an **external network dependency** with its own latency and
  rate limits — folds directly into NFR-2 (latency budget) and NFR-7 (rate-limit
  handling). The agent loop may issue multiple MCP calls per question; each is a latency
  contributor against the 30s budget.

### Latency target (NFR-2, A-3) — feasible but tight; treat as a budget
- A multi-step agentic loop (think → search docs → read docs → synthesise) routinely
  costs tens of seconds. p95 ≤ 30s is **achievable but not generous**. Recommend
  functional-design cap the agent's tool-call iterations and define a hard timeout that
  triggers FR-17 (graceful failure) rather than letting a request run unbounded.
- The 30s is end-to-end and includes external MCP + inference round-trips not fully under
  our control. Keep A-3 flagged; revisit with a measured budget in nfr-design.

### Capability coverage (FR-9–FR-13) — feasible
- Architecture review, solution design, cost/right-sizing, troubleshooting, and IaC
  snippet generation (Terraform/CDK/SAM) are all LLM-output behaviours grounded by MCP.
  No additional external integration is required beyond inference + MCP. The scope
  expansion (Q4 a+b+c+d) increases prompt/answer breadth but **not** architectural
  surface area — acceptable. OOS-3 (no execution/deploy of IaC) keeps this bounded and
  removes the need for any AWS write credentials, which materially simplifies NFR-5.

### Secret detection (FR-15, NFR-4, A-6) — feasible as best-effort
- Heuristic/regex pattern matching (key prefixes, token shapes, high-entropy strings) is
  the realistic mechanism; A-6 correctly frames precision/recall as a nfr-design concern.
  NFR-4 (non-propagation) is testable with known secret patterns. Sound as written.

### Feedback & metrics (FR-16, FR-18) — feasible, but see gap G-4
- `reaction_added` events capture 👍/👎 (FR-16). Adoption metrics (FR-18) require a
  **durable store** for counts — see the tension with A-8 in Gaps below.

---

## 2. Constraints to carry into design (record, do not solve here)

- **C-1 (Slack 3s ack):** async accept-and-enqueue is mandatory, not optional. → functional/infra-design.
- **C-2 (Token/context budget):** thread context (FR-4) + pasted architecture can exceed
  the inference model's context window. A max-input / context-truncation policy is needed.
  Not currently captured by any FR/NFR. → see G-2.
- **C-3 (External dependency availability):** Kiro inference and the MCP server are both
  external; bot availability (NFR-9) is bounded by theirs. NFR-9 should acknowledge
  dependency-bounded availability rather than an absolute number.
- **C-4 (Single deployable unit, A-4):** the ack-then-answer split implies at least an
  intake path + an async worker path *within* one unit. This is compatible with A-4 (one
  deployable) but functional-design must show the internal async boundary.

---

## 3. Gaps / missing requirements (recommend the owner add)

- **G-1 (Slack event idempotency / retry de-dup):** Slack re-delivers events when no 200
  arrives in 3s (`X-Slack-Retry-Num`). Without de-duplication the bot can process and
  answer the same question multiple times. Recommend a new FR: "duplicate Slack event
  deliveries for the same message are processed at most once." Verifiable, and directly
  caused by C-1.
- **G-2 (Input size bound):** No requirement bounds the size of a question or accumulated
  thread context (C-2). Recommend an FR or NFR: define max input size / truncation
  behaviour, with a clear user-facing message when input is too large (ties to FR-17).
- **G-3 (Self-/bot-message loop prevention):** No requirement states the bot must ignore
  its own messages and other bots' messages. Without it, a bot answer that contains an
  `@mention` could re-trigger the bot. Recommend an explicit exclusion FR (cheap, prevents
  infinite loops).
- **G-4 (Metrics durability vs A-8):** FR-18 needs persisted counts (distinct developers,
  questions/week) and FR-16 needs persisted feedback signals, but A-8 says no durable
  cross-session store. These are not contradictory — metrics/feedback are *aggregate
  operational data*, not *conversation memory* — but the requirements should state that
  explicitly so units-generation doesn't read A-8 as "no datastore at all." Recommend
  clarifying A-8: "ephemeral applies to *conversation* memory; a minimal metrics/feedback
  store is permitted and required by FR-16/FR-18."
- **G-5 (Concurrency):** No requirement addresses simultaneous questions from multiple
  developers/channels. Implied-but-unstated. Recommend an NFR noting the service must
  handle N concurrent in-flight questions without head-of-line blocking (relevant to the
  async-worker sizing in infra-design).

These are additive and low-effort; none change the committed scope.

---

## 4. Prioritization view (risk-first)

1. **Validate Kiro programmatic inference (A-1/FR-5)** — highest risk; can invalidate the
   design. De-risk before functional-design commits.
2. **Async ack-then-answer + Slack idempotency (FR-3/NFR-1/C-1/G-1)** — core mechanic;
   high value, well-understood, must be designed correctly first.
3. **MCP grounding + citations (FR-6/FR-7)** — core value proposition; feasible, medium
   effort.
4. **Inference/MCP failure & rate-limit handling (FR-17/NFR-7)** — reliability backbone;
   medium effort.
5. **Capability breadth (FR-9–FR-13), feedback/metrics (FR-16/FR-18), secret detection
   (FR-15)** — high value but lower architectural risk; layered on the core.

## 5. Items explicitly NOT changing

- No objection to any committed scope decision (Q1–Q8). The scope expansion in Q4 is
  architecturally low-cost as noted.
- OOS-3 (no IaC execution) should be preserved — it keeps AWS write credentials out of
  the system entirely and simplifies NFR-5 (least privilege).
