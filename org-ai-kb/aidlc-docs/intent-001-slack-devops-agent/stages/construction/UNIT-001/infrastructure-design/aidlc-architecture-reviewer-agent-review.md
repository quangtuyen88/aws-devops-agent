# Architecture Review — Infrastructure Design (UNIT-001) — FINAL

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `infrastructure-design` (construction) · Unit: **UNIT-001** ·
> Reviewer: aidlc-architecture-reviewer-agent · Autonomy: **supervised**.
> Review iteration: 2 (final) · Reviewed: 2026-06-17.

## Verdict

**READY.**

All four blocking findings from review iteration 1 (F1–F4) are resolved correctly and
consistently across `infrastructure-specification.md`, `components.yaml`, and `unit.md`.
The three minor watch-items (F5–F7) are addressed in the spec text, not merely
acknowledged. The service mapping, security boundaries, observability design, timing
invariant, and NFR traceability are sound. One new minor item (F8) is recorded as a
carry-forward to code-generation — it does not block this stage.

## Scope reviewed (iteration 2)

- `infrastructure-specification.md` (now with §0 F-notes, §1 key-design note, §2.4 F5/F6
  notes, §9 findings-resolution table, §10 self-check), `components.yaml` infra appendix,
  `unit.md` infra appendix, `plan.md`, `questions.md`.
- Re-cross-referenced against `functional-design/entities.yaml` (ENT-008),
  `functional-design/functional-spec.md` (W4), and `nfr-design/nfr-spec.md` (§5 + targets).

## Verification of prior findings

### F1 — ProcessingJob dedup key — RESOLVED ✓
The spec now sets **PK = `slack-event-identity`** (`channel-id#message-ts`, ENT-008
`unique:true`) with a conditional `PutItem` on `attribute_not_exists(slack-event-identity)`
as the at-most-once-completed dedup mechanism (CS-3/NFR-19), and demotes **`job-id` to a
stamped, immutable `uuid` attribute** (== correlation-id, DA-1) that is explicitly *not*
the dedup key and *not* derived from `channel#message-ts` (optional GSI for correlation-id
lookup). The single-winner lease is a conditional `UpdateItem` on the same item. This now
matches `entities.yaml` ENT-008. `components.yaml` CMP-006 mapping updated in lock-step.
Verified consistent (§1 key-design note; components.yaml CMP-006 `storage`).

### F2 — Reaction/feedback ingestion path (W4/FR-16) — RESOLVED ✓
Reactions are now correctly modelled as **inbound** events: API Gateway → **intake**
Lambda, handled **synchronously**, appending `FeedbackSignal` to `OperationalData` via
CMP-007/API-INT-007 — **never** entering SQS or the worker. The matching IAM grant is
added: `intake-lambda-role` now holds `dynamodb:PutItem + Query/GetItem` on
`OperationalData` (append-only, **no `UpdateItem`**, per BR-018/BR-020/R-3). The prior
worker-outbound "reaction capture" text is removed. Verified across §1 CMP-001 row, §3
network notes, §4.2 IAM, components.yaml CMP-001/CMP-007.

### F3 — Recovery reaper — RESOLVED ✓
The **EventBridge Scheduler → reaper Lambda** is now a first-class mapped element: §1
service-mapping row, §4.1 secret consumption (`slack/bot-token`), §4.2
`reaper-lambda-role` (DynamoDB `UpdateItem/Query` on ProcessingJob, SQS receive/delete on
**DLQ only**, `secretsmanager:GetSecretValue` on `slack/bot-token` only, logs — no
data-plane perms beyond ProcessingJob), §6 `recovery` Terraform module, and components.yaml
CMP-006. It posts the FR-17 in-thread failure message using
`ProcessingJob.originating-message-ref` (confirmed durable on ENT-008) + `slack/bot-token`.
Least-privilege preserved. Verified.

### F4 — kiro-gateway availability model — RESOLVED ✓
`kiro-gateway` is now explicitly classified **OWN infrastructure** in the NFR-9
error-budget split (its token-refresh/task/AZ failures count against our budget; only the
upstream Kiro/Bedrock model backends + MCP remain on the dependency side). Failover
semantics are stated unambiguously: Kiro→Bedrock is an **operator-flipped
config/deploy-time** switch, **not** automatic per-request — on breaker-open, in-flight
jobs fail gracefully (FR-17) until cutover. In-band resilience is provided instead by
raising the Fargate baseline **1→2 tasks Multi-AZ (autoscale 2→4)**, removing the
single-point-of-failure for the primary path. Numbers are consistent across §2.3, §7
NFR-9, components.yaml CMP-003, and unit.md. Verified.

### F5 — visibility==staleness boundary race — ADDRESSED ✓
§2.4 now specifies an **inclusive `>=` reclaim check** (`now − last_transition_at >= 90s`)
as the primary resolution, requires the NFR-19 kill-worker test to assert the exact 90s
boundary, and notes an optional visibility margin (95s) as defense-in-depth.

### F6 — heartbeat-as-lease-refresh — ADDRESSED ✓
§2.4 states this as an **explicit liveness assumption**, explains why a starved-timer
reclaim is safe (single-winner lease + idempotent post BR-027 ⇒ at-most-once *completed*),
and directs code-generation to keep heartbeat emission off the critical CPU path.

### F7 — introduced 4,000 output-token value — ADDRESSED ✓
§0 item 1 and §7 NFR-14 flag the 4,000 reserved-output value as an **infra-introduced
tunable `Config` default**, explicitly *not* an nfr-design requirement (NFR-14 governs the
input budget only).

## New minor watch-item (does not block)

### F8 — Durable backing for the F2 `answer-message-ts → correlation-id` resolution
The inbound reaction path (F2) requires resolving a reaction's `answer-message-ts` (the
Slack ts of the bot's *answer* post) to the answer's `correlation-id` to key the
`FeedbackSignal` (BR-018). `Answer` (ENT-004) is transient and `ProcessingJob` carries
`originating-message-ref` (the *question* message), not the answer ts — so a durable
`answer-message-ts → correlation-id` record must be written when the worker posts the
answer for the intake `Query/GetItem` to resolve against. The granted IAM supports this
(worker `PutItem` on OperationalData; intake `Query/GetItem`), but **which write persists
this mapping, and the key/GSI it is queried by, is not spelled out**. This is an
entity/code-generation concern rather than an infra-design defect, and the IAM surface is
already correct — record it for confirmation at code-generation (or a functional-design
note), not as a blocker here.

## Summary

| ID | Finding | Iteration-1 severity | Status |
|----|---------|----------------------|--------|
| F1 | ProcessingJob PK conflated job-id with dedup key | Correctness (blocked) | Resolved ✓ |
| F2 | Reaction/feedback path mischaracterized; ingress+IAM unmapped | Completeness (blocked) | Resolved ✓ |
| F3 | Recovery reaper compute+IAM unmapped | Completeness (blocked) | Resolved ✓ |
| F4 | kiro-gateway availability/failover unclear | Resilience (blocked) | Resolved ✓ |
| F5 | visibility==staleness boundary race | Edge case | Addressed ✓ |
| F6 | heartbeat-as-lease-refresh dependency | Assumption | Addressed ✓ |
| F7 | introduced 4k output-token value | Documentation | Addressed ✓ |
| F8 | durable backing for answer-ts→correlation-id resolution | Documentation | Carry to code-generation |

No stable ID (CMP/ENT/NFR/UNIT/FR/BR/CS/A) was renamed; copy-forward expansions remain in
place. The open **AGPL-3.0 `kiro-gateway` licensing watch-item** is correctly carried to
the code-generation gate with Bedrock-primary as the ready fallback via the CMP-003 seam.

**This stage is ready to advance to code-generation.** F8 and the AGPL item should be
surfaced at that gate.
