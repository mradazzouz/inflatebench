"""Disk cache keyed by request hash, so reruns cost nothing and crashed runs resume."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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

# A caller's check of a reply: why it is unusable, or None (CachedLLM.complete).
Reject = Callable[["Completion"], "str | None"]

# Stop reasons that mean the reply was cut off by the token limit (Anthropic, OpenAI-compatible).
TRUNCATED = frozenset({"max_tokens", "length"})
# Stop reasons that mean the provider refused to answer (Anthropic, OpenAI-compatible).
REFUSED = frozenset({"refusal", "content_filter"})
# Characters kept as-is in pending-batch file names; anything else is replaced.
_SAFE_CHARS = "A-Za-z0-9_.-"


class ReplyError(RuntimeError):
    """A reply that must not be cached or counted: empty, cut off by max_tokens, or rejected by
    the caller's own check. `reason` is "truncated", "empty" or "rejected"; `completion` is the
    unusable reply (never cached)."""

    def __init__(self, message: str, reason: str = "", completion: Completion | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.completion = completion


def problem_reason(completion: Completion) -> str:
    """ReplyError.reason for a reply that reply_problem rejected."""
    return "truncated" if completion.stop_reason in TRUNCATED else "empty"


def reply_problem(completion: Completion, accept_refusal: bool = False) -> str | None:
    """Why a completion is unusable, or None. An empty or truncated summary, verdict or agent
    turn would otherwise be stored and scored as if the model had answered in full.

    With `accept_refusal` (agent calls, where a refusal is behaviour to record), a provider
    refusal is a usable reply even when it is empty.
    """
    if completion.stop_reason in TRUNCATED:
        return f"reply cut off at the token limit (stop_reason {completion.stop_reason!r}); raise max_tokens"
    if accept_refusal and completion.stop_reason in REFUSED:
        return None
    if not completion.text.strip():
        return "empty reply"
    return None


def _replace(src: str, dst: Path, attempts: int = 5, delay: float = 0.05) -> None:
    """os.replace, retried on PermissionError: on Windows the target is briefly locked while
    another process (often antivirus) has it open, which a short wait clears."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))


def _write_atomic(path: Path, record: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file and rename, so a crash never leaves a partial entry.
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
        _replace(tmp, path)
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
        # A readable slug plus a hash of the exact id, so distinct ids never share a file, even
        # on case-insensitive file systems or when an id holds characters unsafe in file names.
        slug = re.sub(rf"[^{_SAFE_CHARS}]+", "_", batch_id)[:80]
        digest = hashlib.sha256(batch_id.encode("utf-8")).hexdigest()[:16]
        return self.root / "_batches" / f"{slug}-{digest}.json"

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
        # Records written before file names carried a hash were named <id>.json. Only an id that
        # is already a safe file name can have been stored that way; others never touch the disk.
        if re.fullmatch(rf"[{_SAFE_CHARS}]+", handle.id):
            (self.root / "_batches" / f"{handle.id}.json").unlink(missing_ok=True)


class CachedLLM:
    """Wraps an LLM so each distinct request reaches the provider at most once.

    Pass `repeat=n` to complete() to get independent samples of the same prompt; it is part
    of the cache key and never sent to the provider.
    """

    def __init__(self, llm: LLM, cache: DiskCache, model: str, usage: UsageLog | None = None,
                 debug_dir: str | Path | None = None) -> None:
        """`debug_dir` (runs/<run_id>/debug) receives every reply cut off at the token limit."""
        from inflatebench.models import provider_settings
        from inflatebench.models.usage import UsageLog

        self.llm = llm
        self.cache = cache
        self.model = model
        self.settings = provider_settings(llm)
        self.usage = usage if usage is not None else UsageLog()
        self.debug_dir = Path(debug_dir) if debug_dir else None

    def request(self, messages: list[Message], **kw: Any) -> Request:
        from inflatebench.models import Request

        return Request(model=self.model, messages=list(messages), params=dict(kw), settings=dict(self.settings))

    def complete(self, messages: list[Message], reject: Reject | None = None, **kw: Any) -> Completion:
        """`reject` (never part of the request or its key) is the caller's own check of a reply:
        it returns why the reply is unusable, or None. A rejected reply raises ReplyError and is
        never cached, like a truncated one."""
        return self.complete_request(self.request(messages, **kw), reject)

    def check(self, completion: Completion, request: Request | None = None,
              reject: Reject | None = None) -> Completion:
        """The completion, or ReplyError when it is empty, truncated or rejected by `reject`
        (never cached or used). A request with accept_refusal=True also takes a provider
        refusal as an answer."""
        problem = reply_problem(completion, bool(request and request.params.get("accept_refusal")))
        reason = problem_reason(completion) if problem else ""
        if not problem and reject is not None and (problem := reject(completion)):
            reason = "rejected"
        if problem:
            saved = (self.save_truncated(request, completion, force=reason == "rejected")
                     if request is not None else None)
            raise ReplyError(f"{self.model}: {problem}" + (f"; reply saved to {saved}" if saved else ""),
                             reason, completion)
        return completion

    def save_truncated(self, request: Request, completion: Completion, force: bool = False) -> Path | None:
        """Write a reply cut off at the token limit (or, with `force`, any unusable reply: text,
        thinking, the request) to debug_dir for inspection; it is never cached. Returns the
        file, or None when nothing is saved."""
        if self.debug_dir is None or not (force or completion.stop_reason in TRUNCATED):
            return None
        key = request.key()
        stamp = re.sub(r"[^0-9T]", "", completion.date or "")[:15] or "nodate"
        kind = "truncated" if completion.stop_reason in TRUNCATED else "rejected"
        path = self.debug_dir / f"{kind}-{key[:16]}-{stamp}.json"
        _write_atomic(path, {"key": key, "model": self.model, "completion": asdict(completion),
                             "request": request.to_dict()})
        log.warning("%s: unusable reply (%s); saved to %s", self.model, kind, path)
        return path

    def complete_request(self, request: Request, reject: Reject | None = None) -> Completion:
        """complete() for a prepared request, whatever cache label (request.model) it carries."""
        request = replace(request, settings=dict(self.settings))
        hit = self.cache.get(request)
        if hit is not None:
            hit = replace(self.check(hit, request, reject), cached=True)
            self.usage.record(hit, request.key())
            return hit
        completion = self.check(self.llm.complete(request.messages, **request.params), request, reject)
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
                out[r.key()] = replace(self.check(hit, r), cached=True)
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
            problem = reply_problem(res, bool(r.params.get("accept_refusal")))
            if problem:
                self.save_truncated(r, res)
                # Paid for, but unusable; resubmitting the same request would fail the same way.
                log.warning("batch %s: request %s: %s", handle.id, k[:12], problem)
                if k in missing:
                    fatal.append(f"{k[:12]}: {problem}")
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
