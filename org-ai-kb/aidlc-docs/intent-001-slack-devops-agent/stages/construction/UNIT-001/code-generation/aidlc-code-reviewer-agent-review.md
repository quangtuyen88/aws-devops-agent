# Code Review — UNIT-001 (Slack DevOps Agent), stage `code-generation`

> Reviewer: aidlc-code-reviewer-agent · Verdict: **READY**
> Scope reviewed: `src/slack_devops_agent/` + `tests/` against functional-design,
> nfr-design, infrastructure-design artifacts and the stage `implementation-map.md`.

## Verdict

**READY.** The generated application code and tests realise the approved design with
clean boundaries, verifiable rule traceability, a safe-by-default security posture, and
all quality gates green. No blocking findings.

## Verification (independently re-run, not trusted from the map)

| Gate | Command | Result |
|---|---|---|
| Lint | `uv run ruff check src tests` | ✅ all checks passed |
| Format | `uv run ruff format --check src tests` | ✅ 63 files formatted |
| Types (strict) | `uv run mypy` | ✅ no issues, 50 source files |
| Security | `uv run bandit -r src/` | ✅ 0 issues (all severities) |
| Tests | `uv run pytest` | ✅ 96 passed |
| Coverage | `uv run pytest --cov` | 88% overall |

Key regression tests confirmed present: inclusive-90s recovery boundary, stale-job
recover-then-resolve, and safety-refuse-blocks-inference (`tests/test_worker.py`,
`tests/test_adapters.py`, `tests/test_domain.py`).

## Strengths

- **Hexagonal boundaries hold.** Pure domain (`domain/rules.py`, `entities.py`) is I/O-free;
  all external coupling sits behind `ports/` Protocols with adapters per component. Dependency
  direction points inward to stable abstractions — no circular flows observed.
- **Rule traceability is real.** BR-001..027 each map to a named, tested function/site; the
  `implementation-map.md` matches the code (spot-checked BR-007/008/011/012/014/016/019/027).
- **Security posture is correct-by-default.**
  - Slack signature verified in `lambda_intake` before any processing; invalid → 401.
  - Safety scanner (CS-4) runs *before* inference/MCP, is refuse-or-allow only, fails **safe
    to refuse** on scanner error, and emits only redacted class descriptors (no raw secrets).
  - `kiro_gateway` is strictly an HTTP client; AGPL boundary documented and respected (no
    vendoring/import); raw prompt is not echoed into the transient exchange.
  - `Answer` model validator enforces BR-015/BR-016 grounding/structure invariants at the
    type boundary.
- **Failure handling is explicit.** Every terminal cause routes to a posted FR-17 message +
  `failed` transition (BR-013); single-winner lease + idempotent post (BR-027) bound
  duplicates; budget/cap/timeout/oversize all have named causes and metrics.

## Non-blocking observations (accept for this slice)

1. **BR-027 repost-window residual (MINOR-b, already documented).** A crash in the narrow
   window between a successful Slack post and the `stamp_answer_ts` write can let a
   recovery-spawned worker post a second answer. Bounded to at-most-one duplicate by the
   single-winner lease and Slack event de-dup. Accepted for UNIT-001; follow-on hardening
   (transactional post+stamp or pre-post intent marker) is correctly tracked.
2. **Dead-ish WARN branch in `orchestrator._run_pipeline`.** The scanner never returns
   `WARN` (refuse-or-allow only), so the WARN post path is unreachable today. Harmless and
   defensive given the `SafetyAction.WARN` enum member; consider removing or covering if the
   scanner posture changes.
3. **`message` event type routed as a mention candidate** in `dispatch_slack_event`. The
   `mentions_bot` filter correctly drops non-mentions, but subscribing to `message` events
   broadens intake invocations — confirm the Slack event subscription scope at deploy time.
4. **Coverage gaps are the documented thin AWS wrappers** (`lambda_worker`/`lambda_reaper`
   at 0%, `wiring`/`dispatch` partial), deferred per Q4=a to post-deploy integration.
   Acceptable; the core logic they delegate to is well covered.

## Deferred (out of scope this pass, correctly flagged)

- Terraform IaC (9 modules) — follow-on slice (Q1=a).
- NFR-11 periodic heartbeat emission — runtime wiring concern; text/cadence defined.
- F8 ENT-008 in-place expansion — flagged for systems-architect confirmation; stable ID
  preserved, no new entity introduced.

No changes required to reach READY. The above items are tracked follow-ons, not gaps.

---

## Follow-on increment review (Terraform IaC + NFR-11 + BR-027) — Verdict: **READY**

> Scope: `infra/terraform/` (9 modules + gateway autoscaling), NFR-11 heartbeat
> (`components/worker/heartbeat.py` + worker wiring), BR-027 pre-post intent marker
> hardening (MINOR-b), and their tests. Reviewed against infra-spec §1–§6, nfr-spec
> (NFR-11), rules.yaml (BR-027), and the stage `plan.md` / `implementation-map.md`.

### Verification (independently re-run)

| Gate | Command | Result |
|---|---|---|
| TF format | `terraform fmt -check -recursive` | ✅ FMT_OK |
| TF validate | `terraform init -backend=false && terraform validate` | ✅ Success, configuration valid |
| Lint | `uv run ruff check src tests` | ✅ all checks passed |
| Format | `uv run ruff format --check src tests` | ✅ 65 files formatted |
| Types (strict) | `uv run mypy` | ✅ no issues, 51 source files |
| Security | `uv run bandit -r src/` | ✅ 0 issues (all severities) |
| Tests | `uv run pytest` | ✅ 105 passed (+9 vs prior) |
| Coverage | `uv run pytest --cov=src` | 88% |

### NFR-11 heartbeat — fidelity confirmed
- `HeartbeatEmitter` posts `HEARTBEAT_TEXT` on a daemon `threading.Thread` driven by a
  `threading.Event`, kept **off the critical CPU path** (infra-spec §2.4/F6). Context-manager
  start/stop guarantees the timer halts on both success and failure paths (BR-013, no dangling
  timer). Beat failures are logged-and-swallowed (best-effort UX, never fails the job).
- Worker wires it via an injectable `heartbeat_factory`; production uses the real emitter,
  tests inject a recorder. Cadence parameterised (`HEARTBEAT_SECONDS`, default 15s) and
  threaded through Terraform env vars for both intake and worker.
- Tests cover beat/count, post-failure swallow, real-thread emit-then-stop, fast-block silence,
  worker enter/exit wiring, and the default-emitter silence + no-lingering-thread assertion.

### BR-027 hardening (MINOR-b) — repost window closed
- `ProcessingJob.post_intent_at` is a pre-post intent marker; `post_attempted` returns True on
  intent OR answer-ts. The worker's early idempotency check now uses `post_attempted` and the
  success path stamps the intent **before** the Slack post (verified in `orchestrator.process`).
- `DynamoJobCoordinator.mark_post_intent` is idempotent via `attribute_not_exists` conditional
  update — the first attempt's marker survives a reclaim.
- Regression tests confirm the closed window: `test_reclaim_with_only_post_intent_does_not_repost_br027`,
  `test_happy_path_stamps_post_intent_before_resolving_br027` (test_worker.py) and
  `test_mark_post_intent_is_idempotent` (test_adapters.py, moto). Prior MINOR-b observation is
  now resolved, not just tracked.

### Terraform — fidelity confirmed
- 9 modules per infra-spec §6. `security` scopes IAM to ARNs **constructed from the name
  prefix**, consuming no other module outputs — cleanly breaks the KMS↔ARN dependency cycle.
- Least-privilege IAM per role (intake/worker/reaper/gateway-task/gateway-execution): scoped
  actions + specific ARNs, no wildcards; Bedrock invoke gated on a non-empty model-ARN list;
  feedback table is append-only (no UpdateItem on intake).
- Timing invariant in lock-step: budget 30s / Lambda 45s / SQS visibility 90s / lease staleness
  90s / maxReceiveCount 3 — all single-sourced from root variables and threaded consistently.
- F8 `answer-ts-index` GSI projects `job_id` (INCLUDE) — matches the adapter's `resolve_answer_ts`.
- Gateway autoscaling: Application Auto Scaling target 2→4 on `ECSServiceAverageCPUUtilization`
  (target-tracking), internal ALB with TLS1.3 listener, deployment circuit breaker w/ rollback,
  private-only SGs (ALB ← worker SG; tasks ← ALB only).
- Security posture: customer-managed KMS CMK (rotation on) across all 3 DynamoDB tables + SQS +
  DLQ + secrets + log groups; PITR on all tables; secrets in Secrets Manager (values out-of-band);
  worker in private subnets with VPC endpoints (DynamoDB gateway; SQS/Secrets/KMS/Bedrock
  interface) keeping AWS-API traffic off NAT.

### Non-blocking observations (accept)
1. Dead-ish `SafetyAction.WARN` branch in `orchestrator._run_pipeline` persists (scanner is
   refuse-or-allow). Harmless/defensive; same status as prior review.
2. Gateway/worker SG egress is `0.0.0.0/0` all-protocol. Standard for outbound; could be
   narrowed to 443 later. Not a gate blocker.
3. Lambda artifact S3 bucket/key default to empty strings — intentional (built package
   supplied at deploy via `-var`); validated as `init -backend=false`, no apply (OOS-3).

**Verdict: READY.** Both prior follow-ons (NFR-11 wiring, BR-027 MINOR-b) are closed with
regression tests; Terraform realises infra-spec §1–§6 with correct least-privilege, lock-step
timing, F8 GSI, and gateway autoscaling. All quality gates independently green. No blocking findings.
