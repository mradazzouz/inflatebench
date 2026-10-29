"""Token prices from config.yaml, in USD per million tokens, keyed by model name.

    prices:
      some-model:
        input: 1.00
        output: 5.00
        cache_write: 1.25   # optional, default 1.25 x input (5-minute prompt cache)
        cache_read: 0.10    # optional, default 0.1 x input
        batch_discount: 0.5 # optional, multiplier for batch calls (default 0.5)

A model with no entry costs 0 (local models through Ollama need none).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_CACHE_WRITE = 1.25
DEFAULT_CACHE_READ = 0.1
DEFAULT_BATCH_DISCOUNT = 0.5


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_write: float
    cache_read: float
    batch_discount: float = DEFAULT_BATCH_DISCOUNT

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Price:
        unknown = set(data) - {"input", "output", "cache_write", "cache_read", "batch_discount"}
        if unknown:
            raise ValueError(f"unknown price fields {sorted(unknown)}")
        inp = float(data["input"])
        return cls(
            input=inp,
            output=float(data["output"]),
            cache_write=float(data.get("cache_write", inp * DEFAULT_CACHE_WRITE)),
            cache_read=float(data.get("cache_read", inp * DEFAULT_CACHE_READ)),
            batch_discount=float(data.get("batch_discount", DEFAULT_BATCH_DISCOUNT)),
        )


class Prices:
    def __init__(self, table: dict[str, Any] | None = None) -> None:
        self.table = {name: Price.from_dict(p) for name, p in (table or {}).items()}

    def get(self, model: str) -> Price | None:
        return self.table.get(model)

    def __contains__(self, model: str) -> bool:
        return model in self.table

    def cost(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
        batch: bool = False,
    ) -> float:
        p = self.get(model)
        if p is None:
            return 0.0
        usd = (
            input_tokens * p.input
            + output_tokens * p.output
            + cache_write_tokens * p.cache_write
            + cache_read_tokens * p.cache_read
        ) / 1_000_000
        return usd * (p.batch_discount if batch else 1.0)
