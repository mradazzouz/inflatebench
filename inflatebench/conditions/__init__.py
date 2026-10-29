"""Compaction conditions: free, sectioned, keep_rules, extractor, pinning."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from inflatebench.schema import Message

if TYPE_CHECKING:
    from inflatebench.models import LLM


class Condition(Protocol):
    name: str

    def compact(self, history: list[Message], llm: LLM) -> list[Message]: ...
