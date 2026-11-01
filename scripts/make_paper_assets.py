"""Turn runs/<run_id>/report/ into LaTeX tables, macros and figures under paper/generated/.

    python scripts/make_paper_assets.py RUN_ID [--config config.yaml] [--out paper/generated]

RUN_ID is a single run or a combined analysis (ib analyze --runs ... --out-id combined); for a
combined one the preregistered hypothesis tables are written too (hypotheses, hypotheses_by_model,
verdicts) and the forest plot is copied with the other figures, each as PDF and PNG.

Every table is a bare tabular (no float, no caption), so the paper sets captions and placement.
Rates are percentages with their 95% bootstrap interval. The label tables are written from
inflatebench/judge/rubric.py, so the appendix uses exactly the judge's definitions.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd
import yaml

from inflatebench.analyze.metrics import CONTROL_TYPES, INFLATING
from inflatebench.analyze.plots import FOREST_ROWS, conditions_in, display
from inflatebench.judge.rubric import ALLOWED_LABELS, EXPECTED, LABEL_DEFINITIONS, PRECEDENCE

ROOT = Path(__file__).resolve().parent.parent
TABLES = ("inflation_rates", "inflation_rates_unflagged", "controls", "precision_recall",
          "behaviour", "regression_items", "regression_behaviour", "hypotheses",
          "hypotheses_by_model", "verdicts")


def tex(s: Any) -> str:
    """Escape text for LaTeX."""
    out = str(s).replace("\\", r"\textbackslash{}")
    for ch in "&%$#_{}":
        out = out.replace(ch, "\\" + ch)
    return out.replace("~", r"\textasciitilde{}").replace("^", r"\textasciicircum{}")


def _missing(x: Any) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def pct(rate: Any, lo: Any = None, hi: Any = None, signed: bool = False) -> str:
    """12.3 [8.1, 16.0] (percent); -- when the rate is undefined."""
    if _missing(rate):
        return "--"
    fmt = "{:+.1f}" if signed else "{:.1f}"
    out = fmt.format(100 * rate)
    if not (_missing(lo) or _missing(hi)):
        out += " {\\scriptsize[" + fmt.format(100 * lo) + ", " + fmt.format(100 * hi) + "]}"
    return out.replace("-", "$-$") if signed else out


def num(x: Any, digits: int = 2) -> str:
    return "--" if _missing(x) else f"{x:.{digits}f}".replace("-", "$-$")


def tabular(header: Sequence[str], rows: Sequence[Sequence[str]], align: str) -> str:
    lines = [f"\\begin{{tabular}}{{{align}}}", r"\toprule", " & ".join(header) + r" \\", r"\midrule"]
    lines += [" & ".join(r) + r" \\" for r in rows]
    lines += [r"\bottomrule", r"\end{tabular}", ""]
    return "\n".join(lines)


def _ordered(df: pd.DataFrame) -> list[tuple[str, str]]:
    """(model, condition) pairs: models sorted, conditions in the paper's fixed order."""
    order = conditions_in(df)
    keys = df[["model", "condition"]].drop_duplicates().itertuples(index=False)
    return sorted(((m, c) for m, c in keys), key=lambda k: (k[0], order.index(k[1])))


def _row_head(model: str, condition: str, many_models: bool) -> list[str]:
    return ([tex(model)] if many_models else []) + [tex(display(condition))]


def rates_table(rates: pd.DataFrame, types: Sequence[str]) -> str:
    """Conditions as rows, one column per type: rate [lo, hi] in percent."""
    rates = rates[rates["type"].isin(types)]
    many = rates["model"].nunique() > 1
    cell = {(r.model, r.condition, r.type): pct(r.rate, r.lo, r.hi) for r in rates.itertuples()}
    rows = [_row_head(m, c, many) + [cell.get((m, c, t), "--") for t in types]
            for m, c in _ordered(rates)]
    header = (["Model"] if many else []) + ["Condition"] + [tex(t) for t in types]
    return tabular(header, rows, "l" * (1 + many) + "r" * len(types))


def precision_recall_table(pr: pd.DataFrame) -> str:
    many = pr["model"].nunique() > 1
    by = {(r.model, r.condition): r for r in pr.itertuples()}
    rows = []
    for m, c in _ordered(pr):
        r = by[(m, c)]
        rows.append(_row_head(m, c, many) + [
            pct(r.precision, r.precision_lo, r.precision_hi),
            pct(r.recall, r.recall_lo, r.recall_hi), pct(r.loss_rate)])
    header = (["Model"] if many else []) + ["Condition", "Precision", "Recall", "Loss"]
    return tabular(header, rows, "l" * (1 + many) + "rrr")


def behaviour_table(beh: pd.DataFrame) -> str:
    many = beh["model"].nunique() > 1
    by = {(r.model, r.condition): r for r in beh.itertuples()}
    rows = []
    for m, c in _ordered(beh):
        r = by[(m, c)]
        induced = getattr(r, "induced", float("nan"))
        rows.append(_row_head(m, c, many) + [
            pct(r.rate, r.lo, r.hi), pct(r.called_rate), pct(r.refusal_rate),
            pct(induced, getattr(r, "induced_lo", None), getattr(r, "induced_hi", None), signed=True)])
    header = (["Model"] if many else []) + ["Condition", "Behavioural", "Called", "Refused", "Induced"]
    return tabular(header, rows, "l" * (1 + many) + "rrrr")


def term_name(term: str) -> str:
    """C(condition, Treatment('free'))[T.sectioned] -> condition: sectioned."""
    m = re.fullmatch(r"C\((\w+)(?:,.*)?\)\[T\.(.+)\]", term)
    return f"{m.group(1)}: {m.group(2)}" if m else term


def regression_table(reg: pd.DataFrame) -> str:
    rows = []
    for r in reg.itertuples():
        if r.effect == "fixed":
            ci = "--" if _missing(r.or_lo) else f"[{num(r.or_lo)}, {num(r.or_hi)}]"
            rows.append([tex(term_name(r.term)), num(r.coef), num(r.sd), num(r.odds_ratio), ci])
        else:
            rows.append([tex(f"{r.term} (random, log sd)"), num(r.coef), num(r.sd), "--", "--"])
    return tabular(["Term", "Coef.", "SD", "OR", "95\\% interval"], rows, "lrrrr")


FOREST = {t: (label, outcome) for t, label, outcome in FOREST_ROWS}


def _comparison(test: str) -> str:
    label, outcome = FOREST.get(test, (test, ""))
    text = tex(label).replace("\u2212", "$-$")
    return f"{text} ({tex(outcome)})" if outcome else text


def p_value(p: Any) -> str:
    if _missing(p):
        return "--"
    if p < 0.001:
        mant, exp = f"{p:.1e}".split("e")
        return f"${mant}\\times 10^{{{int(exp)}}}$"
    return f"{p:.3f}"


def hypotheses_table(hyp: pd.DataFrame) -> str:
    """H1-H5 and H2b (confirmatory): rate difference in percentage points with its 95% paired
    bootstrap interval, odds ratio with its 95% interval, Holm p and the test's verdict."""
    rows = []
    order = [t for t, _, _ in FOREST_ROWS]
    tests = hyp[hyp["test"].isin(order)].assign(_k=lambda d: d["test"].map(order.index)).sort_values("_k")
    for r in tests.itertuples():
        ci = "--" if _missing(r.or_lo) else f"{num(r.odds_ratio)} {{\\scriptsize[{num(r.or_lo)}, {num(r.or_hi)}]}}"
        rows.append([tex(r.test), _comparison(r.test),
                     pct(r.rate_diff, r.rate_diff_lo, r.rate_diff_hi, signed=True),
                     ci if r.test != "H2b" else "--", p_value(r.p_holm) if r.test != "H2b" else "--",
                     tex(r.test_verdict)])
    return tabular(["Test", "Comparison", "Difference (pp)", "Odds ratio", "Holm $p$", "Verdict"],
                   rows, "llrrrl")


def hypotheses_by_model_table(bm: pd.DataFrame) -> str:
    """Rate difference per test (rows) and model (columns), in percentage points."""
    order = [t for t, _, _ in FOREST_ROWS]
    models = sorted(bm["model"].dropna().unique())
    cell = {(r.test, r.model): pct(r.rate_diff, r.rate_diff_lo, r.rate_diff_hi, signed=True)
            for r in bm.itertuples()}
    rows = [[tex(t), _comparison(t)] + [cell.get((t, m), "--") for m in models]
            for t in order if t in set(bm["test"])]
    return tabular(["Test", "Comparison"] + [tex(m) for m in models], rows, "ll" + "r" * len(models))


def verdicts_table(summary: dict[str, Any]) -> str | None:
    """Verdict per hypothesis: confirmatory, then each robustness analysis that ran."""
    hyp = summary.get("hypotheses") or {}
    names = [(k, label) for k, label in (("confirmatory", "Confirmatory"),
                                         ("robustness: unflagged labels", "Unflagged labels"),
                                         ("robustness: judges agree", "Judges agree"))
             if "verdicts" in hyp.get(k, {})]
    if not names:
        return None
    hypotheses = list(hyp[names[0][0]]["verdicts"])
    rows = [[tex(h)] + [tex(hyp[k]["verdicts"].get(h, "--")) for k, _ in names] for h in hypotheses]
    return tabular(["Hypothesis"] + [label for _, label in names], rows, "l" + "l" * len(names))


def label_tables() -> dict[str, str]:
    """Label definitions, allowed labels per type and the precedence order, from the rubric."""
    defs = tabular(["Label", "Definition"],
                   [[f"\\texttt{{{tex(k)}}}", tex(v)] for k, v in LABEL_DEFINITIONS.items()],
                   "lp{0.72\\linewidth}")
    allowed = tabular(["Item type", "Correct outcome", "Allowed labels"],
                      [[f"\\texttt{{{tex(t)}}}", tex(EXPECTED[t]), tex(", ".join(ls))]
                       for t, ls in ALLOWED_LABELS.items()],
                      "lp{0.38\\linewidth}p{0.3\\linewidth}")
    order = " $>$ ".join(f"\\texttt{{{tex(lab)}}}" for lab in PRECEDENCE) + "\n"
    return {"labels": defs, "allowed_labels": allowed, "precedence": order}


def macros(summary: dict[str, Any], run_id: str, run_info: dict[str, Any]) -> str:
    vals: dict[str, Any] = {
        "RunId": run_id, "Judge": summary.get("judge", ""),
        "NScenarios": summary.get("n_scenarios", ""), "NItems": summary.get("n_items", ""),
        "NBoot": summary.get("n_boot", ""), "Repeats": run_info.get("repeats", ""),
        "ExcludedFlagged": summary.get("robustness_unflagged", {}).get("excluded_labels", ""),
    }
    final = summary.get("judge", "final")
    for key, name in (("quote_flags", "QuoteFlagRate"), ("type_flags", "TypeFlagRate")):
        rate = summary.get(key, {}).get(final, {}).get("rate")
        vals[name] = "--" if rate is None else f"{100 * rate:.1f}\\%"
    lines = ["% Generated by scripts/make_paper_assets.py; do not edit."]
    lines += [f"\\newcommand{{\\ib{k}}}{{{v if k in ('QuoteFlagRate', 'TypeFlagRate') else tex(v)}}}"
              for k, v in vals.items()]
    return "\n".join(lines) + "\n"


def make_assets(report: Path, out: Path, run_id: str, run_info: dict[str, Any] | None = None) -> list[Path]:
    """Write tables, macros and figures for one report directory; return the files written."""
    if not (report / "summary.json").exists():
        raise FileNotFoundError(f"{report / 'summary.json'} not found; run ib analyze first")
    # Start clean, so nothing from an earlier run stays behind.
    for sub in ("tables", "figures"):
        shutil.rmtree(out / sub, ignore_errors=True)
        (out / sub).mkdir(parents=True)
    summary = json.loads((report / "summary.json").read_text(encoding="utf-8"))
    written: list[Path] = []

    def write(name: str, text: str) -> None:
        path = out / name
        path.write_text(text, encoding="utf-8")
        written.append(path)

    jobs: list[tuple[str, str, Callable[[pd.DataFrame], str]]] = [
        ("inflation_rates", "inflation_rates.csv", lambda d: rates_table(d, INFLATING)),
        ("inflation_rates_unflagged", "inflation_rates_unflagged.csv", lambda d: rates_table(d, INFLATING)),
        ("controls", "inflation_rates.csv", lambda d: rates_table(d, tuple(CONTROL_TYPES))),
        ("precision_recall", "precision_recall.csv", precision_recall_table),
        ("behaviour", "behaviour.csv", behaviour_table),
        ("regression_items", "regression_items.csv", regression_table),
        ("regression_behaviour", "regression_behaviour.csv", regression_table),
        ("hypotheses", "hypotheses.csv", hypotheses_table),
        ("hypotheses_by_model", "hypotheses_by_model.csv", hypotheses_by_model_table),
    ]
    for name, csv, fn in jobs:
        if (report / csv).exists():
            write(f"tables/{name}.tex", fn(pd.read_csv(report / csv)))
    if (verdicts := verdicts_table(summary)) is not None:
        write("tables/verdicts.tex", verdicts)
    for name, text in label_tables().items():
        write(f"tables/{name}.tex", text)
    write("macros.tex", macros(summary, run_id, run_info or {}))
    for fig in sorted((*(report / "figures").glob("*.pdf"), *(report / "figures").glob("*.png"))):
        written.append(Path(shutil.copy2(fig, out / "figures" / fig.name)))
    return written


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("run_id")
    p.add_argument("--config", default=str(ROOT / "config.yaml"), help="path to config.yaml")
    p.add_argument("--run-dir", default=None, help="run directory (default: paths.runs/<run_id>)")
    p.add_argument("--out", default=str(ROOT / "paper" / "generated"), help="output directory")
    args = p.parse_args(argv)
    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
        run_dir = Path(cfg.get("paths", {}).get("runs", "runs")) / args.run_id
    run_json = run_dir / "run.json"
    run_info = json.loads(run_json.read_text(encoding="utf-8")) if run_json.exists() else {}
    try:
        written = make_assets(run_dir / "report", Path(args.out), args.run_id, run_info)
    except FileNotFoundError as e:
        print(f"make_paper_assets: {e}", file=sys.stderr)
        return 1
    print(f"wrote {len(written)} files to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
