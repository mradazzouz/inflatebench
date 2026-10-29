"""Pinning: user constraints quoted once into a pinned block re-inserted verbatim (after Governance Decay)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from inflatebench.conditions._common import ask, bullets, parse_list, prompt, summary_message
from inflatebench.conditions.summarize import Sectioned
from inflatebench.schema import Message

if TYPE_CHECKING:
    from inflatebench.models import LLM


def is_pinned(m: Message) -> bool:
    return m.role == "system" and m.content.startswith(prompt("pinned_header"))


class Pinning(Sectioned):
    """Sectioned summary plus a pinned block that compaction never rewrites.

    A pinned block already in the history (from an earlier compaction) is kept
    verbatim and left out of the summary; only user messages not yet pinned are
    sent to the extractor, so each constraint is extracted once.
    """

    name = "pinning"

    def compact(self, history: list[Message], llm: LLM) -> list[Message]:
        pinned: list[str] = []
        rest: list[Message] = []
        for m in history:
            if is_pinned(m):
                pinned += [i for i in parse_list(m.content) if i not in pinned]
                rest = []  # user messages before the block were already extracted
            else:
                rest.append(m)
        history = [m for m in history if not is_pinned(m)]
        user = [m for m in rest if m.role == "user"]
        if user:
            pinned += [i for i in parse_list(ask(llm, prompt("pin_extract"), user)) if i not in pinned]
        out = [summary_message(self.summarize(history, llm))]
        if pinned:
            out.append(Message("system", bullets(prompt("pinned_header"), pinned)))
        return out
