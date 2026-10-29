"""Stage 5: tables and figures -> runs/<run_id>/report/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from inflatebench.analyze import metrics as m
from inflatebench.analyze import plots
from inflatebench.analyze.stats import mixed_logit, ratio_ci
from inflatebench.judge.judges import FINAL
from inflatebench.schema import Label, ProbeResult, Scenario, read_jsonl


def inflation_rates(items: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> pd.DataFrame:
    """Rate per type (inflation types, control errors and loss) per condition and model."""
    tables = []
    for kind in m.ALL_TYPES:
        t = ratio_ci(m.type_counts(items, kind), m.GROUP, n_boot, seed)
        tables.append(t.assign(type=kind))
    out = pd.concat(tables, ignore_index=True)
    return out[["type"] + [c for c in out.columns if c != "type"]]


def precision_recall(items: pd.DataFrame, invented: pd.DataFrame, n_boot: int = 2000,
                     seed: int = 0) -> pd.DataFrame:
    p = ratio_ci(m.precision_counts(items, invented), m.GROUP, n_boot, seed)
    r = ratio_ci(m.recall_counts(items), m.GROUP, n_boot, seed)
    p = p.rename(columns={"rate": "precision", "lo": "precision_lo", "hi": "precision_hi",
                          "num": "rules_genuine", "den": "rules_listed"})
    r = r.rename(columns={"rate": "recall", "lo": "recall_lo", "hi": "recall_hi",
                          "num": "active_kept", "den": "active"})
    out = p.drop(columns="scenarios").merge(r.drop(columns="scenarios"), on=m.GROUP, how="outer")
    out["loss_rate"] = 1 - out["recall"]
    return out


def behaviour_rates(probes: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> pd.DataFrame:
    return ratio_ci(m.behaviour_counts(probes), m.GROUP, n_boot, seed)


def regressions(items: pd.DataFrame, probes: pd.DataFrame | None) -> dict[str, pd.DataFrame | str]:
    """Item-level inflation and probe-level behaviour; a failed fit is reported, not raised."""
    jobs = {"items": items[m.inflation_eligible(items)].assign(inflated=m.any_inflation(items))}
    if probes is not None and len(probes):
        jobs["behaviour"] = probes
    out: dict[str, pd.DataFrame | str] = {}
    for name, df in jobs.items():
        if df.empty or df["inflated"].nunique() < 2:
            out[name] = "skipped: outcome has a single value"
            continue
        try:
            out[name] = mixed_logit(df, "inflated")
        except (ValueError, np.linalg.LinAlgError) as e:
            out[name] = f"failed: {e}"
    return out


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(df.to_json(orient="records"))


def analyze(labels: Iterable[Label], scenarios: Iterable[Scenario],
            probes: Iterable[ProbeResult] | None, out_dir: str | Path, judge: str = FINAL,
            n_boot: int = 2000, seed: int = 0, figures: bool = True) -> dict[str, Any]:
    """Write CSV tables, regression tables, figures and summary.json; return the summary."""
    out = Path(out_dir)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    scenarios, labels = list(scenarios), list(labels)
    items = m.item_frame(labels, scenarios, judge)
    if items.empty:
        raise ValueError(f"no labels from judge {judge!r}")
    invented = m.invented_frame(labels, judge)
    probe_df = m.probe_frame(probes, scenarios) if probes is not None else None

    rates = inflation_rates(items, n_boot, seed)
    pr = precision_recall(items, invented, n_boot, seed)
    rates.to_csv(out / "inflation_rates.csv", index=False)
    pr.to_csv(out / "precision_recall.csv", index=False)
    items.to_csv(out / "items.csv", index=False)
    summary: dict[str, Any] = {"judge": judge, "n_items": len(items),
                               "n_scenarios": int(items["scenario_id"].nunique()),
                               "n_boot": n_boot, "seed": seed,
                               "inflation_rates": _records(rates),
                               "precision_recall": _records(pr)}
    beh = None
    if probe_df is not None and len(probe_df):
        beh = behaviour_rates(probe_df, n_boot, seed)
        beh.to_csv(out / "behaviour.csv", index=False)
        summary["behaviour"] = _records(beh)

    summary["regression"] = {}
    for name, res in regressions(items, probe_df).items():
        if isinstance(res, str):
            summary["regression"][name] = {"note": res}
            continue
        res.to_csv(out / f"regression_{name}.csv", index=False)
        summary["regression"][name] = {"formula": res.attrs["formula"], "n": res.attrs["n"],
                                       "terms": _records(res)}

    if figures:
        fig = out / "figures"
        plots.rates_by_type(rates, m.INFLATING, fig / "inflation_by_type.png",
                            "Inflation rate by type")
        plots.rates_by_type(rates, tuple(m.CONTROL_TYPES), fig / "controls_and_loss.png",
                            "Control errors and loss")
        plots.precision_recall(pr, fig / "precision_recall.png")
        if beh is not None:
            plots.behaviour(beh, fig / "behaviour.png")
        summary["figures"] = sorted(p.name for p in fig.glob("*.png"))

    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def analyze_run(run_dir: str | Path, scenarios_path: str | Path, **kw: Any) -> dict[str, Any]:
    """Read labels.jsonl (and probes.jsonl if present) from a run and write its report/."""
    run_dir = Path(run_dir)
    probes_path = run_dir / "probes.jsonl"
    probes = list(read_jsonl(probes_path, ProbeResult)) if probes_path.exists() else None
    return analyze(read_jsonl(run_dir / "labels.jsonl", Label),
                   read_jsonl(scenarios_path, Scenario), probes, run_dir / "report", **kw)
