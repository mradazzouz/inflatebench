import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from conftest import INFLATE_P, synthetic_run
from inflatebench.analyze import analyze, analyze_run, mixed_logit, ratio_ci
from inflatebench.analyze.stats import diff_ci
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
    terms = res.set_index("term")
    assert terms.loc["scenario_id", "effect"] == terms.loc["template", "effect"] == "random_log_sd"
    assert res.attrs["formula"].endswith("+ (1 | scenario_id) + (1 | template)")
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


def test_behaviour_reports_the_refusal_rate():
    scen = [Scenario.from_dict(s.to_dict() | {"id": sid}) for sid, s in
            zip(("a", "b"), list(read_jsonl(Path(__file__).parent / "fixtures" / "scenarios.jsonl",
                                            Scenario))[:2])]
    probes = [ProbeResult("a", "free", "x", 0, probe_called=True, inflated=True),
              ProbeResult("a", "free", "x", 1, refusal="text"),
              ProbeResult("b", "free", "x", 0, refusal="provider"),
              ProbeResult("b", "free", "x", 1),  # no call, no refusal: a question, say
              ProbeResult("a", "full", "x", 0, probe_called=True),
              ProbeResult("b", "full", "x", 0, probe_called=True)]
    df = m.probe_frame(probes, scen)
    assert df["refused"].tolist() == [False, True, True, False, False, False]
    rows = behaviour_rates(df, n_boot=50).set_index("condition")
    free = rows.loc["free"]
    assert free["refusal_rate"] == pytest.approx(2 / 4)  # alongside the behavioural rates
    assert (free["refusal_rate_num"], free["refusal_rate_den"]) == (2, 4)
    assert free["refusal_rate_lo"] <= free["refusal_rate"] <= free["refusal_rate_hi"]
    assert free["rate"] == pytest.approx(1 / 4) and rows.loc["full", "refusal_rate"] == 0


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
    on_disk = json.loads((report / "summary.json").read_text(encoding="utf-8"))
    assert on_disk["n_scenarios"] == 24
    beh = pd.read_csv(report / "behaviour.csv").groupby("condition")["rate"].mean()
    assert beh["free"] < beh["pinning"]
    assert {"formula", "n", "terms"} <= set(on_disk["regression"]["behaviour"])
    beh_cols = set(pd.read_csv(report / "behaviour.csv").columns)
    assert {"rate", "called_rate", "called_rate_lo", "rate_when_called", "rate_when_called_hi"} <= beh_cols
    assert on_disk["behaviour"][0]["called_rate"] >= on_disk["behaviour"][0]["rate"]
    assert on_disk["quote_flags"][FINAL]["rate"] == 1 / 2  # see the flagged label below


def test_robustness_tables_exclude_flagged_labels(tmp_path, pilot):
    s = pilot[0]
    labels = labels_for(s, {"h1": "correct", "c1": "correct", "o1": "promoted", "s1": "correct",
                            "r1": "correct", "r2": "correct"}, invented=1)
    labels = [replace(l, quote_flagged=True) if l.item_id == "o1" else l for l in labels]
    labels.append(replace(labels[0], judge="other", quote_flagged=True))  # another judge's flag
    summary = analyze(labels, pilot, None, tmp_path / "rep", n_boot=10, figures=False)
    main = {r["type"]: r for r in summary["inflation_rates"]}
    robust = {r["type"]: r for r in summary["robustness_unflagged"]["inflation_rates"]}
    assert main["promoted"]["rate"] == 1.0  # main results keep every label
    assert robust["promoted"]["den"] == 0  # the flagged one-off is left out of the check
    assert summary["robustness_unflagged"]["excluded_labels"] == 1
    assert summary["robustness_unflagged"]["n_items"] == summary["n_items"] - 1
    for name in ("inflation_rates_unflagged.csv", "precision_recall_unflagged.csv"):
        assert (tmp_path / "rep" / name).exists()


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


def test_bootstrap_resamples_templates_not_scenarios():
    # Two templates of 10 scenarios each: one always inflated, one never. Drawn by scenario, the
    # interval would be narrow; drawn by template, a replicate holds 0, 1 or 2 copies of each.
    counts = pd.DataFrame({"g": ["a"] * 20, "scenario_id": [f"s{k}" for k in range(20)],
                           "template": ["t0"] * 10 + ["t1"] * 10,
                           "num": [1.0] * 10 + [0.0] * 10, "den": [1.0] * 20})
    by_template = ratio_ci(counts, ["g"], n_boot=500).iloc[0]
    by_scenario = ratio_ci(counts.drop(columns="template"), ["g"], n_boot=500).iloc[0]
    assert by_template["rate"] == by_scenario["rate"] == 0.5
    assert (by_template["clusters"], by_template["scenarios"]) == (2, 20)
    assert by_scenario["clusters"] == 20
    assert by_template["hi"] - by_template["lo"] > 2 * (by_scenario["hi"] - by_scenario["lo"])
    assert by_template["lo"] == 0.0 and by_template["hi"] == 1.0


def test_diff_ci_is_paired_against_the_baseline():
    rows = []
    for k in range(30):
        t = f"t{k % 10}"
        base = float(k % 3 == 0)  # baseline rate 1/3
        rows += [{"condition": "full", "model": "m", "scenario_id": f"s{k}", "template": t,
                  "num": base, "den": 1.0},
                 # 'up' adds exactly 0.2 per scenario on top of the baseline, so the paired
                 # difference is the same in every replicate.
                 {"condition": "up", "model": "m", "scenario_id": f"s{k}", "template": t,
                  "num": base + 0.2, "den": 1.0}]
    d = diff_ci(pd.DataFrame(rows), "full", n_boot=200).iloc[0]
    assert d["condition"] == "up" and d["diff"] == pytest.approx(0.2)
    assert d["diff_lo"] == pytest.approx(0.2) and d["diff_hi"] == pytest.approx(0.2)
    assert diff_ci(pd.DataFrame(rows), "missing").empty


def test_behaviour_reports_compaction_induced_rate_against_full_history():
    scen = list(read_jsonl(Path(__file__).parent / "fixtures" / "scenarios.jsonl", Scenario))[:2]
    probes = []
    for s in scen:
        for rep in range(2):
            probes.append(ProbeResult(s.id, "full", "x", rep, probe_called=True, inflated=rep == 0))
            probes.append(ProbeResult(s.id, "pinning", "x", rep, probe_called=True, inflated=True))
    beh = behaviour_rates(m.probe_frame(probes, scen), n_boot=50).set_index("condition")
    assert beh.loc["full", "rate"] == 0.5 and beh.loc["pinning", "rate"] == 1.0
    assert beh.loc["pinning", "induced"] == pytest.approx(0.5)
    assert beh.loc["pinning", "induced_when_called"] == pytest.approx(0.5)
    assert np.isnan(beh.loc["full", "induced"])  # the baseline has no difference of its own
    # The behaviour regression compares conditions with the full-history baseline.
    from inflatebench.analyze.report import regressions

    many = [replace(p, scenario_id=s.id) for s in scen for p in probes if p.scenario_id == s.id]
    df = m.probe_frame(many, scen)
    res = regressions(m.item_frame([], scen), df)["behaviour"]
    assert any("reference='full'" in t for t in res["term"])


def test_robustness_tables_also_exclude_off_type_labels(tmp_path, pilot):
    s = pilot[0]
    labels = labels_for(s, {"h1": "correct", "c1": "correct", "o1": "promoted", "s1": "correct",
                            "r1": "correct", "r2": "correct"})
    labels = [replace(l, type_flagged=True) if l.item_id == "o1" else l for l in labels]
    summary = analyze(labels, pilot, None, tmp_path / "rep", n_boot=10, figures=False)
    robust = {r["type"]: r for r in summary["robustness_unflagged"]["inflation_rates"]}
    assert robust["promoted"]["den"] == 0 and summary["robustness_unflagged"]["excluded_labels"] == 1
    assert summary["type_flags"][FINAL] == {"labels": 6, "flagged": 1, "rate": 1 / 6}


def test_judges_agree_robustness_drops_tie_broken_items_and_invented_rules(tmp_path, pilot):
    s = pilot[0]
    meta = dict(scenario_id=s.id, condition="free", model="x", repeat=0)
    final = {i.id: "correct" for i in s.items} | {"o1": "promoted"}
    labels = labels_for(s, final)
    for judge in ("a", "b"):
        # The main judges disagree on o1 only; the tie-break judge c decides it.
        labels += [Label(judge=judge, item_id=i, label=l, **meta)
                   for i, l in (final | ({"o1": "correct"} if judge == "b" else {})).items()]
    labels.append(Label(judge="c", item_id="o1", label="promoted", **meta))
    # Both main judges list the first invented rule; only a and the tie-break list the second.
    both, one = "Always run the tests first.", "Never open draft pull requests."
    for judge, quotes in (("a", [both, one]), ("b", [both + " Every time."]), ("c", [one]), (FINAL, [both, one])):
        labels += [Label(judge=judge, item_id=None, label=INVENTED, quote=q, **meta) for q in quotes]

    summary = analyze(labels, pilot, None, tmp_path / "rep", n_boot=10, figures=False,
                      judge_roles={"a": "first", "b": "second", "c": "tiebreak"})
    main = {r["type"]: r for r in summary["inflation_rates"]}
    agree = summary["robustness_judges_agree"]
    robust = {r["type"]: r for r in agree["inflation_rates"]}
    assert main["promoted"]["rate"] == 1.0 and robust["promoted"]["den"] == 0
    assert agree["main_judges"] == ["a", "b"]
    assert (agree["excluded_items"], agree["excluded_invented"]) == (1, 1)
    assert agree["n_items"] == summary["n_items"] - 1
    # Precision: the promoted one-off and the invented rule only one judge listed leave the
    # rules listed.
    main_pr, agree_pr = summary["precision_recall"][0], agree["precision_recall"][0]
    assert agree_pr["rules_listed"] == main_pr["rules_listed"] - 2
    for name in ("inflation_rates_judges_agree.csv", "precision_recall_judges_agree.csv"):
        assert (tmp_path / "rep" / name).exists()
    # Without judge.json roles the main judges are the two that labelled every item.
    assert m.main_judges(labels) == ("a", "b")
    assert m.main_judges(labels, {"b": "first", "a": "second"}) == ("b", "a")


def test_judges_agree_robustness_needs_two_main_judges(tmp_path, pilot):
    labels = labels_for(pilot[0], {i.id: "correct" for i in pilot[0].items})
    summary = analyze(labels, pilot, None, tmp_path / "rep", n_boot=10, figures=False)
    assert summary["robustness_judges_agree"]["note"].startswith("skipped")
    assert not (tmp_path / "rep" / "inflation_rates_judges_agree.csv").exists()


def test_analyze_run_reads_judge_roles_from_judge_json(tmp_path):
    from inflatebench.cli import main

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    cfg["paths"].update(runs=str(tmp_path / "runs"), cache=str(tmp_path / "cache"))
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    base = ["--config", str(path)]
    pilot_path = str(Path(__file__).parent.parent / "data" / "pilot.jsonl")
    main(base + ["compact", "--run-id", "r", "--scenarios", pilot_path, "--fake", "--repeats", "1",
                 "--limit", "2", "--condition", "free"])
    main(base + ["judge", "--run-id", "r", "--fake"])
    assert main(base + ["analyze", "--run-id", "r", "--n-boot", "10", "--no-figures"]) == 0
    roles = {j["role"]: j["name"] for j in json.loads((tmp_path / "runs/r/judge.json").read_text(encoding="utf-8"))["judges"]}
    summary = json.loads((tmp_path / "runs/r/report/summary.json").read_text(encoding="utf-8"))
    assert summary["robustness_judges_agree"]["main_judges"] == [roles["first"], roles["second"]]
    assert (tmp_path / "runs/r/report/inflation_rates_judges_agree.csv").exists()
