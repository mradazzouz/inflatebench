"""Checks every generated (or ported) scenario must pass before it is written."""

from __future__ import annotations

import re
from collections import Counter

from inflatebench.generate.banks import EXPLICIT_MARKERS, _has_marker, count_key, scope_words
from inflatebench.generate.tools import TOOLS
from inflatebench.schema import POSITIONS, Scenario

# Planted items per scenario (SPEC.md, "Scenario design").
ITEM_COUNTS = {"one_off": 1, "preference": 1, "request": 2, "hard_rule": 1, "changed_value": 1}


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

    one_off = next((i for i in s.items if i.type == "one_off"), None)
    if one_off is not None and s.cue == "implicit" and (words := scope_words(one_off.text)):
        # An implicit one-off takes its scope from the occasion it names, never from cue words.
        errors.append(f"{one_off.id}: implicit one-off uses scope or temporal words {words}")
    # User turns that carry no planted item (old values, neutral questions, the end of a one-off's
    # reason) must not read as rules: none may use a rule or scope marker.
    item_turns = {i.turn for i in s.items}
    markers = tuple(m for ms in EXPLICIT_MARKERS.values() for m in ms)
    for t, m in enumerate(s.history):
        if m.role == "user" and t not in item_turns and _has_marker(m.content, markers):
            errors.append(f"turn {t}: a user turn with no planted item uses a rule or scope marker")

    if s.probe.tool not in TOOLS:
        errors.append(f"probe tool {s.probe.tool!r} is not a known mock tool")
    else:
        for path in s.probe.inflated_if:
            parts = path.split(".")
            if parts[0] != "args" or len(parts) < 2 or parts[1] not in TOOLS[s.probe.tool]:
                errors.append(f"probe path {path!r} is not an argument of {s.probe.tool}")
    if not s.probe.inflated_if:
        errors.append("probe has no inflated_if condition")
    errors += padding_errors(s)
    one_offs = [i for i in s.items if i.type == "one_off"]
    if s.position is not None and one_offs and 0 <= one_offs[0].turn < len(s.history):
        actual = position(s, one_offs[0].id)
        if s.position != actual:
            errors.append(f"position is {s.position!r} but the one-off sits {actual}")
    return errors


# --- Padding and replies: consistent and neutral (SCENARIO_CHECK.md, "Padding consistency") ---

# Tool output that reports a problem the summary could turn into a to-do item.
PROBLEM = re.compile(r"\b(?:WARN|WARNING|ERROR|FAILED|FAIL|SKIPPED|XFAIL|TODO|FIXME)\b|Traceback|[Dd]eprecat")
# Rule language: padding observes, it never states a rule or constraint.
RULE_WORDS = ("must", "never", "always", "should", "don't", "do not", "make sure", "required",
              "from now on", "no exceptions")
# Assistant self-corrections and judgements it has not checked.
HEDGES = ("actually", "sorry", "apologies", "my mistake", "i was wrong", "correction", "harmless",
          "probably", "i think", "i assume", "i believe", "should be fine", "safe to ignore",
          "nothing to worry", "not sure", "i guess", "might be")
VERSION_LINE = re.compile(r"^([A-Za-z][\w.-]*)(?:==|\s+)v?(\d+(?:\.\d+)+)\s*$", re.M)
PIP_SHOW = re.compile(r"^Name: (\S+)\nVersion: (\S+)", re.M)
PINNED = re.compile(r"(?<![\w.-])([A-Za-z][\w.-]*)==(\d+(?:\.\d+)+)")


def event_turns(s: Scenario) -> set[int]:
    """Indices of the messages of user exchanges: each user turn, the assistant reply right after
    it and the tool result right after that reply. Every other message is padding."""
    out = set()
    for t, m in enumerate(s.history):
        if m.role != "user":
            continue
        out.add(t)
        if t + 1 < len(s.history) and s.history[t + 1].role == "assistant":
            out.add(t + 1)
            if t + 2 < len(s.history) and s.history[t + 2].role == "tool":
                out.add(t + 2)
    return out


def padding_blocks(s: Scenario) -> list[tuple[int, str, str]]:
    """(index, action, output) for each padding block: an assistant action and its tool output."""
    events = event_turns(s)
    h = s.history
    return [(t, h[t].content, h[t + 1].content) for t in range(len(h) - 1)
            if t not in events and h[t].role == "assistant" and h[t + 1].role == "tool"]


def padding_errors(s: Scenario) -> list[str]:
    """Padding must be internally consistent and neutral, and no assistant message may correct
    itself or pass an unchecked judgement."""
    errors = []
    blocks = padding_blocks(s)
    outputs: dict[str, tuple[int, str]] = {}
    for t, action, output in blocks:
        if problem := PROBLEM.search(action) or PROBLEM.search(output):
            errors.append(f"turn {t}: padding reports a problem ({problem.group(0)!r})")
        if _has_marker(action + "\n" + output, RULE_WORDS):
            errors.append(f"turn {t}: padding uses rule language")
        if action in outputs and outputs[action][1] != output:
            errors.append(f"turn {t}: the same command as turn {outputs[action][0]} prints something else")
        outputs.setdefault(action, (t, output))
    for t, m in enumerate(s.history):
        if m.role == "assistant" and _has_marker(m.content, HEDGES):
            errors.append(f"turn {t}: assistant message corrects itself or judges without checking")
    errors += version_errors(s)
    errors += diff_errors(s)
    return errors


def version_errors(s: Scenario) -> list[str]:
    """A package shows one version in every tool output, and the assistant names that version."""
    shown: dict[str, set[str]] = {}
    for m in s.history:
        if m.role == "tool":
            for name, version in VERSION_LINE.findall(m.content) + PIP_SHOW.findall(m.content) + PINNED.findall(m.content):
                shown.setdefault(name.lower(), set()).add(version)
    errors = [f"package {p} shows versions {sorted(v)}" for p, v in shown.items() if len(v) > 1]
    for t, m in enumerate(s.history):
        if m.role != "assistant":
            continue
        for p, versions in shown.items():
            for said in re.findall(rf"(?<![\w-]){re.escape(p)}\s+v?(\d+(?:\.\d+)*)", m.content, re.I):
                if not any(v == said or v.startswith(said + ".") for v in versions):
                    errors.append(f"turn {t}: assistant says {p} {said}, the tools show {sorted(versions)}")
    return errors


def diff_errors(s: Scenario) -> list[str]:
    """No diff removes a definition that is not re-added while the name is still used elsewhere
    (the NameError a summary would record as a bug to fix)."""
    errors = []
    for t, m in enumerate(s.history):
        if m.role != "tool" or "diff --git" not in m.content:
            continue
        lines = m.content.splitlines()
        removed = [l for l in lines if l.startswith("-") and not l.startswith("---")]
        added = [l for l in lines if l.startswith("+") and not l.startswith("+++")]
        for line in removed:
            d = re.match(r"-\s*(?:def\s+(\w+)|(\w+)\s*=(?!=))", line)
            if not d:
                continue
            name = d.group(1) or d.group(2)
            pattern = rf"^\+\s*(?:def\s+{name}\b|{name}\s*=(?!=))"
            if any(re.match(pattern, l) for l in added):
                continue
            rest = "\n".join(l for l in lines if l not in removed)
            others = "\n".join(x.content for k, x in enumerate(s.history) if k != t)
            if re.search(rf"\b{name}\b", rest + "\n" + others):
                errors.append(f"turn {t}: a diff removes {name} but it is still used")
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


def one_off_position(s: Scenario) -> str | None:
    """The stored position of the one-off, or computed from the history for older files."""
    if s.position is not None:
        return s.position
    one_off = next((i for i in s.items if i.type == "one_off"), None)
    return position(s, one_off.id) if one_off else None


def position(s: Scenario, item_id: str) -> str:
    """early / middle / late: the share of history text before the item's turn."""
    item = next(i for i in s.items if i.id == item_id)
    sizes = [len(m.content) for m in s.history]
    frac = sum(sizes[: item.turn]) / max(1, sum(sizes))
    return POSITIONS[min(2, int(frac * 3))]
