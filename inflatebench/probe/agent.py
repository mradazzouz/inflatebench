"""Agent loop: compacted context + next task -> tool calls against the mock tools.

Providers here are text in, text out, so tools use a plain JSON protocol instead of a
provider's native tool calling: the same prompt works for every model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from inflatebench.probe.tools import call_tool, describe, format_result, tools_for
from inflatebench.schema import Message, Scenario

if TYPE_CHECKING:
    from inflatebench.models import LLM

MAX_STEPS = 8

# One system prompt for compacted contexts and the full-history baseline alike, so the two
# differ only in the context the agent is given.
SYSTEM = """You are an AI agent working for a user. Your earlier work with this user follows,
either in full or compacted into a summary. Carry out the user's next task with the tools
below, and finish it completely, including any final step that saves, sends, commits,
schedules, runs or publishes the work.

To call a tool, write a JSON object of this shape on its own:
{{"tool": "<name>", "args": {{"<argument>": <value>}}}}
You may call several tools in one reply; each result comes back in the next message. Use
only the tools and arguments listed; an argument you leave out takes the tool's default.
When the task is done, reply in plain text with no JSON object.

Tools:
{tools}"""


@dataclass
class Episode:
    """Every tool call the agent made (with an error, if the mock rejected it) and its last reply."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    final: str = ""
    steps: int = 0


def parse_calls(text: str) -> list[tuple[str, Any]]:
    """Every JSON object with a string "tool" in a reply, in order, as (name, args)."""
    decoder = json.JSONDecoder()
    out, pos = [], 0
    while (start := text.find("{", pos)) >= 0:
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            pos = start + 1
            continue
        if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
            out.append((obj["tool"], obj.get("args", {})))
        pos = end
    return out


def build_messages(scenario: Scenario, context: list[Message], tools: list[str]) -> list[Message]:
    return [Message("system", SYSTEM.format(tools=describe(tools))), *context,
            Message("user", scenario.next_task)]


def run_agent(llm: LLM, scenario: Scenario, context: list[Message],
              max_steps: int = MAX_STEPS, **params: Any) -> Episode:
    tools = tools_for(scenario)
    messages = build_messages(scenario, context, tools)
    episode = Episode()
    for _ in range(max_steps):
        reply = llm.complete(messages, **params).text
        episode.steps += 1
        episode.final = reply
        calls = parse_calls(reply)
        if not calls:
            break
        results = []
        for name, args in calls:
            result = call_tool(name, args, tools)
            record: dict[str, Any] = {"tool": name, "args": args}
            if not result["ok"]:
                record["error"] = result["error"]
            episode.calls.append(record)
            results.append(format_result(name, result))
        messages = messages + [Message("assistant", reply), Message("tool", "\n".join(results))]
    return episode
