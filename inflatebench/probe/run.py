"""Stage 4: run the agent on every summary of a run -> runs/<run_id>/probes.jsonl."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from inflatebench.probe.agent import MAX_STEPS, run_agent
from inflatebench.probe.check import inflated
from inflatebench.schema import ProbeResult, Scenario, Summary, read_jsonl, write_jsonl

if TYPE_CHECKING:
    from inflatebench.models import LLM


def probe_summary(agent: LLM, scenario: Scenario, summary: Summary, agent_name: str = "",
                  max_steps: int = MAX_STEPS) -> ProbeResult:
    # The repeat is part of the cache key, so repeats are fresh samples that still resume.
    episode = run_agent(agent, scenario, summary.messages, max_steps, repeat=summary.repeat)
    return ProbeResult(
        scenario_id=scenario.id, condition=summary.condition, model=summary.model,
        repeat=summary.repeat, tool_calls=episode.calls,
        inflated=inflated(episode.calls, scenario.probe),
        agent=agent_name,
        probe_called=any(c["tool"] == scenario.probe.tool for c in episode.calls),
    )


def probe_summaries(agent: LLM, scenarios: Iterable[Scenario], summaries: Iterable[Summary],
                    agent_name: str = "", max_steps: int = MAX_STEPS) -> list[ProbeResult]:
    by_id = {s.id: s for s in scenarios}
    return [probe_summary(agent, by_id[s.scenario_id], s, agent_name, max_steps) for s in summaries]


def probe_run(agent: LLM, scenarios_path: str | Path, run_dir: str | Path, agent_name: str = "",
              max_steps: int = MAX_STEPS) -> Path:
    run_dir = Path(run_dir)
    results = probe_summaries(agent, read_jsonl(scenarios_path, Scenario),
                              read_jsonl(run_dir / "summaries.jsonl", Summary), agent_name, max_steps)
    out = run_dir / "probes.jsonl"
    write_jsonl(out, results)
    return out
