import json
from pathlib import Path

import pytest
import yaml

from inflatebench.cli import _fake_agent_responder, _fake_judge_responder, main
from inflatebench.generate.tools import TOOLS
from inflatebench.judge.rubric import build_prompt
from inflatebench.models import FakeLLM
from inflatebench.probe import (
    DOMAIN_TOOLS,
    FULL,
    call_inflated,
    call_tool,
    inflated,
    matches,
    parse_calls,
    probe_full,
    probe_run,
    probe_summary,
    resolve,
    run_agent,
    tools_for,
)
from inflatebench.schema import Message, Probe, ProbeResult, Scenario, Summary, read_jsonl, write_jsonl

PILOT = Path(__file__).parent.parent / "data" / "pilot.jsonl"


@pytest.fixture(scope="module")
def pilot_all() -> list[Scenario]:
    return list(read_jsonl(PILOT, Scenario))


def build(path: str, value):
    """The smallest call whose value at a dotted path is `value`."""
    parts = path.split(".")
    for part in reversed(parts[1:]):
        if part.isdigit():
            value = [{}] * int(part) + [value]
        else:
            value = {part: value}
    return {parts[0]: value}


def merge(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return {k: merge(a[k], b[k]) if k in a and k in b else a.get(k, b.get(k)) for k in a | b}
    return b


def inflated_call(probe: Probe) -> dict:
    call = {"tool": probe.tool}
    for path, exp in probe.inflated_if.items():
        value = f"Text with {exp['contains']} in it" if isinstance(exp, dict) else exp
        call = merge(call, build(path, value))
    return call


def agent(*replies: str) -> FakeLLM:
    return FakeLLM(list(replies))


# --- mock tools -----------------------------------------------------------------------------


def test_domain_tools_cover_every_mock_tool_once():
    listed = [t for names in DOMAIN_TOOLS.values() for t in names]
    assert sorted(listed) == sorted(TOOLS)


def test_every_generated_probe_tool_belongs_to_its_domain():
    from inflatebench.generate import generate

    for s in generate(240, 0):
        assert s.probe.tool in DOMAIN_TOOLS[s.domain], s.id


def test_every_pilot_probe_tool_is_offered(pilot_all):
    for s in pilot_all:
        tools = tools_for(s)
        assert s.probe.tool in tools
        assert set(DOMAIN_TOOLS[s.domain]) <= set(tools)


def test_call_tool_validates_name_and_arguments():
    allowed = ["restart_worker", "deploy"]
    assert call_tool("restart_worker", {"name": "w", "force": True}, allowed)["ok"]
    assert "unknown tool" in call_tool("send_email", {}, allowed)["error"]
    assert "no argument" in call_tool("deploy", {"colour": "red"}, allowed)["error"]
    assert "JSON object" in call_tool("deploy", ["x"], allowed)["error"]


# --- checks ---------------------------------------------------------------------------------


def test_resolve_follows_dicts_and_list_indices():
    call = {"tool": "save_itinerary", "args": {"days": [{"hotel": "A"}, {"hotel": "B"}]}}
    assert resolve(call, "args.days.1.hotel") == "B"
    assert not matches(resolve(call, "args.days.5.hotel"), "B")
    assert not matches(resolve(call, "args.missing"), None)


def test_matches_rules():
    assert matches(True, True) and not matches(1, True) and not matches(False, True)
    assert matches(6, 6) and not matches(True, 1)
    assert matches(["a", "dark"], "dark") and not matches(["a"], "dark")
    assert matches("CC: laura@x.com", {"contains": "Laura"})
    assert matches(["bob", "Laura Smith"], {"contains": "laura"})
    assert not matches(["bob"], {"contains": "laura"}) and not matches(3, {"contains": "3"})


def test_every_probe_fires_only_on_its_inflated_call(pilot_all):
    from inflatebench.generate import Paraphraser, generate

    for s in pilot_all + generate(60, 0, Paraphraser(None)):
        call = inflated_call(s.probe)
        assert call_tool(call["tool"], call["args"], tools_for(s))["ok"], s.id
        assert call_inflated(call, s.probe), s.id
        assert not call_inflated({"tool": s.probe.tool, "args": {}}, s.probe), s.id
        assert not call_inflated(call | {"tool": "other_tool"}, s.probe), s.id


def test_all_paths_must_match():
    probe = Probe("deploy", {"args.canary": False, "args.env": "production"})
    assert inflated([{"tool": "deploy", "args": {"canary": False, "env": "production"}}], probe)
    assert not inflated([{"tool": "deploy", "args": {"canary": False, "env": "staging"}}], probe)
    assert inflated([{"tool": "deploy", "args": {}},
                     {"tool": "deploy", "args": {"canary": False, "env": "production"}}], probe)


# --- agent loop -----------------------------------------------------------------------------


def test_parse_calls_reads_every_tool_object():
    text = ('First I commit.\n```json\n{"tool": "git_commit", "args": {"message": "x {y}"}}\n```\n'
            'Then {not json} and {"note": 1} and {"tool": "run_tests"}')
    assert parse_calls(text) == [("git_commit", {"message": "x {y}"}), ("run_tests", {})]
    assert parse_calls("All done.") == []


def test_run_agent_feeds_context_task_and_results(pilot_all):
    scen = next(s for s in pilot_all if s.id == "pilot-B")
    context = [Message("system", "Summary: restart workers with --force.")]
    llm = agent('{"tool": "restart_worker", "args": {"name": "w1", "force": true, "bogus": 1}}',
                '{"tool": "restart_worker", "args": {"name": "w1", "force": true}}', "Restarted.")
    episode = run_agent(llm, scen, context)
    first = llm.calls[0]
    assert first[0].role == "system" and "restart_worker(" in first[0].content
    assert first[1] == context[0] and first[-1] == Message("user", scen.next_task)
    assert "no argument" in llm.calls[1][-1].content and llm.calls[1][-1].role == "tool"
    assert episode.steps == 3 and episode.final == "Restarted."
    assert "error" in episode.calls[0] and "error" not in episode.calls[1]
    assert inflated(episode.calls, scen.probe)


def test_run_agent_stops_at_max_steps(pilot_all):
    llm = agent('{"tool": "git_commit", "args": {}}')
    episode = run_agent(llm, pilot_all[0], [], max_steps=3)
    assert episode.steps == 3 and len(episode.calls) == 3


def test_probe_summary_records_result(pilot_all):
    scen = pilot_all[0]  # git_commit, args.skip_tests
    summary = Summary(scen.id, "pinning", "m", 2, [Message("system", "Skip tests on commit.")])
    res = probe_summary(agent('{"tool": "git_commit", "args": {"skip_tests": true}}', "ok"),
                        scen, summary, agent_name="a")
    assert (res.condition, res.model, res.repeat, res.agent) == ("pinning", "m", 2, "a")
    assert res.inflated and res.probe_called
    clean = probe_summary(agent('{"tool": "run_tests", "args": {}}', "ok"), scen, summary)
    assert not clean.inflated and not clean.probe_called
    assert ProbeResult.from_dict(json.loads(res.to_json())) == res


def test_probe_run_writes_one_result_per_summary(tmp_path, pilot_all):
    write_jsonl(tmp_path / "s.jsonl", pilot_all[:2])
    run = tmp_path / "run"
    write_jsonl(run / "summaries.jsonl",
                [Summary(s.id, c, "m", 0, [Message("system", "x")]) for s in pilot_all[:2]
                 for c in ("free", "pinning")])
    out = probe_run(FakeLLM(_fake_agent_responder), tmp_path / "s.jsonl", run)
    results = list(read_jsonl(out, ProbeResult))
    # One per summary, plus one full-history baseline per scenario, model and repeat.
    assert len(results) == 4 + 2 and all(r.probe_called and not r.inflated for r in results)
    assert sorted((r.scenario_id, r.condition) for r in results if r.condition == FULL) == [
        (s.id, FULL) for s in pilot_all[:2]]
    out = probe_run(FakeLLM(_fake_agent_responder), tmp_path / "s.jsonl", run, full=False)
    assert len(list(read_jsonl(out, ProbeResult))) == 4


def test_full_history_baseline_shows_the_agent_the_whole_history(pilot_all):
    scen = next(s for s in pilot_all if s.id == "pilot-B")
    llm = agent('{"tool": "restart_worker", "args": {"name": "w1", "force": true}}', "Restarted.")
    res = probe_full(llm, scen, "m", 1, agent_name="a")
    sent = llm.calls[0]
    assert sent[1:-1] == scen.history and sent[-1] == Message("user", scen.next_task)
    assert (res.condition, res.model, res.repeat, res.agent) == (FULL, "m", 1, "a") and res.inflated
    # Same system prompt as for a compacted context: only the context differs.
    other = agent("Done.")
    probe_summary(other, scen, Summary(scen.id, "free", "m", 1, [Message("system", "x")]))
    assert other.calls[0][0] == sent[0]
    assert "either in full or compacted" in sent[0].content


# --- fakes and CLI --------------------------------------------------------------------------


def test_fake_judge_labels_kept_and_lost_items(pilot_all):
    scen = pilot_all[0]
    hard = next(i for i in scen.items if i.type == "hard_rule")
    reply = json.loads(_fake_judge_responder(build_prompt(scen, f"Rules: {hard.text}")))
    labels = {r["item_id"]: r["label"] for r in reply["items"]}
    assert labels[hard.id] == "correct"
    assert labels["c1"] == "lost" and labels["o1"] == "correct"


def pipeline_config(tmp_path) -> str:
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["paths"].update(scenarios=str(tmp_path / "missing.jsonl"), runs=str(tmp_path / "runs"),
                        cache=str(tmp_path / "cache"))
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return str(path)


def test_cli_full_pipeline_with_fakes(tmp_path):
    cfg = pipeline_config(tmp_path)
    base = ["--config", cfg]
    run = tmp_path / "runs" / "e2e"
    assert main(base + ["compact", "--run-id", "e2e", "--scenarios", str(PILOT), "--fake",
                        "--repeats", "1", "--limit", "5"]) == 0
    assert json.loads((run / "run.json").read_text())["scenarios"] == str(PILOT)
    # judge, probe and analyze find the scenarios through run.json
    assert main(base + ["judge", "--run-id", "e2e", "--fake"]) == 0
    assert main(base + ["probe", "--run-id", "e2e", "--fake"]) == 0
    assert main(base + ["analyze", "--run-id", "e2e", "--n-boot", "50", "--no-figures"]) == 0
    probes = list(read_jsonl(run / "probes.jsonl", ProbeResult))
    n_cond = len(yaml.safe_load(open("config.yaml"))["conditions"])
    assert len(probes) == 5 * n_cond + 5 and all(p.probe_called for p in probes)
    summary = json.loads((run / "report/summary.json").read_text())
    assert summary["n_scenarios"] == 5 and "behaviour" in summary
    beh = {r["condition"]: r for r in summary["behaviour"]}
    assert "full" in beh and all(r["induced"] == r["rate"] - beh["full"]["rate"]
                                 for c, r in beh.items() if c != "full")
    assert (run / "judge_calls.jsonl").exists() and (run / "probe_calls.jsonl").exists()


def test_cli_stages_log_models_settings_dates_and_costs(tmp_path):
    cfg = pipeline_config(tmp_path)
    base = ["--config", cfg]
    run = tmp_path / "runs" / "meta"
    main(base + ["compact", "--run-id", "meta", "--scenarios", str(PILOT), "--fake",
                 "--repeats", "1", "--limit", "2", "--condition", "free"])
    main(base + ["judge", "--run-id", "meta", "--fake"])
    main(base + ["probe", "--run-id", "meta", "--fake", "--max-steps", "3"])
    info = json.loads((run / "run.json").read_text())
    assert info["date"] and info["settings"] == {"provider": "fake", "model": "fake"}
    assert info["calls"] == 2 and info["cost"] == 0.0 and info["batch"] is True
    judge = json.loads((run / "judge.json").read_text())
    assert [j["role"] for j in judge["judges"]] == ["first", "second", "tiebreak"]
    assert all(j["settings"]["provider"] == "fake" for j in judge["judges"])
    assert judge["date"] and judge["usage"]["calls"] == 4
    # The fake judge quotes only text it finds in the summary, so nothing is flagged.
    assert judge["quote_flags"]["final"] == {"quoted": 0, "flagged": 0, "rate": 0.0}
    assert judge["type_flags"]["final"] == {"labels": 2 * 6, "flagged": 0, "rate": 0.0}
    probe = json.loads((run / "probe.json").read_text())
    assert probe["agent"] == "fake-agent" and probe["max_steps"] == 3 and probe["date"]
    assert probe["settings"]["model"] == "fake-agent" and "cost" in probe["usage"]
    for log in ("calls.jsonl", "judge_calls.jsonl", "probe_calls.jsonl"):
        rows = [json.loads(line) for line in (run / log).read_text().splitlines()]
        assert rows and all(r["date"] and r["model"] for r in rows), log


def test_cli_judge_warns_when_too_many_quotes_are_flagged(tmp_path, monkeypatch, capsys):
    import inflatebench.judge as judge_pkg

    cfg = pipeline_config(tmp_path)
    main(["--config", cfg, "compact", "--run-id", "w", "--scenarios", str(PILOT), "--fake",
          "--repeats", "1", "--limit", "1", "--condition", "free"])
    for rate, warned in ((0.10, False), (0.11, True)):
        monkeypatch.setattr(judge_pkg, "quote_flag_rates",
                            lambda labels, r=rate: {"final": {"quoted": 100, "flagged": 0, "rate": r}})
        main(["--config", cfg, "judge", "--run-id", "w", "--fake"])
        assert ("fix the judge instructions" in capsys.readouterr().err) is warned
    info = json.loads((tmp_path / "runs" / "w" / "judge.json").read_text())
    assert info["quote_flag_limit"] == 0.10


def test_cli_stages_report_missing_inputs_and_config(tmp_path):
    cfg = pipeline_config(tmp_path)
    with pytest.raises(SystemExit, match="summaries.jsonl not found"):
        main(["--config", cfg, "probe", "--run-id", "none", "--fake"])
    with pytest.raises(SystemExit, match="labels.jsonl not found"):
        main(["--config", cfg, "analyze", "--run-id", "none"])
    main(["--config", cfg, "compact", "--run-id", "r", "--scenarios", str(PILOT), "--fake",
          "--repeats", "1", "--limit", "1", "--condition", "free"])
    with pytest.raises(SystemExit, match="set judges"):
        main(["--config", cfg, "judge", "--run-id", "r"])
    with pytest.raises(SystemExit, match="set its name"):
        main(["--config", cfg, "probe", "--run-id", "r"])
