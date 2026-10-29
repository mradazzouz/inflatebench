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


def cohen_kappa(a: Sequence[str], b: Sequence[str], weights: Sequence[float] | None = None) -> float:
    """Cohen's kappa for two raters over the same items; 1.0 when both are constant and equal.

    With `weights`, each item counts by its weight in the observed agreement and in both
    raters' label shares (no weights is every weight 1).
    """
    if len(a) != len(b) or (weights is not None and len(weights) != len(a)):
        raise ValueError("raters must label the same number of items")
    w = list(weights) if weights is not None else [1.0] * len(a)
    total = sum(w)
    if total == 0:
        return float("nan")
    observed = sum(wi for x, y, wi in zip(a, b, w) if x == y) / total
    ca: Counter[str] = Counter()
    cb: Counter[str] = Counter()
    for x, y, wi in zip(a, b, w):
        ca[x] += wi
        cb[y] += wi
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (total * total)
    if expected >= 1.0 - 1e-12:
        return 1.0 if observed >= 1.0 - 1e-12 else 0.0
    return (observed - expected) / (1 - expected)


def per_label_kappa(a: Sequence[str], b: Sequence[str],
                    weights: Sequence[float] | None = None) -> dict[str, float]:
    """Kappa of each label against the rest (is it this label or not), for every label either
    rater used. The overall kappa is dominated by common labels; this shows the rare ones."""
    used = [lab for lab in LABELS if lab in set(a) | set(b)]
    return {lab: cohen_kappa([lab if x == lab else "other" for x in a],
                             [lab if y == lab else "other" for y in b], weights)
            for lab in used}


def by_rater(labels: Iterable[Label]) -> dict[str, dict[Key, str]]:
    """judge -> item key -> label, for planted items only (invented rules are not paired)."""
    out: dict[str, dict[Key, str]] = {}
    for lab in labels:
        if lab.label == INVENTED:
            continue
        out.setdefault(lab.judge, {})[item_key(lab)] = lab.label
    return out


def _agreement(a: Sequence[str], b: Sequence[str], w: Sequence[float]) -> dict[str, Any]:
    total = sum(w)
    return {
        "agreement": sum(wi for p, q, wi in zip(a, b, w) if p == q) / total if total else float("nan"),
        "kappa": cohen_kappa(a, b, w),
        "per_label_kappa": per_label_kappa(a, b, w),
    }


def pair_stats(x: dict[Key, str], y: dict[Key, str]) -> dict[str, Any]:
    """Unweighted agreement, overall and per-label kappa and the confusion counts of two raters."""
    keys = sorted(set(x) & set(y))
    a, b = [x[k] for k in keys], [y[k] for k in keys]
    confusion = Counter(zip(a, b))
    return {"n": len(keys), **_agreement(a, b, [1.0] * len(keys)),
            "confusion": {f"{p}|{q}": c for (p, q), c in sorted(confusion.items())}}


def human_pair_stats(x: dict[Key, str], y: dict[Key, str],
                     weights: dict[Key, float] | None = None) -> dict[str, Any]:
    """Two raters on the human-check sample, in two clearly separate blocks:

    - `unweighted_sample`: every sampled item counts once. This is agreement on the stratified
      sample itself, and the kappa gate uses it.
    - `weighted_population`: each item counts by its sample weight (pairs in its stratum / pairs
      drawn from it), an estimate of agreement over the whole pool of (summary, item) pairs;
      None without weights.
    """
    keys = sorted(set(x) & set(y))
    a, b = [x[k] for k in keys], [y[k] for k in keys]
    out: dict[str, Any] = {
        "n": len(keys),
        "unweighted_sample": _agreement(a, b, [1.0] * len(keys)),
        "weighted_population": None,
        "confusion": {f"{p}|{q}": c for (p, q), c in sorted(Counter(zip(a, b)).items())},
    }
    if weights is not None:
        if missing := [k for k in keys if k not in weights]:
            raise ValueError(f"{len(missing)} labelled items have no sample weight, e.g. {missing[0]}")
        out["weighted_population"] = _agreement(a, b, [weights[k] for k in keys])
    return out


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


# What the two agreement blocks of human_check mean, stored with the result.
BASIS = {
    "unweighted_sample": "unweighted, on the stratified human-check sample; the kappa gate uses this",
    "weighted_population": "weighted by the sample weights; an estimate for the full pool of items",
}


def human_check(human: Iterable[Label], judge: Iterable[Label], judge_name: str = FINAL,
                gate: float = KAPPA_GATE, weights: dict[Key, float] | None = None) -> dict[str, Any]:
    """Agreement between each pair of human annotators and between each human and the judge:
    overall and per-label (one label against the rest) kappa, unweighted on the stratified
    sample and, given the sample weights (run.sample_weights), weighted to the full pool.

    `passes` is True when every unweighted human-vs-judge kappa reaches the gate (SPEC: 0.7).
    """
    humans = by_rater(human)
    judged = by_rater(judge).get(judge_name, {})
    out: dict[str, Any] = {"humans": {}, "human_vs_judge": {}, "gate": gate,
                           "gate_on": "unweighted_sample", "basis": BASIS}
    for p, q in combinations(sorted(humans), 2):
        out["humans"][f"{p} vs {q}"] = human_pair_stats(humans[p], humans[q], weights)
    for name in sorted(humans):
        out["human_vs_judge"][name] = human_pair_stats(humans[name], judged, weights)
    kappas = [s["unweighted_sample"]["kappa"] for s in out["human_vs_judge"].values() if s["n"]]
    out["passes"] = bool(kappas) and min(kappas) >= gate
    return out
