# ADR-0001: Concentrate the at-most-once-completed invariant behind `claim_and_guard`

## Status

Accepted.

## Context

"A recovery-spawned worker must never double-post an answer" is the system's core
correctness property (BR-011/BR-021/BR-022/BR-027). It currently emerges from the
interaction of six fragments spread across six modules:

1. `Worker.process`'s inline sequence: completion short-circuit, lease acquisition,
   `post_attempted` check, attempt-bound check (`orchestrator.py`).
2. `ProcessingJob.post_attempted` (`domain/entities.py`).
3. `DynamoJobCoordinator.acquire_lease`'s CAS and `mark_post_intent`'s idempotent stamp
   (`components/jobs/coordinator.py`).
4. `rules.is_lease_stale` / `rules.attempts_exhausted` (`domain/rules.py`).
5. `state_machine._ALLOWED` (`domain/state_machine.py`).
6. `Reaper.recover_stale` (`components/recovery/reaper.py`).

Nobody owns the invariant end-to-end. A new reader has to reconstruct it by reading
`Worker.process` line-by-line alongside four other files, and the only thing exercising
the full decision procedure is the 8-fake `test_worker.py` harness — there is no test
that targets the decision procedure directly.

## Decision

Add `claim_and_guard()` — a single function, in a new `components/jobs/claim.py`
module, that composes the *existing* `JobCoordinator` primitives (`get`, `acquire_lease`,
`transition`) with the *existing* pure rules (`rules.should_process_existing`,
`rules.attempts_exhausted`) into one call:

```python
def claim_and_guard(
    jobs: JobCoordinator,
    identity: tuple[str, str],
    now: datetime,
    *,
    staleness_seconds: int,
    max_attempts: int,
) -> ClaimResult:
    ...
```

`ClaimResult.decision` is one of:

- `PROCEED` — the caller won the lease, the job has not been posted, attempts remain.
  Run the pipeline.
- `SKIP_COMPLETED` — the job is already `resolved`/`failed`. Nothing to do.
- `SKIP_ALREADY_POSTED` — the lease was won, but `post_attempted` is already true (a
  prior attempt stamped the pre-post intent marker or the answer landed). Resolve
  without reposting.
- `LEASE_LOST` — the CAS lost to a competing worker, or a live (non-stale) lease is
  held elsewhere.
- `EXHAUSTED` — the lease was won but `attempt_count` is already at the cap (a race with
  the reaper). Abandon to `failed`.

`Worker.process` replaces its inline four-branch sequence with one call to
`claim_and_guard` plus a dispatch on `decision`. A new reader can now answer "can this
double-post?" by reading `claim.py` top to bottom — one module, roughly 25 lines,
independently unit-testable against the existing `FakeJobCoordinator` with no new test
infrastructure.

`state_machine._ALLOWED`, `DynamoJobCoordinator.acquire_lease`'s CAS, and
`mark_post_intent` are unchanged and **not** folded into `claim_and_guard` — they are
correctly-scoped lower-level primitives (generic transition legality, and the durable
atomic operations respectively), not part of the *decision* the invariant makes. Their
existing tests keep protecting them directly.

## Rejected alternative: `claim()` as a new `JobCoordinator` protocol method

The plan's initial sketch put `claim()` directly on the `JobCoordinator` port, so
`Worker.process` would call `self.jobs.claim(...)` instead of a free function.

Rejected because:

- It widens the `JobCoordinator` Protocol with a method whose entire body is derivable
  from the port's own other methods (`get` + `acquire_lease` + the pure rules) — nothing
  about it is adapter-specific. A Protocol member that never needs adapter-specific
  behavior is a smell: every current and future implementation (`DynamoJobCoordinator`,
  `FakeJobCoordinator`, and any future backend) would carry a near-identical copy of the
  same orchestration logic, or the two existing implementations would need to be
  refactored to share it via a mixin — more moving parts than the free-function version
  for the same behavior.
- It would force either duplicating the decision logic between `DynamoJobCoordinator`
  and `FakeJobCoordinator`, or introducing a shared base/mixin — either way, more
  surface area than a function that takes any `JobCoordinator` and works unchanged
  against both.
- The free function needs zero changes to the `JobCoordinator` Protocol, `DynamoJobCoordinator`,
  or `FakeJobCoordinator` — it is purely additive, which keeps the blast radius of a
  "highest risk" phase as small as the goal allows.

## Also considered and rejected: routing the Reaper through `claim_and_guard` too

The plan sketch describes "a single coordinator-level operation that both the Worker
and the Reaper call." Tracing `Reaper.recover_stale` and `Reaper.drain_dead_letters`
shows this doesn't fit: the reaper never posts an answer, so `SKIP_ALREADY_POSTED` is
meaningless to it, and — critically — `claim_and_guard` *acquires the lease* as part of
reaching a decision. If the reaper called it just to ask "retriable or exhausted?", a
stale job would be claimed (transitioned to `in-progress`, `attempt_count` incremented,
`last_transition_at` refreshed) by the reaper itself before being re-enqueued. The
worker that later reclaims it from the queue would then find a *fresh* (non-stale)
in-progress lease and lose its own CAS — the message would bounce until the
reaper-claimed lease went stale again, which is a regression, not a simplification.

The reaper's actual decision ("retriable vs. exhausted", `rules.attempts_exhausted`) is
already a single, correctly-scoped call — it was never actually scattered. Left as-is.

## Consequences

- `Worker.process` shrinks to a decision-dispatch over `ClaimResult`, the pipeline run,
  and the post/resolve tail — no inline lease/completion/attempt bookkeeping.
- New tests in `tests/test_claim.py` exercise `claim_and_guard` directly (single-winner
  lease, repost-after-intent refusal, stale-lease takeover) without going through the
  full `Worker` pipeline.
- `test_worker.py` and `test_entrypoints.py` (reaper) are unchanged and must stay green —
  they are the end-to-end safety net for this refactor.
- See `CONTEXT.md` for the sharpened vocabulary this work introduces: *lease*, *post
  intent*, *claim-and-guard*.
