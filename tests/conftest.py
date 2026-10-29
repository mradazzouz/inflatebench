"""Shared fixtures: the ported pilot scenarios and a seeded synthetic run."""

from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path

import pytest

from inflatebench.analyze.metrics import INFLATION_TYPES
from inflatebench.judge.judges import FINAL
from inflatebench.schema import INVENTED, Label, ProbeResult, Scenario, Summary, read_jsonl

FIXTURES = Path(__file__).parent / "fixtures"
CONDITIONS = ["free", "sectioned", "keep_rules", "extractor", "pinning"]
# Chance that an eligible item is inflated, per condition (pinning inflates most).
INFLATE_P = {"free": 0.10, "sectioned": 0.30, "keep_rules": 0.40, "extractor": 0.50, "pinning": 0.60}
LOSE_P = {"free": 0.40, "sectioned": 0.25, "keep_rules": 0.15, "extractor": 0.08, "pinning": 0.04}


@pytest.fixture
def pilot() -> list[Scenario]:
    return list(read_jsonl(FIXTURES / "scenarios.jsonl", Scenario))


@pytest.fixture
def summaries() -> list[Summary]:
    return list(read_jsonl(FIXTURES / "summaries.jsonl", Summary))


def synthetic_label(item_type: str, scoped: bool, condition: str, rng: random.Random) -> str:
    kinds = [k for k, rule in INFLATION_TYPES.items() if rule(item_type, scoped)]
    if kinds and rng.random() < INFLATE_P[condition]:
        return rng.choice(kinds)
    if item_type in ("hard_rule", "changed_value", "preference") and rng.random() < LOSE_P[condition]:
        return "lost"
    if item_type == "changed_value" and rng.random() < 0.1:
        return "stale"
    return "correct"


def synthetic_run(base: list[Scenario], n_scenarios: int = 40, models=("m-a", "m-b"),
                  repeats: int = 2, seed: int = 0):
    """Scenarios cloned from the pilot fixtures, with final labels and probes drawn at known rates."""
    rng = random.Random(seed)
    call_rng = random.Random(seed + 1)  # separate, so the label and probe draws stay as they were
    scenarios = []
    for k in range(n_scenarios):
        s = base[k % len(base)]
        scenarios.append(replace(s, id=f"syn-{k:03d}", seed=k, cue=("explicit", "implicit")[k % 2],
                                 template=f"syn-t{k % 8}",  # shared one-off templates, as generated
                                 length=("short", "medium", "long")[k % 3],
                                 # k // 6, so position is not confounded with cue and length
                                 position=("early", "middle", "late")[(k // 6) % 3]))
    labels, probes = [], []
    for s in scenarios:
        bias = rng.gauss(0, 0.5)  # per-scenario difficulty, the random effect
        for cond in CONDITIONS:
            for model in models:
                for rep in range(repeats):
                    meta = dict(scenario_id=s.id, condition=cond, model=model, repeat=rep)
                    any_inflated = False
                    for item in s.items:
                        lab = synthetic_label(item.type, item.scope is not None, cond, rng)
                        any_inflated |= lab not in ("correct", "lost", "stale")
                        labels.append(Label(judge=FINAL, item_id=item.id, label=lab, **meta))
                    if rng.random() < INFLATE_P[cond] / 2:
                        labels.append(Label(judge=FINAL, item_id=None, label=INVENTED,
                                            quote="Always notify on-call.", **meta))
                    acted = any_inflated and rng.random() < min(1.0, 0.6 + bias / 4)
                    called = acted or call_rng.random() < 0.5
                    probes.append(ProbeResult(inflated=acted, probe_called=called, **meta))
    return scenarios, labels, probes
