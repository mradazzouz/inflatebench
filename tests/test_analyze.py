import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from conftest import INFLATE_P, synthetic_run
from inflatebench.analyze import analyze, analyze_run, mixed_logit, ratio_ci
from inflatebench.analyze import metrics as m
from inflatebench.analyze.report import behaviour_rates, inflation_rates, precision_recall
from inflatebench.generate.validate import position
from inflatebench.judge import FINAL
from inflatebench.schema import INVENTED, Label, ProbeResult, Scenario, read_jsonl, write_jsonl


def labels_for(scenario, labels, condition="free", model="x", repeat=0, invented=0):
    meta = dict(scenario_id=scenario.id, condition=condition, model=model, repeat=repeat)
    out = [Label(judge=FINAL, item_id=i, label=l, **meta) for i, l in labels.items()]
    out += [Label(judge=FINAL, item_id=None, label=INVENTED, quote="q", **meta)] * invented
    return out


def test_metrics_on_hand_labelled_summary(pilot):
    s = pilot[2]
    bad = {"h1": "correct", "c1": "stale", "o1": "promoted", "s1": "hardened",
           "r1": "request_promoted", "r2": "correct"}
    labels = labels_for(s, bad, invented=1) + [Label(scenario_id=s.id, condition="free", model="x",
                                                     repeat=0, judge="other", item_id="h1", label="lost")]
    items = m.item_frame(labels, pilot)
    assert len(items) == 6  # other judges and invented rules are excluded
    rates = inflation_rates(items, n_boot=50).set_index("type")
    assert rates.loc["promoted", "rate"] == 1.0
    assert rates.loc["widened", "rate"] == 0.0  # eligible (o1 is scoped) but not widened
    assert rates.loc["hardened", "rate"] == 1.0
    assert rates.loc["request_promoted", "rate"] == 0.5
    assert rates.loc["stale", "rate"] == 1.0
    assert rates.loc["lost", "rate"] == 0.0
    pr = precision_recall(items, m.invented_frame(labels), n_boot=50).iloc[0]
    # Listed rules: h1 and s1 genuine; c1 stale, o1, r1 spurious; one invented -> 2 / 6.
    assert pr["rules_listed"] == 6 and pr["precision"] == pytest.approx(2 / 6)
    assert pr["recall"] == 1.0 and pr["loss_rate"] == 0.0


def test_widened_is_not_eligible_for_changed_values():
    # In real data c1 carries scope "replaces <old value>", which is not a scope it could widen.
    data = list(read_jsonl(Path(__file__).parent.parent / "data" / "pilot.jsonl", Scenario))
    s = data[0]
    assert next(i for i in s.items if i.type == "changed_value").scope is not None
    labels = labels_for(s, {"h1": "correct", "c1": "correct", "o1": "widened", "p1": "correct",
                            "r1": "correct", "r2": "correct"})
    items = m.item_frame(labels, data)
    assert not m.eligible(items, "widened")[items["item_type"] == "changed_value"].any()
    widened = inflation_rates(items, n_boot=20).set_index("type").loc["widened"]
    assert (widened["num"], widened["den"], widened["rate"]) == (1, 1, 1.0)
    assert not m.inflation_eligible(items)[items["item_type"] == "changed_value"].any()


def test_recall_counts_lost_rules(pilot):
    s = pilot[0]
    labels = labels_for(s, {"h1": "lost", "c1": "correct", "o1": "correct", "s1": "lost",
                            "r1": "correct", "r2": "correct"})
    pr = precision_recall(m.item_frame(labels, pilot), m.invented_frame(labels), n_boot=20).iloc[0]
    assert pr["recall"] == pytest.approx(1 / 3)
    assert pr["precision"] == 1.0


def test_ratio_ci_brackets_rate_and_is_reproducible():
    counts = pd.DataFrame({"g": ["a"] * 30 + ["b"] * 30,
                           "scenario_id": [f"s{k}" for k in range(30)] * 2,
                           "num": [1, 0, 0] * 10 + [1, 1, 0] * 10, "den": [1.0] * 60})
    ci = ratio_ci(counts, ["g"], n_boot=500, seed=3).set_index("g")
    assert ci.loc["a", "rate"] == pytest.approx(1 / 3)
    assert ci.loc["b", "rate"] == pytest.approx(2 / 3)
    for g in "ab":
        assert ci.loc[g, "lo"] < ci.loc[g, "rate"] < ci.loc[g, "hi"]
    assert ci.loc["a", "scenarios"] == 30
    pd.testing.assert_frame_equal(ci, ratio_ci(counts, ["g"], n_boot=500, seed=3).set_index("g"))
    # Constant per-scenario rate: every resample gives the same value.
    flat = counts.assign(num=1.0)
    ci = ratio_ci(flat, ["g"], n_boot=100)
    assert (ci["lo"] == 1.0).all() and (ci["hi"] == 1.0).all()


def test_ratio_ci_handles_empty_and_zero_denominators():
    assert ratio_ci(pd.DataFrame(columns=["g", "scenario_id", "num", "den"]), ["g"]).empty
    counts = pd.DataFrame({"g": ["a"], "scenario_id": ["s"], "num": [0.0], "den": [0.0]})
    row = ratio_ci(counts, ["g"], n_boot=10).iloc[0]
    assert np.isnan(row["rate"]) and np.isnan(row["lo"])


def test_synthetic_rates_recover_planted_effects(pilot):
    scenarios, labels, probes = synthetic_run(pilot, n_scenarios=40)
    items = m.item_frame(labels, scenarios)
    rates = inflation_rates(items, n_boot=200)
    promoted = rates[rates["type"] == "promoted"].groupby("condition")["rate"].mean()
    assert promoted["free"] < promoted["sectioned"] < promoted["pinning"]
    pr = precision_recall(items, m.invented_frame(labels), n_boot=200).groupby("condition").mean(
        numeric_only=True)
    # The RQ3 trade-off as planted: pinning keeps more rules but lists more spurious ones.
    assert pr.loc["pinning", "recall"] > pr.loc["free", "recall"]
    assert pr.loc["pinning", "precision"] < pr.loc["free", "precision"]


def test_mixed_logit_finds_condition_effect(pilot):
    scenarios, labels, _ = synthetic_run(pilot, n_scenarios=40)
    items = m.item_frame(labels, scenarios)
    df = items[m.inflation_eligible(items)].assign(inflated=m.any_inflation(items))
    res = mixed_logit(df, "inflated")
    coef = res.set_index("term")["coef"]
    term = "C(condition, Treatment(reference='free'))[T.pinning]"
    assert coef[term] > 1.0  # planted: 0.10 vs 0.60 inflation probability, log-odds ~2.6
    assert res.set_index("term").loc["scenario_id", "effect"] == "random_log_sd"
    assert res.attrs["formula"].endswith("+ (1 | scenario_id)")
    assert "C(model)[T.m-b]" in coef and "C(cue, Treatment(reference='explicit'))[T.implicit]" in coef
    assert "C(position, Treatment(reference='early'))[T.late]" in coef
    assert "position" in res.attrs["formula"]


def test_position_comes_from_the_scenario_or_its_history(pilot):
    scenarios, labels, probes = synthetic_run(pilot, n_scenarios=18)
    items = m.item_frame(labels, scenarios)
    assert set(items["position"]) == {"early", "middle", "late"}
    assert set(m.probe_frame(probes, scenarios)["position"]) == {"early", "middle", "late"}
    # Files written before position was stored: computed from where the one-off sits.
    old = m.item_frame(labels_for(pilot[0], {i.id: "correct" for i in pilot[0].items}), pilot)
    assert set(old["position"]) == {position(pilot[0], "o1")}


def test_behaviour_reports_probe_calls_and_rate_when_called():
    def probe(sid, called, inflated):
        return ProbeResult(sid, "free", "x", 0, probe_called=called, inflated=inflated)

    scen = [Scenario.from_dict(s.to_dict() | {"id": sid}) for sid, s in
            zip(("a", "b"), list(read_jsonl(Path(__file__).parent / "fixtures" / "scenarios.jsonl",
                                            Scenario))[:2])]
    # a: called and inflated, called and not; b: not called twice.
    probes = [probe("a", True, True), probe("a", True, False), probe("b", False, False),
              probe("b", False, False)]
    row = behaviour_rates(m.probe_frame(probes, scen), n_boot=50).iloc[0]
    assert row["rate"] == pytest.approx(1 / 4)  # overall
    assert row["called_rate"] == pytest.approx(2 / 4)
    assert row["rate_when_called"] == pytest.approx(1 / 2)
    assert (row["rate_when_called_num"], row["rate_when_called_den"]) == (1, 2)
    assert row["called_rate_lo"] <= row["called_rate"] <= row["called_rate_hi"]


def test_mixed_logit_drops_constant_factors(pilot):
    scenarios, labels, _ = synthetic_run(pilot, n_scenarios=12, models=("only",))
    items = m.item_frame(labels, scenarios)
    df = items[m.inflation_eligible(items)].assign(inflated=m.any_inflation(items))
    res = mixed_logit(df, "inflated")
    assert not any("model" in t for t in res["term"])


def test_analyze_run_writes_report(tmp_path, pilot):
    scenarios, labels, probes = synthetic_run(pilot, n_scenarios=24)
    run = tmp_path / "runs" / "r1"
    write_jsonl(tmp_path / "scenarios.jsonl", scenarios)
    labels += [Label(scenario_id=scenarios[0].id, condition="free", model="m-a", repeat=0, judge=FINAL,
                     item_id=None, label=INVENTED, quote=q, quote_flagged=flag)
               for q, flag in (("in the text", False), ("made up", True))]
    labels = [replace(l, quote="") if l.quote and l.label != INVENTED else l for l in labels]
    labels = [l for l in labels if not (l.label == INVENTED and l.quote == "Always notify on-call.")]
    write_jsonl(run / "labels.jsonl", labels)
    write_jsonl(run / "probes.jsonl", probes)
    summary = analyze_run(run, tmp_path / "scenarios.jsonl", n_boot=100)
    report = run / "report"
    for name in ("inflation_rates.csv", "precision_recall.csv", "behaviour.csv", "items.csv",
                 "regression_items.csv", "regression_behaviour.csv", "summary.json"):
        assert (report / name).exists(), name
    assert summary["figures"] == ["behaviour.png", "controls_and_loss.png",
                                  "inflation_by_type.png", "precision_recall.png"]
    for fig in summary["figures"]:
        assert (report / "figures" / fig).read_bytes()[:4] == b"\x89PNG"
    on_disk = json.loads((report / "summary.json").read_text())
    assert on_disk["n_scenarios"] == 24
    beh = pd.read_csv(report / "behaviour.csv").groupby("condition")["rate"].mean()
    assert beh["free"] < beh["pinning"]
    assert {"formula", "n", "terms"} <= set(on_disk["regression"]["behaviour"])
    beh_cols = set(pd.read_csv(report / "behaviour.csv").columns)
    assert {"rate", "called_rate", "called_rate_lo", "rate_when_called", "rate_when_called_hi"} <= beh_cols
    assert on_disk["behaviour"][0]["called_rate"] >= on_disk["behaviour"][0]["rate"]
    assert on_disk["quote_flags"][FINAL]["rate"] == 1 / 2  # see the flagged label below


def test_analyze_without_probes_or_variation(tmp_path, pilot):
    labels = labels_for(pilot[0], {i.id: "correct" for i in pilot[0].items})
    summary = analyze(labels, pilot, None, tmp_path / "rep", n_boot=10, figures=False)
    assert "behaviour" not in summary
    assert summary["regression"]["items"]["note"].startswith("skipped")
    with pytest.raises(ValueError):
        analyze(labels, pilot, None, tmp_path / "rep2", judge="nobody")


def test_synthetic_inflate_probabilities_are_ordered():
    # Guards the fixture assumptions the tests above rely on.
    assert list(INFLATE_P.values()) == sorted(INFLATE_P.values())
