"""Bootstrap intervals over one-off templates and the mixed-effects logistic regression."""

from __future__ import annotations

import warnings
from typing import Sequence

import numpy as np
import pandas as pd

FACTORS = ("condition", "model", "cue", "length", "position")
# Reference level per factor when present, so coefficients read as "versus baseline".
REFERENCE = {"condition": "free", "cue": "explicit", "length": "short", "position": "early"}


def _unit(counts: pd.DataFrame) -> str:
    """The resampling unit: the one-off template when the counts carry it, else the scenario."""
    return "template" if "template" in counts.columns else "scenario_id"


def _replicates(counts: pd.DataFrame, n_boot: int, seed: int) -> tuple[dict, np.ndarray]:
    """Unit index and bootstrap weights: weights[b, u] = how often unit u is drawn in replicate b."""
    ids = np.array(sorted(counts[_unit(counts)].unique()))
    rng = np.random.default_rng(seed)
    weights = rng.multinomial(len(ids), np.full(len(ids), 1 / len(ids)), size=n_boot)
    return {u: k for k, u in enumerate(ids)}, weights


def _sums(g: pd.DataFrame, index: dict, unit: str) -> tuple[np.ndarray, np.ndarray]:
    num, den = np.zeros(len(index)), np.zeros(len(index))
    pos = g[unit].map(index).to_numpy()
    np.add.at(num, pos, g["num"].to_numpy(float))
    np.add.at(den, pos, g["den"].to_numpy(float))
    return num, den


def _boot(weights: np.ndarray, num: np.ndarray, den: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return (weights @ num) / (weights @ den)


def ratio_ci(counts: pd.DataFrame, by: Sequence[str], n_boot: int = 2000, seed: int = 0,
             level: float = 0.95) -> pd.DataFrame:
    """Rate sum(num)/sum(den) per group with a percentile bootstrap interval.

    `counts` has one row per group and scenario with columns num and den, and a template column
    when scenarios come from shared one-off templates. The bootstrap resamples templates (each
    with all of its scenarios), else scenarios. Every group is resampled with the same draws, so
    intervals for different conditions are paired, as the conditions share scenarios.
    """
    by = list(by)
    cols = by + ["rate", "lo", "hi", "num", "den", "scenarios", "clusters"]
    if counts.empty:
        return pd.DataFrame(columns=cols)
    unit = _unit(counts)
    index, weights = _replicates(counts, n_boot, seed)
    alpha = (1 - level) / 2
    rows = []
    for key, g in counts.groupby(by, sort=True) if by else [((), counts)]:
        num, den = _sums(g, index, unit)
        total = den.sum()
        rate = num.sum() / total if total else np.nan
        boot = _boot(weights, num, den)
        boot = boot[np.isfinite(boot)]
        lo, hi = (np.quantile(boot, [alpha, 1 - alpha]) if len(boot) else (np.nan, np.nan))
        key = key if isinstance(key, tuple) else (key,)
        rows.append(dict(zip(by, key)) | {"rate": rate, "lo": lo, "hi": hi, "num": num.sum(),
                                           "den": total,
                                           "scenarios": int(g.loc[g["den"] > 0, "scenario_id"].nunique()),
                                           "clusters": int((den > 0).sum())})
    return pd.DataFrame(rows, columns=cols)


def diff_ci(counts: pd.DataFrame, baseline: str, factor: str = "condition",
            by: Sequence[str] = ("model",), n_boot: int = 2000, seed: int = 0,
            level: float = 0.95) -> pd.DataFrame:
    """Rate of each `factor` level minus the `baseline` level's rate, within each `by` group,
    with a paired percentile bootstrap interval (both rates use the same template draws).

    Returns one row per non-baseline level: diff, diff_lo, diff_hi.
    """
    by = list(by)
    cols = [factor] + by + ["diff", "diff_lo", "diff_hi"]
    if counts.empty or baseline not in set(counts[factor]):
        return pd.DataFrame(columns=cols)
    unit = _unit(counts)
    index, weights = _replicates(counts, n_boot, seed)
    alpha = (1 - level) / 2
    rows = []
    for key, g in counts.groupby(by, sort=True) if by else [((), counts)]:
        key = key if isinstance(key, tuple) else (key,)
        base = g[g[factor] == baseline]
        if base.empty:
            continue
        bnum, bden = _sums(base, index, unit)
        bboot = _boot(weights, bnum, bden)
        for level_, h in g[g[factor] != baseline].groupby(factor, sort=True):
            num, den = _sums(h, index, unit)
            point = (num.sum() / den.sum() if den.sum() else np.nan) - (
                bnum.sum() / bden.sum() if bden.sum() else np.nan)
            d = _boot(weights, num, den) - bboot
            d = d[np.isfinite(d)]
            lo, hi = (np.quantile(d, [alpha, 1 - alpha]) if len(d) else (np.nan, np.nan))
            rows.append({factor: level_} | dict(zip(by, key)) | {"diff": point, "diff_lo": lo, "diff_hi": hi})
    return pd.DataFrame(rows, columns=cols)


def _term(factor: str, levels: Sequence[str]) -> str:
    # The full-history baseline, when present, is the natural reference for behaviour.
    ref = "full" if factor == "condition" and "full" in levels else REFERENCE.get(factor)
    if ref in levels:
        return f"C({factor}, Treatment(reference={ref!r}))"
    return f"C({factor})"


GROUPS = ("scenario_id", "template")


def mixed_logit(df: pd.DataFrame, outcome: str, factors: Sequence[str] = FACTORS,
                groups: Sequence[str] = GROUPS, seed: int = 0) -> pd.DataFrame:
    """Logistic regression with fixed effects for `factors` and random intercepts per one-off
    template and per scenario (scenarios nest in templates).

    Fitted with statsmodels' BinomialBayesMixedGLM (variational Bayes); factors with a single
    level in the data are dropped, and so is a grouping with no repeats (one scenario per
    template, as in the pilot). Returns one row per fixed effect (log-odds coefficient,
    posterior sd, odds ratio and 95% interval) plus each random effect's sd.
    """
    from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM

    data = df.copy()
    data[outcome] = data[outcome].astype(float)
    used = [f for f in factors if data[f].nunique() > 1]
    rhs = " + ".join(_term(f, sorted(data[f].unique())) for f in used) or "1"
    present = [g for g in groups if g in data.columns]
    vcs = []
    for g in present:
        # A grouping identical to one already used adds nothing (pilot: template == scenario).
        if not any(data.groupby(g)[h].nunique().max() == 1 and data.groupby(h)[g].nunique().max() == 1
                   for h in vcs):
            vcs.append(g)
    model = BinomialBayesMixedGLM.from_formula(
        f"{outcome} ~ {rhs}", {g: f"0 + C({g})" for g in vcs}, data)
    np.random.seed(seed)  # fit_vb starts from a fixed point, but keep runs reproducible
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = model.fit_vb()
    rows = []
    for name, mean, sd in zip(result.model.exog_names, result.fe_mean, result.fe_sd):
        lo, hi = mean - 1.96 * sd, mean + 1.96 * sd
        rows.append({"term": name, "effect": "fixed", "coef": mean, "sd": sd,
                     "odds_ratio": np.exp(mean), "or_lo": np.exp(lo), "or_hi": np.exp(hi)})
    for name, mean, sd in zip(result.model.vcp_names, result.vcp_mean, result.vcp_sd):
        # vcp_mean is the posterior mean of log(sd) of the random intercept.
        rows.append({"term": name, "effect": "random_log_sd", "coef": mean, "sd": sd,
                     "odds_ratio": np.nan, "or_lo": np.nan, "or_hi": np.nan})
    out = pd.DataFrame(rows)
    out.attrs["formula"] = f"{outcome} ~ {rhs} + " + " + ".join(f"(1 | {g})" for g in vcs)
    out.attrs["n"] = len(data)
    return out
