"""Phrase-bank entry types, domain templates and scope-cue checks.

Every entry carries an explicit and an implicit variant of the same user
utterance. Both contain `key` exactly once; acknowledgements and tool output
never repeat it, so the key pins the item to a single turn of the history.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any, Callable

# Words that state scope or softness outright. An explicit variant must use one;
# for one-offs and preferences an implicit variant must use none, so that its
# scope or strength comes only from context (pilot round 2).
EXPLICIT_MARKERS: dict[str, tuple[str, ...]] = {
    "one_off": (
        "only", "this time", "this once", "for this run", "just this", "one-off",
        "one-time", "one time", "for now", "for today", "just for",
    ),
    "preference": (
        "if possible", "ideally", "where possible", "if you can", "when possible",
    ),
    "hard_rule": ("never", "always", "must", "no exceptions", "under no circumstances"),
    "changed_value": ("from now on", "instead", "from today", "change of plans"),
    "request": ("now, please",),
}
IMPLICIT_FORBIDS_MARKERS = ("one_off", "preference")


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(re.search(rf"(?<![\w-]){re.escape(m)}(?![\w-])", low) for m in markers)


def cue_ok(text: str, item_type: str, cue: str) -> bool:
    """Does `text` carry the scope cue its condition asks for?"""
    markers = EXPLICIT_MARKERS[item_type]
    if cue == "explicit":
        return _has_marker(text, markers)
    if item_type in IMPLICIT_FORBIDS_MARKERS:
        return not _has_marker(text, markers)
    return True


def count_key(text: str, key: str) -> int:
    """Case-insensitive, non-overlapping occurrences of `key` in `text`."""
    return text.lower().count(key.lower())


@dataclass(frozen=True)
class Phrase:
    """One bank entry: a user utterance in two cue variants plus the reply."""

    key: str
    explicit: str
    implicit: str
    ack: str = "Understood."
    tool: str | None = None  # tool output after the acknowledgement
    scope: str | None = None

    def text(self, cue: str) -> str:
        return self.explicit if cue == "explicit" else self.implicit

    def texts(self) -> list[str]:
        return [self.explicit, self.implicit, self.ack] + ([self.tool] if self.tool else [])


def request(key: str, text: str, tool: str, ack: str = "On it.") -> Phrase:
    """A task request; its explicit variant frames it as a task for now."""
    return Phrase(key=key, explicit=f"{text.rstrip('.')} now, please.", implicit=text,
                  ack=ack, tool=tool)


@dataclass(frozen=True)
class Change(Phrase):
    """A changed value: `before` sets the old value, the utterance replaces it."""

    old: str = ""
    before: str = ""
    before_ack: str = "OK."

    def texts(self) -> list[str]:
        return super().texts() + [self.before, self.before_ack]


@dataclass(frozen=True)
class OneOff(Phrase):
    """A one-off whose promotion the next task and probe would expose."""

    next_task: str = ""
    probe_tool: str = ""
    inflated_if: dict[str, Any] = field(default_factory=dict)

    def texts(self) -> list[str]:
        return super().texts() + [self.next_task]


Padder = Callable[[random.Random, int], tuple[str, str]]


@dataclass(frozen=True)
class Domain:
    """A domain template: openers, phrase banks and realistic tool-output padding.

    Each padder takes an rng and a row budget and returns (assistant action,
    tool output).
    """

    name: str
    intros: tuple[str, ...]
    hard_rules: tuple[Phrase, ...]
    preferences: tuple[Phrase, ...]
    requests: tuple[Phrase, ...]
    changes: tuple[Change, ...]
    one_offs: tuple[OneOff, ...]
    padders: tuple[Padder, ...]

    def entries(self) -> list[tuple[str, Phrase]]:
        groups = [
            ("hard_rule", self.hard_rules),
            ("preference", self.preferences),
            ("request", self.requests),
            ("changed_value", self.changes),
            ("one_off", self.one_offs),
        ]
        return [(t, p) for t, bank in groups for p in bank]
