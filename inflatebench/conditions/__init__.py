"""Compaction conditions: free, sectioned, keep_rules, extractor, pinning."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from inflatebench.schema import Message

if TYPE_CHECKING:
    from inflatebench.models import LLM


class Condition(Protocol):
    name: str

    def compact(self, history: list[Message], llm: LLM) -> list[Message]: ...


from inflatebench.conditions._common import NEUTRAL_HEADER, neutral_context  # noqa: E402
from inflatebench.conditions.extractor import Extractor  # noqa: E402
from inflatebench.conditions.pinning import Pinning  # noqa: E402
from inflatebench.conditions.summarize import FreeSummary, KeepRules, Sectioned  # noqa: E402

CONDITIONS: dict[str, type[Condition]] = {c.name: c for c in (FreeSummary, Sectioned, KeepRules, Extractor, Pinning)}


def get_condition(name: str) -> Condition:
    try:
        return CONDITIONS[name]()
    except KeyError:
        raise ValueError(f"unknown condition {name!r}; expected one of {list(CONDITIONS)}") from None


__all__ = ["CONDITIONS", "NEUTRAL_HEADER", "Condition", "Extractor", "FreeSummary", "KeepRules", "Pinning",
           "Sectioned", "get_condition", "neutral_context"]
