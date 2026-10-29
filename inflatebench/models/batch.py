"""Run a stage's model calls in phases, each phase sent as one batch per provider.

A stage (compact, judge) is written as plain sequential code over `llm.complete`. To batch
it, the stage is run against `Deferred` stand-ins: while collecting, each call is answered
from the disk cache or queued, and the unit of work that needed it is skipped (`Pending`).
`run_phases` sends each round's queue as one batch per provider, then reruns the stage, so
calls that depend on earlier answers go out in the next phase. Once nothing is queued, the
stage runs a last time for real, now entirely from fresh results and the disk cache.

Resuming is the disk cache's job: answered calls are on disk and submitted batches are
recorded under the cache's `_batches/`, so a crashed run collects them instead of paying again.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable

from inflatebench.models import Completion, Request
from inflatebench.schema import Message

if TYPE_CHECKING:
    from inflatebench.models.cache import CachedLLM

log = logging.getLogger(__name__)

MAX_PHASES = 10  # a stage needing more is looping (two suffice for compact and judge)


class Pending(Exception):
    """A deferred call is not answered yet; it is queued for the next phase."""


@dataclass
class _State:
    """Shared by a Deferred and its views, so all of a provider's calls go in one batch."""

    collecting: bool = True
    queue: dict[str, Request] = field(default_factory=dict)
    fresh: dict[str, Completion] = field(default_factory=dict)  # paid for in this run
    lock: threading.Lock = field(default_factory=threading.Lock)


class Deferred:
    """Stands in for a CachedLLM while a stage collects its calls into phases.

    With `batch` false, each phase's calls are made one at a time instead (providers without
    a batch API, or models without `batch: true` in config.yaml); phases and resume still work.
    """

    def __init__(self, llm: CachedLLM, *, batch: bool = True, model: str | None = None) -> None:
        self.llm = llm
        self.batch = batch
        self.model = model or llm.model
        self.state = _State()

    def view(self, model: str) -> Deferred:
        """The same provider under another cache label (e.g. one per repeat), batched together."""
        other = Deferred(self.llm, batch=self.batch, model=model)
        other.state = self.state
        return other

    def request(self, messages: list[Message], **kw: Any) -> Request:
        return Request(model=self.model, messages=list(messages), params=dict(kw), settings=dict(self.llm.settings))

    def want(self, messages: list[Message], **kw: Any) -> None:
        """Queue a call the stage will make later, so it goes out in this phase."""
        if not self.state.collecting:
            return
        r = self.request(messages, **kw)
        if r.key() not in self.state.fresh and r not in self.llm.cache:
            self.state.queue[r.key()] = r

    def complete(self, messages: list[Message], **kw: Any) -> Completion:
        r = self.request(messages, **kw)
        k = r.key()
        s = self.state
        if s.collecting:
            hit = s.fresh.get(k) or self.llm.cache.get(r)
            if hit is None:
                s.queue[k] = r
                raise Pending(k)
            return self.llm.check(hit, r)
        if k in s.fresh:
            # Its usage was logged when the phase collected it; hand it over once as paid.
            return s.fresh.pop(k)
        return self.llm.complete_request(r)

    def flush(self, **batch_kw: Any) -> int:
        """Answer every queued call: one batch, or one call at a time without `batch`."""
        s = self.state
        todo = list(s.queue.values())
        s.queue.clear()
        if not todo:
            return 0
        if self.batch:
            done = self.llm.run_batch(todo, **batch_kw)
        else:
            done = [self.llm.complete_request(r) for r in todo]
        with s.lock:
            for r, c in zip(todo, done):
                if not c.cached:
                    s.fresh[r.key()] = c
        return len(todo)


def run_phases(step: Callable[[], Any], llms: Iterable[Deferred], *, max_phases: int = MAX_PHASES,
               **batch_kw: Any) -> int:
    """Run `step` until it queues no calls, flushing each phase; returns the number of phases.

    `step` runs the whole stage and must skip a unit of work that raises Pending. Providers
    are flushed in parallel, so the judges' batches of one phase are all in flight together.
    Afterwards the Deferreds answer for real; run `step` once more to get the stage's output.
    """
    groups = list({id(d.state): d for d in llms}.values())
    phases = 0
    try:
        while True:
            step()
            busy = [d for d in groups if d.state.queue]
            if not busy:
                return phases
            phases += 1
            if phases > max_phases:
                raise RuntimeError(f"stage still queueing calls after {max_phases} phases")
            log.info("phase %d: %s", phases, ", ".join(f"{d.llm.model} {len(d.state.queue)} calls" for d in busy))
            with ThreadPoolExecutor(len(busy)) as pool:
                list(pool.map(lambda d: d.flush(**batch_kw), busy))
    finally:
        for d in groups:
            d.state.collecting = False
