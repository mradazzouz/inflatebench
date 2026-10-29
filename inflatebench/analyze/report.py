"""Stage 5: tables and figures -> runs/<run_id>/report/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from inflatebench.analyze import metrics as m
from inflatebench.analyze import plots
from inflatebench.analyze.stats import diff_ci, mixed_logit, ratio_ci
from inflatebench.judge.judges import FINAL
from inflatebench.judge.run import quote_flag_rates, type_flag_rates
from inflatebench.schema import Label, ProbeResult, Scenario, Summary, read_jsonl


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
    """Behavioural inflation over all probes (rate, lo, hi), how often the probe tool was called
    (called_rate), how often the agent refused the task instead (refusal_rate; refusals count as
    not inflated in `rate`) and behavioural inflation among probes that called it
    (rate_when_called).

    With the full-history baseline in the probes (condition "full"), each compacted condition
    also gets `induced` (its rate minus the full-history rate for the same model, with a paired
    bootstrap interval): the behavioural inflation that compaction causes. The same difference
    is given for rate_when_called (`induced_when_called`).
    """
    from inflatebench.probe.run import FULL

    out = ratio_ci(m.behaviour_counts(probes), m.GROUP, n_boot, seed)
    for counts, prefix in ((m.called_counts, "called_rate"), (m.refusal_counts, "refusal_rate"),
                           (m.behaviour_when_called_counts, "rate_when_called")):
        t = ratio_ci(counts(probes), m.GROUP, n_boot, seed)
        t = t.rename(columns={"rate": prefix, "lo": f"{prefix}_lo", "hi": f"{prefix}_hi",
                              "num": f"{prefix}_num", "den": f"{prefix}_den"})
        out = out.merge(t.drop(columns=["scenarios", "clusters"]), on=m.GROUP, how="left")
    for counts, prefix in ((m.behaviour_counts, "induced"), (m.behaviour_when_called_counts,
                                                             "induced_when_called")):
        d = diff_ci(counts(probes), FULL, n_boot=n_boot, seed=seed)
        d = d.rename(columns={"diff": prefix, "diff_lo": f"{prefix}_lo", "diff_hi": f"{prefix}_hi"})
        out = out.merge(d, on=m.GROUP, how="left")
    return out


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
                               "quote_flags": quote_flag_rates(labels),
                               "type_flags": type_flag_rates(labels),
                               "n_scenarios": int(items["scenario_id"].nunique()),
                               "n_boot": n_boot, "seed": seed,
                               "inflation_rates": _records(rates),
                               "precision_recall": _records(pr)}
    # Robustness check: the same tables without flagged labels (a quote that stayed unverified,
    # or a label the item's type does not allow).
    kept = [lab for lab in labels if not (lab.judge == judge and (lab.quote_flagged or lab.type_flagged))]
    items_kept = m.item_frame(kept, scenarios, judge)
    rates_kept = inflation_rates(items_kept, n_boot, seed)
    pr_kept = precision_recall(items_kept, m.invented_frame(kept, judge), n_boot, seed)
    rates_kept.to_csv(out / "inflation_rates_unflagged.csv", index=False)
    pr_kept.to_csv(out / "precision_recall_unflagged.csv", index=False)
    summary["robustness_unflagged"] = {"excluded_labels": len(labels) - len(kept),
                                       "n_items": len(items_kept),
                                       "inflation_rates": _records(rates_kept),
                                       "precision_recall": _records(pr_kept)}
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


def check_coverage(summaries: Iterable[Summary], scenarios: Iterable[Scenario],
                   labels: Iterable[Label], probes: Iterable[ProbeResult] | None,
                   judge: str = FINAL) -> None:
    """Raise ValueError unless the judge labelled every planted item of every summary exactly
    once, and there is exactly one probe per summary, with nothing left over from another run.

    Labels or probes from an earlier ib compact of the same run id, a judge or probe run that
    stopped part way, or a summary written twice would otherwise be counted without a word.
    """
    items = {s.id: [i.id for i in s.items] for s in scenarios}
    keys = [(s.scenario_id, s.condition, s.model, s.repeat) for s in summaries]
    if len(set(keys)) != len(keys):
        raise ValueError("summaries.jsonl has the same summary more than once")
    want = {k + (i,) for k in keys for i in items[k[0]]}
    got = [(l.scenario_id, l.condition, l.model, l.repeat, l.item_id)
           for l in labels if l.judge == judge and l.item_id is not None]

    def problems(found: list[tuple], expected: set[tuple], what: str) -> list[str]:
        out = []
        if len(set(found)) != len(found):
            out.append(f"{len(found) - len(set(found))} duplicate {what}")
        if missing := expected - set(found):
            out.append(f"{len(missing)} {what} missing, e.g. {sorted(missing)[0]}")
        if extra := set(found) - expected:
            out.append(f"{len(extra)} {what} for no current summary, e.g. {sorted(extra)[0]}")
        return out

    errors = problems(got, want, f"{judge!r} labels")
    if probes is not None:
        from inflatebench.probe.run import FULL

        found = [(p.scenario_id, p.condition, p.model, p.repeat) for p in probes]
        expected = set(keys)
        if any(k[1] == FULL for k in found):  # the full-history baseline, unless --no-full
            expected |= {(sid, FULL, model, repeat) for sid, _, model, repeat in keys}
        errors += problems(found, expected, "probes")
    if errors:
        raise ValueError("labels or probes do not match summaries.jsonl (rerun ib judge or "
                         "ib probe): " + "; ".join(errors))


def analyze_run(run_dir: str | Path, scenarios_path: str | Path, **kw: Any) -> dict[str, Any]:
    """Read labels.jsonl (and probes.jsonl if present) from a run and write its report/.

    When the run has summaries.jsonl, final labels and probes must cover it exactly
    (check_coverage).
    """
    run_dir = Path(run_dir)
    probes_path = run_dir / "probes.jsonl"
    probes = list(read_jsonl(probes_path, ProbeResult)) if probes_path.exists() else None
    labels = list(read_jsonl(run_dir / "labels.jsonl", Label))
    scenarios = list(read_jsonl(scenarios_path, Scenario))
    if (run_dir / "summaries.jsonl").exists():
        # The panel's final labels cover every item; a single judge's (--judge) may not.
        check_coverage(read_jsonl(run_dir / "summaries.jsonl", Summary), scenarios, labels, probes)
    return analyze(labels, scenarios, probes, run_dir / "report", **kw)
