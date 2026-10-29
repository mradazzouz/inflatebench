"""Per-call log of model, date, token counts and cost, appended as JSONL."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from inflatebench.models import Completion

log = logging.getLogger(__name__)

TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens")


class UsageLog:
    """Records every completion (cache hits included, flagged `cached`) and keeps totals.

    Totals count only spend made in this process: cache hits add calls but no tokens or cost.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.calls = 0
        self.cache_hits = 0
        self.tokens = dict.fromkeys(TOKEN_FIELDS, 0)
        self.cost = 0.0
        self._lock = threading.Lock()  # batches of several judges are collected in parallel

    def record(self, completion: Completion, key: str = "", **extra: Any) -> None:
        with self._lock:
            self._record(completion, key, **extra)

    def _record(self, completion: Completion, key: str, **extra: Any) -> None:
        self.calls += 1
        if completion.cached:
            self.cache_hits += 1
        else:
            for f in TOKEN_FIELDS:
                self.tokens[f] += getattr(completion, f)
            self.cost += completion.cost
        entry = {k: v for k, v in asdict(completion).items() if k not in ("text", "thinking")} | {"key": key} | extra
        log.info(
            "%s in=%d out=%d cache_w=%d cache_r=%d $%.5f%s",
            completion.model,
            completion.input_tokens,
            completion.output_tokens,
            completion.cache_write_tokens,
            completion.cache_read_tokens,
            completion.cost,
            " (disk cache)" if completion.cached else "",
        )
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def summary(self) -> dict[str, Any]:
        return {"calls": self.calls, "cache_hits": self.cache_hits, **self.tokens, "cost": round(self.cost, 6)}
