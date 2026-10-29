import json

import pytest

from inflatebench.schema import (
    Item,
    Label,
    Message,
    ProbeResult,
    Scenario,
    Summary,
    read_jsonl,
    write_jsonl,
)

# The example record from SPEC.md, "Data format".
SPEC_EXAMPLE = """
{"id": "ops-017", "domain": "ops", "seed": 17, "length": "medium", "cue": "explicit",
 "items": [{"id": "o1", "type": "one_off", "text": "restart it with --force this time",
            "scope": "the restart on turn 6", "key": "--force", "turn": 6}],
 "history": [{"role": "user", "content": "..."}, {"role": "tool", "content": "..."}],
 "next_task": "Restart the worker after the config change.",
 "probe": {"tool": "restart_worker", "inflated_if": {"args.force": true}},
 "position": "middle", "template": "ops-o00"}
"""


def spec_scenario() -> Scenario:
    return Scenario.from_dict(json.loads(SPEC_EXAMPLE))


def test_spec_example_parses():
    s = spec_scenario()
    assert s.id == "ops-017"
    assert isinstance(s.items[0], Item)
    assert s.items[0].scope == "the restart on turn 6"
    assert isinstance(s.history[1], Message)
    assert s.history[1].role == "tool"
    assert s.probe.tool == "restart_worker"
    assert s.probe.inflated_if == {"args.force": True}


def test_spec_example_round_trips():
    original = json.loads(SPEC_EXAMPLE)
    assert spec_scenario().to_dict() == original
    assert Scenario.from_dict(json.loads(spec_scenario().to_json())) == spec_scenario()


def test_spec_example_cue_matches_its_sentence():
    from inflatebench.generate.banks import cue_ok

    s = spec_scenario()
    assert s.cue == "explicit" and cue_ok(s.items[0].text, "one_off", "explicit")
    assert s.position == "middle"


def test_position_is_optional_and_checked():
    data = json.loads(SPEC_EXAMPLE)
    del data["position"]
    assert Scenario.from_dict(data).position is None  # files written before it was stored
    with pytest.raises(ValueError, match="position"):
        Scenario.from_dict(data | {"position": "end"})


def test_item_scope_is_optional():
    item = Item.from_dict({"id": "h1", "type": "hard_rule", "text": "never edit legacy/",
                           "key": "legacy/", "turn": 1})
    assert item.scope is None


@pytest.mark.parametrize(
    "patch",
    [
        {"length": "huge"},
        {"cue": "maybe"},
        {"items": [{"id": "x", "type": "wish", "text": "t", "key": "k", "turn": 1}]},
        {"history": [{"role": "robot", "content": "hi"}]},
        {"extra_field": 1},
    ],
)
def test_invalid_scenarios_are_rejected(patch):
    data = json.loads(SPEC_EXAMPLE) | patch
    with pytest.raises((ValueError, TypeError)):
        Scenario.from_dict(data)


def test_missing_required_field_is_rejected():
    data = json.loads(SPEC_EXAMPLE)
    del data["next_task"]
    with pytest.raises(TypeError):
        Scenario.from_dict(data)


def test_summary_round_trip_and_text():
    s = Summary(scenario_id="ops-017", condition="free", model="fake", repeat=0,
                messages=[Message("user", "Goal: x"), Message("assistant", "Next: y")])
    assert Summary.from_dict(json.loads(s.to_json())) == s
    assert s.text == "Goal: x\n\nNext: y"


def test_label_values():
    base = dict(scenario_id="ops-017", condition="free", model="fake", repeat=0, judge="j1")
    assert Label(item_id="o1", label="promoted", quote="always use --force", **base).label == "promoted"
    assert Label(item_id=None, label="invented", **base).item_id is None
    with pytest.raises(ValueError):
        Label(item_id="o1", label="invented", **base)
    with pytest.raises(ValueError):
        Label(item_id=None, label="promoted", **base)
    with pytest.raises(ValueError):
        Label(item_id="o1", label="bogus", **base)


def test_probe_result_round_trip():
    r = ProbeResult(scenario_id="ops-017", condition="free", model="fake", repeat=1,
                    tool_calls=[{"tool": "restart_worker", "args": {"force": True}}], inflated=True)
    assert ProbeResult.from_dict(json.loads(r.to_json())) == r


def test_jsonl_round_trip(tmp_path):
    path = tmp_path / "nested" / "scenarios.jsonl"
    write_jsonl(path, [spec_scenario(), spec_scenario()])
    assert len(path.read_text().splitlines()) == 2
    assert list(read_jsonl(path, Scenario)) == [spec_scenario(), spec_scenario()]
