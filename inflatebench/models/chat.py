"""Turn our Message list into the system + user/assistant turns that chat APIs accept."""

from __future__ import annotations

from datetime import datetime, timezone

from inflatebench.schema import Message

TOOL_PREFIX = "[tool output]\n"


def to_chat(messages: list[Message]) -> tuple[str, list[dict[str, str]]]:
    """System messages are joined into one system prompt.

    Scenario histories hold tool output as plain text without tool-call ids, which neither
    API accepts as a tool turn, so a `tool` message becomes a user turn marked as tool output.
    """
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    turns = []
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            turns.append({"role": "user", "content": TOOL_PREFIX + m.content})
        else:
            turns.append({"role": m.role, "content": m.content})
    return system, turns


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
