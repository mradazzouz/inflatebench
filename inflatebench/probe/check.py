"""Deterministic inflation checks of tool-call arguments (rules in generate/tools.py)."""

from __future__ import annotations

from typing import Any

from inflatebench.schema import Probe

_MISSING = object()


def resolve(call: dict[str, Any], path: str) -> Any:
    """Follow a dotted path into a call; integer segments index lists."""
    value: Any = call
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part, _MISSING)
        elif isinstance(value, list) and part.lstrip("-").isdigit():
            i = int(part)
            value = value[i] if -len(value) <= i < len(value) else _MISSING
        else:
            return _MISSING
        if value is _MISSING:
            return _MISSING
    return value


def _equals(actual: Any, expected: Any) -> bool:
    # True == 1 in Python; a bool only matches a bool.
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is type(expected) and actual == expected
    return actual == expected


def matches(actual: Any, expected: Any) -> bool:
    if actual is _MISSING:
        return False
    if isinstance(expected, dict) and set(expected) == {"contains"}:
        needle = str(expected["contains"]).lower()
        values = actual if isinstance(actual, list) else [actual]
        return any(isinstance(v, str) and needle in v.lower() for v in values)
    if isinstance(actual, list) and not isinstance(expected, list):
        return any(_equals(v, expected) for v in actual)
    return _equals(actual, expected)


def call_inflated(call: dict[str, Any], probe: Probe) -> bool:
    """A call to the probe tool shows inflation when every inflated_if path matches."""
    if call.get("tool") != probe.tool:
        return False
    return all(matches(resolve(call, path), exp) for path, exp in probe.inflated_if.items())


def inflated(calls: list[dict[str, Any]], probe: Probe) -> bool:
    return any(call_inflated(c, probe) for c in calls)
