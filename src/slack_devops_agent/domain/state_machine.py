"""ProcessingJob state machine (ENT-008; functional-spec.md W2/W3, Q2=b terminals).

Pure transition validation — no I/O. The Job Coordinator (CMP-006) applies these
transitions durably with single-winner leasing (BR-027); this module only decides
whether a transition is *legal* and computes the next state.
"""

from __future__ import annotations

from .enums import JobStatus

# Legal transitions for the ProcessingJob FSM (functional-spec.md state-machine table).
_ALLOWED: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.SEEN: frozenset({JobStatus.IN_PROGRESS, JobStatus.FAILED}),
    # in-progress may re-enter in-progress on recovery (BR-021, attempt++).
    JobStatus.IN_PROGRESS: frozenset({JobStatus.IN_PROGRESS, JobStatus.RESOLVED, JobStatus.FAILED}),
    JobStatus.RESOLVED: frozenset(),
    JobStatus.FAILED: frozenset(),
}


class IllegalTransitionError(ValueError):
    """Raised when a ProcessingJob transition is not permitted by the FSM."""


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    """Return True if ``current -> target`` is a legal ProcessingJob transition.

    Terminal states (resolved/failed) permit no outgoing transition (Q2=b).
    """
    return target in _ALLOWED[current]


def assert_transition(current: JobStatus, target: JobStatus) -> None:
    """Raise :class:`IllegalTransitionError` if ``current -> target`` is illegal."""
    if not can_transition(current, target):
        raise IllegalTransitionError(
            f"illegal ProcessingJob transition: {current.value} -> {target.value}"
        )
