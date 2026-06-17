# NFR Design — Clarification Questions

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `nfr-design` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-systems-architect-agent · Status: `plan-and-clarify`.
>
> These resolve the concrete **numeric thresholds and quality postures** that earlier
> stages deliberately deferred to nfr-design (A-3, A-6, A-7, A-9, NFR-8/9/10) and that
> need a human/business decision because they encode budget appetite, UX tolerance, and
> security posture — not just engineering judgement. Items under my own architectural
> authority (tech stack, retry/backoff mechanics, circuit-breaker pattern, observability
> signals, concurrency mechanism) are recorded as **recommendations in `plan.md`**, not
> here. Each question carries a recommendation; "go with recommendations" is a valid
> answer to all.

---

### Q1 of 5: Confirm or adjust the full-answer latency target (NFR-2 / A-3).

NFR-1 (ack p95 < 3s) is fixed by Slack's retry window and is not in question. NFR-2's
full-answer target of **p95 ≤ 30s** was a working default chosen at requirements time
(A-3, flagged for confirmation here). A grounded answer runs: inference + 1..N MCP tool
calls (CS-5 cap) + answer composition — each MCP round-trip and the model generation add
seconds.

a) **Keep p95 ≤ 30s** as the full-answer SLO; add a **"still working…" heartbeat** posted
   in-thread at ~15s so the user is not left staring at a bare ack on slow answers.
b) **Relax to p95 ≤ 45s** (with the 15s heartbeat) — more headroom for multi-tool grounding
   and large architecture reviews, fewer timeouts counted as failures.
c) **Tighten to p95 ≤ 20s** — snappier, but raises the risk that complex grounded answers
   trip the timeout and resolve as `failed`.
d) Other / a different number.

**Trade Offs:** (a) honours the existing default and the heartbeat removes the "is it
stuck?" anxiety without changing the budget. (b) buys reliability headroom for the heavy
architecture-review path (FR-9) at the cost of a slower worst case. (c) feels best when it
works but will inflate the `failed` rate (Q2-Q-of-functional-design terminal) on exactly
the high-value complex questions.

**Recommendation:** **a**. Keep ≤ 30s and add the 15s heartbeat. It preserves the
traceable A-3 default, and the heartbeat is a cheap UX win that decouples *perceived*
latency from the hard SLO. (NFR-2 stays the SLO; the heartbeat is an additive UX rule.)

[Answer]:

---

### Q2 of 5: Set the cost guardrail — thresholds and behaviour on exceed (NFR-8 / A-7).

NFR-8 requires a bound on inference/MCP usage to prevent runaway cost; A-7 defers the
actual numbers to here. Two levers: a **per-request cap** (max inference calls + max MCP
tool calls per question — already shaped by the CS-5 grounding cap) and a **per-period
cap** (a rolling budget across the workspace). And a **behaviour** when a cap is hit.

a) **Per-request cap only** — bound each question (e.g. ≤ 2 inference calls, ≤ 5 MCP tool
   calls per question); no workspace-wide period budget. On exceed within a request →
   resolve `failed` with a clear in-thread message.
b) **Per-request cap + per-period soft budget** — the per-request cap above, **plus** a
   rolling daily/weekly request budget that, when exceeded, **degrades gracefully**
   (queues / posts "daily capacity reached, try later") rather than hard-failing silently.
c) **Per-request cap + per-period hard cap** — same, but the period budget **hard-stops**
   new questions until the window resets.
d) Other / specify your own numbers and behaviour.

**Trade Offs:** (a) is the simplest real guardrail and directly caps the dominant cost
driver (per-question fan-out), but a runaway *volume* of questions could still accumulate
cost. (b) adds a backstop against volume runaway while staying user-friendly, at the cost
of a small amount of budget-tracking state in CMP-007 (already the budget owner per CS-1).
(c) is the safest for cost but the bluntest for users — a hard stop mid-day is a poor
experience for an internal helper tool.

**Recommendation:** **b**. The per-request cap stops per-question runaway; a per-period
**soft** budget backstops volume runaway without a jarring hard cutoff. CMP-007 already
owns the within-budget decision (CS-1/NFR-8), so the period counter lives where it belongs.
I will propose concrete starting numbers in the artifact (e.g. ≤ 2 inference / ≤ 5 MCP per
request; period budget tuned to expected weekly question volume) for you to adjust.

[Answer]:

---

### Q3 of 5: Set the availability target (NFR-9), bounded by external dependencies.

NFR-9 is **dependency-bounded** (C-3): the bot can never be more available than Kiro
inference + `aws-knowledge-mcp-server`. The target here is the bot service's **own** SLO,
within that ceiling, and the operating window.

a) **Business-hours best-effort** — target ~99% availability during defined business hours
   (e.g. Mon–Fri 08:00–18:00 local); no overnight/weekend SLO. Matches a single-workspace
   internal dev-help tool (A-5).
b) **24/7 best-effort** — target ~99% around the clock; monitored continuously.
c) **24/7 with a higher SLO** — e.g. 99.9%, with the operational investment (alerting,
   on-call, redundancy) that implies.

**Trade Offs:** (a) right-sizes the SLO and the operational/observability investment to an
internal tool used during the workday, and is honest about the dependency ceiling. (b)
covers off-hours users at a modestly higher monitoring cost but the same architecture. (c)
implies real on-call and redundancy spend that is hard to justify for an internal advisory
bot and is largely capped by the external dependencies anyway.

**Recommendation:** **a**. Business-hours best-effort (~99% in-window), explicitly noted as
dependency-bounded, with the bot reporting external-dependency outages as graceful in-thread
failures (FR-17) rather than counting them against an unachievable SLO. Off-hours requests
are still served best-effort, just not under SLO.

[Answer]:

---

### Q4 of 5: Set the secret/credential-detection posture (FR-15 / NFR-4 / A-6).

A-6 says detection is best-effort/heuristic and the **behaviour** (warn vs hard-refuse) is
decided here. The non-negotiable invariant is NFR-4: flagged input is **never** forwarded
to inference or MCP. The fork is what the *user* experiences when input is flagged.

a) **Hard refuse** — on a positive detection, the bot does not process the question at all;
   it replies in-thread explaining a secret/credential pattern was detected and asks the
   user to remove it and re-ask. No override.
b) **Refuse with explicit re-ask** — same as (a), but the message names *what kind* of
   pattern matched (e.g. "looks like an AWS access key") to help the user redact and retry.
c) **Warn + user override** — warn the user, and let them explicitly confirm ("send anyway")
   to proceed. (Note: this would forward flagged content on override, which **conflicts with
   NFR-4** as currently written — choosing this means amending NFR-4.)

**Trade Offs:** (a)/(b) keep NFR-4 intact (flagged input never leaves the boundary) and are
the safe default for a tool whose data-policy (NFR-3) already forbids secrets. (b) is
strictly more helpful than (a) at no extra risk — naming the matched class is guidance, not
the secret itself. (c) is the most flexible for false positives but breaks the NFR-4
guarantee and pushes a security decision onto users; not advisable for a shared channel.

**Recommendation:** **b**. Hard-refuse-and-re-ask, naming the matched pattern class (never
echoing the secret value — NFR-6). Preserves NFR-4 with no override path, and the named
class turns a refusal into actionable guidance. Detection stays heuristic (curated regex
set for common AWS keys, tokens, private keys, connection strings); I will document the
starting rule set and its known best-effort precision/recall limits in the artifact.

[Answer]:

---

### Q5 of 5: Set the max input size and oversize behaviour (FR-21 / A-9 / C-2).

A question plus accumulated thread context (FR-4) can exceed the inference model's context
window. A-9/C-2 defer the **size limit** and the **truncation-vs-reject** behaviour to here.
The numeric token budget is partly bound by the model (an infrastructure-design input), so
here we fix the **policy shape** and a conservative default; the exact token number is
finalised against the chosen model in infrastructure-design.

a) **Truncate-with-notice** — when input exceeds the budget, keep the most recent thread
   context + the current question, drop the oldest context, and post an in-thread notice
   that earlier context was trimmed. Never silently truncate.
b) **Reject-and-ask** — when input exceeds the budget, do not process; reply that the input
   is too large and ask the user to shorten it or start a fresh thread.
c) **Hybrid** — truncate-with-notice for moderate overflow (drop old thread context), but
   reject-and-ask if the *current question alone* still exceeds the budget after trimming.

**Trade Offs:** (a) maximises "it just works" but a silently-relevant earlier message could
be the one dropped, subtly degrading the answer (the notice mitigates this). (b) is the most
predictable and never produces a context-starved answer, but is the most disruptive — it
makes the user do the work. (c) gets the best of both: trim recoverable overflow, only
reject when even the bare question can't fit.

**Recommendation:** **c**. Hybrid. Trim old thread context with a notice for normal overflow
(common, recoverable), and reject-with-guidance only when the current question itself can't
fit (rare, genuinely un-processable). This honours FR-21's "no silent truncation" and ties
cleanly to the `failed` terminal only in the genuinely-impossible case. Conservative default
budget proposed in the artifact, finalised vs the model in infrastructure-design.

[Answer]:

---

> After answers: items confirmed here become measurable rows in `nfr.yaml` (with concrete
> numbers and verification methods) and design narrative in `nfr-spec.md`. Anything left to
> the chosen model/runtime (exact token budget, concurrency instance count) is explicitly
> handed to infrastructure-design with the *policy* fixed here.

---

## Human Answer (recorded 2026-06-17T13:38:12+08:00)

**"go with recommendations"** — accept all five, and the plan.md architecture-authority
choices (Python 3.12 + Slack Bolt, async/idempotent workers, retry+backoff+circuit-breaker,
observability-as-NFR-verification):
- **Q1: a** — NFR-2 full-answer SLO stays p95 ≤ 30s; add a "still working…" heartbeat at ~15s.
- **Q2: b** — Per-request cap (≤2 inference / ≤5 MCP calls per question) PLUS a per-period
  rolling SOFT budget that degrades gracefully ("daily capacity reached, try later"), owned
  by CMP-007. Owner proposes concrete starting numbers in nfr.yaml.
- **Q3: a** — Business-hours best-effort ~99% (in-window), explicitly dependency-bounded (C-3);
  external-dependency outages reported as graceful in-thread failures (FR-17), not counted
  against the SLO. Off-hours served best-effort, not under SLO.
- **Q4: b** — Hard-refuse-and-re-ask on secret detection, naming the matched pattern class
  (never echoing the secret value, NFR-6), NO override path. NFR-4 invariant preserved.
  Detection is heuristic (curated regex for AWS keys/tokens/private keys/connection strings);
  document best-effort precision/recall limits.
- **Q5: c** — Hybrid oversize handling: trim oldest thread context with an in-thread notice
  for normal overflow; reject-and-ask only when the current question alone exceeds the budget.
  No silent truncation (FR-21). Conservative default token budget in nfr.yaml; exact number
  finalised vs the chosen model in infrastructure-design.
