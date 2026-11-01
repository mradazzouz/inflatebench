"""Publication figures with matplotlib (Agg backend), each saved as PNG (300 dpi) and PDF.

Presentation only: every number drawn here is read from a table the report already wrote.

Conventions shared by every figure:
- conditions in a fixed order (CONDITION_ORDER) under short display names (DISPLAY), each with
  the same colour in every figure, whichever subset is plotted;
- one panel per model, side by side, with a shared y-axis;
- the legend in its own row below the panels, never on the data or the title;
- sized for a paper: 6.8 in wide (full width) or 3.3 in (one column), all text >= 8 pt at
  print size.
"""

from __future__ import annotations

import math
import textwrap
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

CONDITION_ORDER = ("free", "free_limited", "sectioned", "sectioned_noconstraints", "keep_rules",
                   "extractor", "pinning", "full")
DISPLAY = {"free": "free", "free_limited": "free (250 words)", "sectioned": "sectioned",
           "sectioned_noconstraints": "sectioned (no Constraints)", "keep_rules": "keep rules",
           "extractor": "extractor", "pinning": "pinning", "full": "full history"}
# One colour per condition, fixed (checked for colour-vision-deficiency separation in this order);
# full history, the baseline, is neutral grey.
COLORS = {"free": "#2a78d6", "free_limited": "#74acf2", "sectioned": "#c2481d",
          "sectioned_noconstraints": "#eda100", "keep_rules": "#1baf7a", "extractor": "#6250d6",
          "pinning": "#e87ba4", "full": "#8a8984"}
EXTRA = ("#3d3c39", "#b5b4ae")  # conditions outside the design, should any appear
TYPE_DISPLAY = {"request_promoted": "request promoted"}
# Model names as the paper writes them, keyed by API id; any other model keeps its id.
MODEL_DISPLAY = {"claude-haiku-5-5": "Claude Haiku 5.5", "glm-5.3-flash": "GLM-5.3-Flash"}
INK, INK_2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
FULL_WIDTH, COLUMN_WIDTH = 6.8, 3.3  # inches
# Points at the figure's own size. 8.5 so that text stays >= 8 pt when a 6.8 in figure is set at
# a 6.5 in text width (TMLR), and in a 3.3 in column.
FONT = 8.5
DPI = 300
MODEL_MARKERS = ("o", "s", "^", "v", "D", "P")
MODEL_SHADES = ("#2a78d6", "#c2481d", "#1baf7a", "#6250d6", "#eda100", "#e87ba4")

RC = {
    "font.family": "DejaVu Sans", "font.size": FONT, "axes.titlesize": FONT + 1,
    "axes.labelsize": FONT, "xtick.labelsize": FONT, "ytick.labelsize": FONT,
    "legend.fontsize": FONT, "figure.titlesize": FONT + 1, "axes.edgecolor": INK_2,
    "axes.linewidth": 0.6, "xtick.color": INK_2, "ytick.color": INK_2, "axes.labelcolor": INK,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.major.size": 2.5,
    "ytick.major.size": 2.5, "pdf.fonttype": 42, "ps.fonttype": 42, "savefig.dpi": DPI,
    "figure.facecolor": "white", "axes.facecolor": "white", "svg.hashsalt": "inflatebench",
}


def display(condition: str) -> str:
    return DISPLAY.get(condition, condition.replace("_", " "))


def model_display(model: str) -> str:
    return MODEL_DISPLAY.get(str(model), str(model))


def conditions_in(df: pd.DataFrame) -> list[str]:
    present = set(df["condition"])
    known = [c for c in CONDITION_ORDER if c in present]
    return known + sorted(present - set(known))


def condition_colors(conditions: Sequence[str]) -> dict[str, str]:
    extra = sorted(c for c in conditions if c not in COLORS)
    return {c: COLORS[c] if c in COLORS else EXTRA[extra.index(c) % len(EXTRA)] for c in conditions}


@contextmanager
def _paper_style() -> Iterator[None]:
    with plt.rc_context(RC):
        yield


def _style(ax: plt.Axes, grid: str = "y") -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis=grid, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _panels(nrows: int, ncols: int, width: float, height: float,
            sharey: bool | str = "row") -> tuple[plt.Figure, np.ndarray]:
    return plt.subplots(nrows, ncols, figsize=(width, height), sharey=sharey, squeeze=False,
                        layout="constrained")


def _corners(t: Any, renderer: Any) -> np.ndarray:
    """The four corners (display units) of a text's rotated box. Its upright bounding box is
    centred on the rotated box, whose sides are the text's unrotated width and height."""
    box = t.get_window_extent(renderer)
    angle = t.get_rotation()
    if angle % 90 == 0:
        return np.array([[box.x0, box.y0], [box.x1, box.y0], [box.x1, box.y1], [box.x0, box.y1]])
    rot = t.get_rotation()
    t.set_rotation(0)
    flat = t.get_window_extent(renderer)
    t.set_rotation(rot)
    a = np.deg2rad(angle)
    u, v = np.array([np.cos(a), np.sin(a)]), np.array([-np.sin(a), np.cos(a)])
    c = np.array([(box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2])
    hw, hh = flat.width / 2, flat.height / 2
    return np.array([c - hw * u - hh * v, c + hw * u - hh * v, c + hw * u + hh * v,
                     c - hw * u + hh * v])


def _intersect(p: np.ndarray, q: np.ndarray) -> bool:
    """Two convex quadrilaterals overlap (separating-axis test; touching does not count)."""
    for poly in (p, q):
        for i in range(4):
            edge = poly[(i + 1) % 4] - poly[i]
            axis = np.array([-edge[1], edge[0]])
            a, b = p @ axis, q @ axis
            if a.max() <= b.min() + 1e-6 or b.max() <= a.min() + 1e-6:
                return False
    return True


def _visible_ticks(axis: Any, lim: tuple[float, float]) -> list[Any]:
    lo, hi = min(lim), max(lim)
    eps = 1e-9 * max(1.0, hi - lo)
    return [t for t, loc in zip(axis.get_ticklabels(), axis.get_ticklocs())
            if lo - eps <= loc <= hi + eps]


def layout_problems(fig: plt.Figure) -> list[str]:
    """Text that collides: any two labels, titles or tick labels overlapping, a legend on an
    axes, or text running off the figure. Empty when the layout is clean."""
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    items: list[tuple[str, np.ndarray]] = []

    def add(name: str, t: Any) -> None:
        if t is not None and t.get_visible() and t.get_text().strip():
            items.append((f"{name} {t.get_text()!r}", _corners(t, r)))

    add("suptitle", fig._suptitle)
    for k, ax in enumerate(fig.axes):
        for title in (ax.title, ax._left_title, ax._right_title):
            add(f"axes {k} title", title)
        add(f"axes {k} xlabel", ax.xaxis.label)
        add(f"axes {k} ylabel", ax.yaxis.label)
        for t in _visible_ticks(ax.xaxis, ax.get_xlim()):
            add(f"axes {k} xtick", t)
        for t in _visible_ticks(ax.yaxis, ax.get_ylim()):
            add(f"axes {k} ytick", t)
        for t in ax.texts:
            add(f"axes {k} note", t)
    problems = []
    for k, leg in enumerate(fig.legends):
        lb = leg.get_window_extent(r)
        items.append((f"legend {k}", np.array([[lb.x0, lb.y0], [lb.x1, lb.y0], [lb.x1, lb.y1],
                                               [lb.x0, lb.y1]])))
        problems += [f"legend {k} overlaps axes {j}" for j, ax in enumerate(fig.axes)
                     if lb.overlaps(ax.get_window_extent(r))]
    for i, (a, pa) in enumerate(items):
        for b, pb in items[i + 1:]:
            if _intersect(pa, pb):
                problems.append(f"{a} overlaps {b}")
    page = fig.bbox
    for name, poly in items:
        if (poly[:, 0].min() < page.x0 - 1 or poly[:, 1].min() < page.y0 - 1
                or poly[:, 0].max() > page.x1 + 1 or poly[:, 1].max() > page.y1 + 1):
            problems.append(f"{name} runs off the figure")
    return problems


def save(fig: plt.Figure, path: str | Path) -> Path:
    """Write `path` as PNG (300 dpi) and the same figure as PDF next to it; return the PNG path."""
    png = Path(path).with_suffix(".png")
    fig.savefig(png, dpi=DPI, metadata={"Software": None})
    fig.savefig(png.with_suffix(".pdf"), metadata={"CreationDate": None, "Creator": None,
                                                   "Producer": None})
    plt.close(fig)
    return png


def _legend_below(fig: plt.Figure, handles: list[Any], ncol: int, note: str | None = None) -> None:
    """The legend in its own row under the panels (constrained layout keeps it off the axes);
    a note, if any, sits right above its entries as the legend's title."""
    if handles:
        leg = fig.legend(handles=handles, loc="outside lower center", ncol=ncol, frameon=False,
                         handlelength=1.2, handletextpad=0.4, columnspacing=1.0, title=note,
                         title_fontsize=FONT)
        leg.get_title().set_color(INK_2)


def _condition_handles(conds: Sequence[str], colors: dict[str, str]) -> list[Patch]:
    return [Patch(facecolor=colors[c], edgecolor="none", label=display(c)) for c in conds]


def _yerr(rate: pd.Series, lo: pd.Series, hi: pd.Series) -> np.ndarray:
    lower = (rate - lo).clip(lower=0).fillna(0)
    upper = (hi - rate).clip(lower=0).fillna(0)
    return np.vstack([lower.to_numpy(), upper.to_numpy()])


def _upper(*series: pd.Series) -> float:
    """Top of a 0-based rate axis: just above the largest value or upper bound, at most 1."""
    vals = pd.concat([pd.Series(s, dtype=float) for s in series]).dropna()
    top = float(vals.max()) if len(vals) else 0.0
    if top <= 0:
        return 0.05
    return min(1.0, top * 1.12)


def _percent_axis(ax: plt.Axes, top: float, axis: str = "y") -> None:
    """Rates are stored as shares; the axis shows percent."""
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: f"{100 * v:g}")
    target = ax.yaxis if axis == "y" else ax.xaxis
    target.set_major_formatter(fmt)
    target.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10]))
    (ax.set_ylim if axis == "y" else ax.set_xlim)(0, top)


def _condition_ticks(ax: plt.Axes, conds: Sequence[str]) -> None:
    ax.set_xticks(np.arange(len(conds)), [display(c) for c in conds], rotation=40, ha="right",
                  rotation_mode="anchor")
    ax.tick_params(axis="x", length=0)
    ax.set_xlim(-0.6, len(conds) - 0.4)


def _models(df: pd.DataFrame) -> list[str]:
    return sorted(df["model"].unique())


def _panel_title(ax: plt.Axes, model: str, many: bool) -> None:
    if many:
        ax.set_title(model_display(model), loc="center", color=INK, pad=4)


def _title(fig: plt.Figure, title: str | None) -> None:
    """The figure's title, top left; None leaves it out (the paper puts it in the caption)."""
    if title:
        fig.suptitle(title, x=0.01, ha="left", color=INK)


def rates_by_type(rates: pd.DataFrame, types: Sequence[str], path: str | Path,
                  title: str | None, small_note: bool = False) -> Path:
    """Grouped bars: one group per type, one bar per condition, one panel per model.

    small_note adds a line under the panels when some bar is too short to see (below about 3%
    of the axis height, say 1% on a 0-40% axis), so a missing bar is not read as a zero."""
    rates = rates[rates["type"].isin(types)]
    models, conds = _models(rates), conditions_in(rates)
    colors = condition_colors(conds)
    with _paper_style():
        fig, axes = _panels(1, max(len(models), 1), FULL_WIDTH, 3.0)
        width = 0.84 / max(len(conds), 1)
        x = np.arange(len(types))
        top = _upper(rates["rate"], rates["hi"])
        for ax, model in zip(axes[0], models):
            _style(ax)
            sub = rates[rates["model"] == model]
            for k, cond in enumerate(conds):
                row = sub[sub["condition"] == cond].set_index("type").reindex(types)
                ax.bar(x - 0.42 + width * (k + 0.5), row["rate"].fillna(0), width * 0.86,
                       yerr=_yerr(row["rate"], row["lo"], row["hi"]), color=colors[cond],
                       error_kw={"ecolor": INK_2, "elinewidth": 0.7, "capsize": 1.2,
                                 "capthick": 0.7})
            names = [TYPE_DISPLAY.get(t, t.replace("_", " ")) for t in types]
            # A type's slot narrower than about 0.8 in (three or more models) gets slanted labels.
            if FULL_WIDTH / max(len(models), 1) / max(len(types), 1) < 0.8:
                ax.set_xticks(x, names, rotation=35, ha="right", rotation_mode="anchor")
            else:
                ax.set_xticks(x, [textwrap.fill(n, 10) for n in names])
            ax.tick_params(axis="x", length=0)
            _percent_axis(ax, top)
            _panel_title(ax, model, len(models) > 1)
        axes[0][0].set_ylabel("% of eligible items")
        _title(fig, title)
        note = _small_bars_note(rates["rate"], top) if small_note else None
        _legend_below(fig, _condition_handles(conds, colors), ncol=min(len(conds), 4), note=note)
    return save(fig, path)


def _small_bars_note(rate: pd.Series, top: float) -> str | None:
    """'Bars below 1% are too short to see; ...' when a bar is under 3% of the axis height (the
    threshold rounded down to one significant digit), else None."""
    thr = 0.03 * top
    digits = -int(np.floor(np.log10(100 * thr)))
    shown = np.floor(100 * thr * 10 ** digits) / 10 ** digits
    if not (rate.dropna() < shown / 100).any():
        return None
    return (f"Bars below {shown:.{max(digits, 0)}f}% may not be visible; the table gives every "
            "rate.")


def precision(pr: pd.DataFrame, path: str | Path,
              title: str | None = "Constraint precision by condition") -> Path:
    """Constraint precision per condition (bars, 95% intervals), one panel per model; recall and
    loss, near-constant, are stated in a note under each panel instead of being plotted."""
    models, conds = _models(pr), conditions_in(pr)
    colors = condition_colors(conds)
    with _paper_style():
        width = FULL_WIDTH if len(models) > 1 else COLUMN_WIDTH
        fig, axes = _panels(1, max(len(models), 1), width, 3.1)
        for ax, model in zip(axes[0], models):
            _style(ax)
            sub = pr[pr["model"] == model].set_index("condition").reindex(conds)
            x = np.arange(len(conds))
            ax.bar(x, sub["precision"].fillna(0), 0.7,
                   yerr=_yerr(sub["precision"], sub["precision_lo"], sub["precision_hi"]),
                   color=[colors[c] for c in conds],
                   error_kw={"ecolor": INK_2, "elinewidth": 0.7, "capsize": 1.5, "capthick": 0.7})
            _condition_ticks(ax, conds)
            _percent_axis(ax, 1.0)
            _panel_title(ax, model, len(models) > 1)
            ax.set_xlabel(_recall_note(sub), color=INK_2, labelpad=4)
        axes[0][0].set_ylabel("constraint precision (%)")
        _title(fig, title)
    return save(fig, path)


def _recall_note(sub: pd.DataFrame) -> str:
    """'recall ≥ 99.9%, loss ≤ 0.1%' over the panel's conditions: the lowest recall rounded
    down and the highest loss rounded up to one decimal, so each bound holds exactly ('recall
    100%' and 'loss 0%' only when every condition is exactly there)."""
    recall, loss = sub["recall"].dropna(), sub["loss_rate"].dropna()
    if recall.empty:
        r = "recall --"
    elif recall.min() >= 1:
        r = "recall 100%"
    else:
        r = f"recall ≥ {_one_decimal(recall.min(), math.floor)}%"
    if loss.empty:
        l_ = "loss --"
    elif loss.max() <= 0:
        l_ = "loss 0%"
    else:
        l_ = f"loss ≤ {_one_decimal(loss.max(), math.ceil)}%"
    return f"{r}, {l_}"


def _one_decimal(share: float, direction: Any) -> str:
    """A share as a percent with one decimal, rounded with `direction` (math.floor or math.ceil)
    on the exact decimal value, so 0.999 gives 99.9 and not 99.8 from 99.89999..."""
    tenths = Decimal(repr(float(share))) * 1000
    return f"{Decimal(direction(tenths)) / 10:.1f}"


# Kept under the old name for callers of the previous scatter.
precision_recall = precision


def behaviour(rates: pd.DataFrame, path: str | Path,
              title: str | None = "Behavioural inflation") -> Path:
    """Top row: behavioural inflation per condition (the full-history baseline included), the
    y-axis scaled to the data. Bottom row, when the full-history probes are there:
    compaction-induced inflation (condition minus full history, paired 95% interval) for each
    compacted condition, with the zero line marked as the baseline on the y-axis, outside the
    data. One column per model."""
    from inflatebench.probe.run import FULL

    rates = rates[rates["rate"].notna()]
    models, conds = _models(rates), conditions_in(rates)
    colors = condition_colors(conds)
    induced = None
    if "induced" in rates.columns and rates["induced"].notna().any():
        induced = rates[rates["induced"].notna()]
    nrows = 2 if induced is not None else 1
    with _paper_style():
        width = FULL_WIDTH if len(models) > 1 else COLUMN_WIDTH
        fig, axes = _panels(nrows, max(len(models), 1), width, 3.0 * nrows)
        top = _upper(rates["rate"], rates["hi"])
        for col, model in enumerate(models):
            ax = axes[0][col]
            _style(ax)
            sub = rates[rates["model"] == model].set_index("condition").reindex(conds)
            x = np.arange(len(conds))
            ax.bar(x, sub["rate"].fillna(0), 0.7, yerr=_yerr(sub["rate"], sub["lo"], sub["hi"]),
                   color=[colors[c] for c in conds],
                   error_kw={"ecolor": INK_2, "elinewidth": 0.7, "capsize": 1.5, "capthick": 0.7})
            _condition_ticks(ax, conds)
            _percent_axis(ax, top)
            _panel_title(ax, model, len(models) > 1)
            if induced is not None:
                # Only the compacted conditions: full history minus itself is not a comparison,
                # so it gets no (empty) slot.
                _induced_panel(axes[1][col], induced[induced["model"] == model], induced,
                               [c for c in conds if c != FULL], colors)
        axes[0][0].set_ylabel("probes acting on\ninflation (%)")
        if induced is not None:
            axes[1][0].set_ylabel("compacted − full history\n(percentage points)")
        _title(fig, title)
    return save(fig, path)


def _induced_panel(ax: plt.Axes, sub: pd.DataFrame, every: pd.DataFrame, conds: Sequence[str],
                   colors: dict[str, str]) -> None:
    sub = sub.set_index("condition").reindex(conds)
    _style(ax)
    ax.axhline(0, color=INK_2, linewidth=0.8, zorder=1)
    for k, cond in enumerate(conds):
        r = sub.loc[cond]
        if pd.isna(r["induced"]):
            continue
        err = _yerr(pd.Series([r["induced"]]), pd.Series([r["induced_lo"]]),
                    pd.Series([r["induced_hi"]]))
        ax.errorbar(k, r["induced"], yerr=err, fmt="o", color=colors[cond], markersize=5,
                    elinewidth=1.2, capsize=2, capthick=1.0, markeredgecolor="white",
                    markeredgewidth=0.8, zorder=3)
    lo = np.nanmin(np.r_[every["induced_lo"].to_numpy(float), every["induced"].to_numpy(float), 0])
    hi = np.nanmax(np.r_[every["induced_hi"].to_numpy(float), every["induced"].to_numpy(float), 0])
    pad = 0.08 * max(hi - lo, 0.02)
    ax.set_ylim(lo - pad, hi + pad)
    # The zero line is the full-history baseline; its tick label says so, on the axis rather
    # than in the plot, so the label can never cover a point or an interval.
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f"{100 * v:+g}" if abs(v) > 1e-12 else "baseline 0"))
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10]))
    _condition_ticks(ax, conds)


# --- Combined report: forest plot of the preregistered rate differences ----------------------

FOREST_ROWS = (  # (test, label, outcome)
    ("H1", "sectioned − free", "inflation"),
    ("H2a", "sectioned − sectioned (no Constraints)", "inflation"),
    ("H2b", "free (250 words) − free", "inflation"),
    ("H3a-extractor", "sectioned − extractor", "loss"),
    ("H3a-pinning", "sectioned − pinning", "loss"),
    ("H3b-extractor", "extractor − sectioned", "inflation"),
    ("H3b-pinning", "pinning − sectioned", "inflation"),
    ("H4", "implicit − explicit cue", "one-offs promoted"),
    ("H5-sectioned", "sectioned − full history", "behaviour"),
    ("H5-extractor", "extractor − full history", "behaviour"),
    ("H5-pinning", "pinning − full history", "behaviour"),
)


def hypotheses_forest(table: pd.DataFrame, by_model: pd.DataFrame, path: str | Path,
                      margin: float = 0.03,
                      title: str | None = "Preregistered rate differences (H1–H5)") -> Path:
    """Rate differences of H1-H5 and H2b with 95% paired bootstrap intervals: pooled over
    models (black diamond) and per model (coloured markers), a zero line, and the H2b
    equivalence band (+/- `margin`) shaded on the H2b row."""
    pooled = table.set_index("test")
    rows = [r for r in FOREST_ROWS if r[0] in pooled.index]
    models = sorted(by_model["model"].dropna().unique()) if len(by_model) else []
    n_series = 1 + len(models)
    step = 0.8 / n_series
    with _paper_style():
        fig, ax = plt.subplots(figsize=(FULL_WIDTH, 0.42 * len(rows) + 1.1), layout="constrained")
        _style(ax, grid="x")
        y = np.arange(len(rows))[::-1].astype(float)
        if any(t == "H2b" for t, _, _ in rows):
            yb = y[[t for t, _, _ in rows].index("H2b")]
            ax.fill_between([-margin, margin], yb - 0.45, yb + 0.45, color="#eda100", alpha=0.22,
                            linewidth=0, zorder=0)
        ax.axvline(0, color=INK_2, linewidth=0.8, zorder=1)
        for k, (test, _, _) in enumerate(rows):
            r = pooled.loc[test]
            offsets = [y[k] + 0.4 - step * (j + 0.5) for j in range(n_series)]
            _forest_point(ax, offsets[0], r["rate_diff"], r["rate_diff_lo"], r["rate_diff_hi"],
                          INK, "D", 4.5)
            mine = by_model[by_model["test"] == test].set_index("model") if len(by_model) else None
            for j, model in enumerate(models):
                if mine is None or model not in mine.index:
                    continue
                q = mine.loc[model]
                _forest_point(ax, offsets[j + 1], q["rate_diff"], q["rate_diff_lo"],
                              q["rate_diff_hi"], MODEL_SHADES[j % len(MODEL_SHADES)],
                              MODEL_MARKERS[j % len(MODEL_MARKERS)], 4)
        ax.set_yticks(y, [f"{t}: {lab} ({out})" for t, lab, out in rows])
        ax.tick_params(axis="y", length=0)
        ax.set_ylim(-0.6, len(rows) - 0.4)
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
            lambda v, _: f"{100 * v:+g}" if abs(v) > 1e-12 else "0"))
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=7, steps=[1, 2, 2.5, 5, 10]))
        vals = pd.concat([table["rate_diff_lo"], table["rate_diff_hi"],
                          by_model["rate_diff_lo"] if len(by_model) else pd.Series(dtype=float),
                          by_model["rate_diff_hi"] if len(by_model) else pd.Series(dtype=float),
                          pd.Series([-margin, margin])]).astype(float).dropna()
        lo, hi = float(vals.min()), float(vals.max())
        pad = 0.05 * (hi - lo)
        ax.set_xlim(lo - pad, hi + pad)
        ax.set_xlabel("rate difference (percentage points, 95% interval)")
        handles = [Line2D([], [], color=INK, marker="D", linestyle="none", markersize=4.5,
                          label="pooled")]
        handles += [Line2D([], [], color=MODEL_SHADES[j % len(MODEL_SHADES)],
                           marker=MODEL_MARKERS[j % len(MODEL_MARKERS)], linestyle="none",
                           markersize=4, label=model_display(m)) for j, m in enumerate(models)]
        handles.append(Patch(facecolor="#eda100", alpha=0.22, edgecolor="none",
                             label=f"H2b equivalence band (±{100 * margin:g} points)"))
        _title(fig, title)
        _legend_below(fig, handles, ncol=min(len(handles), 4))
    return save(fig, path)


def _forest_point(ax: plt.Axes, y: float, est: Any, lo: Any, hi: Any, color: str, marker: str,
                  size: float) -> None:
    if pd.isna(est):
        return
    xerr = None
    if not (pd.isna(lo) or pd.isna(hi)):
        xerr = [[max(est - lo, 0)], [max(hi - est, 0)]]
    ax.errorbar(est, y, xerr=xerr, fmt=marker, color=color, markersize=size, elinewidth=1.0,
                capsize=0, markeredgecolor="white", markeredgewidth=0.6, zorder=3)
