"""Agreement statistics: Cohen's kappa between judges, and between humans and the judge."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Any, Iterable, Sequence

from inflatebench.judge.judges import FINAL
from inflatebench.schema import INVENTED, LABELS, Label

# Spec: proceed with the main run only if judge-human kappa is at least this.
KAPPA_GATE = 0.7

Key = tuple[str, str, str, int, str]


def item_key(label: Label) -> Key:
    return (label.scenario_id, label.condition, label.model, label.repeat, label.item_id or "")


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Cohen's kappa for two raters over the same items; 1.0 when both are constant and equal."""
    if len(a) != len(b):
        raise ValueError("raters must label the same number of items")
    n = len(a)
    if n == 0:
        return float("nan")
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def by_rater(labels: Iterable[Label]) -> dict[str, dict[Key, str]]:
    """judge -> item key -> label, for planted items only (invented rules are not paired)."""
    out: dict[str, dict[Key, str]] = {}
    for lab in labels:
        if lab.label == INVENTED:
            continue
        out.setdefault(lab.judge, {})[item_key(lab)] = lab.label
    return out


def pair_stats(x: dict[Key, str], y: dict[Key, str]) -> dict[str, Any]:
    keys = sorted(set(x) & set(y))
    a, b = [x[k] for k in keys], [y[k] for k in keys]
    confusion = Counter(zip(a, b))
    return {
        "n": len(keys),
        "agreement": (sum(p == q for p, q in zip(a, b)) / len(keys)) if keys else float("nan"),
        "kappa": cohen_kappa(a, b),
        "confusion": {f"{p}|{q}": c for (p, q), c in sorted(confusion.items())},
    }


def agreement_report(labels: Iterable[Label], raters: Sequence[str] | None = None) -> dict[str, Any]:
    """Pairwise agreement for every pair of raters, plus how often the tie-break was used."""
    labels = list(labels)
    table = by_rater(labels)
    names = list(raters) if raters is not None else sorted(table)
    pairs = {f"{p} vs {q}": pair_stats(table.get(p, {}), table.get(q, {}))
             for p, q in combinations(names, 2)}
    report: dict[str, Any] = {"raters": names, "pairs": pairs}
    if FINAL in table:
        judges = [n for n in table if n != FINAL]
        # Items labelled by three raters plus final were sent to the tie-break.
        counts = Counter(k for n in judges for k in table[n])
        disputed = sum(1 for k in table[FINAL] if counts[k] >= 3)
        report["tiebreak"] = {"items": len(table[FINAL]), "disputed": disputed,
                              "rate": disputed / len(table[FINAL]) if table[FINAL] else 0.0}
    report["label_counts"] = {
        name: {lab: sum(1 for v in table[name].values() if v == lab) for lab in LABELS}
        for name in names if name in table
    }
    return report


def human_check(human: Iterable[Label], judge: Iterable[Label], judge_name: str = FINAL,
                gate: float = KAPPA_GATE) -> dict[str, Any]:
    """Kappa between each pair of human annotators and between each human and the judge.

    `passes` is True when every human-vs-judge kappa reaches the gate (SPEC: 0.7).
    """
    humans = by_rater(human)
    judged = by_rater(judge).get(judge_name, {})
    out: dict[str, Any] = {"humans": {}, "human_vs_judge": {}, "gate": gate}
    for p, q in combinations(sorted(humans), 2):
        out["humans"][f"{p} vs {q}"] = pair_stats(humans[p], humans[q])
    for name in sorted(humans):
        out["human_vs_judge"][name] = pair_stats(humans[name], judged)
    kappas = [s["kappa"] for s in out["human_vs_judge"].values() if s["n"]]
    out["passes"] = bool(kappas) and min(kappas) >= gate
    return out
