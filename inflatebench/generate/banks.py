"""Phrase-bank entry types, domain templates and scope-cue checks.

Every entry carries an explicit and an implicit variant of the same user
utterance. Both contain `key` exactly once; acknowledgements and tool output
never repeat it, so the key pins the item to a single turn of the history.

Only the one-off follows the scenario's cue. The other items always use one fixed
variant (FIXED_CUE), so the explicit/implicit factor changes the one-off and nothing else;
their other variant is kept in the bank for paraphrase experiments but never used.
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
    "request": (),
}
IMPLICIT_FORBIDS_MARKERS = ("one_off", "preference")
# The variant every non-one-off item uses whatever the scenario's cue: hard rules, preferences
# and changed values state their strength outright, requests are plain task requests.
FIXED_CUE = {"hard_rule": "explicit", "preference": "explicit", "changed_value": "explicit",
             "request": "implicit"}
# Words an implicit one-off must not contain: the explicit scope markers plus temporal words,
# so its scope comes only from the context (the occasion it names), never from a cue word.
SCOPE_WORDS = tuple(dict.fromkeys(EXPLICIT_MARKERS["one_off"] + (
    "today", "tonight", "tomorrow", "yesterday", "now", "right now", "currently", "at the moment",
    "for the moment", "for now", "this time", "once", "just", "yet", "still", "temporarily",
    "this week", "this morning", "this afternoon", "this evening", "later", "until", "while",
    "during", "for a while", "again",
)))


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(re.search(rf"(?<![\w-]){re.escape(m)}(?![\w-])", low) for m in markers)


def item_cue(item_type: str, cue: str) -> str:
    """The variant an item uses in a scenario with this cue (only one-offs follow the cue)."""
    return cue if item_type == "one_off" else FIXED_CUE[item_type]


def scope_words(text: str) -> list[str]:
    """The scope and temporal words (SCOPE_WORDS) in `text`."""
    return [w for w in SCOPE_WORDS if _has_marker(text, (w,))]


def cue_ok(text: str, item_type: str, cue: str) -> bool:
    """Does `text` carry the cue its item uses in a scenario with this cue?

    An explicit variant must use one of its type's markers; an implicit one-off must use no
    scope or temporal word at all, and an implicit preference no softness marker.
    """
    cue = item_cue(item_type, cue)
    markers = EXPLICIT_MARKERS[item_type]
    if cue == "explicit":
        return _has_marker(text, markers)
    if item_type == "one_off":
        return not scope_words(text)
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
    # Hard rules: probe tools ("deploy") or probe arguments ("run_job.full_refresh") the rule
    # forbids or gates.
    blocks: tuple[str, ...] = ()

    def text(self, cue: str) -> str:
        return self.explicit if cue == "explicit" else self.implicit

    def texts(self) -> list[str]:
        return [self.explicit, self.implicit, self.ack] + ([self.tool] if self.tool else [])


def request(key: str, text: str, tool: str, ack: str = "On it.") -> Phrase:
    """A task request: one plain wording, the same in every scenario."""
    return Phrase(key=key, explicit=text, implicit=text, ack=ack, tool=tool)


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
    # A later (user, assistant) exchange saying the reason for the one-off has ended, for
    # one-offs whose reason could otherwise still hold at the next task.
    resolved: tuple[str, str] | None = None

    def texts(self) -> list[str]:
        return super().texts() + [self.next_task] + list(self.resolved or ())


def blocks_probe(rule: Phrase, one_off: OneOff) -> bool:
    """Does the hard rule forbid or gate the one-off's probe tool, or an argument the probe checks?"""
    args = {f"{one_off.probe_tool}.{path.split('.')[1]}" for path in one_off.inflated_if}
    return one_off.probe_tool in rule.blocks or bool(args & set(rule.blocks))


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
    # (user, assistant) exchanges that are not instructions: questions, thanks, clarifications.
    neutral: tuple[tuple[str, str], ...] = ()

    def entries(self) -> list[tuple[str, Phrase]]:
        groups = [
            ("hard_rule", self.hard_rules),
            ("preference", self.preferences),
            ("request", self.requests),
            ("changed_value", self.changes),
            ("one_off", self.one_offs),
        ]
        return [(t, p) for t, bank in groups for p in bank]
