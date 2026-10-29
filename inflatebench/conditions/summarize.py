"""Single-call conditions: free summary, sectioned template, keep-rules prompt, and the two
ablations that separate the sectioned template's Constraints section from its word limit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from inflatebench.conditions._common import ask, prompt, summary_message
from inflatebench.schema import Message

if TYPE_CHECKING:
    from inflatebench.models import LLM


class PromptCondition:
    """Summarises the history with one prompt and returns it as one message."""

    name = ""
    prompts: tuple[str, ...] = ()

    @property
    def instructions(self) -> str:
        return "\n\n".join(prompt(p) for p in self.prompts)

    def summarize(self, history: list[Message], llm: LLM) -> str:
        return ask(llm, self.instructions, history)

    def compact(self, history: list[Message], llm: LLM) -> list[Message]:
        return [summary_message(self.summarize(history, llm))]


class FreeSummary(PromptCondition):
    name = "free"
    prompts = ("free",)


class Sectioned(PromptCondition):
    """Five fixed sections and a 250-word limit (pilot round 2)."""

    name = "sectioned"
    prompts = ("sectioned",)


class KeepRules(PromptCondition):
    """The sectioned template plus an instruction to keep user rules verbatim."""

    name = "keep_rules"
    prompts = ("sectioned", "keep_rules")


class FreeLimited(PromptCondition):
    """Ablation: the free summary with the sectioned template's 250-word limit."""

    name = "free_limited"
    prompts = ("free_limited",)


class SectionedNoConstraints(PromptCondition):
    """Ablation: the sectioned template without its Constraints & Preferences section."""

    name = "sectioned_noconstraints"
    prompts = ("sectioned_noconstraints",)
