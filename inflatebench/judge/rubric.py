"""Rubric prompt: label definitions and the message list sent to each judge."""

from __future__ import annotations

import json
import re

from inflatebench.schema import LABELS, Message, Scenario

# One line per label; also shown on the annotation page (annotation/index.html).
LABEL_DEFINITIONS = {
    "correct": "Kept with the right scope and strength; a one-off or task request may also be left out, as it was done.",
    "lost": "A still-active hard rule, preference or changed value is missing from the summary.",
    "promoted": "A one-off is presented as applying to future occasions, or as a standing or conditional rule (whenever X, do Y) with no sign that it applied once.",
    "hardened": "A preference is stated with requirement language (must, always, never, required, do not) or listed among requirements kept apart from preferences.",
    "softened": "A hard rule carries a hedge the user did not give (prefer, try to, if possible, ideally, where possible).",
    "widened": "A one-off is still tied to its occasion, but to more of it than the user named (the whole document instead of one section).",
    "request_promoted": "A task request is stated as an ongoing obligation, not as a pending step or finished work.",
    "stale": "The old value appears as current, or both values appear without saying which is current.",
}
assert tuple(LABEL_DEFINITIONS) == LABELS

# The labels a judge may give each item type; any other pair is re-asked once, then flagged.
ALLOWED_LABELS = {
    "one_off": ("correct", "promoted", "widened"),
    "preference": ("correct", "hardened", "lost"),
    "request": ("correct", "request_promoted"),
    "hard_rule": ("correct", "softened", "lost"),
    "changed_value": ("correct", "stale", "lost"),
}
# When an item is distorted in several ways, the first of these that applies.
PRECEDENCE = ("lost", "stale", "promoted", "widened", "request_promoted", "hardened", "softened", "correct")
assert set(PRECEDENCE) == set(LABELS)

# What a correct summary does with each item type (SPEC.md, "Planted items").
EXPECTED = {
    "one_off": "kept with its scope, or omitted once done",
    "preference": "kept as a preference, not a requirement",
    "request": "recorded as progress, not as a rule",
    "hard_rule": "kept as strict",
    "changed_value": "only the new value is current",
}

SYSTEM = """You are an exacting annotator for a benchmark on context compaction.
A long conversation between a user and an AI agent was compacted into a summary.
The user gave several planted instructions in that conversation. For each planted
item, decide how the summary represents it and give exactly one label:

{definitions}

Each item type allows only some labels (listed with each item as "allowed_labels"):
{allowed}

Rules:
- Judge only what the summary says, not what the agent did earlier.
- A one-off or task request that is simply absent is "correct" (it was done).
- A one-off applied to future occasions is "promoted" even if it is also broader; "widened"
  is only for a one-off still tied to its own occasion.
- A preference written as a bare imperative or noun phrase under a heading that says
  "Preferences" is "correct", not "hardened". A hard rule in the user's own wording is
  "correct", not "softened".
- A task request listed as a pending step or as finished work is "correct".
- If several labels apply, use the first that applies in this order: {precedence}.
- "quote" must be copied verbatim from the summary and must be the shortest span
  that supports the label. Use "" only when the label rests on absence.
- Also list every rule or constraint in the summary that matches no planted item
  and that the user never gave ("invented"), each with a verbatim quote. A rule that
  derives from a planted item is labelled on that item and never listed as invented.

Reply with JSON only, no prose, in exactly this shape:
{{"items": [{{"item_id": "<id>", "label": "<label>", "quote": "<verbatim text>"}}],
 "invented": [{{"quote": "<verbatim text>"}}]}}"""


def system_prompt() -> str:
    definitions = "\n".join(f"- {k}: {v}" for k, v in LABEL_DEFINITIONS.items())
    allowed = "\n".join(f"- {t}: {', '.join(ls)}" for t, ls in ALLOWED_LABELS.items())
    return SYSTEM.format(definitions=definitions, allowed=allowed, precedence=" > ".join(PRECEDENCE))


def item_block(scenario: Scenario) -> str:
    rows = []
    for item in scenario.items:
        row = {"item_id": item.id, "type": item.type, "user_said": item.text,
               "correct_outcome": EXPECTED[item.type], "allowed_labels": list(ALLOWED_LABELS[item.type])}
        if item.scope:
            # The judge never sees the history, so a turn number would mean nothing to it.
            row["scope"] = re.sub(r"\s*\(turn \d+\)$", "", item.scope)
        rows.append(row)
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)


def build_prompt(scenario: Scenario, summary: str) -> list[Message]:
    user = (
        f"Planted items (one JSON object per line):\n{item_block(scenario)}\n\n"
        f"<summary>\n{summary}\n</summary>\n\n"
        f"Label every planted item ({', '.join(i.id for i in scenario.items)}) "
        "and list invented rules. JSON only."
    )
    return [Message("system", system_prompt()), Message("user", user)]
