"""Token and cost estimate for `ib compact --dry-run`; makes no API calls and needs no keys."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from inflatebench.models.pricing import Prices
from inflatebench.schema import Scenario

CHARS_PER_TOKEN = 4  # rough for English text; good enough for a budget check
PROMPT_OVERHEAD = 400  # condition instructions, templates and extractor prompts, in tokens
DEFAULT_OUTPUT_TOKENS = 1000  # summary plus any thinking tokens, per call
# Model calls per compaction: extractor and pinning make a separate extraction call.
CALLS_PER_CONDITION = {"free": 1, "sectioned": 1, "keep_rules": 1, "extractor": 2, "pinning": 2}


def approx_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


@dataclass
class Estimate:
    model: str
    scenarios: int
    conditions: list[str]
    repeats: int
    calls: int
    input_tokens: int
    output_tokens: int
    batch: bool
    cost: float | None  # None when config.yaml has no price for the model

    def lines(self) -> list[str]:
        cost = (
            f"${self.cost:,.2f}" + (" (batch discount applied)" if self.batch else "")
            if self.cost is not None
            else f"unknown: add {self.model!r} under prices in config.yaml"
        )
        return [
            f"model:         {self.model}",
            f"scenarios:     {self.scenarios}",
            f"conditions:    {', '.join(self.conditions)}",
            f"repeats:       {self.repeats}",
            f"model calls:   {self.calls:,}",
            f"input tokens:  ~{self.input_tokens:,}",
            f"output tokens: ~{self.output_tokens:,}",
            f"cost:          {cost}",
            "(upper bound: assumes no prompt-cache or disk-cache hits)",
        ]


def estimate(
    scenarios: list[Scenario],
    entry: dict[str, Any],
    conditions: list[str],
    repeats: int,
    prices: Prices,
    output_tokens: int = DEFAULT_OUTPUT_TOKENS,
) -> Estimate:
    per_scenario = [
        approx_tokens("\n".join(m.content for m in s.history)) + PROMPT_OVERHEAD for s in scenarios
    ]
    calls_per_scenario = sum(CALLS_PER_CONDITION.get(c, 1) for c in conditions) * repeats
    calls = calls_per_scenario * len(scenarios)
    inp = sum(per_scenario) * calls_per_scenario
    out = calls * output_tokens
    name = entry.get("name", "")
    batch = bool(entry.get("batch"))
    cost = prices.cost(name, input_tokens=inp, output_tokens=out, batch=batch) if name in prices else None
    return Estimate(name, len(scenarios), list(conditions), repeats, calls, inp, out, batch, cost)
