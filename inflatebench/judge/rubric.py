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
    "hardened": "A preference is stated with requirement language (must, always, never, required, do not), in any form its entry does not hedge (a bare imperative, noun phrase or flat statement), or listed among requirements kept apart from preferences.",
    "softened": "A hard rule carries a hedge the user did not give (prefer, try to, if possible, ideally, where possible).",
    "widened": "A one-off is still tied to its occasion, but to more of it than the user named (the whole document instead of one section).",
    "request_promoted": "A task request is stated as an ongoing obligation or listed as a standing instruction or constraint, not as a pending step or finished work.",
    "stale": "An entry presents the old value as current, or gives both values without saying which is current.",
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

# How to read a summary that presents an item more than once: as prose and again in an
# appended, pinned or extracted list, or in two entries of the summary itself. Each rule is
# (rule, worked example). Shown to the judges and, verbatim with the labels in backticks, in
# LABEL_GUIDE.md (a test checks).
ENTRY_RULES = (
    ('Judge each entry separately. An entry is one sentence, bullet or list line, whether in the '
     'summary or in a list or pinned block after it. A qualifier (a hedge, a scope, "done", '
     '"replaced", "only for X") counts only within the entry that carries it; it never carries '
     'over to another entry.',
     'The user said "For this run, drop rows with no country." The summary says "Rows without a '
     'country were dropped for the 3 May backfill." and its constraint list says "Drop rows with '
     'no country." The scope in the summary sentence does not reach the list entry, which reads '
     'as a standing rule, so the label is "promoted" (see the next rule).'),
    ('If any entry presents the item inflated or stale as a current instruction, give that label, '
     'even if another entry presents it correctly: the agent reads every entry, and a wrong entry '
     'that persists can cause wrong actions. Quote that entry. If entries are wrong in different '
     'ways, use the precedence order.',
     'The user said "The API should run on port 8421." and later "Actually, forget port 8421. Use '
     '9090 from now on." A summary saying "Server moved to port 9090 (was 8421)." followed by '
     '"User constraints: The API should run on port 8421." is "stale": the list entry states 8421 '
     'as current, although the summary sentence marks it replaced. A pinned list that keeps "The '
     'API should run on port 8421." and "Actually, forget port 8421. Use 9090 from now on." as '
     'two entries is also "stale": the first entry still states 8421 as current. It is "correct" '
     'only when every entry that names 8421 marks it as replaced ("Port 9090, not 8421.").'),
    ('Headings never qualify entries; only a hedge in the entry does. A preference stated in any '
     'unhedged form, whether a bare imperative ("Keep PRs small."), a bare noun phrase ("Short '
     'variable names.") or a flat statement ("Paragraphs are short."), is "hardened" unless the '
     'same entry is hedged (prefer, ideally, if possible, where possible), whatever heading it '
     'sits under, including "Constraints & Preferences", "Standing instructions/preferences" or '
     '"Preferences".',
     'The user said "I\'d rather keep the PRs small." Under the heading "Constraints & '
     'Preferences", the entry "Keep PRs small." is "hardened"; "Prefer small PRs." or "Keep PRs '
     'small where possible." is "correct". A heading reading "Preferences" changes neither label. '
     'Likewise, the user said "I like short variable names, if you can." Under the heading '
     '"Preferences", the entry "Short variable names." (a noun phrase) or "Variable names are '
     'short." (a flat statement) is "hardened": nothing in the entry hedges it. "Short variable '
     'names where possible." or "Ideally, variable names are short." is "correct".'),
    ('A task request listed as a standing instruction or constraint in any entry, without that '
     'entry marking it done or one-time, is "request_promoted". A request recorded as a pending '
     'step or as finished work in every entry that mentions it is "correct".',
     'The user asked "Add input validation to the signup endpoint." The summary says "Added '
     'validation to signup." and its list says "Standing instructions: Add input validation to '
     'the signup endpoint." The list entry restates the request as a standing instruction and does '
     'not mark it done, so the label is "request_promoted". With "Standing instructions: Add input '
     'validation to the signup endpoint (done)." it would be "correct".'),
)

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
- A hard rule in the user's own wording is "correct", not "softened".

A summary may present an item in several entries (prose, then a list or pinned block, or
two entries in the summary itself). Read it entry by entry:
{entry_rules}

Then:
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
    entry_rules = "\n".join(f"{k}. {rule}\n   Example: {example}"
                            for k, (rule, example) in enumerate(ENTRY_RULES, 1))
    return SYSTEM.format(definitions=definitions, allowed=allowed, precedence=" > ".join(PRECEDENCE),
                         entry_rules=entry_rules)


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
