"""Synthetic runs with known effects for the preregistered hypothesis tests (test_hypotheses.py).

Two runs, one model each, on shared scenarios cloned from the pilot fixtures. Labels and probes
are drawn at rates set per condition, so each hypothesis has a known truth:

- inflation (one-offs promoted, preferences hardened, requests promoted) at INFLATE[condition];
  implicit one-offs are promoted IMPLICIT_BOOST more often;
- active items lost at LOSE[condition];
- free_limited gets exactly free's labels and probes (difference 0 in every bootstrap draw);
- no softened or stale labels unless `stale` names a (model, condition) cell and its rate;
- the probe acts on inflation at BEHAVE[condition], the full-history baseline included.
"""

from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path

from inflatebench.judge.judges import FINAL
from inflatebench.schema import Label, Message, ProbeResult, Scenario, Summary, read_jsonl, write_jsonl

FIXTURES = Path(__file__).parent / "fixtures"
CONDITIONS = ["free", "sectioned", "keep_rules", "extractor", "pinning", "free_limited",
              "sectioned_noconstraints"]
INFLATE = {"free": 0.10, "sectioned": 0.35, "keep_rules": 0.35, "extractor": 0.60, "pinning": 0.60,
           "free_limited": 0.10, "sectioned_noconstraints": 0.10}
LOSE = {"free": 0.35, "sectioned": 0.35, "keep_rules": 0.20, "extractor": 0.08, "pinning": 0.08,
        "free_limited": 0.35, "sectioned_noconstraints": 0.35}
BEHAVE = {"full": 0.05, "free": 0.10, "sectioned": 0.40, "keep_rules": 0.40, "extractor": 0.50,
          "pinning": 0.50, "free_limited": 0.10, "sectioned_noconstraints": 0.10}
IMPLICIT_BOOST = 0.35
MODELS = ("m-haiku", "m-glm")
INFLATED_LABEL = {"one_off": "promoted", "preference": "hardened", "request": "request_promoted"}


def scenarios(n: int = 48) -> list[Scenario]:
    base = list(read_jsonl(FIXTURES / "scenarios.jsonl", Scenario))
    return [replace(base[k % len(base)], id=f"pre-{k:03d}", seed=k, template=f"pre-t{k % 12}",
                    cue=("explicit", "implicit")[k % 2], length=("short", "medium", "long")[k % 3],
                    position=("early", "middle", "late")[(k // 6) % 3]) for k in range(n)]


def draw(item_type: str, condition: str, cue: str, rng: random.Random, inflate: dict, lose: dict,
         stale_p: float, boost: float = IMPLICIT_BOOST) -> str:
    p = inflate[condition] + (boost if item_type == "one_off" and cue == "implicit" else 0.0)
    if item_type in INFLATED_LABEL and rng.random() < p:
        return INFLATED_LABEL[item_type]
    if item_type in ("hard_rule", "changed_value", "preference") and rng.random() < lose[condition]:
        return "lost"
    if item_type == "changed_value" and rng.random() < stale_p:
        return "stale"
    return "correct"


def run(scen: list[Scenario], model: str, seed: int, repeats: int = 2, inflate: dict | None = None,
        lose: dict | None = None, behave: dict | None = None,
        stale: dict[tuple[str, str], float] | None = None, implicit_boost: float = IMPLICIT_BOOST,
        copy_free: bool = True):
    """Summaries, final labels (plus identical labels from main judges a and b) and probes of one
    run. With copy_free False, free_limited is drawn at its own rates instead of copying free."""
    inflate, lose, behave = inflate or INFLATE, lose or LOSE, behave or BEHAVE
    rng = random.Random(seed)
    summaries, labels, probes = [], [], []
    for s in scen:
        for rep in range(repeats):
            drawn: dict[str, list[Label]] = {}
            acted: dict[str, bool] = {}
            for cond in ["full"] + CONDITIONS:
                meta = dict(scenario_id=s.id, condition=cond, model=model, repeat=rep)
                if cond == "free_limited" and copy_free:  # exactly free's outcome
                    drawn[cond] = [replace(l, condition=cond) for l in drawn["free"]]
                    acted[cond] = acted["free"]
                elif cond != "full":
                    sp = (stale or {}).get((model, cond), 0.0)
                    drawn[cond] = [Label(judge=FINAL, item_id=i.id, label=draw(i.type, cond, s.cue, rng,
                                                                                inflate, lose, sp,
                                                                                implicit_boost), **meta)
                                   for i in s.items]
                if cond != "free_limited" or not copy_free:
                    acted[cond] = rng.random() < behave[cond]
                if cond != "full":
                    summaries.append(Summary(s.id, cond, model, rep, [Message("user", "summary")]))
                    labels += drawn[cond]
                    labels += [replace(l, judge=j) for j in ("a", "b") for l in drawn[cond]]
                probes.append(ProbeResult(inflated=acted[cond], probe_called=True, agent="agent", **meta))
    return summaries, labels, probes


def write_run(root: Path, run_id: str, scen_path: Path, summaries, labels, probes) -> Path:
    import json

    d = root / run_id
    write_jsonl(d / "summaries.jsonl", summaries)
    write_jsonl(d / "labels.jsonl", labels)
    write_jsonl(d / "probes.jsonl", probes)
    (d / "run.json").write_text(json.dumps({"scenarios": str(scen_path)}), encoding="utf-8")
    (d / "judge.json").write_text(json.dumps({"judges": [{"name": "a", "role": "first"},
                                                         {"name": "b", "role": "second"},
                                                         {"name": "c", "role": "tiebreak"}]}),
                                  encoding="utf-8")
    return d
