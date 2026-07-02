# Domain glossary

Concepts this codebase names explicitly. Prefer these terms over generic ones
("service", "manager") when describing this code.

## Lease

The right for exactly one worker (live or recovery-spawned) to be processing a given
`ProcessingJob`. Held by transitioning the job to `in-progress` via an atomic
compare-and-swap on `last_transition_at` (`DynamoJobCoordinator.acquire_lease`). A lease
is *stale* — reclaimable by another worker — once it has been held for at least
`lease_staleness_seconds` (90s) without progressing, per `rules.is_lease_stale`. Set
comfortably above the per-request time budget (30s) so a live job is never reclaimed out
from under itself. See ADR-0001.

## Post intent

The marker (`ProcessingJob.post_intent_at`) stamped immediately *before* the Slack
answer is posted, so a crash in the narrow window between posting and durably recording
`answer_message_ts` is still detectable on recovery. `ProcessingJob.post_attempted` is
true once either `post_intent_at` or `answer_message_ts` is set — in both cases a
recovery-spawned worker resolves the job *without* reposting. This is what makes the
at-most-once-*completed* guarantee (BR-011/BR-027) hold even across a crash that lands
between "message sent to Slack" and "ts recorded."

## Claim-and-guard

The single decision procedure — `components/jobs/claim.py::claim_and_guard` — that
answers "may this worker process this job?" It concentrates the at-most-once-completed
invariant behind one call: completion short-circuit, lease acquisition, post-intent
check, attempt-bound check. See ADR-0001 for why it lives as a free function over the
`JobCoordinator` port rather than as a new port method, and why the reaper does not
route through it.
