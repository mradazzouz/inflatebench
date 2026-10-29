"""Rubric prompt: label definitions and the message list sent to each judge."""

from __future__ import annotations

import json

from inflatebench.schema import LABELS, Message, Scenario

# One line per label; also shown on the annotation page (annotation/index.html).
LABEL_DEFINITIONS = {
    "correct": "Kept with the right scope and strength, or correctly omitted once done.",
    "lost": "A still-active rule or preference is missing from the summary.",
    "promoted": "A one-off (scoped to one file, run, item, section or date) appears as a standing rule.",
    "hardened": "A soft preference appears as a requirement.",
    "softened": "A hard standing rule appears as a preference or optional.",
    "widened": "A scoped rule appears with a broader scope than the user gave it.",
    "request_promoted": "A one-time task request appears as a standing rule rather than as progress.",
    "stale": "An old, replaced value appears as current.",
}
assert tuple(LABEL_DEFINITIONS) == LABELS

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

Rules:
- Judge only what the summary says, not what the agent did earlier.
- A one-off or task request that is simply absent is "correct" (it was done).
- If an item is distorted in several ways, pick the label for the most consequential one.
- "quote" must be copied verbatim from the summary and must be the shortest span
  that supports the label. Use "" only when the label rests on absence.
- Also list every rule or constraint in the summary that matches no planted item
  and that the user never gave ("invented"), each with a verbatim quote.

Reply with JSON only, no prose, in exactly this shape:
{{"items": [{{"item_id": "<id>", "label": "<label>", "quote": "<verbatim text>"}}],
 "invented": [{{"quote": "<verbatim text>"}}]}}"""


def system_prompt() -> str:
    definitions = "\n".join(f"- {k}: {v}" for k, v in LABEL_DEFINITIONS.items())
    return SYSTEM.format(definitions=definitions)


def item_block(scenario: Scenario) -> str:
    rows = []
    for item in scenario.items:
        row = {"item_id": item.id, "type": item.type, "user_said": item.text,
               "correct_outcome": EXPECTED[item.type]}
        if item.scope:
            row["scope"] = item.scope
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
