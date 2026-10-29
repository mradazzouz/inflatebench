"""Helpers shared by the conditions: prompt loading, transcripts, list parsing."""

from __future__ import annotations

import re
from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING

from inflatebench.schema import Message

if TYPE_CHECKING:
    from inflatebench.models import LLM


@cache
def prompt(name: str) -> str:
    """Text of prompts/<name>.md, without trailing whitespace."""
    return files("inflatebench.conditions").joinpath("prompts", f"{name}.md").read_text(encoding="utf-8").rstrip()


def transcript(history: list[Message]) -> str:
    turns = "\n\n".join(f"[{m.role}] {m.content}" for m in history)
    return f"<conversation>\n{turns}\n</conversation>"


def ask(llm: LLM, instructions: str, history: list[Message]) -> str:
    """One call: the instructions as system message, the history as a transcript."""
    messages = [Message("system", instructions), Message("user", transcript(history))]
    return llm.complete(messages).text.strip()


def parse_list(text: str) -> list[str]:
    """Bulleted lines of an extractor reply; NONE or no bullets gives []."""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if line[:2] in ("- ", "* "):
            item = line[2:].strip()
            if item and item not in items:
                items.append(item)
    return items


def bullets(header: str, items: list[str]) -> str:
    return header + "\n" + "\n".join(f"- {i}" for i in items)


def summary_message(text: str) -> Message:
    return Message("system", f"{prompt('summary_header')}\n\n{text}")


# What the judge and human annotators see in place of a condition's own headers.
NEUTRAL_HEADER = "Context carried over from the earlier conversation:"
CONDITION_HEADERS = ("summary_header", "extracted_header", "pinned_header")


def neutral_context(messages: list[Message]) -> str:
    """One compacted context as plain text under a single neutral header.

    The summary, an appended constraint list and a pinned block are merged in order, and every
    header a condition adds is dropped, so the text does not say which condition produced it.
    """
    headers = {prompt(h) for h in CONDITION_HEADERS}
    parts = []
    for m in messages:
        text = "\n".join(line for line in m.content.splitlines() if line.strip() not in headers)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            parts.append(text)
    return "\n\n".join([NEUTRAL_HEADER] + parts)
