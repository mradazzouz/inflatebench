"""Helpers shared by the conditions: prompt loading, transcripts, list parsing."""

from __future__ import annotations

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
