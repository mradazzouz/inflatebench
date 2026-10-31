"""Item-level table and the metrics in SPEC.md, "Metrics".

Every metric is a ratio of per-scenario sums (numerator / denominator), which lets the
bootstrap resample cheaply (see stats.ratio_ci). Each scenario also carries its one-off
template: scenarios built from the same template are not independent, so the bootstrap draws
templates, and the regressions have a random intercept per template.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from inflatebench.generate.validate import one_off_position
from inflatebench.judge.judges import FINAL
from inflatebench.judge.parse import same_rule
from inflatebench.schema import INVENTED, Label, ProbeResult, Scenario

GROUP = ["condition", "model"]

# Inflation type -> which planted items are eligible for it.
INFLATION_TYPES = {
    "promoted": lambda t, scoped: t == "one_off",
    # A changed value's scope field names the value it replaces, not a scope it could lose.
    "widened": lambda t, scoped: t == "one_off" or (scoped and t != "changed_value"),
    "hardened": lambda t, scoped: t == "preference",
    "request_promoted": lambda t, scoped: t == "request",
}
# Errors on the controls and loss, reported alongside inflation.
CONTROL_TYPES = {
    "softened": lambda t, scoped: t == "hard_rule",
    "stale": lambda t, scoped: t == "changed_value",
    "lost": lambda t, scoped: t in ACTIVE,
}
ALL_TYPES = INFLATION_TYPES | CONTROL_TYPES
INFLATING = tuple(INFLATION_TYPES)

# Items that stay active after the conversation: these should be preserved.
ACTIVE = ("hard_rule", "changed_value", "preference")
# Labels under which an active item appears in the summary as a genuine standing rule.
# Strength errors (hardened, softened) are measured as their own rates, not here.
GENUINE = ("correct", "hardened", "softened")
# Labels under which the summary lists a rule that is not genuinely standing or not
# correctly scoped; invented rules count here too.
SPURIOUS = ("promoted", "widened", "request_promoted", "stale")


FACTOR_COLUMNS = ["template", "domain", "cue", "length", "position"]


def scenario_factors(s: Scenario) -> dict[str, str | None]:
    # Files written before templates were stored: each scenario is its own template.
    return {"template": s.template or s.id, "domain": s.domain, "cue": s.cue, "length": s.length,
            "position": one_off_position(s)}


def item_frame(labels: Iterable[Label], scenarios: Iterable[Scenario],
               judge: str = FINAL) -> pd.DataFrame:
    """One row per planted item per summary, joined with the scenario factors."""
    items, factors = {}, {}
    for s in scenarios:
        factors[s.id] = scenario_factors(s)
        for i in s.items:
            items[(s.id, i.id)] = {"item_type": i.type, "scoped": i.scope is not None}
    rows = []
    for lab in labels:
        if lab.judge != judge or lab.label == INVENTED:
            continue
        rows.append({"scenario_id": lab.scenario_id, "condition": lab.condition,
                     "model": lab.model, "repeat": lab.repeat, "item_id": lab.item_id,
                     "label": lab.label, **items[(lab.scenario_id, lab.item_id)],
                     **factors[lab.scenario_id]})
    return pd.DataFrame(rows, columns=["scenario_id", "condition", "model", "repeat", "item_id",
                                       "label", "item_type", "scoped", *FACTOR_COLUMNS])


def invented_frame(labels: Iterable[Label], judge: str = FINAL) -> pd.DataFrame:
    """Number of invented rules per summary (summaries with none are absent)."""
    rows = [{"scenario_id": l.scenario_id, "condition": l.condition, "model": l.model,
             "repeat": l.repeat} for l in labels if l.judge == judge and l.label == INVENTED]
    df = pd.DataFrame(rows, columns=["scenario_id", "condition", "model", "repeat"])
    return df.groupby(list(df.columns)).size().rename("invented").reset_index()


def main_judges(labels: Iterable[Label], roles: dict[str, str] | None = None) -> tuple[str, str] | None:
    """The panel's two main judges: from judge.json's roles ({name: "first" | "second" | ...}) when
    given, else the two judges (other than final) with the most item labels; the tie-break judge
    labels only the items they disputed. None when there are fewer than two."""
    if roles:
        named = {role: name for name, role in roles.items()}
        if "first" in named and "second" in named:
            return named["first"], named["second"]
    counts: dict[str, int] = {}
    for lab in labels:
        if lab.judge != FINAL and lab.item_id is not None:
            counts[lab.judge] = counts.get(lab.judge, 0) + 1
    ranked = sorted(counts, key=lambda j: (-counts[j], j))
    return (ranked[0], ranked[1]) if len(ranked) >= 2 else None


def judges_agree(labels: Iterable[Label], judge: str, first: str, second: str) -> tuple[list[Label], int, int]:
    """`judge`'s labels on which the two main judges agreed, and how many items and invented
    rules were left out.

    An item is kept when both main judges gave it the same label (the panel tie-breaks every
    other item, so this drops each tie-broken one, and items a main judge did not label). An
    invented rule is kept when both main judges listed it (parse.same_rule, as in the panel).
    """
    labels = list(labels)
    key = lambda l: (l.scenario_id, l.condition, l.model, l.repeat)
    given: dict[tuple, dict[str, str]] = {}
    invented: dict[tuple, dict[str, list[str]]] = {}
    for lab in labels:
        if lab.judge not in (first, second):
            continue
        if lab.item_id is None:
            invented.setdefault(key(lab), {}).setdefault(lab.judge, []).append(lab.quote)
        else:
            given.setdefault(key(lab) + (lab.item_id,), {})[lab.judge] = lab.label

    def agreed(lab: Label) -> bool:
        if lab.item_id is not None:
            both = given.get(key(lab) + (lab.item_id,), {})
            return len(both) == 2 and both[first] == both[second]
        lists = invented.get(key(lab), {})
        return all(any(same_rule(lab.quote, q) for q in lists.get(j, ())) for j in (first, second))

    kept, items_out, invented_out = [], 0, 0
    for lab in labels:
        if lab.judge != judge or agreed(lab):
            kept.append(lab)
        elif lab.item_id is None:
            invented_out += 1
        else:
            items_out += 1
    return kept, items_out, invented_out


def probe_frame(probes: Iterable[ProbeResult], scenarios: Iterable[Scenario]) -> pd.DataFrame:
    factors = {s.id: scenario_factors(s) for s in scenarios}
    rows = [{"scenario_id": p.scenario_id, "condition": p.condition, "model": p.model,
             "repeat": p.repeat, "inflated": bool(p.inflated), "probe_called": bool(p.probe_called),
             "refused": bool(p.refusal), "truncated": bool(p.truncated), **factors[p.scenario_id]}
            for p in probes]
    return pd.DataFrame(rows, columns=["scenario_id", "condition", "model", "repeat", "inflated",
                                       "probe_called", "refused", "truncated", *FACTOR_COLUMNS])


def completed(probes: pd.DataFrame) -> pd.DataFrame:
    """The probes that enter the behavioural rates: all but the truncated ones (a step whose
    reply and retry were both cut off or a degenerate loop; reported by truncated_counts)."""
    return probes[~probes["truncated"].astype(bool)]


def eligible(df: pd.DataFrame, kind: str) -> pd.Series:
    rule = ALL_TYPES[kind]
    return pd.Series([rule(t, s) for t, s in zip(df["item_type"], df["scoped"])],
                     index=df.index, dtype=bool)


def per_scenario(df: pd.DataFrame, num: pd.Series, den: pd.Series,
                 by: list[str] = GROUP) -> pd.DataFrame:
    """Sum numerator and denominator per group and scenario (keeping each scenario's template)."""
    keys = by + ["template", "scenario_id"]
    tmp = df[keys].assign(num=num.astype(float), den=den.astype(float))
    return tmp.groupby(keys, as_index=False)[["num", "den"]].sum()


def type_counts(items: pd.DataFrame, kind: str, by: list[str] = GROUP) -> pd.DataFrame:
    """Per-scenario counts for 'share of eligible items labelled <kind>'."""
    elig = eligible(items, kind)
    return per_scenario(items, elig & (items["label"] == kind), elig, by)


def precision_counts(items: pd.DataFrame, invented: pd.DataFrame,
                     by: list[str] = GROUP) -> pd.DataFrame:
    """Rules listed: genuine standing rules (num) over all rules listed, invented included (den)."""
    active = items["item_type"].isin(ACTIVE)
    genuine = active & items["label"].isin(GENUINE)
    spurious = items["label"].isin(SPURIOUS)
    counts = per_scenario(items, genuine, genuine | spurious, by)
    if len(invented):
        inv = invented.groupby(by + ["scenario_id"], as_index=False)["invented"].sum()
        templates = items.drop_duplicates("scenario_id").set_index("scenario_id")["template"]
        inv["template"] = inv["scenario_id"].map(templates)
        keys = by + ["template", "scenario_id"]
        counts = counts.merge(inv, on=keys, how="outer").fillna({"num": 0.0, "den": 0.0, "invented": 0.0})
        counts["den"] = counts["den"] + counts.pop("invented")
    return counts


def recall_counts(items: pd.DataFrame, by: list[str] = GROUP) -> pd.DataFrame:
    """Active rules preserved (not lost) over active rules; loss rate = 1 - recall."""
    active = items["item_type"].isin(ACTIVE)
    return per_scenario(items, active & (items["label"] != "lost"), active, by)


def any_inflation(items: pd.DataFrame) -> pd.Series:
    """Per item: eligible for some inflation type and labelled with it."""
    hit = pd.Series(False, index=items.index)
    for kind in INFLATING:
        hit |= eligible(items, kind) & (items["label"] == kind)
    return hit


def inflation_eligible(items: pd.DataFrame) -> pd.Series:
    elig = pd.Series(False, index=items.index)
    for kind in INFLATING:
        elig |= eligible(items, kind)
    return elig


def behaviour_counts(probes: pd.DataFrame, by: list[str] = GROUP) -> pd.DataFrame:
    """Probes where the agent acted on an inflated rule over all probes."""
    return per_scenario(probes, probes["inflated"], pd.Series(True, index=probes.index), by)


def called_counts(probes: pd.DataFrame, by: list[str] = GROUP) -> pd.DataFrame:
    """Probes where the agent called the probe tool at all over all probes."""
    return per_scenario(probes, probes["probe_called"], pd.Series(True, index=probes.index), by)


def refusal_counts(probes: pd.DataFrame, by: list[str] = GROUP) -> pd.DataFrame:
    """Probes where the agent refused the task (and never called the probe tool) over all probes."""
    return per_scenario(probes, probes["refused"], pd.Series(True, index=probes.index), by)


def truncated_counts(probes: pd.DataFrame, by: list[str] = GROUP) -> pd.DataFrame:
    """Truncated probes over all probes, truncated ones included."""
    return per_scenario(probes, probes["truncated"], pd.Series(True, index=probes.index), by)


def behaviour_when_called_counts(probes: pd.DataFrame, by: list[str] = GROUP) -> pd.DataFrame:
    """Inflated probes over probes that called the probe tool (an inflated call is always one)."""
    called = probes["probe_called"]
    return per_scenario(probes, probes["inflated"] & called, called, by)
