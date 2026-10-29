"""Stage 3: judge every summary of a run -> runs/<run_id>/labels.jsonl."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Iterable

from inflatebench.conditions import neutral_context
from inflatebench.judge.judges import PanelJudge
from inflatebench.judge.rubric import ALLOWED_LABELS
from inflatebench.models import Deferred, Pending, run_phases
from inflatebench.schema import Label, Scenario, Summary, read_jsonl, write_jsonl


def judge_summaries(panel: PanelJudge, scenarios: Iterable[Scenario],
                    summaries: Iterable[Summary]) -> list[Label]:
    """Labels for every summary. Judges on models.Deferred LLMs are batched in phases:
    both judges' calls first, then the tie-break calls (and any retries of malformed replies).
    """
    by_id = {s.id: s for s in scenarios}
    summaries = list(summaries)

    def step() -> list[Label]:
        out: list[Label] = []
        for summary in summaries:
            try:
                out += panel.label(by_id[summary.scenario_id], summary)
            except Pending:
                continue  # answered in the next phase
        return out

    deferred = [j.llm for j in panel.judges if isinstance(j.llm, Deferred)]
    if deferred:
        run_phases(step, deferred)
    return step()


def judge_run(panel: PanelJudge, scenarios_path: str | Path, run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    labels = judge_summaries(panel, read_jsonl(scenarios_path, Scenario),
                             read_jsonl(run_dir / "summaries.jsonl", Summary))
    out = run_dir / "labels.jsonl"
    write_jsonl(out, labels)
    return out


# Above this share of flagged final quotes, fix the judge instructions before the main run.
QUOTE_FLAG_LIMIT = 0.10


def quote_flag_rates(labels: Iterable[Label]) -> dict[str, dict[str, Any]]:
    """Per judge: labels with a quote, how many of those quotes were flagged as not in the
    summary after one re-ask, and the rate. Labels resting on absence (no quote) are left out."""
    out: dict[str, dict[str, Any]] = {}
    for lab in labels:
        row = out.setdefault(lab.judge, {"quoted": 0, "flagged": 0})
        if lab.quote:
            row["quoted"] += 1
            row["flagged"] += lab.quote_flagged
    for row in out.values():
        row["rate"] = row["flagged"] / row["quoted"] if row["quoted"] else 0.0
    return dict(sorted(out.items()))


def type_flag_rates(labels: Iterable[Label]) -> dict[str, dict[str, Any]]:
    """Per judge: planted-item labels, how many kept a label their item type does not allow
    after one re-ask, and the rate."""
    out: dict[str, dict[str, Any]] = {}
    for lab in labels:
        if lab.item_id is None:
            continue
        row = out.setdefault(lab.judge, {"labels": 0, "flagged": 0})
        row["labels"] += 1
        row["flagged"] += lab.type_flagged
    for row in out.values():
        row["rate"] = row["flagged"] / row["labels"] if row["labels"] else 0.0
    return dict(sorted(out.items()))


def make_annotation_sample(scenarios: Iterable[Scenario], summaries: Iterable[Summary],
                           n: int = 200, seed: int = 0,
                           include_history: bool = True) -> tuple[list[dict], list[dict]]:
    """Randomly sample n (summary, item) pairs for human labelling, blind to condition.

    Returns (sample, key): the sample rows go to the annotation page and carry only an
    opaque uid; the key rows map each uid back to condition, model and repeat.
    """
    by_id = {s.id: s for s in scenarios}
    pool = [(summ, item) for summ in summaries for item in by_id[summ.scenario_id].items]
    rng = random.Random(seed)
    picked = rng.sample(pool, min(n, len(pool)))
    sample, key = [], []
    for k, (summ, item) in enumerate(picked):
        uid = f"u{k:04d}"
        scen = by_id[summ.scenario_id]
        row: dict[str, Any] = {"uid": uid, "scenario_id": scen.id, "item_id": item.id,
                               "item_type": item.type, "item_text": item.text,
                               "item_scope": item.scope, "summary": neutral_context(summ.messages),
                               "allowed_labels": list(ALLOWED_LABELS[item.type])}
        if include_history:
            row["history"] = [m.to_dict() for m in scen.history]
        sample.append(row)
        key.append({"uid": uid, "scenario_id": scen.id, "condition": summ.condition,
                    "model": summ.model, "repeat": summ.repeat, "item_id": item.id})
    return sample, key


def write_rows(path: str | Path, rows: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_rows(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_human_labels(labels_path: str | Path, key_path: str | Path) -> list[Label]:
    """Join labels saved by annotation/index.html with the sample key into Label records.

    Each saved row has uid, annotator, label and quote; judge becomes "human:<annotator>".
    """
    key = {r["uid"]: r for r in read_rows(key_path)}
    out = []
    for row in read_rows(labels_path):
        k = key[row["uid"]]
        out.append(Label(scenario_id=k["scenario_id"], condition=k["condition"],
                         model=k["model"], repeat=k["repeat"],
                         judge=f"human:{row['annotator']}", item_id=k["item_id"],
                         label=row["label"], quote=row.get("quote", "")))
    return out
