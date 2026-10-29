"""Extractor: a second call lists standing user constraints after the summary (after CompInt)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from inflatebench.conditions._common import ask, bullets, parse_list, prompt, summary_message
from inflatebench.conditions.summarize import Sectioned
from inflatebench.schema import Message

if TYPE_CHECKING:
    from inflatebench.models import LLM


class Extractor(Sectioned):
    """Sectioned summary, then the extracted list appended in the same message."""

    name = "extractor"

    def extract(self, history: list[Message], llm: LLM) -> list[str]:
        return parse_list(ask(llm, prompt("extract"), history))

    def compact(self, history: list[Message], llm: LLM) -> list[Message]:
        summary = self.summarize(history, llm)
        constraints = self.extract(history, llm)
        if constraints:
            summary += "\n\n" + bullets(prompt("extracted_header"), constraints)
        return [summary_message(summary)]
