# Clarification Questions — Story Generation

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Owner: aidlc-product-manager-agent

`requirements.md` (21 FRs, 10 NFRs, 9 assumptions, 6 out-of-scope, C-1..C-4) is detailed and
settled, so most story content can be derived directly. These two questions resolve the only
genuine ambiguities that change **which personas and stories exist** — i.e. the shape of the
artifact, not its wording. Everything else (story granularity, ordering, system-story modelling
of async/de-dup/bot-loop behaviour) is a decomposition-method decision I will make per the
story-decomposition skill and record in `plan.md`.

Progress: 2 questions (Q1–Q2).

---

### Q1: Is there an Operator / Platform Admin persona with their own stories?

Several requirements imply an actor who *configures and operates* the bot, distinct from the
developer who *asks questions*: FR-2 (channel allowlist), NFR-3 (publish the data-sensitivity
usage policy), NFR-5 (store credentials in a secret manager / least privilege), NFR-8 (set the
cost-guardrail thresholds). Requirements name only "developers" and "the system."

a) **Model an Operator/Platform Admin persona** with explicit user stories (e.g. "configure the
   channel allowlist", "rotate credentials", "set the cost guardrail", "publish the usage policy")
b) **No operator persona** — treat all configuration as deployment-time/IaC setup, covered later
   by infrastructure-design and (where runtime-relevant) by *system* stories, not user stories
c) Other

**Trade Offs:** (a) makes operational ownership explicit and gives the allowlist/guardrail
requirements a clear actor and testable stories, but adds config-management stories that are
arguably deployment concerns for a single-unit greenfield service. (b) keeps the story set
focused on the developer's question-answer journey and defers config to design, at the cost of
FR-2/NFR-5/NFR-8 having no user-facing story (they would still be covered by system stories +
NFRs as cross-cutting acceptance criteria, so coverage is not lost).

**Recommendation:** (a), but lightweight — a single **Platform Operator** persona owning just the
config/governance stories that have a real human decision (allowlist membership, guardrail
threshold, usage-policy publication). Pure secret storage (NFR-5) stays a cross-cutting criterion,
not a story. This keeps every requirement traceable to an actor without inflating the backlog.

[Answer]:

---

### Q2: Is *consuming* metrics & feedback in scope for this release, or capture-only?

FR-16 captures 👍/👎 helpfulness and FR-18 captures adoption metrics (distinct developers, questions
per week). The requirements specify **capture** but name no one who **views or reports** them, and
there is no dashboard in scope (OOS lists none either way).

a) **Capture-only this release** — record the signals (one system story per capture); viewing/
   reporting them is out of scope and deferred
b) **Include a consumption story** — e.g. "As a Platform Operator / team lead, I want a weekly
   adoption + helpfulness summary, so that I can report on the bot's value"
c) Other

**Trade Offs:** (a) matches the verbatim requirements (which say "records"/"captures", not
"reports") and keeps the release thin, but leaves the success metric (FR-18) captured yet unseen
by a human in v1. (b) closes the loop on the adoption goal but adds a reporting story whose output
format/destination is unspecified and would need its own clarification.

**Recommendation:** (a) — capture-only, with a note that a reporting/summary story is **deferred,
not deleted**. The data store for these signals is already permitted (A-8), so a future reporting
story can consume it without rework. This respects the requirements as written and avoids
inventing an unspecified reporting feature.

[Answer]:

---

## Human Answers (recorded 2026-06-17T09:57:32+08:00)

- **Q1: a** — Model a lightweight **Platform Operator** persona owning the config/governance
  stories with a real human decision (channel allowlist membership, cost-guardrail threshold,
  usage-policy publication). Pure secret storage (NFR-5) remains a cross-cutting acceptance
  criterion, not a standalone story.
- **Q2: a** — Capture-only for this release (one system story per captured signal). A
  reporting/summary story is deferred, not deleted; the A-8 data store allows it later without rework.
