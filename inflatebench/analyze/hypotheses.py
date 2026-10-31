"""The confirmatory tests of PREREGISTRATION.md, sections 1 and 4, as written.

H1-H5 (Holm family of 10): each test is one coefficient, or a contrast between two
coefficients, of a mixed-effects logistic regression (stats.mixed_logit: fixed effects for
condition, model, cue, length and position; random intercepts per one-off template and per
scenario). z = posterior mean / posterior sd for a coefficient and (b1 - b2) / sqrt(sd1^2 + sd2^2)
for a contrast (the variational posterior is mean-field); the p-value is two-sided normal. Each
test predicts a positive estimate, and passes only if the estimate is positive and the
Holm-adjusted p is below 0.05. A hypothesis with several tests is supported only if all of them
pass; H3 is assessed separately for extractor and for pinning.

H2b (not in the Holm family): the 95% paired bootstrap interval for the combined inflation rate
of free_limited minus free lies entirely within +/-0.03.

H6 (not in the Holm family): in every model x condition cell, the upper limit of the 95%
bootstrap interval of the softened rate (hard rules) and of the stale rate (changed values) is
below 0.05; reported cell by cell with the number of failing cells.

Effect sizes: every test also gets the rate difference with its paired bootstrap interval
(templates resampled, shared draws), pooled over models and per model, and the odds ratio with
its 95% interval from the regression.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erfc, sqrt
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from inflatebench.analyze import metrics as m
from inflatebench.analyze.stats import REFERENCE, diff_ci, mixed_logit, ratio_ci

ALPHA = 0.05
EQUIVALENCE_MARGIN = 0.03
CONTROL_LIMIT = 0.05
CONTROLS = ("softened", "stale")

SUPPORTED, NOT_SUPPORTED, NOT_TESTED = "supported", "not supported", "not tested"


@dataclass(frozen=True)
class Test:
    """One test of the Holm family: estimate = coef(level) - coef(minus), predicted > 0.

    `minus` None means the factor's reference level (coefficient 0). The rate difference is
    rate(level) - rate(minus or reference) on the same outcome.
    """

    test: str
    hypothesis: str
    comparison: str
    fit: str  # "items" | "lost" | "promoted" | "behaviour"
    factor: str
    level: str
    minus: str | None = None


# The ten tests of H1-H5 (PREREGISTRATION.md, section 4, table "Each test uses its own fitted model").
TESTS: tuple[Test, ...] = (
    Test("H1", "H1", "sectioned - free, combined inflation (sectioned coefficient)", "items",
         "condition", "sectioned"),
    Test("H2a", "H2", "sectioned - sectioned_noconstraints, combined inflation", "items",
         "condition", "sectioned", "sectioned_noconstraints"),
    Test("H3a-extractor", "H3 (extractor)", "sectioned - extractor, loss (positive = extractor loses less)",
         "lost", "condition", "sectioned", "extractor"),
    Test("H3a-pinning", "H3 (pinning)", "sectioned - pinning, loss (positive = pinning loses less)",
         "lost", "condition", "sectioned", "pinning"),
    Test("H3b-extractor", "H3 (extractor)", "extractor - sectioned, combined inflation", "items",
         "condition", "extractor", "sectioned"),
    Test("H3b-pinning", "H3 (pinning)", "pinning - sectioned, combined inflation", "items",
         "condition", "pinning", "sectioned"),
    Test("H4", "H4", "implicit - explicit cue, one-offs promoted (cue implicit coefficient)",
         "promoted", "cue", "implicit"),
    Test("H5-sectioned", "H5", "sectioned - full, behavioural inflation (sectioned coefficient)",
         "behaviour", "condition", "sectioned"),
    Test("H5-extractor", "H5", "extractor - full, behavioural inflation (extractor coefficient)",
         "behaviour", "condition", "extractor"),
    Test("H5-pinning", "H5", "pinning - full, behavioural inflation (pinning coefficient)",
         "behaviour", "condition", "pinning"),
)
HYPOTHESES = ("H1", "H2", "H3 (extractor)", "H3 (pinning)", "H4", "H5", "H6")

COLUMNS = ["analysis", "hypothesis", "test", "comparison", "predicted", "model", "condition",
           "estimate", "se", "z", "p", "p_holm", "odds_ratio", "or_lo", "or_hi",
           "rate", "rate_lo", "rate_hi", "rate_base", "rate_diff", "rate_diff_lo", "rate_diff_hi",
           "criterion", "test_verdict", "hypothesis_verdict", "note"]
POOLED = "pooled"


def normal_p(z: float) -> float:
    """Two-sided p-value of a standard normal z."""
    return float(erfc(abs(z) / sqrt(2)))


def holm(p: Sequence[float]) -> np.ndarray:
    """Holm step-down adjusted p-values (NaN entries are left out of the family and stay NaN)."""
    p = np.asarray(p, dtype=float)
    out = np.full(len(p), np.nan)
    idx = [i for i in np.argsort(p, kind="stable") if np.isfinite(p[i])]
    k, running = len(idx), 0.0
    for rank, i in enumerate(idx):
        running = max(running, min(1.0, (k - rank) * p[i]))
        out[i] = running
    return out


# --- Regressions ----------------------------------------------------------------------------

def regression_data(name: str, items: pd.DataFrame,
                    probes: pd.DataFrame | None) -> tuple[pd.DataFrame | None, str]:
    """The rows and outcome of each preregistered model."""
    if name == "items":  # inflation-eligible items, combined inflation (report.regressions)
        return items[m.inflation_eligible(items)].assign(inflated=m.any_inflation(items)), "inflated"
    if name == "lost":  # active items, lost
        active = items[items["item_type"].isin(m.ACTIVE)]
        return active.assign(lost=active["label"] == "lost"), "lost"
    if name == "promoted":  # one-off items, promoted
        oneoff = items[m.eligible(items, "promoted")]
        return oneoff.assign(promoted=oneoff["label"] == "promoted"), "promoted"
    if name == "behaviour":  # all completed probes, the full-history baseline included
        return (m.completed(probes) if probes is not None and len(probes) else None), "inflated"
    raise ValueError(f"unknown regression {name!r}")


def fit(name: str, items: pd.DataFrame, probes: pd.DataFrame | None,
        seed: int = 0) -> pd.DataFrame | str:
    """A fitted model, or a note saying why there is none (as report.regressions)."""
    df, outcome = regression_data(name, items, probes)
    if df is None or df.empty:
        return "skipped: no data"
    if df[outcome].nunique() < 2:
        return "skipped: outcome has a single value"
    try:
        return mixed_logit(df, outcome, seed=seed)
    except (ValueError, np.linalg.LinAlgError) as e:
        return f"failed: {e}"


def coefficient(res: pd.DataFrame, factor: str, level: str) -> tuple[float, float] | None:
    """(posterior mean, posterior sd) of a level's fixed effect; (0, 0) for the reference level;
    None when the level is not in the model."""
    fixed = res[res["effect"] == "fixed"]
    for term, coef, sd in zip(fixed["term"], fixed["coef"], fixed["sd"]):
        if term.startswith(f"C({factor}") and term.endswith(f"[T.{level}]"):
            return float(coef), float(sd)
    ref = [t for t in fixed["term"] if t.startswith(f"C({factor}, Treatment(reference=")]
    if ref and f"reference={level!r}" in ref[0]:
        return 0.0, 0.0
    return None


def _reference(test: Test) -> str:
    if test.factor == "condition" and test.fit == "behaviour":
        from inflatebench.probe.run import FULL

        return FULL
    return REFERENCE[test.factor]


def contrast(res: pd.DataFrame | str, test: Test) -> dict[str, Any]:
    """Estimate, se, z, p, odds ratio and its interval for one test, or a note."""
    if isinstance(res, str):
        return {"note": f"regression {test.fit}: {res}"}
    # A coefficient is "versus the reference": without the full-history probes, the behaviour
    # model's reference falls back to free, and its coefficients are not the H5 contrasts.
    want = _reference(test)
    refs = {t.split("reference=")[1].split(")")[0].strip("'\"") for t in res["term"]
            if t.startswith(f"C({test.factor}, Treatment(reference=")}
    if refs and want not in refs:
        return {"note": f"regression {test.fit}: reference {test.factor} is {sorted(refs)[0]!r}, "
                        f"not {want!r}"}
    a = coefficient(res, test.factor, test.level)
    b = coefficient(res, test.factor, test.minus) if test.minus else (0.0, 0.0)
    if a is None or b is None:
        missing = test.level if a is None else test.minus
        return {"note": f"regression {test.fit}: no {test.factor} {missing!r} in the model"}
    est, se = a[0] - b[0], sqrt(a[1] ** 2 + b[1] ** 2)
    z = est / se if se > 0 else np.nan
    return {"estimate": est, "se": se, "z": z, "p": normal_p(z) if np.isfinite(z) else np.nan,
            "odds_ratio": np.exp(est), "or_lo": np.exp(est - 1.96 * se),
            "or_hi": np.exp(est + 1.96 * se)}


# --- Rates and bootstrap differences --------------------------------------------------------

def outcome_counts(fit_name: str, items: pd.DataFrame, probes: pd.DataFrame | None,
                   by: list[str]) -> pd.DataFrame:
    """Per-scenario num/den for the outcome a regression models, grouped by `by`."""
    if fit_name == "items":
        return m.per_scenario(items, m.any_inflation(items), m.inflation_eligible(items), by)
    if fit_name == "lost":
        return m.type_counts(items, "lost", by)
    if fit_name == "promoted":
        return m.type_counts(items, "promoted", by)
    if probes is None or not len(probes):
        return pd.DataFrame(columns=by + ["template", "scenario_id", "num", "den"])
    return m.behaviour_counts(m.completed(probes), by)


def rate_difference(counts: pd.DataFrame, factor: str, level: str, base: str,
                    per_model: bool, n_boot: int, seed: int) -> pd.DataFrame:
    """rate(level) - rate(base) with the paired bootstrap interval (and both rates), pooled over
    models or per model. Columns: [model], rate, rate_base, rate_diff, rate_diff_lo, rate_diff_hi."""
    by = ["model"] if per_model else []
    two = counts[counts[factor].isin([level, base])]
    cols = by + ["rate", "rate_base", "rate_diff", "rate_diff_lo", "rate_diff_hi"]
    if two.empty or base not in set(two[factor]) or level not in set(two[factor]):
        return pd.DataFrame(columns=cols)
    rates = ratio_ci(two, [factor] + by, n_boot, seed).set_index([factor] + by)["rate"]
    d = diff_ci(two, base, factor=factor, by=by, n_boot=n_boot, seed=seed)
    d = d[d[factor] == level]
    rows = []
    for _, r in d.iterrows():
        key = tuple(r[b] for b in by)
        at = lambda lev: rates.get((lev, *key) if by else lev)
        rows.append(dict(zip(by, key)) | {"rate": at(level), "rate_base": at(base),
                                          "rate_diff": r["diff"], "rate_diff_lo": r["diff_lo"],
                                          "rate_diff_hi": r["diff_hi"]})
    return pd.DataFrame(rows, columns=cols)


# --- The table ------------------------------------------------------------------------------

def _combine(verdicts: Sequence[str]) -> str:
    if not verdicts:
        return NOT_TESTED
    if any(v == NOT_SUPPORTED for v in verdicts):
        return NOT_SUPPORTED
    if any(v == NOT_TESTED for v in verdicts):
        return NOT_TESTED
    return SUPPORTED


def hypothesis_table(items: pd.DataFrame, probes: pd.DataFrame | None, n_boot: int = 2000,
                     seed: int = 0, fits: Mapping[str, pd.DataFrame | str] | None = None,
                     analysis: str = "confirmatory") -> dict[str, Any]:
    """The preregistered tests of H1-H6 on these items and probes.

    `fits` may carry already fitted models (keys items, lost, promoted, behaviour); the others
    are fitted here. Returns {"table": one row per test (and per H6 cell), "by_model": rate
    differences per model, "fits": every model used, "verdicts": {hypothesis: verdict}}.
    """
    fits = dict(fits or {})
    for name in ("items", "lost", "promoted", "behaviour"):
        if name not in fits:
            fits[name] = fit(name, items, probes, seed)

    rows, by_model = [], []
    for t in TESTS:
        base = t.minus or _reference(t)
        counts = outcome_counts(t.fit, items, probes, [t.factor])
        pooled = rate_difference(counts, t.factor, t.level, base, False, n_boot, seed)
        row = {"analysis": analysis, "hypothesis": t.hypothesis, "test": t.test,
               "comparison": t.comparison, "predicted": "> 0", "model": POOLED,
               "criterion": f"estimate > 0 and Holm p < {ALPHA}"} | contrast(fits[t.fit], t)
        if len(pooled):
            row |= pooled.iloc[0].to_dict()
        rows.append(row)
        per = rate_difference(outcome_counts(t.fit, items, probes, [t.factor, "model"]),
                              t.factor, t.level, base, True, n_boot, seed)
        by_model += [{"analysis": analysis, "test": t.test, "comparison": t.comparison} | r
                     for r in per.to_dict("records")]

    table = pd.DataFrame(rows, columns=COLUMNS)
    table["p_holm"] = holm(table["p"].to_numpy(float))
    ok = (table["estimate"] > 0) & (table["p_holm"] < ALPHA)
    table["test_verdict"] = np.where(table["p_holm"].notna(), np.where(ok, SUPPORTED, NOT_SUPPORTED),
                                     NOT_TESTED)

    # H2b: equivalence of free_limited and free (pooled; per model descriptively).
    counts = outcome_counts("items", items, probes, ["condition"])
    eq = rate_difference(counts, "condition", "free_limited", "free", False, n_boot, seed)
    h2b = {"analysis": analysis, "hypothesis": "H2", "test": "H2b",
           "comparison": "free_limited - free, combined inflation (paired bootstrap)",
           "predicted": f"within +/-{EQUIVALENCE_MARGIN}", "model": POOLED,
           "criterion": f"95% interval within [-{EQUIVALENCE_MARGIN}, {EQUIVALENCE_MARGIN}]"}
    if len(eq) and np.isfinite(eq.iloc[0]["rate_diff_lo"]):
        r = eq.iloc[0]
        h2b |= r.to_dict()
        inside = r["rate_diff_lo"] > -EQUIVALENCE_MARGIN and r["rate_diff_hi"] < EQUIVALENCE_MARGIN
        h2b["test_verdict"] = SUPPORTED if inside else NOT_SUPPORTED
    else:
        h2b |= {"test_verdict": NOT_TESTED, "note": "free_limited or free missing"}
    per = rate_difference(outcome_counts("items", items, probes, ["condition", "model"]),
                          "condition", "free_limited", "free", True, n_boot, seed)
    by_model += [{"analysis": analysis, "test": "H2b", "comparison": h2b["comparison"]} | r
                 for r in per.to_dict("records")]

    # H6: controls per model x condition cell.
    h6 = []
    for kind in CONTROLS:
        ci = ratio_ci(m.type_counts(items, kind), m.GROUP, n_boot, seed)
        for _, r in ci.sort_values(["model", "condition"]).iterrows():
            row = {"analysis": analysis, "hypothesis": "H6", "test": f"H6-{kind}",
                   "comparison": f"{kind} rate ({'hard rules' if kind == 'softened' else 'changed values'})",
                   "predicted": f"< {CONTROL_LIMIT}", "model": r["model"], "condition": r["condition"],
                   "rate": r["rate"], "rate_lo": r["lo"], "rate_hi": r["hi"],
                   "criterion": f"upper 95% bound < {CONTROL_LIMIT}"}
            if r["den"] > 0 and np.isfinite(r["hi"]):
                row["test_verdict"] = SUPPORTED if r["hi"] < CONTROL_LIMIT else NOT_SUPPORTED
            else:
                row |= {"test_verdict": NOT_TESTED, "note": "no eligible items"}
            h6.append(row)

    table = pd.concat([table, pd.DataFrame([h2b], columns=COLUMNS), pd.DataFrame(h6, columns=COLUMNS)],
                      ignore_index=True)
    verdicts = {h: _combine(list(table.loc[table["hypothesis"] == h, "test_verdict"])) for h in HYPOTHESES}
    table["hypothesis_verdict"] = table["hypothesis"].map(verdicts)
    h6_cells = table[table["hypothesis"] == "H6"]
    return {"table": table, "verdicts": verdicts, "fits": fits,
            "by_model": pd.DataFrame(by_model, columns=["analysis", "test", "comparison", "model", "rate",
                                                        "rate_base", "rate_diff", "rate_diff_lo",
                                                        "rate_diff_hi"]),
            "h6_failing_cells": int((h6_cells["test_verdict"] == NOT_SUPPORTED).sum()),
            "h6_cells": int(len(h6_cells))}


# --- Markdown -------------------------------------------------------------------------------

def _num(x: Any, digits: int = 3) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return ""
    if isinstance(x, (float, np.floating)):
        return f"{x:.{digits}f}"
    return str(x)


def _p(x: Any) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return ""
    return f"{x:.2e}" if x < 0.001 else f"{x:.4f}"


def _ci(est: Any, lo: Any, hi: Any) -> str:
    if est is None or (isinstance(est, float) and not np.isfinite(est)):
        return ""
    return f"{_num(est)} [{_num(lo)}, {_num(hi)}]"


def markdown_table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    esc = lambda v: str(v).replace("|", "\\|")
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(esc(v) for v in r) + " |" for r in rows]
    return "\n".join(lines)


def to_markdown(result: dict[str, Any], title: str, intro: str = "") -> str:
    """One section of hypotheses.md for one analysis (confirmatory or a robustness check)."""
    t = result["table"]
    out = [f"## {title}", ""]
    if intro:
        out += [intro, ""]
    out += ["### Verdicts by hypothesis", "",
            markdown_table(["hypothesis", "verdict"], [[h, v] for h, v in result["verdicts"].items()]), ""]
    holm_rows = t[t["test"].isin([x.test for x in TESTS])]
    out += ["### H1-H5 (Holm family of 10 tests)", "",
            "Estimate: log-odds coefficient or contrast from the mixed-effects regression; z = "
            "estimate / se; p two-sided; Holm across the 10 tests. Rate difference: pooled over "
            "models, paired template bootstrap, 95% interval.", "",
            markdown_table(["test", "comparison", "estimate", "se", "z", "p", "Holm p",
                            "odds ratio [95%]", "rate diff [95%]", "verdict", "note"],
                           [[r.test, r.comparison, _num(r.estimate), _num(r.se), _num(r.z, 2), _p(r.p),
                             _p(r.p_holm), _ci(r.odds_ratio, r.or_lo, r.or_hi),
                             _ci(r.rate_diff, r.rate_diff_lo, r.rate_diff_hi), r.test_verdict,
                             "" if pd.isna(r.note) else r.note]
                            for r in holm_rows.itertuples()]), ""]
    eq = t[t["test"] == "H2b"]
    out += ["### H2b (equivalence, not in the Holm family)", "",
            markdown_table(["comparison", "free_limited", "free", "difference [95%]", "criterion", "verdict"],
                           [[r.comparison, _num(r.rate), _num(r.rate_base),
                             _ci(r.rate_diff, r.rate_diff_lo, r.rate_diff_hi), r.criterion, r.test_verdict]
                            for r in eq.itertuples()]), ""]
    h6 = t[t["hypothesis"] == "H6"]
    out += ["### H6 (controls per model x condition, not in the Holm family)", "",
            f"{result['h6_failing_cells']} of {result['h6_cells']} cells fail.", "",
            markdown_table(["control", "model", "condition", "rate [95%]", "verdict"],
                           [[r.test.removeprefix("H6-"), r.model, r.condition,
                             _ci(r.rate, r.rate_lo, r.rate_hi), r.test_verdict] for r in h6.itertuples()]), ""]
    bm = result["by_model"]
    if len(bm):
        out += ["### Rate differences per model", "",
                markdown_table(["test", "model", "rate", "baseline rate", "difference [95%]"],
                               [[r.test, r.model, _num(r.rate), _num(r.rate_base),
                                 _ci(r.rate_diff, r.rate_diff_lo, r.rate_diff_hi)] for r in bm.itertuples()]),
                ""]
    return "\n".join(out)
