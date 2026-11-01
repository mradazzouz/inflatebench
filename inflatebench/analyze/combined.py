"""Combined analysis across runs: ib analyze --runs <run> <run> ... --out-id <id>.

Pools the runs' final labels and probes (each run compacted with its own model, which stays a
factor: a fixed effect in every regression, a panel in every figure, a row per model in every
table), writes the same tables and figures as the single-run analysis to runs/<id>/report/, and
adds the preregistered hypothesis tests (hypotheses.py) for the main analysis and the two
robustness analyses (flagged labels left out; only items the two main judges agreed on).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from inflatebench.analyze import hypotheses as hy
from inflatebench.analyze import metrics as m
from inflatebench.analyze.report import _records, analyze, load_run
from inflatebench.judge.judges import FINAL
from inflatebench.schema import Label, ProbeResult, Scenario

CONFIRMATORY = "confirmatory"
ROBUST_UNFLAGGED = "robustness: unflagged labels"
ROBUST_AGREE = "robustness: judges agree"


def load_runs(runs: Mapping[str, tuple[str | Path, str | Path]]) -> dict[str, Any]:
    """Each run's labels, scenarios, probes and judge roles, checked so they can be pooled:
    every run passes its own coverage check, runs share no model (the model is how a pooled row
    keeps its run), a shared scenario id means the same scenario, and either every run has
    probes or none has."""
    if len(runs) < 2:
        raise ValueError("a combined analysis needs at least two runs")
    loaded, models_of, scenarios = {}, {}, {}
    for run_id, (run_dir, scen_path) in runs.items():
        labels, scen, probes, roles = load_run(run_dir, scen_path)
        models = sorted({lab.model for lab in labels} | {p.model for p in probes or ()})
        for other, theirs in models_of.items():
            if shared := set(models) & set(theirs):
                raise ValueError(f"runs {other!r} and {run_id!r} share model {sorted(shared)[0]!r}; "
                                 "the model is the factor that tells pooled runs apart")
        models_of[run_id] = models
        for s in scen:
            if scenarios.setdefault(s.id, s) != s:
                raise ValueError(f"scenario {s.id!r} differs between runs")
        loaded[run_id] = {"labels": labels, "probes": probes, "roles": roles, "models": models,
                          "dir": str(run_dir), "scenarios": str(scen_path)}
    with_probes = [r for r, v in loaded.items() if v["probes"] is not None]
    if with_probes and len(with_probes) != len(loaded):
        missing = sorted(set(loaded) - set(with_probes))
        raise ValueError(f"runs {missing} have no probes.jsonl but {with_probes} do; probe every run "
                         "or none")
    return {"runs": loaded, "scenarios": list(scenarios.values())}


def judges_agree_by_run(runs: Mapping[str, dict[str, Any]], judge: str
                        ) -> tuple[dict[str, list[str]], list[Label], int, int] | None:
    """The judges-agree selection made within each run (with that run's own main judges), then
    pooled; None when a run lacks two main judges."""
    pairs, kept, items_out, invented_out = {}, [], 0, 0
    for run_id, run in runs.items():
        pair = m.main_judges(run["labels"], run["roles"])
        if pair is None:
            return None
        k, i, v = m.judges_agree(run["labels"], judge, *pair)
        pairs[run_id], items_out, invented_out = list(pair), items_out + i, invented_out + v
        kept += k
    return pairs, kept, items_out, invented_out


def _fits_from_summary(regression: dict[str, Any]) -> dict[str, pd.DataFrame | str]:
    """The items and behaviour models the report already fitted, so they are not fitted again."""
    out: dict[str, pd.DataFrame | str] = {}
    for name in ("items", "behaviour"):
        entry = regression.get(name)
        if entry is None:
            continue
        out[name] = entry["note"] if "note" in entry else pd.DataFrame(entry["terms"])
    return out


def analyze_runs(runs: Mapping[str, tuple[str | Path, str | Path]], out_dir: str | Path,
                 judge: str = FINAL, n_boot: int = 2000, seed: int = 0,
                 figures: bool = True) -> dict[str, Any]:
    """Write the combined report of `runs` ({run id: (run dir, scenarios path)}) to `out_dir`."""
    data = load_runs(runs)
    loaded, scenarios = data["runs"], data["scenarios"]
    labels = [lab for run in loaded.values() for lab in run["labels"]]
    probes: list[ProbeResult] | None = None
    if all(run["probes"] is not None for run in loaded.values()):
        probes = [p for run in loaded.values() for p in run["probes"]]
    agree = judges_agree_by_run(loaded, judge)

    out = Path(out_dir)
    summary = analyze(labels, scenarios, probes, out, judge=judge, n_boot=n_boot, seed=seed,
                      figures=figures, judges_agree=agree, behaviour_counts=True)
    summary["runs"] = {r: {"dir": v["dir"], "scenarios": v["scenarios"], "models": v["models"]}
                       for r, v in loaded.items()}

    items = m.item_frame(labels, scenarios, judge)
    probe_df = m.probe_frame(probes, scenarios) if probes is not None else None
    fits = _fits_from_summary(summary["regression"])
    analyses = [(CONFIRMATORY, items, fits)]
    analyses.append((ROBUST_UNFLAGGED, m.item_frame(m.unflagged(labels, judge), scenarios, judge),
                     {"behaviour": fits.get("behaviour")} if "behaviour" in fits else {}))
    if agree is not None:
        analyses.append((ROBUST_AGREE, m.item_frame(agree[1], scenarios, judge),
                         {"behaviour": fits.get("behaviour")} if "behaviour" in fits else {}))

    results = {}
    for name, its, given in analyses:
        res = hy.hypothesis_table(its, probe_df, n_boot, seed, given, analysis=name)
        results[name] = res
    # The two regressions only the hypotheses use, from the main analysis.
    for name in ("lost", "promoted"):
        res = results[CONFIRMATORY]["fits"][name]
        if isinstance(res, str):
            summary["regression"][name] = {"note": res}
        else:
            res.to_csv(out / f"regression_{name}.csv", index=False)
            summary["regression"][name] = {"formula": res.attrs.get("formula"), "n": res.attrs.get("n"),
                                           "terms": _records(res)}

    files = {CONFIRMATORY: "hypotheses", ROBUST_UNFLAGGED: "hypotheses_robustness_unflagged",
             ROBUST_AGREE: "hypotheses_robustness_judges_agree"}
    summary["hypotheses"] = {}
    for name, res in results.items():
        res["table"].to_csv(out / f"{files[name]}.csv", index=False)
        res["by_model"].to_csv(out / f"{files[name]}_by_model.csv", index=False)
        summary["hypotheses"][name] = {"verdicts": res["verdicts"], "h6_cells": res["h6_cells"],
                                       "h6_failing_cells": res["h6_failing_cells"],
                                       "tests": _records(res["table"]),
                                       "by_model": _records(res["by_model"])}
    if agree is None:
        summary["hypotheses"][ROBUST_AGREE] = {"note": "skipped: labels from two main judges are needed"}

    beh = pd.read_csv(out / "behaviour.csv") if (out / "behaviour.csv").exists() else None
    (out / "hypotheses.md").write_text(render(summary, results, beh, agree is not None), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def render(summary: dict[str, Any], results: dict[str, dict[str, Any]],
           beh: pd.DataFrame | None, agree: bool) -> str:
    runs = summary["runs"]
    lines = ["# Preregistered hypothesis tests (combined analysis)", "",
             "Runs: " + "; ".join(f"`{r}` (model {', '.join(v['models'])})" for r, v in runs.items())
             + f". Items: {summary['n_items']} over {summary['n_scenarios']} scenarios. "
             f"Bootstrap: {summary['n_boot']} replicates resampling one-off templates, seed {summary['seed']}.",
             "",
             "Tests as written in PREREGISTRATION.md (section 4): mixed-effects logistic regressions "
             "with fixed effects for condition, model, cue, length and position and random "
             "intercepts per template and per scenario. A test supports its hypothesis only if the "
             "estimate is in the predicted direction (> 0 as framed here) and the Holm-adjusted p is "
             "below 0.05; a hypothesis with several tests needs all of them.", ""]
    lines.append(hy.to_markdown(results[CONFIRMATORY], "Confirmatory analysis"))
    note = ("**Robustness analysis, not confirmatory.** {what} The same tests and rules as above; "
            "H5 rests on the probes, not on labels, so it is the same as in the confirmatory analysis.")
    lines.append(hy.to_markdown(results[ROBUST_UNFLAGGED], "Robustness: unflagged labels",
                                note.format(what="Final labels flagged after a re-ask (quote not "
                                            "found, or a label the item type does not allow) are "
                                            "left out.")))
    if agree:
        lines.append(hy.to_markdown(results[ROBUST_AGREE], "Robustness: judges agree",
                                    note.format(what="Only items on which the two main judges gave "
                                                "the same label (no tie-break), selected within each run.")))
    else:
        lines += ["## Robustness: judges agree", "", "Skipped: labels from two main judges are needed.", ""]
    if beh is not None and "probes" in beh.columns:
        rows = beh.sort_values(["model", "condition"])
        lines += ["## Probes: truncated and refused, per condition and model", "",
                  "Truncated probes are left out of the behavioural rates; refusals are kept and "
                  "count as not inflated.", "",
                  hy.markdown_table(["model", "condition", "probes", "truncated", "completed", "refused",
                                     "behavioural rate"],
                                    [[r.model, r.condition, int(r.probes), int(r.truncated), int(r.completed),
                                      int(r.refused), hy._num(r.rate)] for r in rows.itertuples()]), ""]
    return "\n".join(lines)
