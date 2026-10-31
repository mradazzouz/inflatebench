"""The preregistered hypothesis tests and the combined analysis across runs, on synthetic runs
with known effects (prereg_synth.py)."""

import json
from dataclasses import replace
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

import prereg_synth as ps
from inflatebench.analyze import analyze_run
from inflatebench.analyze import hypotheses as hy
from inflatebench.analyze import metrics as m
from inflatebench.analyze.combined import ROBUST_AGREE, ROBUST_UNFLAGGED, analyze_runs
from inflatebench.judge.judges import FINAL
from inflatebench.schema import write_jsonl

N_BOOT = 200
HOLM_TESTS = ["H1", "H2a", "H3a-extractor", "H3a-pinning", "H3b-extractor", "H3b-pinning", "H4",
              "H5-sectioned", "H5-extractor", "H5-pinning"]


def pooled(scen, **kw):
    """Labels and probes of two runs (one per model), pooled."""
    labels, probes = [], []
    for k, model in enumerate(ps.MODELS):
        _, lab, pr = ps.run(scen, model, seed=k, **kw)
        labels += lab
        probes += pr
    return labels, probes


def table(scen, labels, probes, **kw):
    return hy.hypothesis_table(m.item_frame(labels, scen), m.probe_frame(probes, scen), n_boot=N_BOOT, **kw)


def verdicts(res):
    return res["table"].set_index("test")["test_verdict"]


@pytest.fixture(scope="module")
def scen():
    return ps.scenarios()


@pytest.fixture(scope="module")
def planted(scen):
    labels, probes = pooled(scen)
    return labels, probes, table(scen, labels, probes)


# --- Pieces ---------------------------------------------------------------------------------

def test_holm_matches_hand_computation():
    p = [0.01, 0.04, 0.03, 0.005, np.nan]
    # Sorted: 0.005*4=0.02, 0.01*3=0.03, 0.03*2=0.06, 0.04*1 -> max(0.06, 0.04)=0.06.
    assert hy.holm(p)[:4] == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert np.isnan(hy.holm(p)[4])
    assert hy.holm([0.5, 0.9]) == pytest.approx([1.0, 1.0])


def test_normal_p_is_two_sided():
    assert hy.normal_p(1.959964) == pytest.approx(0.05, abs=1e-6)
    assert hy.normal_p(-1.959964) == pytest.approx(0.05, abs=1e-6)
    assert hy.normal_p(0) == 1.0
    assert 0 < hy.normal_p(30) < 1e-100  # no underflow to 0 for large z


def test_coefficient_and_contrast_follow_the_preregistered_formulas():
    ref = "C(condition, Treatment(reference='free'))"
    res = pd.DataFrame({"term": ["Intercept", f"{ref}[T.extractor]", f"{ref}[T.sectioned]",
                                 "C(cue, Treatment(reference='explicit'))[T.implicit]", "template"],
                        "effect": ["fixed"] * 4 + ["random_log_sd"],
                        "coef": [-1.0, 0.9, 0.5, 0.7, 0.1], "sd": [0.1, 0.3, 0.4, 0.2, 0.1]})
    one = hy.contrast(res, hy.TESTS[0])  # H1: sectioned coefficient
    assert one["estimate"] == 0.5 and one["z"] == pytest.approx(0.5 / 0.4)
    assert one["p"] == pytest.approx(hy.normal_p(1.25))
    assert one["odds_ratio"] == pytest.approx(np.exp(0.5))
    assert one["or_lo"] == pytest.approx(np.exp(0.5 - 1.96 * 0.4))
    h3b = next(t for t in hy.TESTS if t.test == "H3b-extractor")  # extractor - sectioned
    two = hy.contrast(res, h3b)
    assert two["estimate"] == pytest.approx(0.4)
    assert two["se"] == pytest.approx(sqrt(0.3 ** 2 + 0.4 ** 2))
    assert two["z"] == pytest.approx(0.4 / 0.5)
    h4 = next(t for t in hy.TESTS if t.test == "H4")
    assert hy.contrast(res, h4)["z"] == pytest.approx(3.5)
    assert hy.coefficient(res, "condition", "free") == (0.0, 0.0)  # the reference level
    h2a = next(t for t in hy.TESTS if t.test == "H2a")
    assert "no condition 'sectioned_noconstraints'" in hy.contrast(res, h2a)["note"]
    assert hy.contrast("skipped: no data", h2a)["note"] == "regression items: skipped: no data"


def test_the_holm_family_has_the_ten_preregistered_tests():
    assert [t.test for t in hy.TESTS] == HOLM_TESTS
    fits = {t.test: t.fit for t in hy.TESTS}
    assert {k for k, v in fits.items() if v == "lost"} == {"H3a-extractor", "H3a-pinning"}
    assert fits["H4"] == "promoted" and fits["H1"] == fits["H2a"] == fits["H3b-pinning"] == "items"


# --- Known effects --------------------------------------------------------------------------

def test_planted_effects_support_every_hypothesis(planted):
    _, _, res = planted
    t = res["table"].set_index("test")
    assert set(res["verdicts"].values()) == {hy.SUPPORTED}
    for test in HOLM_TESTS:
        assert t.loc[test, "estimate"] > 0 and t.loc[test, "p_holm"] < 0.05, test
        assert t.loc[test, "z"] == pytest.approx(t.loc[test, "estimate"] / t.loc[test, "se"])
        assert t.loc[test, "rate_diff_lo"] <= t.loc[test, "rate_diff"] <= t.loc[test, "rate_diff_hi"]
        assert t.loc[test, "or_lo"] < t.loc[test, "odds_ratio"] < t.loc[test, "or_hi"]
    # Holm-adjusted p computed over the family of ten.
    assert t.loc[HOLM_TESTS, "p_holm"].to_numpy() == pytest.approx(hy.holm(t.loc[HOLM_TESTS, "p"]))
    # Rate differences recover the planted ones (pooled over models).
    assert t.loc["H1", "rate_diff"] == pytest.approx(ps.INFLATE["sectioned"] - ps.INFLATE["free"], abs=0.05)
    assert t.loc["H3a-extractor", "rate_diff"] == pytest.approx(ps.LOSE["sectioned"] - ps.LOSE["extractor"], abs=0.07)
    assert t.loc["H5-extractor", "rate_diff"] == pytest.approx(ps.BEHAVE["extractor"] - ps.BEHAVE["full"], abs=0.08)
    assert t.loc["H4", "rate_diff"] == pytest.approx(ps.IMPLICIT_BOOST, abs=0.08)
    # free_limited has exactly free's labels: the paired difference is 0 in every draw.
    assert (t.loc["H2b", "rate_diff"], t.loc["H2b", "rate_diff_lo"], t.loc["H2b", "rate_diff_hi"]) == (0, 0, 0)
    assert np.isnan(t.loc["H2b", "p_holm"])  # not in the Holm family
    # H6: two controls x two models x seven conditions, all with no errors.
    h6 = res["table"][res["table"]["hypothesis"] == "H6"]
    assert len(h6) == res["h6_cells"] == 28 and res["h6_failing_cells"] == 0
    assert set(h6["model"]) == set(ps.MODELS) and set(h6["condition"]) == set(ps.CONDITIONS)


def test_model_is_a_fixed_effect_with_template_and_scenario_intercepts(planted):
    _, _, res = planted
    for name in ("items", "lost", "promoted", "behaviour"):
        terms = list(res["fits"][name]["term"])
        assert any(t.startswith("C(model)") for t in terms), name
        assert {"template", "scenario_id"} <= set(terms), name
    assert any("reference='full'" in t for t in res["fits"]["behaviour"]["term"])


def test_per_model_rate_differences(planted):
    _, _, res = planted
    bm = res["by_model"]
    assert set(bm["model"]) == set(ps.MODELS)
    assert set(bm["test"]) == set(HOLM_TESTS) | {"H2b"}
    h2b = bm[bm["test"] == "H2b"]
    assert (h2b["rate_diff"] == 0).all()


def test_direction_must_match(scen):
    # sectioned inflates far less than free: a large, significant effect in the wrong direction.
    inflate = ps.INFLATE | {"sectioned": 0.0, "free": 0.4, "free_limited": 0.4}
    labels, probes = pooled(scen, inflate=inflate)
    res = table(scen, labels, probes)
    h1 = res["table"].set_index("test").loc["H1"]
    assert h1["estimate"] < 0 and h1["p_holm"] < 0.05
    assert h1["test_verdict"] == hy.NOT_SUPPORTED and res["verdicts"]["H1"] == hy.NOT_SUPPORTED


def test_no_effects_support_nothing(scen):
    flat = {c: 0.2 for c in ps.CONDITIONS}
    labels, probes = pooled(scen, inflate=flat, lose=flat, behave=flat | {"full": 0.2}, implicit_boost=0.0)
    res = table(scen, labels, probes)
    v = verdicts(res)
    for test in HOLM_TESTS:
        assert v[test] == hy.NOT_SUPPORTED, test
    for h in ("H1", "H3 (extractor)", "H3 (pinning)", "H4", "H5"):
        assert res["verdicts"][h] == hy.NOT_SUPPORTED


def test_a_model_that_cannot_be_fitted_is_not_tested(scen):
    labels, probes = pooled(scen)
    labels = [replace(l, label="correct") if l.item_id == "o1" else l for l in labels]  # no one-off promoted
    res = table(scen, labels, probes)
    h4 = res["table"].set_index("test").loc["H4"]
    assert h4["test_verdict"] == hy.NOT_TESTED and np.isnan(h4["p_holm"])
    assert h4["note"] == "regression promoted: skipped: outcome has a single value"
    assert res["verdicts"]["H4"] == hy.NOT_TESTED


def test_h2_needs_both_parts(scen):
    # free_limited inflates much more than free: H2a still holds, H2b (equivalence) fails.
    labels, probes = pooled(scen, inflate=ps.INFLATE | {"free_limited": 0.3}, copy_free=False)
    res = table(scen, labels, probes)
    v = verdicts(res)
    assert v["H2a"] == hy.SUPPORTED and v["H2b"] == hy.NOT_SUPPORTED
    assert res["table"].set_index("test").loc["H2b", "rate_diff_lo"] > hy.EQUIVALENCE_MARGIN
    assert res["verdicts"]["H2"] == hy.NOT_SUPPORTED


def test_h3_is_assessed_separately_for_extractor_and_pinning(scen):
    # pinning loses as much as sectioned: H3a fails for pinning only.
    labels, probes = pooled(scen, lose=ps.LOSE | {"pinning": ps.LOSE["sectioned"]})
    res = table(scen, labels, probes)
    v = verdicts(res)
    assert v["H3a-pinning"] == hy.NOT_SUPPORTED and v["H3b-pinning"] == hy.SUPPORTED
    assert res["verdicts"]["H3 (pinning)"] == hy.NOT_SUPPORTED
    assert res["verdicts"]["H3 (extractor)"] == hy.SUPPORTED


def test_h5_needs_all_three_conditions_and_the_full_baseline(scen):
    labels, probes = pooled(scen, behave=ps.BEHAVE | {"pinning": ps.BEHAVE["full"]})
    res = table(scen, labels, probes)
    assert verdicts(res)["H5-pinning"] == hy.NOT_SUPPORTED and verdicts(res)["H5-sectioned"] == hy.SUPPORTED
    assert res["verdicts"]["H5"] == hy.NOT_SUPPORTED
    # Without the full-history baseline H5 cannot be tested.
    no_full = [p for p in probes if p.condition != "full"]
    res = table(scen, labels, no_full)
    assert verdicts(res)["H5-sectioned"] == hy.NOT_TESTED
    assert "reference condition is 'free', not 'full'" in res["table"].set_index("test").loc["H5-sectioned", "note"]
    assert res["verdicts"]["H5"] == hy.NOT_TESTED
    # The untestable tests leave the Holm family; the others are still adjusted over seven.
    t = res["table"].set_index("test")
    seven = HOLM_TESTS[:7]
    assert t.loc[seven, "p_holm"].to_numpy() == pytest.approx(hy.holm(t.loc[seven, "p"]))


def test_h6_fails_cell_by_cell(scen):
    labels, probes = pooled(scen, stale={("m-glm", "pinning"): 0.4})
    res = table(scen, labels, probes)
    h6 = res["table"][res["table"]["hypothesis"] == "H6"]
    failing = h6[h6["test_verdict"] == hy.NOT_SUPPORTED]
    assert res["h6_failing_cells"] == 1
    assert failing[["test", "model", "condition"]].values.tolist() == [["H6-stale", "m-glm", "pinning"]]
    assert failing.iloc[0]["rate_hi"] >= hy.CONTROL_LIMIT
    assert res["verdicts"]["H6"] == hy.NOT_SUPPORTED
    assert (h6.drop(failing.index)["rate_hi"] < hy.CONTROL_LIMIT).all()


# --- Combined analysis ----------------------------------------------------------------------

def write_runs(tmp_path, scen, edit=None):
    scen_path = tmp_path / "scenarios.jsonl"
    write_jsonl(scen_path, scen)
    runs = {}
    for k, model in enumerate(ps.MODELS):
        summaries, labels, probes = ps.run(scen, model, seed=k)
        if edit:
            labels, probes = edit(model, labels, probes)
        d = ps.write_run(tmp_path / "runs", f"main-{model}", scen_path, summaries, labels, probes)
        runs[f"main-{model}"] = (d, scen_path)
    return runs


def robustness_edit(model, labels, probes):
    """In both runs: every inflated sectioned label is flagged (the unflagged check loses H1); the
    second main judge disagrees on every inflated extractor label (the judges-agree check loses
    H3b for extractor). Two probes are truncated and three refused, in the first run only."""
    out = []
    for l in labels:
        inflated = l.label in ps.INFLATED_LABEL.values()
        if l.judge == FINAL and l.condition == "sectioned" and inflated:
            l = replace(l, quote_flagged=True)
        if l.judge == "b" and l.condition == "extractor" and inflated:
            l = replace(l, label="correct")
        out.append(l)
    if model == ps.MODELS[0]:
        sec = [k for k, p in enumerate(probes) if p.condition == "sectioned"]
        for k in sec[:2]:
            probes[k] = replace(probes[k], truncated="max_tokens", inflated=False)
        for k in sec[2:5]:
            probes[k] = replace(probes[k], refusal="text", inflated=False, probe_called=False)
    return out, probes


@pytest.fixture(scope="module")
def combined(tmp_path_factory, scen):
    tmp = tmp_path_factory.mktemp("combined")
    runs = write_runs(tmp, scen, robustness_edit)
    out = tmp / "runs" / "combined" / "report"
    return analyze_runs(runs, out, n_boot=N_BOOT), out


def test_combined_report_has_single_run_tables_and_the_hypotheses(combined):
    summary, out = combined
    for name in ("inflation_rates.csv", "precision_recall.csv", "behaviour.csv", "items.csv",
                 "regression_items.csv", "regression_behaviour.csv", "regression_lost.csv",
                 "regression_promoted.csv", "inflation_rates_unflagged.csv",
                 "inflation_rates_judges_agree.csv", "hypotheses.csv", "hypotheses.md",
                 "hypotheses_by_model.csv", "hypotheses_robustness_unflagged.csv",
                 "hypotheses_robustness_judges_agree.csv", "summary.json"):
        assert (out / name).exists(), name
    assert summary["figures"] == ["behaviour.png", "controls_and_loss.png", "inflation_by_type.png",
                                  "precision_recall.png"]
    assert set(pd.read_csv(out / "inflation_rates.csv")["model"]) == set(ps.MODELS)
    assert summary["runs"]["main-m-haiku"]["models"] == ["m-haiku"]
    on_disk = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert on_disk["hypotheses"]["confirmatory"]["verdicts"] == summary["hypotheses"]["confirmatory"]["verdicts"]
    assert any(t["term"].startswith("C(model)") for t in on_disk["regression"]["items"]["terms"])
    # The judges-agree selection is made within each run, with its own main judges.
    assert on_disk["robustness_judges_agree"]["main_judges"] == {r: ["a", "b"] for r in summary["runs"]}


def test_combined_confirmatory_and_robustness_verdicts(combined):
    summary, out = combined
    conf = pd.read_csv(out / "hypotheses.csv")
    assert set(conf["analysis"]) == {"confirmatory"}
    assert dict(zip(conf["hypothesis"], conf["hypothesis_verdict"]))["H1"] == hy.SUPPORTED
    assert set(summary["hypotheses"]["confirmatory"]["verdicts"].values()) == {hy.SUPPORTED}

    unfl = pd.read_csv(out / "hypotheses_robustness_unflagged.csv").set_index("test")
    assert set(unfl["analysis"]) == {ROBUST_UNFLAGGED}
    # Without the flagged labels sectioned has no inflation left: H1 turns negative.
    assert unfl.loc["H1", "estimate"] < 0 and unfl.loc["H1", "test_verdict"] == hy.NOT_SUPPORTED
    agree = pd.read_csv(out / "hypotheses_robustness_judges_agree.csv").set_index("test")
    assert set(agree["analysis"]) == {ROBUST_AGREE}
    assert agree.loc["H3b-extractor", "test_verdict"] == hy.NOT_SUPPORTED
    assert agree.loc["H3b-pinning", "test_verdict"] == hy.SUPPORTED
    # H5 rests on the probes, so it is the same in every analysis.
    conf = conf.set_index("test")
    for t in ("H5-sectioned", "H5-extractor", "H5-pinning"):
        assert unfl.loc[t, "z"] == pytest.approx(conf.loc[t, "z"]) == pytest.approx(agree.loc[t, "z"])
    md = (out / "hypotheses.md").read_text(encoding="utf-8")
    assert "## Confirmatory analysis" in md
    assert "## Robustness: unflagged labels" in md and "## Robustness: judges agree" in md
    assert md.count("**Robustness analysis, not confirmatory.**") == 2


def test_combined_behaviour_table_counts_truncated_and_refused(combined):
    _, out = combined
    beh = pd.read_csv(out / "behaviour.csv").set_index(["condition", "model"])
    row = beh.loc[("sectioned", "m-haiku")]
    assert (row["probes"], row["truncated"], row["completed"], row["refused"]) == (96, 2, 94, 3)
    assert row["den"] == 94  # truncated probes leave the rate's denominator
    other = beh.loc[("sectioned", "m-glm")]
    assert (other["truncated"], other["refused"]) == (0, 0)
    assert (beh["probes"] == beh["truncated"] + beh["completed"]).all()
    md = (out / "hypotheses.md").read_text(encoding="utf-8")
    assert "| m-haiku | sectioned | 96 | 2 | 94 | 3 |" in md


def test_single_run_analysis_is_unchanged(tmp_path, scen):
    runs = write_runs(tmp_path, scen[:12])
    run_dir, scen_path = runs["main-m-haiku"]
    summary = analyze_run(run_dir, scen_path, n_boot=20, figures=False)
    report = run_dir / "report"
    assert not list(report.glob("hypotheses*"))
    assert "hypotheses" not in summary and "runs" not in summary
    assert not {"probes", "refused", "completed"} & set(pd.read_csv(report / "behaviour.csv").columns)
    assert not (report / "regression_lost.csv").exists()
    assert summary["robustness_judges_agree"]["main_judges"] == ["a", "b"]


def test_combined_refuses_runs_it_cannot_pool(tmp_path, scen):
    small = scen[:6]
    runs = write_runs(tmp_path, small)
    one = dict(list(runs.items())[:1])
    with pytest.raises(ValueError, match="at least two runs"):
        analyze_runs(one, tmp_path / "out", n_boot=10)
    # Same model in both runs.
    same = write_runs(tmp_path / "same", small, lambda model, l, p: (
        [replace(x, model="m") for x in l], [replace(x, model="m") for x in p]))
    # Coverage still holds per run only when summaries agree; rewrite them with the model too.
    for d, _ in same.values():
        from inflatebench.schema import Summary, read_jsonl
        write_jsonl(d / "summaries.jsonl", [replace(s, model="m") for s in read_jsonl(d / "summaries.jsonl", Summary)])
    with pytest.raises(ValueError, match="share model 'm'"):
        analyze_runs(same, tmp_path / "out", n_boot=10)
    # Probes in one run only.
    (runs["main-m-glm"][0] / "probes.jsonl").unlink()
    with pytest.raises(ValueError, match="probe every run or none"):
        analyze_runs(runs, tmp_path / "out", n_boot=10)


def test_cli_combined_analysis(tmp_path, scen, capsys):
    from inflatebench.cli import main

    write_runs(tmp_path, scen[:24])
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    cfg["paths"].update(runs=str(tmp_path / "runs"), cache=str(tmp_path / "cache"))
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    base = ["--config", str(path), "analyze"]
    assert main(base + ["--runs", "main-m-haiku", "main-m-glm", "--out-id", "combined",
                        "--n-boot", "20", "--no-figures"]) == 0
    report = tmp_path / "runs" / "combined" / "report"
    assert (report / "hypotheses.csv").exists() and (report / "hypotheses.md").exists()
    assert "hypotheses: H1 " in capsys.readouterr().out
    for args, msg in ((["--runs", "main-m-haiku", "main-m-glm"], "needs --out-id"),
                      (["--runs", "main-m-haiku", "--out-id", "c"], "at least two"),
                      (["--runs", "main-m-haiku", "main-m-glm", "--out-id", "main-m-glm"], "must not be one of"),
                      (["--runs", "main-m-haiku", "nope", "--out-id", "c"], "run the earlier stages first"),
                      (["--run-id", "main-m-haiku", "--runs", "main-m-haiku", "main-m-glm", "--out-id", "c"],
                       "not both"),
                      (["--run-id", "main-m-haiku", "--out-id", "c"], "goes with --runs"),
                      ([], "pass --run-id")):
        with pytest.raises(SystemExit, match=msg):
            main(base + args)
