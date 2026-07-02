# Architecture Improvement Plan

Goal: remove the architectural friction found in the 2026-07-02 review — restore locality
(the tested path must be the shipped path), fix two live resilience bugs, type the queue
contract, deduplicate wiring, and give the at-most-once invariant a single home.

Every finding below was verified against the source (file:line references checked, not
assumed). Work through the phases in order — each is an independent, shippable PR.
Verification for every phase: `uv run pytest`.

---

## Phase 1 — Collapse the bypassed `rules.py` predicates

**Goal:** one home per decision. Today five `rules.py` predicates are unit-tested but
production re-implements the decision inline, so a green test proves nothing about
shipped behavior.

**Verified state:**

| Function | Callers in `src/` | Callers in `tests/` |
|---|---|---|
| `rules.safety_blocks_forward` | none — `orchestrator.py:211` inlines `verdict.recommended_action == SafetyAction.REFUSE` | `test_domain.py:163-164` |
| `rules.safety_requires_warning` | none — `orchestrator.py:213` inlines the `WARN` check | `test_domain.py:165` |
| `rules.should_process_existing` | none — `orchestrator.py:129` inlines `existing.status.is_complete` | `test_domain.py:114-118` |
| `rules.should_reply_not_designated` | none — `handler.py:92` inlines the enum comparison | `test_domain.py:108` |
| `rules.validate_answer` | none | none |
| `rules.terminal_status_for_failure` | none | none |

**How:**

1. Delete `rules.validate_answer` and `rules.terminal_status_for_failure` (dead code, zero
   callers anywhere).
2. Route the three real call sites through the surviving rules:
   - `components/worker/orchestrator.py:211-213` — replace the inline
     `recommended_action == SafetyAction.REFUSE / WARN` checks with
     `rules.safety_blocks_forward(verdict)` / `rules.safety_requires_warning(verdict)`.
   - `components/worker/orchestrator.py:129` — replace the inline
     `existing.status.is_complete` check with `rules.should_process_existing(existing)`.
   - `components/intake/handler.py:92` — replace the inline
     `NonAllowlistedBehaviour.REPLY_NOT_DESIGNATED` comparison with
     `rules.should_reply_not_designated(...)`.
3. While there: `JobStatus.is_complete` (`domain/enums.py:25-27`) is a pure alias of
   `is_terminal`. After step 2 the orchestrator no longer uses it — delete the alias and
   keep `is_terminal` as the single spelling.
4. Do **not** touch the algorithmic rules (`is_within_budget`, `aggregate_feedback`,
   `net_reactor_signal`, `is_lease_stale`, `classify_answer_type`, `attempts_exhausted`,
   `within_size_budget`, `question_alone_overflows`) — they are already called by
   production and carry real depth.

**Tests (TDD):** the existing `test_domain.py` predicate tests stay and become truthful.
Existing `test_worker.py` / `test_intake.py` behavior tests must stay green unchanged —
this phase is a pure re-routing with zero behavior change.

**Acceptance:** `grep -rn "safety_blocks_forward\|should_process_existing\|should_reply_not_designated" src/` shows call sites in orchestrator/handler; `validate_answer` and
`terminal_status_for_failure` no longer exist; full suite green.

---

## Phase 2 — Fix the resilience layer: inert settings + a breaker that can never trip

**Goal:** make the documented resilience env vars actually take effect, and make the
circuit breaker actually able to open.

**Verified state — two live bugs:**

1. **Inert settings.** `config/settings.py:73-77` defines `retry_base_ms`,
   `retry_max_attempts`, `retry_cap_ms`, `breaker_failure_threshold`,
   `breaker_reset_seconds`. Grep confirms nothing outside `settings.py` reads them.
   `orchestrator.py:265-266` hardcodes
   `CircuitBreaker(dep, self.clock, failure_threshold=5, reset_seconds=30)` and
   `BackoffPolicy(max_attempts=2)`. Tuning the env vars silently does nothing.
2. **Breaker never trips.** `CircuitBreaker` keeps `_consecutive_failures` as instance
   state with no shared registry, and `_guarded` (`orchestrator.py:262-270`) constructs a
   **fresh breaker per call**. Each instance sees exactly one `call()`, so
   `_consecutive_failures` can never reach the threshold of 5. The breaker is functionally
   inert. Its own docstring states the intent: "one per worker invocation".

**How:**

1. Extend `WorkerConfig` (`orchestrator.py:73-83`) with the five resilience fields:
   `retry_base_ms`, `retry_max_attempts`, `retry_cap_ms`, `breaker_failure_threshold`,
   `breaker_reset_seconds`.
2. In `wiring.py` `build_worker` (`wiring.py:76-84`), pass them from `Settings` alongside
   the existing fields.
3. In `Worker`, build **one breaker per dependency name, once** — a
   `dict[str, CircuitBreaker]` created lazily in `_guarded` (keyed by `dep`) or eagerly in
   `__init__`, using the config values. Reuse the same instance across `_guarded` calls so
   consecutive failures accumulate. Build one `BackoffPolicy` from config at construction
   time instead of per call.
4. **Decision point — retry attempt count.** Current shipped behavior is
   `max_attempts=2` (3 total tries via `retry_call`'s `range(max_attempts + 1)`); the
   Settings default is `3` (4 total tries). Honoring settings with the current default
   changes behavior. Pick one explicitly:
   - (a) keep shipped behavior: change the `Settings` default to `2`, or
   - (b) accept the documented default of `3`.
   Recommendation: (a) — preserve behavior in this PR, tune deliberately later. Note
   `base_ms`/`cap_ms` defaults (500/8000) already match, so only this one field differs.
5. Optional (same PR or follow-up): lift the breaker-registry + policy construction into a
   small collaborator (e.g. a guarded-call helper owning `dict[str, CircuitBreaker]` +
   `BackoffPolicy`) so `Worker` shrinks toward pure pipeline orchestration.

**Tests (TDD, Red first):**

- Red: a test that calls `_guarded`-protected operations through `Worker.process` with a
  fake dependency failing `breaker_failure_threshold` times and asserts the breaker opens
  (fails fast with the FR-17 dependency failure, without invoking the dependency again).
  This test fails today because the breaker is rebuilt per call.
- Red: a test constructing `Worker` with `WorkerConfig(retry_max_attempts=0)` and
  asserting exactly one attempt happens. Fails today because config is ignored.
- Green: implement steps 1-4.

**Acceptance:** both new tests green; no hardcoded `failure_threshold=`/`max_attempts=`
literals left in `orchestrator.py`; full suite green.

---

## Phase 3 — Type the queue message contract

**Goal:** one schema for the SQS work message, owned in one place, used by all three
readers/writers of the durable boundary.

**Verified state:** the shape `{job_id, channel_id, message_ts, correlation_id, author_id}`
is hand-written three times:

- writer: `components/queue/sqs.py:29-38`
- worker reader: `entrypoints/dispatch.py:51-55` (`parse_sqs_record`)
- DLQ drain reader: `entrypoints/lambda_reaper.py:54-55` (reads `channel_id`/`message_ts`,
  logs-and-skips on `KeyError` — a field rename would silently discard DLQ messages as
  "malformed")

**How:**

1. Add a `WorkMessage` model (Pydantic, matching the codebase's entity style) next to the
   queue component — e.g. `components/queue/message.py` — with fields
   `job_id: UUID`, `channel_id: str`, `message_ts: str`, `correlation_id: UUID`,
   `author_id: str`, plus `to_json()` and `from_json(body: str)` (tolerating the
   missing-`author_id` fallback that `dispatch.py` documents for FR-18).
2. `SqsWorkQueue.enqueue` builds and serializes a `WorkMessage` instead of a dict literal.
3. `dispatch.parse_sqs_record` deserializes via `WorkMessage.from_json` and returns the
   same tuple it does today (keep the entrypoint signature stable).
4. `lambda_reaper._drain_dlq` deserializes via `WorkMessage.from_json`; keep the
   skip-malformed guard for genuinely corrupt bodies.

**Tests (TDD):** one round-trip test (`from_json(to_json(msg)) == msg`), one
missing-`author_id` tolerance test, one malformed-body test. Existing dispatch/reaper
tests stay green.

**Acceptance:** the field names appear as string literals in exactly one module; full
suite green. Deployment note: the wire format is unchanged, so mixed-version producers
and consumers during rollout are safe.

---

## Phase 4 — Single composition root

**Goal:** one place that builds the object graph; adapter constructor changes become
one-line edits.

**Verified state:** three near-identical construction sites —
`wiring.py:27-49` (`build_intake_handler`), `wiring.py:52-84` (`build_worker`), and
`lambda_reaper.py:29-42` (`_build_reaper`, which never imports `wiring`).
`DynamoJobCoordinator(...)` is constructed verbatim at `wiring.py:36`, `wiring.py:58`,
and `lambda_reaper.py:33`; `boto3.resource`/`WebClient`/`SystemClock` are built in all
three.

**How:**

1. In `wiring.py`, extract the shared trio into a small private helper (plain function
   returning the dynamo resource, `SlackGatewayAdapter`, and clock — no DI framework).
2. Rewrite `build_intake_handler` and `build_worker` on top of it.
3. Add `build_reaper(settings) -> Reaper` to `wiring.py` and make
   `lambda_reaper._build_reaper` a thin call to it (or delete `_build_reaper` and call
   `wiring.build_reaper` directly from the handler).
4. Keep the DLQ-drain SQS client where it is — it is reaper-specific.

**Tests:** `test_entrypoints.py` / `test_glue.py` must stay green; add one construction
test for `build_reaper` mirroring however the existing builders are covered.

**Acceptance:** `DynamoJobCoordinator(` appears exactly once in `src/`; `lambda_reaper`
imports its dependencies from `wiring`; full suite green.

---

## Phase 5 — Prune the `AnswerComposer` port (optional, low priority)

**Goal:** remove a hypothetical seam. 9 of 10 ports have a single production adapter;
most earn their keep as test seams over external systems. `AnswerComposer`
(`ports/__init__.py:198-209`) does not: single pure in-process implementation, no fake
(tests already use `DefaultAnswerComposer` directly — see `test_worker.py:9`,
`test_heartbeat.py:120,168`, `test_inference.py:200`), consumed only by the Worker.

**How:**

1. Change `Worker`'s field annotation (`orchestrator.py:110`) from the `AnswerComposer`
   Protocol to the concrete `DefaultAnswerComposer`.
2. Delete the `AnswerComposer` Protocol from `ports/__init__.py`.
3. `wiring.py:73` is unchanged (already passes `DefaultAnswerComposer()`).

Do **not** prune `SafetyScanner` or `GroundingClient` — they wrap external-ish concerns
and their fakes are used widely.

**Tests:** no test changes needed; suite green.

**Acceptance:** `AnswerComposer` gone from ports; full suite green. Skip this phase if it
turns contentious — payoff is small.

---

## Phase 6 — Give the at-most-once-completed invariant a single home (design-first)

**Goal:** the system's core correctness property — "a recovery-spawned worker must never
double-post an answer" — currently emerges from the interaction of six modules. Nobody
owns it. Concentrate it.

**Verified fragments:**

1. `orchestrator.process` — `post_attempted` short-circuit and mark-intent-before-post
   ordering (`orchestrator.py:143-145, 174-176`)
2. `entities.ProcessingJob.post_attempted` (`entities.py:197-206`)
3. `jobs/coordinator.acquire_lease` CAS (`coordinator.py:93-129`) and idempotent
   `mark_post_intent` (`coordinator.py:158-172`)
4. `rules.is_lease_stale` / `attempts_exhausted` (`rules.py:61-77`)
5. `state_machine._ALLOWED` transition table
6. `recovery/reaper.recover_stale` (`reaper.py:46-63`)

**How (direction, not final design):**

1. **Do not start with code.** Run a design session first (design-it-twice: sketch at
   least two candidate interfaces) — this touches the most correctness-critical code in
   the repo, and the coordinator's CAS logic currently looks correct.
2. Candidate shape: a single coordinator-level "claim-and-guard" operation that both the
   Worker and the Reaper call — it internally handles lease CAS, staleness, attempt
   bounds, and the post-intent gate, and returns an explicit decision
   (proceed / skip-completed / skip-already-posted / exhausted).
3. Success criterion: a new reader can answer the double-post question by reading **one**
   module top-to-bottom; the invariant becomes directly testable through that one
   interface instead of only via the 8-fake `test_worker.py` harness.
4. Capture the chosen design and its rejected alternative as the project's first ADR
   (`docs/adr/0001-...`), and start a `CONTEXT.md` naming the concepts this work
   sharpened: *lease*, *post intent*, *claim-and-guard*.

**Tests:** the existing worker/reaper end-to-end tests are the safety net — they must
pass unchanged before and after. New unit tests target the claim-and-guard interface
directly (single-winner lease, repost-after-intent refusal, stale-lease takeover).

**Acceptance:** invariant readable in one module; existing suite green; ADR recorded.

---

## Suggested order and sizing

| Phase | Risk | Size | Note |
|---|---|---|---|
| 1 — rules collapse | none (pure re-routing) | S | do first |
| 2 — resilience fix | low, fixes 2 live bugs | M | one behavior decision (retry default) |
| 3 — typed queue message | low | S | wire format unchanged |
| 4 — composition root | low | S | mechanical |
| 5 — composer prune | none | XS | optional |
| 6 — invariant home | high | L | design session + ADR first |

One PR per phase, Conventional Commits (`refactor:` for 1/4/5, `fix:` for 2, `feat:` or
`refactor:` for 3, `refactor:` for 6).
