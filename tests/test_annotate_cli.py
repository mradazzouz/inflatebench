"""ib annotate sample | check and ib judge --only-key: the preregistered human check from the
command line. Every path is built with pathlib under tmp_path, so the tests run the same on
Windows."""

import json
from collections import Counter
from pathlib import Path

import pytest
import yaml

from inflatebench.cli import main
from inflatebench.judge import FINAL
from inflatebench.judge.run import read_rows, write_rows
from inflatebench.schema import LABELS, Label, Summary, read_jsonl, write_jsonl

FIXTURES = Path(__file__).parent / "fixtures"
RUNS = {"main-haiku": "model-a", "main-glm": "model-b"}


@pytest.fixture
def setup(tmp_path, summaries):
    """A config under tmp_path and two runs (one model each) over the fixture scenarios."""
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cfg["paths"] |= {"runs": str(tmp_path / "runs"), "cache": str(tmp_path / "cache")}
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    texts = [s.messages for s in summaries]
    scenario_ids = [json.loads(line)["id"]
                    for line in (FIXTURES / "scenarios.jsonl").read_text(encoding="utf-8").splitlines()]
    for run_id, model in RUNS.items():
        run_dir = tmp_path / "runs" / run_id
        run_dir.mkdir(parents=True)
        write_jsonl(run_dir / "summaries.jsonl",
                    [Summary(sid, cond, model, rep, texts[k % len(texts)])
                     for k, (sid, cond, rep) in enumerate((sid, cond, rep) for sid in scenario_ids
                                                          for cond in ("free", "sectioned")
                                                          for rep in range(2))])
        (run_dir / "run.json").write_text(json.dumps({"scenarios": str(FIXTURES / "scenarios.jsonl")}),
                                          encoding="utf-8")
    return tmp_path, config


def _sample(tmp_path, config, *extra, n=24, seed=7):
    out, key = tmp_path / "annotation" / "sample.jsonl", tmp_path / "annotation" / "sample_key.jsonl"
    code = main(["--config", str(config), "annotate", "sample", "--runs", *RUNS, "--n", str(n),
                 "--seed", str(seed), "--out", str(out), "--key", str(key), *extra])
    assert code == 0
    return out, key


def test_sample_is_blind_split_over_models_and_refuses_to_overwrite(setup, capsys):
    tmp_path, config = setup
    out, key = _sample(tmp_path, config)
    assert str(out) in capsys.readouterr().out
    sample, key_rows = read_rows(out), read_rows(key)
    assert len(sample) == len(key_rows) == 24
    assert [r["uid"] for r in sample] == [r["uid"] for r in key_rows]
    assert not any({"condition", "model", "run_id", "repeat"} & set(r) for r in sample)
    assert Counter(r["model"] for r in key_rows) == {"model-a": 12, "model-b": 12}
    assert {(r["run_id"], r["model"]) for r in key_rows} == set(RUNS.items())
    # Within a model, every item type x condition stratum gets the same share.
    per_stratum = Counter(r["stratum"] for r in key_rows)
    assert set(per_stratum.values()) == {1, 2} and len(per_stratum) == 2 * 5 * 2

    with pytest.raises(SystemExit, match="already exist.*--force"):
        _sample(tmp_path, config, seed=8)
    assert read_rows(key) == key_rows  # left alone
    _sample(tmp_path, config, "--force")  # same seed, same draw
    assert read_rows(key) == key_rows and read_rows(out) == sample


def test_sample_defaults_to_the_annotation_folder(setup, monkeypatch):
    tmp_path, config = setup
    monkeypatch.chdir(tmp_path)
    assert main(["--config", str(config), "annotate", "sample", "--runs", *RUNS, "--n", "10",
                 "--seed", "0"]) == 0
    assert len(read_rows(Path("annotation") / "sample.jsonl")) == 10
    assert len(read_rows(Path("annotation") / "sample_key.jsonl")) == 10


def test_sample_needs_a_seed_and_existing_runs(setup):
    tmp_path, config = setup
    with pytest.raises(SystemExit):
        main(["--config", str(config), "annotate", "sample", "--runs", *RUNS])
    with pytest.raises(SystemExit, match="run the earlier stages first"):
        main(["--config", str(config), "annotate", "sample", "--runs", "nope", "--seed", "0",
              "--out", str(tmp_path / "s.jsonl"), "--key", str(tmp_path / "k.jsonl")])


def _judge_sample(tmp_path, config, key):
    for run_id in RUNS:
        assert main(["--config", str(config), "judge", "--run-id", run_id, "--fake",
                     "--only-key", str(key)]) == 0


def test_judge_only_key_writes_a_separate_file_and_warms_the_cache(setup, capsys):
    tmp_path, config = setup
    _, key = _sample(tmp_path, config, n=6)
    _judge_sample(tmp_path, config, key)
    run_dir = tmp_path / "runs" / "main-haiku"
    assert not (run_dir / "labels.jsonl").exists() and not (run_dir / "judge.json").exists()
    assert (run_dir / "judge_sample.json").exists() and (run_dir / "judge_calls_sample.jsonl").exists()
    wanted = {(r["scenario_id"], r["condition"], r["model"], r["repeat"])
              for r in read_rows(key) if r["run_id"] == "main-haiku"}
    judged = {(l.scenario_id, l.condition, l.model, l.repeat)
              for l in read_jsonl(run_dir / "labels_sample.jsonl", Label)}
    assert judged == wanted
    sampled_calls = len(read_rows(run_dir / "judge_calls_sample.jsonl"))
    capsys.readouterr()

    # The full run afterwards labels every summary and answers the sampled ones from the cache.
    assert main(["--config", str(config), "judge", "--run-id", "main-haiku", "--fake"]) == 0
    assert f"{sampled_calls} from cache" in capsys.readouterr().out
    assert len({(l.scenario_id, l.condition, l.repeat)
                for l in read_jsonl(run_dir / "labels.jsonl", Label)}) == 16
    assert {(l.scenario_id, l.condition, l.model, l.repeat)
            for l in read_jsonl(run_dir / "labels_sample.jsonl", Label)} == wanted


def test_judge_only_key_with_no_matching_summary(setup):
    tmp_path, config = setup
    key = tmp_path / "other_key.jsonl"
    write_rows(key, [{"uid": "u0000", "scenario_id": "pilot-01", "condition": "free", "model": "x",
                      "repeat": 0, "item_id": "i1", "weight": 1.0, "run_id": "main-haiku"}])
    with pytest.raises(SystemExit, match="no summary of run 'main-haiku'"):
        main(["--config", str(config), "judge", "--run-id", "main-haiku", "--fake", "--only-key", str(key)])
    with pytest.raises(SystemExit, match="not found"):
        main(["--config", str(config), "judge", "--run-id", "main-haiku", "--fake",
              "--only-key", str(tmp_path / "missing.jsonl")])


def _final_labels(tmp_path):
    out = {}
    for run_id in RUNS:
        for lab in read_jsonl(tmp_path / "runs" / run_id / "labels_sample.jsonl", Label):
            if lab.judge == FINAL and lab.item_id:
                out[(lab.scenario_id, lab.condition, lab.model, lab.repeat, lab.item_id)] = lab.label
    return out


def _human_file(path, key, annotator, label_for):
    write_rows(path, [{"uid": r["uid"], "annotator": annotator, "quote": "",
                       "label": label_for((r["scenario_id"], r["condition"], r["model"], r["repeat"],
                                           r["item_id"]))}
                      for r in read_rows(key)])
    return path


def test_check_reports_both_blocks_and_passes_the_gate(setup, capsys):
    tmp_path, config = setup
    _, key = _sample(tmp_path, config)
    _judge_sample(tmp_path, config, key)
    final = _final_labels(tmp_path)
    ana = _human_file(tmp_path / "sample.labels.ana.jsonl", key, "ana", final.get)
    keys = sorted((r["scenario_id"], r["condition"], r["model"], r["repeat"], r["item_id"])
                  for r in read_rows(key))
    flip = set(keys[:2])  # bo disagrees with the judge on two items
    bo = _human_file(tmp_path / "sample.labels.bo.jsonl", key, "bo",
                     lambda k: "correct" if k in flip and final[k] != "correct" else
                     "lost" if k in flip else final[k])
    capsys.readouterr()
    code = main(["--config", str(config), "annotate", "check", "--key", str(key),
                 "--labels", str(ana), str(bo), "--runs", *RUNS])
    printed = capsys.readouterr().out
    result = json.loads((key.parent / "check.json").read_text(encoding="utf-8"))
    assert code == 0 and "GATE PASSED" in printed
    assert "unweighted_sample" in printed and "weighted_population" in printed
    assert result["passes"] and result["gate"] == 0.7 and result["gate_on"] == "unweighted_sample"
    assert set(result["human_vs_judge"]) == {"human:ana", "human:bo"}
    assert set(result["humans"]) == {"human:ana vs human:bo"}
    hj = result["human_vs_judge"]["human:ana"]
    assert hj["n"] == 24 and hj["unweighted_sample"]["kappa"] == 1.0
    assert hj["weighted_population"]["kappa"] == 1.0
    assert set(hj["unweighted_sample"]["per_label_kappa"]) <= set(LABELS)
    assert result["human_vs_judge"]["human:bo"]["unweighted_sample"]["agreement"] == pytest.approx(22 / 24)
    assert result["labelled"] == {"human:ana": 24, "human:bo": 24}
    # Runs default to those the key names.
    out = tmp_path / "elsewhere" / "check.json"
    assert main(["--config", str(config), "annotate", "check", "--key", str(key), "--labels", str(ana),
                 "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["runs"] == sorted(RUNS)


def test_check_fails_the_gate_clearly(setup, capsys):
    tmp_path, config = setup
    _, key = _sample(tmp_path, config)
    _judge_sample(tmp_path, config, key)
    final = _final_labels(tmp_path)
    # Always the label the judge did not give, among those the fake judge uses.
    contrary = _human_file(tmp_path / "x.jsonl", key, "cy",
                           lambda k: "lost" if final[k] == "correct" else "correct")
    capsys.readouterr()
    code = main(["--config", str(config), "annotate", "check", "--key", str(key),
                 "--labels", str(contrary), "--runs", *RUNS])
    printed = capsys.readouterr().out
    assert code == 1 and "GATE FAILED" in printed
    assert json.loads((key.parent / "check.json").read_text(encoding="utf-8"))["passes"] is False


def test_check_needs_judge_labels_for_every_sampled_item(setup):
    tmp_path, config = setup
    _, key = _sample(tmp_path, config)
    labels = _human_file(tmp_path / "h.jsonl", key, "ana", lambda k: "correct")
    with pytest.raises(SystemExit, match="no judge labels"):
        main(["--config", str(config), "annotate", "check", "--key", str(key), "--labels", str(labels)])
    main(["--config", str(config), "judge", "--run-id", "main-haiku", "--fake", "--only-key", str(key)])
    with pytest.raises(SystemExit, match="no judge labels"):
        main(["--config", str(config), "annotate", "check", "--key", str(key), "--labels", str(labels)])
    # Judge labels present but only for one run's items.
    other = tmp_path / "runs" / "main-glm" / "labels_sample.jsonl"
    write_jsonl(other, [])
    with pytest.raises(SystemExit, match=r"12 of 24 sampled items have no judge label"):
        main(["--config", str(config), "annotate", "check", "--key", str(key), "--labels", str(labels)])


def test_check_rejects_labels_from_another_sample(setup):
    tmp_path, config = setup
    _, key = _sample(tmp_path, config)
    _judge_sample(tmp_path, config, key)
    stray = tmp_path / "stray.jsonl"
    write_rows(stray, [{"uid": "u9999", "annotator": "ana", "label": "correct", "quote": ""}])
    with pytest.raises(SystemExit, match="u9999.*not in"):
        main(["--config", str(config), "annotate", "check", "--key", str(key), "--labels", str(stray)])


def _keys(rows):
    return {(r["scenario_id"], r["condition"], r["model"], r["repeat"], r["item_id"]) for r in rows}


def test_sample_exclude_key_draws_fresh_items_with_new_uids(setup, capsys):
    tmp_path, config = setup
    _, key = _sample(tmp_path, config, n=24)
    out2, key2 = tmp_path / "annotation" / "sample_v2.jsonl", tmp_path / "annotation" / "sample_key_v2.jsonl"
    capsys.readouterr()
    assert main(["--config", str(config), "annotate", "sample", "--runs", *RUNS, "--n", "24", "--seed", "8",
                 "--out", str(out2), "--key", str(key2), "--exclude-key", str(key)]) == 0
    assert f"left out the 24 (summary, item) pairs of {key}" in capsys.readouterr().out
    first, second = read_rows(key), read_rows(key2)
    assert len(second) == 24 and not _keys(first) & _keys(second)
    assert [r["uid"] for r in second] == [f"u{k:04d}" for k in range(24, 48)]
    assert [r["uid"] for r in read_rows(out2)] == [r["uid"] for r in second]
    # Weights still count the excluded pairs: weight x pairs drawn is the stratum's whole pool
    # in both samples.
    def pool(rows):
        drawn = Counter(r["stratum"] for r in rows)
        return {r["stratum"]: r["weight"] * drawn[r["stratum"]] for r in rows}

    shared = pool(first).keys() & pool(second).keys()
    assert shared and all(pool(first)[s] == pytest.approx(pool(second)[s]) for s in shared)

    # Labels saved for the first sample cannot be joined to the second key.
    labels = _human_file(tmp_path / "h.jsonl", key, "ana", lambda k: "correct")
    _judge_sample(tmp_path, config, key2)
    with pytest.raises(SystemExit, match="u0000.*not in"):
        main(["--config", str(config), "annotate", "check", "--key", str(key2), "--labels", str(labels)])

    # A third sample may exclude both; everything left is drawn.
    out3, key3 = tmp_path / "s3.jsonl", tmp_path / "k3.jsonl"
    assert main(["--config", str(config), "annotate", "sample", "--runs", *RUNS, "--n", "500", "--seed", "9",
                 "--out", str(out3), "--key", str(key3), "--exclude-key", str(key),
                 "--exclude-key", str(key2)]) == 0
    third = read_rows(key3)
    assert not _keys(third) & (_keys(first) | _keys(second))
    assert third[0]["uid"] >= "u0048" and min(r["uid"] for r in third) == "u0048"


def test_sample_exclude_key_must_exist_and_differ_from_the_outputs(setup):
    tmp_path, config = setup
    _, key = _sample(tmp_path, config, n=6)
    base = ["--config", str(config), "annotate", "sample", "--runs", *RUNS, "--n", "6", "--seed", "1"]
    with pytest.raises(SystemExit, match="--exclude-key .* not found"):
        main(base + ["--out", str(tmp_path / "s.jsonl"), "--key", str(tmp_path / "k.jsonl"),
                     "--exclude-key", str(tmp_path / "missing.jsonl")])
    with pytest.raises(SystemExit, match="also an output file"):
        main(base + ["--out", str(tmp_path / "s.jsonl"), "--key", str(key), "--force",
                     "--exclude-key", str(key)])


def test_judge_only_key_out_keeps_the_first_sample_labels(setup, capsys):
    tmp_path, config = setup
    _, key = _sample(tmp_path, config, n=6)
    _judge_sample(tmp_path, config, key)
    run_dir = tmp_path / "runs" / "main-haiku"
    before = (run_dir / "labels_sample.jsonl").read_text(encoding="utf-8")
    out2, key2 = tmp_path / "s2.jsonl", tmp_path / "k2.jsonl"
    assert main(["--config", str(config), "annotate", "sample", "--runs", *RUNS, "--n", "6", "--seed", "2",
                 "--out", str(out2), "--key", str(key2), "--exclude-key", str(key)]) == 0
    capsys.readouterr()
    assert main(["--config", str(config), "judge", "--run-id", "main-haiku", "--fake",
                 "--only-key", str(key2), "--out", "labels_sample_v2.jsonl"]) == 0
    assert str(run_dir / "labels_sample_v2.jsonl") in capsys.readouterr().out
    assert (run_dir / "labels_sample.jsonl").read_text(encoding="utf-8") == before
    assert (run_dir / "judge_calls_sample_v2.jsonl").exists()
    info = json.loads((run_dir / "judge_sample_v2.json").read_text(encoding="utf-8"))
    assert info["labels"] == "labels_sample_v2.jsonl" and info["only_key"] == str(key2)
    wanted = {(r["scenario_id"], r["condition"], r["model"], r["repeat"])
              for r in read_rows(key2) if r["run_id"] == "main-haiku"}
    assert {(l.scenario_id, l.condition, l.model, l.repeat)
            for l in read_jsonl(run_dir / "labels_sample_v2.jsonl", Label)} == wanted


@pytest.mark.parametrize("args, match", [
    (["--out", "labels_v2.jsonl"], "--out needs --only-key"),
    (["--only-key", "KEY", "--out", "labels.jsonl"], "must be a file name like"),
    (["--only-key", "KEY", "--out", "sub/labels_v2.jsonl"], "must be a file name like"),
    (["--only-key", "KEY", "--out", "labels_v2.json"], "must be a file name like"),
])
def test_judge_out_is_checked(setup, args, match):
    tmp_path, config = setup
    _, key = _sample(tmp_path, config, n=6)
    args = [str(key) if a == "KEY" else a for a in args]
    with pytest.raises(SystemExit, match=match):
        main(["--config", str(config), "judge", "--run-id", "main-haiku", "--fake", *args])
    assert not list((tmp_path / "runs" / "main-haiku").glob("labels*.jsonl"))


def test_check_uses_the_named_judge_label_files(setup, capsys):
    tmp_path, config = setup
    _, key = _sample(tmp_path, config, n=12)
    _judge_sample(tmp_path, config, key)
    out2, key2 = tmp_path / "s2.jsonl", tmp_path / "k2.jsonl"
    assert main(["--config", str(config), "annotate", "sample", "--runs", *RUNS, "--n", "12", "--seed", "3",
                 "--out", str(out2), "--key", str(key2), "--exclude-key", str(key)]) == 0
    for run_id in RUNS:
        assert main(["--config", str(config), "judge", "--run-id", run_id, "--fake", "--only-key", str(key2),
                     "--out", "labels_sample_v2.jsonl"]) == 0
    final = {}
    for run_id in RUNS:
        for lab in read_jsonl(tmp_path / "runs" / run_id / "labels_sample_v2.jsonl", Label):
            if lab.judge == FINAL and lab.item_id:
                final[(lab.scenario_id, lab.condition, lab.model, lab.repeat, lab.item_id)] = lab.label
    labels = _human_file(tmp_path / "v2.ana.jsonl", key2, "ana", final.get)
    check = ["--config", str(config), "annotate", "check", "--key", str(key2), "--labels", str(labels)]
    # The default looks in labels_sample.jsonl, which holds the first sample only.
    with pytest.raises(SystemExit, match="sampled items have no judge label"):
        main(check)
    capsys.readouterr()
    assert main(check + ["--judge-labels", "labels_sample_v2.jsonl"]) == 0
    assert "GATE PASSED" in capsys.readouterr().out
    # The result is named after the key (k2.jsonl), so check.json of a first check is kept.
    result = json.loads((key2.parent / "check_k2.json").read_text(encoding="utf-8"))
    assert result["judge_labels"] == {r: str(tmp_path / "runs" / r / "labels_sample_v2.jsonl") for r in RUNS}
    # First found wins; a missing name is skipped.
    assert main(check + ["--judge-labels", "labels_nope.jsonl", "labels_sample_v2.jsonl"]) == 0
    with pytest.raises(SystemExit, match=r"no judge labels \(labels_nope.jsonl\)"):
        main(check + ["--judge-labels", "labels_nope.jsonl"])
    with pytest.raises(SystemExit, match="not paths"):
        main(check + ["--judge-labels", str(tmp_path / "runs" / "main-haiku" / "labels_sample_v2.jsonl")])


@pytest.mark.parametrize("key, check", [("sample_key.jsonl", "check.json"),
                                        ("sample_key_v2.jsonl", "check_v2.json"),
                                        ("k2.jsonl", "check_k2.json")])
def test_check_result_is_named_after_the_key(key, check):
    from inflatebench.cli import _check_path

    assert _check_path(Path("annotation") / key) == Path("annotation") / check
