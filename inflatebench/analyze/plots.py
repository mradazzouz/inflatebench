"""Figures with matplotlib (Agg backend, PNG)."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

CONDITION_ORDER = ("free", "sectioned", "keep_rules", "extractor", "pinning")
# Categorical slots in fixed order; a condition keeps its colour whichever subset is plotted.
PALETTE = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def conditions_in(df: pd.DataFrame) -> list[str]:
    present = set(df["condition"])
    known = [c for c in CONDITION_ORDER if c in present]
    return known + sorted(present - set(known))


def condition_colors(conditions: Sequence[str]) -> dict[str, str]:
    extra = sorted(c for c in conditions if c not in CONDITION_ORDER)
    order = list(CONDITION_ORDER) + extra
    return {c: PALETTE[order.index(c) % len(PALETTE)] for c in conditions}


def _style(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _figure(ncols: int, width: float = 4.8, height: float = 3.6):
    fig, axes = plt.subplots(1, ncols, figsize=(width * ncols, height), sharey=True,
                             squeeze=False, facecolor=SURFACE)
    return fig, axes[0]


def _yerr(df: pd.DataFrame) -> np.ndarray:
    lo = (df["rate"] - df["lo"]).clip(lower=0).fillna(0)
    hi = (df["hi"] - df["rate"]).clip(lower=0).fillna(0)
    return np.vstack([lo.to_numpy(), hi.to_numpy()])


def rates_by_type(rates: pd.DataFrame, types: Sequence[str], path: str | Path,
                  title: str) -> Path:
    """Grouped bars: one group per type, one bar per condition, one panel per model."""
    rates = rates[rates["type"].isin(types)]
    models = sorted(rates["model"].unique())
    conds = conditions_in(rates)
    colors = condition_colors(conds)
    fig, axes = _figure(max(len(models), 1), width=max(4.8, 1.3 * len(types) + 1.5))
    width = 0.8 / max(len(conds), 1)
    x = np.arange(len(types))
    for ax, model in zip(axes, models):
        _style(ax)
        sub = rates[rates["model"] == model]
        for k, cond in enumerate(conds):
            row = sub[sub["condition"] == cond].set_index("type").reindex(types)
            ax.bar(x - 0.4 + width * (k + 0.5), row["rate"].fillna(0), width * 0.88,
                   yerr=_yerr(row), color=colors[cond], label=cond,
                   error_kw={"ecolor": INK_2, "elinewidth": 1, "capsize": 2})
        ax.set_xticks(x, [t.replace("_", " ") for t in types])
        ax.set_title(model, fontsize=10, color=INK)
        ax.set_ylim(0, 1)
    axes[0].set_ylabel("share of eligible items", color=INK_2, fontsize=9)
    _finish(fig, axes[0], title, path)
    return Path(path)


def precision_recall(pr: pd.DataFrame, path: str | Path) -> Path:
    """Recall (x) against precision (y) per condition with 95% intervals, one panel per model."""
    models = sorted(pr["model"].unique())
    conds = conditions_in(pr)
    colors = condition_colors(conds)
    fig, axes = _figure(max(len(models), 1), width=4.4, height=4.0)
    for ax, model in zip(axes, models):
        _style(ax)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        sub = pr[pr["model"] == model].set_index("condition")
        for cond in conds:
            if cond not in sub.index:
                continue
            r = sub.loc[cond]
            ax.errorbar(r["recall"], r["precision"],
                        xerr=[[max(r["recall"] - r["recall_lo"], 0)], [max(r["recall_hi"] - r["recall"], 0)]],
                        yerr=[[max(r["precision"] - r["precision_lo"], 0)],
                              [max(r["precision_hi"] - r["precision"], 0)]],
                        fmt="o", markersize=8, color=colors[cond], ecolor=colors[cond],
                        elinewidth=1.2, markeredgecolor=SURFACE, markeredgewidth=2, label=cond)
        ax.set_xlim(0, 1.02)
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("constraint recall", color=INK_2, fontsize=9)
        ax.set_title(model, fontsize=10, color=INK)
    axes[0].set_ylabel("constraint precision", color=INK_2, fontsize=9)
    _finish(fig, axes[0], "Lost rules versus inflated rules", path)
    return Path(path)


def behaviour(rates: pd.DataFrame, path: str | Path) -> Path:
    """Behavioural inflation rate per condition, one panel per model."""
    models = sorted(rates["model"].unique())
    conds = conditions_in(rates)
    colors = condition_colors(conds)
    fig, axes = _figure(max(len(models), 1), width=max(3.6, 0.8 * len(conds) + 1.2))
    for ax, model in zip(axes, models):
        _style(ax)
        sub = rates[rates["model"] == model].set_index("condition").reindex(conds)
        x = np.arange(len(conds))
        ax.bar(x, sub["rate"].fillna(0), 0.6, yerr=_yerr(sub), color=[colors[c] for c in conds],
               error_kw={"ecolor": INK_2, "elinewidth": 1, "capsize": 2})
        ax.set_xticks(x, conds, rotation=20)
        ax.set_ylim(0, 1)
        ax.set_title(model, fontsize=10, color=INK)
    axes[0].set_ylabel("share of probes acting on inflation", color=INK_2, fontsize=9)
    fig.suptitle("Behavioural inflation", color=INK, fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return Path(path)


def _finish(fig: plt.Figure, ax: plt.Axes, title: str, path: str | Path) -> None:
    handles, labels = ax.get_legend_handles_labels()
    if len(handles) > 1:
        fig.legend(handles, labels, loc="upper right", ncol=len(handles), frameon=False,
                   fontsize=9, labelcolor=INK_2)
    fig.suptitle(title, color=INK, fontsize=11, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
