"""Bootstrap intervals over scenarios and the mixed-effects logistic regression."""

from __future__ import annotations

import warnings
from typing import Sequence

import numpy as np
import pandas as pd

FACTORS = ("condition", "model", "cue", "length", "position")
# Reference level per factor when present, so coefficients read as "versus baseline".
REFERENCE = {"condition": "free", "cue": "explicit", "length": "short", "position": "early"}


def ratio_ci(counts: pd.DataFrame, by: Sequence[str], n_boot: int = 2000, seed: int = 0,
             level: float = 0.95) -> pd.DataFrame:
    """Rate sum(num)/sum(den) per group with a percentile bootstrap interval over scenarios.

    `counts` has one row per group and scenario with columns num and den. Every group is
    resampled with the same scenario draws, so intervals for different conditions are
    paired, as the conditions share scenarios.
    """
    by = list(by)
    cols = by + ["rate", "lo", "hi", "num", "den", "scenarios"]
    if counts.empty:
        return pd.DataFrame(columns=cols)
    ids = np.array(sorted(counts["scenario_id"].unique()))
    index = {s: k for k, s in enumerate(ids)}
    rng = np.random.default_rng(seed)
    # weights[b, s] = how often scenario s is drawn in bootstrap replicate b.
    weights = rng.multinomial(len(ids), np.full(len(ids), 1 / len(ids)), size=n_boot)
    alpha = (1 - level) / 2
    rows = []
    for key, g in counts.groupby(by, sort=True) if by else [((), counts)]:
        num = np.zeros(len(ids))
        den = np.zeros(len(ids))
        pos = g["scenario_id"].map(index).to_numpy()
        np.add.at(num, pos, g["num"].to_numpy(float))
        np.add.at(den, pos, g["den"].to_numpy(float))
        total = den.sum()
        rate = num.sum() / total if total else np.nan
        with np.errstate(invalid="ignore", divide="ignore"):
            boot = (weights @ num) / (weights @ den)
        boot = boot[np.isfinite(boot)]
        lo, hi = (np.quantile(boot, [alpha, 1 - alpha]) if len(boot) else (np.nan, np.nan))
        key = key if isinstance(key, tuple) else (key,)
        rows.append(dict(zip(by, key)) | {"rate": rate, "lo": lo, "hi": hi, "num": num.sum(),
                                           "den": total, "scenarios": int((den > 0).sum())})
    return pd.DataFrame(rows, columns=cols)


def _term(factor: str, levels: Sequence[str]) -> str:
    ref = REFERENCE.get(factor)
    if ref in levels:
        return f"C({factor}, Treatment(reference={ref!r}))"
    return f"C({factor})"


def mixed_logit(df: pd.DataFrame, outcome: str, factors: Sequence[str] = FACTORS,
                group: str = "scenario_id", seed: int = 0) -> pd.DataFrame:
    """Logistic regression with fixed effects for `factors` and a random intercept per scenario.

    Fitted with statsmodels' BinomialBayesMixedGLM (variational Bayes); factors with a single
    level in the data are dropped. Returns one row per fixed effect (log-odds coefficient,
    posterior sd, odds ratio and 95% interval) plus the random-effect sd.
    """
    from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM

    data = df.copy()
    data[outcome] = data[outcome].astype(float)
    used = [f for f in factors if data[f].nunique() > 1]
    rhs = " + ".join(_term(f, sorted(data[f].unique())) for f in used) or "1"
    model = BinomialBayesMixedGLM.from_formula(
        f"{outcome} ~ {rhs}", {group: f"0 + C({group})"}, data)
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
    out.attrs["formula"] = f"{outcome} ~ {rhs} + (1 | {group})"
    out.attrs["n"] = len(data)
    return out
