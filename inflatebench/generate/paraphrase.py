"""LLM paraphrasing of bank phrases into variants that keep key, scope and strength."""

from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING

from inflatebench.generate.banks import EXPLICIT_MARKERS, IMPLICIT_FORBIDS_MARKERS, count_key, cue_ok
from inflatebench.schema import Message

if TYPE_CHECKING:
    from inflatebench.models import LLM

N_VARIANTS = 3

ROLE = {
    "one_off": "a one-off instruction that applies only to one file, run, item, section or date",
    "preference": "a soft preference, not a requirement",
    "request": "a single task request, not a standing rule",
    "hard_rule": "a strict standing rule",
    "changed_value": "an update that replaces an earlier value",
}

PROMPT = """Paraphrase a message a user wrote to an AI assistant. Write {n} variants.

The message is {role}. Each variant must:
- keep the meaning, the strength and the scope exactly the same;
- contain the exact phrase "{key}" once, unchanged;
- be one or two sentences in the same casual register.
{cue_rule}
Return only a JSON list of {n} strings.

Message: {text}"""

CUE_RULES = {
    "explicit": "Keep the words that state the scope or strength outright (for example: {markers}).",
    "implicit": "Do not add words that state the scope or strength outright, such as: {markers}. "
                "Leave the scope to the context, as in the original.",
}


def build_prompt(text: str, key: str, item_type: str, cue: str, n: int = N_VARIANTS) -> str:
    rule = ""
    if cue == "explicit" or item_type in IMPLICIT_FORBIDS_MARKERS:
        markers = ", ".join(f'"{m}"' for m in EXPLICIT_MARKERS[item_type])
        rule = "- " + CUE_RULES[cue].format(markers=markers)
    return PROMPT.format(n=n, role=ROLE[item_type], key=key, cue_rule=rule, text=text)


def parse_variants(reply: str) -> list[str]:
    """Pull a JSON list of strings out of a reply; [] when there is none."""
    start, end = reply.find("["), reply.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [v.strip() for v in data if isinstance(v, str) and v.strip()] if isinstance(data, list) else []


def acceptable(variant: str, original: str, key: str, item_type: str, cue: str) -> bool:
    return (
        variant != original
        and count_key(variant, key) == 1
        and cue_ok(variant, item_type, cue)
        and len(variant) <= 3 * len(original) + 40
        and "\n" not in variant
    )


class Paraphraser:
    """Asks an LLM for variants of each phrase once and keeps those that pass the checks.

    With no LLM, every phrase is its own only variant, so generation works offline.
    """

    def __init__(self, llm: LLM | None = None, n: int = N_VARIANTS) -> None:
        self.llm = llm
        self.n = n
        self._memo: dict[tuple[str, str, str, str], list[str]] = {}

    def variants(self, text: str, key: str, item_type: str, cue: str) -> list[str]:
        memo_key = (text, key, item_type, cue)
        if memo_key not in self._memo:
            found: list[str] = []
            if self.llm is not None:
                prompt = build_prompt(text, key, item_type, cue, self.n)
                reply = self.llm.complete([Message("user", prompt)]).text
                for v in parse_variants(reply):
                    if acceptable(v, text, key, item_type, cue) and v not in found:
                        found.append(v)
            self._memo[memo_key] = found[: self.n] or [text]
        return self._memo[memo_key]

    def pick(self, rng: random.Random, text: str, key: str, item_type: str, cue: str) -> str:
        options = self.variants(text, key, item_type, cue)
        return options[rng.randrange(len(options))]
