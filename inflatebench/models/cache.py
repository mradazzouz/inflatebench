"""Disk cache keyed by request hash, so reruns cost nothing and crashed runs resume."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from inflatebench.schema import Message

if TYPE_CHECKING:
    from inflatebench.models import LLM, BatchHandle, Completion, Request


class DiskCache:
    """Stores one JSON file per request at <root>/<key[:2]>/<key>.json."""

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
        path = self._path(request.key())
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"request": request.to_dict(), "completion": asdict(completion)}
        # Write to a temp file and rename, so a crash never leaves a partial entry.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise

    def __contains__(self, request: Request) -> bool:
        return self._path(request.key()).exists()


class CachedLLM:
    """Wraps an LLM so each distinct request reaches the provider at most once."""

    def __init__(self, llm: LLM, cache: DiskCache, model: str) -> None:
        self.llm = llm
        self.cache = cache
        self.model = model

    def complete(self, messages: list[Message], **kw: Any) -> Completion:
        from inflatebench.models import Request

        request = Request(model=self.model, messages=list(messages), params=dict(kw))
        hit = self.cache.get(request)
        if hit is not None:
            return replace(hit, cached=True)
        completion = self.llm.complete(messages, **kw)
        self.cache.put(request, completion)
        return completion

    def submit_batch(self, requests: list[Request]) -> BatchHandle:
        return self.llm.submit_batch(requests)
