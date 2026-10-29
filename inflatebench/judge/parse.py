"""Parse and validate a judge's JSON reply."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from inflatebench.schema import LABELS, Scenario


class JudgeError(ValueError):
    """The judge reply is not valid JSON or does not cover the planted items."""


@dataclass
class Verdict:
    """One judge's parsed reply: item_id -> (label, quote), plus invented quotes."""

    items: dict[str, tuple[str, str]]
    invented: list[str] = field(default_factory=list)
    # Quotes not found in the summary after one re-ask: item ids, and invented quotes.
    flagged_items: set[str] = field(default_factory=set)
    flagged_invented: set[str] = field(default_factory=set)
    # Items whose label their type does not allow, after one re-ask.
    flagged_types: set[str] = field(default_factory=set)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> Any:
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for chunk in candidates:
        chunk = chunk.strip()
        start = chunk.find("{")
        if start < 0:
            continue
        try:
            obj, _ = json.JSONDecoder().raw_decode(chunk[start:])
        except json.JSONDecodeError:
            continue
        return obj
    raise JudgeError(f"no JSON object in judge reply: {text[:200]!r}")


def parse_verdict(text: str, scenario: Scenario) -> Verdict:
    data = _extract_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise JudgeError("judge reply has no 'items' list")
    expected = {i.id for i in scenario.items}
    items: dict[str, tuple[str, str]] = {}
    for entry in data["items"]:
        if not isinstance(entry, dict):
            raise JudgeError(f"item entry is not an object: {entry!r}")
        item_id, label = entry.get("item_id"), entry.get("label")
        quote = entry.get("quote") or ""
        if item_id not in expected:
            raise JudgeError(f"unknown item_id {item_id!r}")
        if label not in LABELS:
            raise JudgeError(f"invalid label {label!r} for {item_id}")
        if item_id in items:
            raise JudgeError(f"item {item_id} labelled twice")
        items[item_id] = (label, str(quote))
    missing = expected - set(items)
    if missing:
        raise JudgeError(f"judge reply misses items {sorted(missing)}")
    invented = []
    for entry in data.get("invented") or []:
        quote = entry.get("quote") if isinstance(entry, dict) else entry
        if isinstance(quote, str) and quote.strip():
            invented.append(quote.strip())
    return Verdict(items=items, invented=invented)


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def quote_in_summary(quote: str, summary: str) -> bool:
    """True if the quote appears in the summary, ignoring case and whitespace."""
    return _squash(quote) in _squash(summary)


def unquoted(verdict: Verdict, summary: str) -> tuple[set[str], set[str]]:
    """Item ids and invented quotes whose quote is not in the summary (an empty quote passes)."""
    items = {i for i, (_, q) in verdict.items.items() if q.strip() and not quote_in_summary(q, summary)}
    invented = {q for q in verdict.invented if not quote_in_summary(q, summary)}
    return items, invented


def same_rule(a: str, b: str, threshold: float = 0.5) -> bool:
    """Whether two invented-rule quotes refer to the same text (containment or word overlap)."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    wa, wb = set(na.split()), set(nb.split())
    return len(wa & wb) / len(wa | wb) >= threshold


def disallowed(verdict: Verdict, scenario: Scenario) -> set[str]:
    """Item ids whose label the item's type does not allow (rubric.ALLOWED_LABELS)."""
    from inflatebench.judge.rubric import ALLOWED_LABELS

    types = {i.id: i.type for i in scenario.items}
    return {i for i, (label, _) in verdict.items.items() if label not in ALLOWED_LABELS[types[i]]}
