"""Checks every generated (or ported) scenario must pass before it is written."""

from __future__ import annotations

from collections import Counter

from inflatebench.generate.banks import count_key
from inflatebench.generate.tools import TOOLS
from inflatebench.schema import Scenario

# Planted items per scenario (SPEC.md, "Scenario design").
ITEM_COUNTS = {"one_off": 1, "preference": 1, "request": 2, "hard_rule": 1, "changed_value": 1}
POSITIONS = ("early", "middle", "late")


def validate(s: Scenario) -> list[str]:
    """Return every problem found; an empty list means the scenario is valid."""
    errors = []
    counts = Counter(i.type for i in s.items)
    if dict(counts) != ITEM_COUNTS:
        errors.append(f"item counts {dict(counts)} != {ITEM_COUNTS}")
    if len({i.id for i in s.items}) != len(s.items):
        errors.append("duplicate item ids")

    for item in s.items:
        total = sum(count_key(m.content, item.key) for m in s.history)
        if total != 1:
            errors.append(f"{item.id}: key {item.key!r} appears {total} times in the history, expected 1")
        if not 0 <= item.turn < len(s.history):
            errors.append(f"{item.id}: turn {item.turn} out of range")
            continue
        msg = s.history[item.turn]
        if msg.role != "user":
            errors.append(f"{item.id}: turn {item.turn} is a {msg.role} message, expected user")
        if count_key(msg.content, item.key) != 1:
            errors.append(f"{item.id}: key {item.key!r} is not in turn {item.turn}")
        if item.text not in msg.content:
            errors.append(f"{item.id}: text is not in turn {item.turn}")
        if count_key(s.next_task, item.key):
            errors.append(f"{item.id}: key {item.key!r} appears in the next task")
        # The agent's prompt lists the mock tools; their descriptions must not hand it the phrase.
        leaks = [t for t, args in TOOLS.items() if any(count_key(d, item.key) for d in args.values())]
        if leaks:
            errors.append(f"{item.id}: key {item.key!r} appears in the description of {leaks}")

    if s.probe.tool not in TOOLS:
        errors.append(f"probe tool {s.probe.tool!r} is not a known mock tool")
    else:
        for path in s.probe.inflated_if:
            parts = path.split(".")
            if parts[0] != "args" or len(parts) < 2 or parts[1] not in TOOLS[s.probe.tool]:
                errors.append(f"probe path {path!r} is not an argument of {s.probe.tool}")
    if not s.probe.inflated_if:
        errors.append("probe has no inflated_if condition")
    return errors


def assert_valid(s: Scenario) -> None:
    errors = validate(s)
    if errors:
        raise ValueError(f"{s.id}: " + "; ".join(errors))


def approx_tokens(text: str) -> int:
    """Rough token count (about four characters per token for English)."""
    return (len(text) + 3) // 4


def history_tokens(s: Scenario) -> int:
    return sum(approx_tokens(m.content) for m in s.history)


def position(s: Scenario, item_id: str) -> str:
    """early / middle / late: the share of history text before the item's turn."""
    item = next(i for i in s.items if i.id == item_id)
    sizes = [len(m.content) for m in s.history]
    frac = sum(sizes[: item.turn]) / max(1, sum(sizes))
    return POSITIONS[min(2, int(frac * 3))]
