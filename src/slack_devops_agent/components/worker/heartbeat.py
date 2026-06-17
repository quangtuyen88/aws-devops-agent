"""CMP-002 — NFR-11 periodic "still working…" heartbeat emitter.

While the W2 pipeline runs (inference + MCP, up to the 30s NFR-17 budget), the worker
posts a periodic in-thread heartbeat (~15s) so the asker sees progress rather than silence.

Per infra-spec §2.4 (F6), heartbeat emission is kept **off the critical CPU path**: it runs
on a daemon background thread driven by a :class:`threading.Event`, so a slow synchronous
section of the pipeline never blocks on (nor is blocked by) the heartbeat. The emitter is a
context manager — entering starts the timer, exiting stops and joins it — so the heartbeat
always stops on both the success and failure paths (BR-013, never a dangling timer).

A failed heartbeat post is logged and swallowed: it is best-effort progress UX and must
never fail the underlying job.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType

from ...domain.entities import OriginatingMessageRef
from ...observability.logging import get_logger
from ...observability.metrics import Metrics
from ...ports import SlackGateway
from .rendering import HEARTBEAT_TEXT

# A waiter returns True when stop was requested before the interval elapsed, else False
# (the semantics of :meth:`threading.Event.wait`). Injectable for deterministic tests.
WaitFn = Callable[[float], bool]


@dataclass
class HeartbeatEmitter:
    """Posts :data:`HEARTBEAT_TEXT` to a thread every ``interval_seconds`` until stopped.

    Use as a context manager around the pipeline::

        with HeartbeatEmitter(slack, ref, 15.0, metrics):
            result = run_pipeline()
    """

    slack: SlackGateway
    ref: OriginatingMessageRef
    interval_seconds: float = 15.0
    metrics: Metrics | None = None
    beats: int = field(default=0, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)

    def start(self) -> None:
        """Start the background heartbeat timer (idempotent)."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="worker-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the timer to stop and wait for the thread to finish."""
        self._stop.set()
        if self._thread is not None:
            # join is bounded: the loop wakes on the stop event immediately.
            self._thread.join(timeout=self.interval_seconds + 1.0)
            self._thread = None

    def _run(self) -> None:
        """Loop: wait one interval; if not stopped, emit one heartbeat."""
        while not self._wait(self.interval_seconds):
            self._beat()

    def _wait(self, seconds: float) -> bool:
        """Block up to ``seconds``; return True if stop was requested meanwhile."""
        return self._stop.wait(seconds)

    def _beat(self) -> None:
        """Emit a single heartbeat post; best-effort (never fails the job)."""
        try:
            self.slack.post_message(self.ref, HEARTBEAT_TEXT)
            self.beats += 1
            if self.metrics is not None:
                self.metrics.count("heartbeat_emitted")
        except Exception:
            get_logger(__name__).warning("heartbeat post failed; continuing")

    def __enter__(self) -> HeartbeatEmitter:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
