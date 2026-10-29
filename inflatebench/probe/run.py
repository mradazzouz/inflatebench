"""Stage 4: run the agent on every summary of a run -> runs/<run_id>/probes.jsonl.

Besides one probe per summary, the agent also acts on each scenario's uncompacted history,
once per model and repeat of the run (condition FULL). That baseline separates what compaction
does to the agent's behaviour from what the agent does with the whole conversation anyway.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from inflatebench.probe.agent import MAX_STEPS, run_agent
from inflatebench.probe.check import inflated, refusal
from inflatebench.schema import Message, ProbeResult, Scenario, Summary, read_jsonl, write_jsonl

if TYPE_CHECKING:
    from inflatebench.models import LLM


# The probe condition in which the agent sees the uncompacted history.
FULL = "full"


def probe_context(agent: LLM, scenario: Scenario, context: list[Message], condition: str,
                  model: str, repeat: int, agent_name: str = "",
                  max_steps: int = MAX_STEPS) -> ProbeResult:
    # The repeat is part of the cache key, so repeats are fresh samples that still resume.
    episode = run_agent(agent, scenario, context, max_steps, repeat=repeat)
    return ProbeResult(
        scenario_id=scenario.id, condition=condition, model=model,
        repeat=repeat, tool_calls=episode.calls,
        inflated=inflated(episode.calls, scenario.probe),
        agent=agent_name,
        probe_called=any(c["tool"] == scenario.probe.tool for c in episode.calls),
        refusal=refusal(episode.final, episode.provider_refused, episode.calls, scenario.probe),
    )


def probe_summary(agent: LLM, scenario: Scenario, summary: Summary, agent_name: str = "",
                  max_steps: int = MAX_STEPS) -> ProbeResult:
    return probe_context(agent, scenario, summary.messages, summary.condition, summary.model,
                         summary.repeat, agent_name, max_steps)


def probe_full(agent: LLM, scenario: Scenario, model: str, repeat: int, agent_name: str = "",
               max_steps: int = MAX_STEPS) -> ProbeResult:
    """The baseline: the agent acts on the scenario's whole history, nothing compacted.

    `model` is the run's compaction model, recorded so the baseline lines up with that model's
    summaries in the analysis; no compaction happens here.
    """
    return probe_context(agent, scenario, scenario.history, FULL, model, repeat, agent_name, max_steps)


def probe_summaries(agent: LLM, scenarios: Iterable[Scenario], summaries: Iterable[Summary],
                    agent_name: str = "", max_steps: int = MAX_STEPS,
                    full: bool = True) -> list[ProbeResult]:
    """One probe per summary, then (with `full`) one full-history probe per scenario, model and
    repeat that the summaries cover."""
    by_id = {s.id: s for s in scenarios}
    summaries = list(summaries)
    out = [probe_summary(agent, by_id[s.scenario_id], s, agent_name, max_steps) for s in summaries]
    if full:
        keys = dict.fromkeys((s.scenario_id, s.model, s.repeat) for s in summaries)
        out += [probe_full(agent, by_id[sid], model, repeat, agent_name, max_steps)
                for sid, model, repeat in keys]
    return out


def probe_run(agent: LLM, scenarios_path: str | Path, run_dir: str | Path, agent_name: str = "",
              max_steps: int = MAX_STEPS, full: bool = True) -> Path:
    run_dir = Path(run_dir)
    results = probe_summaries(agent, read_jsonl(scenarios_path, Scenario),
                              read_jsonl(run_dir / "summaries.jsonl", Summary), agent_name, max_steps,
                              full)
    out = run_dir / "probes.jsonl"
    write_jsonl(out, results)
    return out
