# Personas

Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`)
Owner: aidlc-product-manager-agent
Source: `requirements.md`, `intent.md`. Persona set fixed by clarification Q1 (answer **a** —
add a lightweight Platform Operator). System stories have no human persona and are listed under
the System actor in `stories.md`.

---

## Developer

- **Role:** Software / DevOps engineer who designs, builds, and operates AWS workloads and asks the bot for help from within Slack.
- **Goals:**
  - Get a trustworthy answer to an AWS/DevOps question without leaving Slack or hunting through docs.
  - Have an architecture reviewed for risks, strengths, and improvements.
  - Get a concrete, buildable design (and ready-to-use IaC/code) for a target stack (e.g. Lambda + API Gateway + DynamoDB).
  - Understand cost/right-sizing and troubleshoot operational issues, grounded in AWS guidance.
- **Context:** Works inside a single Slack workspace, in dedicated allowlisted channels (e.g. `#devops-help`). Asks by `@mention`ing the bot in a channel or thread; iterates via thread follow-ups. Shares only internal/non-production content per the usage policy (NFR-3). Mobile or desktop Slack; expects code blocks and clickable citation links.
- **Pain points:**
  - Generic LLM answers fabricate AWS details or omit citations — hard to trust.
  - Re-pasting earlier context on every follow-up is tedious.
  - A request that hangs with no response (silent failure) is worse than a clear error.
  - Doesn't know whether an answer was based on real AWS docs or invented.
- **Stories:** S-1, S-6, S-7, S-8, S-9, S-10, S-11, S-13, S-14, S-25
  *(S-14 is the developer-facing rejection experience when mentioning the bot in a non-allowlisted channel.)*

---

## Platform Operator

- **Role:** The engineer/team responsible for configuring, governing, and operating the bot service for the workspace. A distinct hat from the question-asking Developer (a single person may wear both).
- **Goals:**
  - Control where the bot operates (which channels are allowlisted) without redeploying.
  - Keep inference/MCP cost within an agreed bound.
  - Publish and maintain the data-sensitivity usage policy so developers know what they may share.
- **Context:** Owns operational responsibility for one Slack workspace. Makes deliberate human decisions about governance: allowlist membership, cost-guardrail threshold, and the published usage policy. Scope is intentionally narrow — only configuration/governance with a real human decision. Pure runtime secret storage (NFR-5) is a cross-cutting acceptance criterion, **not** an operator story (per Q1).
- **Pain points:**
  - No clear owner/path for "which channels can use the bot?" leads to it being mentioned where it shouldn't answer.
  - Unbounded inference/MCP usage risks runaway cost with no visibility or cap.
  - If the usage policy isn't published, developers may paste secrets or production data.
- **Stories:** S-15, S-17, S-18
