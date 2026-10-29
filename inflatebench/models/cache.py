"""Disk cache keyed by request hash, so reruns cost nothing and crashed runs resume."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator

from inflatebench.schema import Message

if TYPE_CHECKING:
    from inflatebench.models import LLM, BatchHandle, Completion, Request
    from inflatebench.models.usage import UsageLog

log = logging.getLogger(__name__)


def _write_atomic(path: Path, record: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file and rename, so a crash never leaves a partial entry.
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


class DiskCache:
    """Stores one JSON file per request at <root>/<key[:2]>/<key>.json.

    Batches submitted but not yet collected are recorded under <root>/_batches/, so a
    crashed run collects them instead of paying for them twice.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, request: Request) -> Completion | None:
        from inflatebench.models import Completion

        path = self._path(request.key())
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        return Completion(**data["completion"])

    def put(self, request: Request, completion: Completion) -> None:
        record = {"request": request.to_dict(), "completion": asdict(completion)}
        _write_atomic(self._path(request.key()), record)

    def __contains__(self, request: Request) -> bool:
        return self._path(request.key()).exists()

    def _pending_path(self, batch_id: str) -> Path:
        return self.root / "_batches" / f"{batch_id}.json"

    def save_pending(self, handle: BatchHandle, requests: list[Request]) -> None:
        record = {"id": handle.id, "size": handle.size, "requests": [r.to_dict() for r in requests]}
        _write_atomic(self._pending_path(handle.id), record)

    def pending(self) -> Iterator[tuple[BatchHandle, list[Request]]]:
        from inflatebench.models import BatchHandle, Request

        for path in sorted((self.root / "_batches").glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            yield BatchHandle(data["id"], data["size"]), [Request.from_dict(r) for r in data["requests"]]

    def drop_pending(self, handle: BatchHandle) -> None:
        self._pending_path(handle.id).unlink(missing_ok=True)


class CachedLLM:
    """Wraps an LLM so each distinct request reaches the provider at most once.

    Pass `repeat=n` to complete() to get independent samples of the same prompt; it is part
    of the cache key and never sent to the provider.
    """

    def __init__(self, llm: LLM, cache: DiskCache, model: str, usage: UsageLog | None = None) -> None:
        from inflatebench.models import provider_settings
        from inflatebench.models.usage import UsageLog

        self.llm = llm
        self.cache = cache
        self.model = model
        self.settings = provider_settings(llm)
        self.usage = usage if usage is not None else UsageLog()

    def request(self, messages: list[Message], **kw: Any) -> Request:
        from inflatebench.models import Request

        return Request(model=self.model, messages=list(messages), params=dict(kw), settings=dict(self.settings))

    def complete(self, messages: list[Message], **kw: Any) -> Completion:
        return self.complete_request(self.request(messages, **kw))

    def complete_request(self, request: Request) -> Completion:
        """complete() for a prepared request, whatever cache label (request.model) it carries."""
        request = replace(request, settings=dict(self.settings))
        hit = self.cache.get(request)
        if hit is not None:
            hit = replace(hit, cached=True)
            self.usage.record(hit, request.key())
            return hit
        completion = self.llm.complete(request.messages, **request.params)
        self.cache.put(request, completion)
        self.usage.record(completion, request.key())
        return completion

    def submit_batch(self, requests: list[Request]) -> BatchHandle:
        return self.llm.submit_batch(requests)

    def run_batch(
        self,
        requests: list[Request],
        *,
        poll_interval: float = 60.0,
        rounds: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> list[Completion]:
        """Complete all requests, in order, through the provider's batch API when it has one.

        Cached requests are skipped; batches left by a crashed run are collected first;
        entries that fail transiently (expired, overloaded) are resubmitted up to `rounds` times.
        """
        # Key every request by this provider's settings, however the caller built it.
        requests = [replace(r, settings=dict(self.settings)) for r in requests]
        out: dict[str, Completion] = {}
        missing: dict[str, Request] = {}
        for r in requests:
            hit = self.cache.get(r)
            if hit is not None:
                out[r.key()] = replace(hit, cached=True)
                self.usage.record(out[r.key()], r.key())
            else:
                missing[r.key()] = r

        if not getattr(self.llm, "supports_batch", False):
            for k, r in list(missing.items()):
                out[k] = self.complete_request(r)
            return [out[r.key()] for r in requests]

        for handle, pending in self.cache.pending():
            if missing.keys() & {r.key() for r in pending}:
                log.info("resuming batch %s (%d requests)", handle.id, handle.size)
                self._collect(handle, pending, out, missing, poll_interval, sleep)

        for _ in range(rounds):
            if not missing:
                break
            todo = list(missing.values())
            handle = self.llm.submit_batch(todo)  # type: ignore[attr-defined]
            self.cache.save_pending(handle, todo)
            log.info("submitted batch %s (%d requests)", handle.id, handle.size)
            self._collect(handle, todo, out, missing, poll_interval, sleep)

        if missing:
            raise RuntimeError(f"{len(missing)} requests still failing after {rounds} batch rounds")
        return [out[r.key()] for r in requests]

    def _collect(
        self,
        handle: BatchHandle,
        requests: list[Request],
        out: dict[str, Completion],
        missing: dict[str, Request],
        poll_interval: float,
        sleep: Callable[[float], None],
    ) -> None:
        from inflatebench.models import BatchError

        while not self.llm.batch_done(handle):  # type: ignore[attr-defined]
            sleep(poll_interval)
        results = self.llm.batch_results(handle)  # type: ignore[attr-defined]
        fatal = []
        for r in requests:
            k = r.key()
            res = results.get(k, BatchError("missing from batch results"))
            if isinstance(res, BatchError):
                log.warning("batch %s: request %s failed: %s", handle.id, k[:12], res)
                if not res.retryable and k in missing:
                    fatal.append(f"{k[:12]}: {res}")
                continue
            self.cache.put(r, res)
            self.usage.record(res, k, batch_id=handle.id)
            # Batches from a crashed run may hold requests this run did not ask for.
            if k in missing:
                out[k] = res
                del missing[k]
        self.cache.drop_pending(handle)
        if fatal:
            raise RuntimeError(f"batch {handle.id} has requests that cannot succeed: " + "; ".join(fatal))
