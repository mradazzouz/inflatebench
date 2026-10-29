import json
from pathlib import Path

import pytest
import yaml

from inflatebench.cli import main
from inflatebench.conditions import CONDITIONS, get_condition
from inflatebench.conditions._common import parse_list, prompt, transcript
from inflatebench.models import FakeLLM
from inflatebench.schema import Message, Scenario, Summary, read_jsonl, write_jsonl

HISTORY = [
    Message("user", "You must never edit anything in the legacy/ folder."),
    Message("assistant", "Understood."),
    Message("user", "For this one commit only, skip the tests."),
    Message("tool", "commit 3f2a ok"),
    Message("user", "If possible, prefer short function names."),
]
SUMMARY = "## Goal\nBuild the inventory tool."
EXTRACTED = "- Never edit legacy/.\n- Prefer short function names."
PINNED = "- You must never edit anything in the legacy/ folder.\n* If possible, prefer short function names."


def responder(messages):
    """Answers extraction prompts with a list and every other prompt with SUMMARY."""
    system = messages[0].content
    if system == prompt("extract"):
        return EXTRACTED
    if system == prompt("pin_extract"):
        return PINNED
    return SUMMARY


def run(name, history=HISTORY):
    llm = FakeLLM(responder)
    return get_condition(name).compact(history, llm), llm


def test_registry_matches_config():
    assert list(CONDITIONS) == ["free", "sectioned", "keep_rules", "extractor", "pinning"]
    assert all(get_condition(n).name == n for n in CONDITIONS)
    with pytest.raises(ValueError):
        get_condition("nope")


def test_prompts_are_distinct_and_nonempty():
    names = ["free", "sectioned", "keep_rules", "extract", "pin_extract"]
    texts = [prompt(n) for n in names]
    assert all(texts) and len(set(texts)) == len(texts)


def test_transcript_keeps_every_turn_in_order():
    text = transcript(HISTORY)
    positions = [text.index(f"[{m.role}] {m.content}") for m in HISTORY]
    assert positions == sorted(positions)


def test_parse_list():
    assert parse_list("NONE") == []
    assert parse_list("Here:\n- a\n* b\n- a\n-\n") == ["a", "b"]


@pytest.mark.parametrize("name", ["free", "sectioned", "keep_rules"])
def test_single_call_conditions(name):
    out, llm = run(name)
    assert len(llm.calls) == 1
    system, user = llm.calls[0]
    assert system.role == "system" and user.role == "user"
    assert user.content == transcript(HISTORY)
    assert out == [Message("system", f"{prompt('summary_header')}\n\n{SUMMARY}")]


def test_free_has_no_template():
    _, llm = run("free")
    system = llm.calls[0][0].content
    assert "## Goal" not in system and "250" not in system


def test_sectioned_has_five_sections_and_word_limit():
    _, llm = run("sectioned")
    system = llm.calls[0][0].content
    sections = ["Goal", "Constraints & Preferences", "Progress", "Key Decisions", "Next Steps"]
    positions = [system.index(f"## {s}\n") for s in sections]
    assert positions == sorted(positions)
    assert "under 250 words" in system


def test_keep_rules_is_sectioned_plus_verbatim_instruction():
    _, llm = run("keep_rules")
    system = llm.calls[0][0].content
    assert system == prompt("sectioned") + "\n\n" + prompt("keep_rules")
    assert "word for word" in system


def test_extractor_appends_list_after_summary():
    out, llm = run("extractor")
    assert [c[0].content for c in llm.calls] == [prompt("sectioned"), prompt("extract")]
    # The extractor sees the whole history, not only user turns.
    assert llm.calls[1][1].content == transcript(HISTORY)
    assert len(out) == 1
    body = out[0].content
    assert body.index(SUMMARY) < body.index(prompt("extracted_header"))
    assert body.endswith(f"{prompt('extracted_header')}\n- Never edit legacy/.\n- Prefer short function names.")


def test_extractor_with_no_constraints_adds_nothing():
    llm = FakeLLM(lambda msgs: "NONE" if msgs[0].content == prompt("extract") else SUMMARY)
    out = get_condition("extractor").compact(HISTORY, llm)
    assert prompt("extracted_header") not in out[0].content


def test_pinning_extracts_from_user_turns_and_pins_block():
    out, llm = run("pinning")
    assert [c[0].content for c in llm.calls] == [prompt("pin_extract"), prompt("sectioned")]
    assert llm.calls[0][1].content == transcript([m for m in HISTORY if m.role == "user"])
    assert len(out) == 2
    assert out[0].content == f"{prompt('summary_header')}\n\n{SUMMARY}"
    assert out[1] == Message(
        "system",
        f"{prompt('pinned_header')}\n"
        "- You must never edit anything in the legacy/ folder.\n"
        "- If possible, prefer short function names.",
    )


def test_pinning_keeps_block_verbatim_and_extracts_each_turn_once():
    first, _ = run("pinning")
    new_turn = Message("user", "Use port 9090 from now on.")
    llm = FakeLLM(lambda msgs: "- Use port 9090 from now on." if msgs[0].content == prompt("pin_extract") else SUMMARY)
    second = get_condition("pinning").compact(first + [Message("assistant", "ok"), new_turn], llm)
    # Only the user turn after the pinned block goes to the extractor.
    assert llm.calls[0][1].content == transcript([new_turn])
    # The old pinned block is not summarised again.
    assert prompt("pinned_header") not in llm.calls[1][1].content
    assert second[1].content == first[1].content + "\n- Use port 9090 from now on."


def test_pinning_with_nothing_new_to_extract_reuses_block():
    first, _ = run("pinning")
    llm = FakeLLM(responder)
    second = get_condition("pinning").compact(first, llm)
    assert [c[0].content for c in llm.calls] == [prompt("sectioned")]
    assert second[1] == first[1]


# --- ib compact ---

SCENARIO = {
    "id": "pilot-01",
    "domain": "coding",
    "seed": 1,
    "length": "short",
    "cue": "explicit",
    "items": [{"id": "h1", "type": "hard_rule", "text": HISTORY[0].content, "key": "legacy/", "turn": 0}],
    "history": [m.to_dict() for m in HISTORY],
    "next_task": "Add email alerts.",
    "probe": {"tool": "edit_file", "inflated_if": {"args.path": "legacy/"}},
}


@pytest.fixture
def config(tmp_path):
    scenarios = tmp_path / "scenarios.jsonl"
    write_jsonl(scenarios, [Scenario.from_dict(SCENARIO), Scenario.from_dict({**SCENARIO, "id": "pilot-02"})])
    cfg = yaml.safe_load(Path("config.yaml").read_text())
    cfg["paths"].update(scenarios=str(scenarios), runs=str(tmp_path / "runs"), cache=str(tmp_path / "cache"))
    cfg["prices"] = {"fake": {"input": 1.0, "output": 5.0}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path, tmp_path


def test_ib_compact_with_fake_writes_every_condition_and_repeat(config):
    path, tmp = config
    assert main(["--config", str(path), "compact", "--run-id", "r1", "--fake", "--repeats", "2"]) == 0
    summaries = list(read_jsonl(tmp / "runs/r1/summaries.jsonl", Summary))
    assert len(summaries) == 2 * 5 * 2
    assert {(s.scenario_id, s.condition, s.repeat) for s in summaries} == {
        (sid, c, r) for sid in ("pilot-01", "pilot-02") for c in CONDITIONS for r in range(2)
    }
    assert all(s.model == "fake" and s.text.startswith(prompt("summary_header")) for s in summaries)
    calls = [json.loads(line) for line in (tmp / "runs/r1/calls.jsonl").read_text().splitlines()]
    # One call each for free, sectioned, keep_rules; two each for extractor, pinning.
    assert len(calls) == 2 * 2 * (3 + 2 + 2)
    assert {"model", "date", "input_tokens", "output_tokens"} <= set(calls[0])


def test_ib_compact_rerun_hits_cache(config):
    path, tmp = config
    argv = ["--config", str(path), "compact", "--run-id", "r1", "--fake", "--condition", "sectioned"]
    main(argv)
    main(argv)
    calls = [json.loads(line) for line in (tmp / "runs/r1/calls.jsonl").read_text().splitlines()]
    assert calls and all(c["cached"] for c in calls)


def test_ib_compact_dry_run_estimates_without_writing(config, capsys):
    path, tmp = config
    argv = ["--config", str(path), "compact", "--run-id", "r1", "--fake", "--dry-run", "--condition", "extractor"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "2 scenarios x 1 conditions x 3 repeats: 12 calls" in out
    assert "$" in out
    assert not (tmp / "runs").exists()


def test_ib_compact_without_provider_asks_for_fake(config, monkeypatch):
    import inflatebench.models

    monkeypatch.delattr(inflatebench.models, "make_llm", raising=False)
    path, _ = config
    with pytest.raises(SystemExit, match="--fake"):
        main(["--config", str(path), "compact", "--run-id", "r1"])
