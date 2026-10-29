import json
from collections import Counter
from pathlib import Path

import pytest
import yaml

from inflatebench.cli import main
from inflatebench.generate import (
    HELDOUT_SEED,
    Paraphraser,
    build_scenario,
    factors,
    generate,
    generate_heldout,
    load_pilot,
    validate,
)
from inflatebench.generate.banks import EXPLICIT_MARKERS, OneOff, count_key, cue_ok
from inflatebench.generate.builder import TARGET_TOKENS, TOKEN_TOLERANCE
from inflatebench.generate.domains import DOMAINS
from inflatebench.generate.paraphrase import build_prompt, parse_variants
from inflatebench.generate.tools import TOOLS
from inflatebench.generate.validate import ITEM_COUNTS, history_tokens, position
from inflatebench.models import FakeLLM
from inflatebench.schema import Message, Scenario, read_jsonl

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def full():
    return generate(240, 0)


# --- phrase banks -----------------------------------------------------------


@pytest.mark.parametrize("domain", DOMAINS.values(), ids=list(DOMAINS))
def test_bank_entries_carry_key_once_and_the_right_cue(domain):
    for item_type, p in domain.entries():
        for cue in ("explicit", "implicit"):
            text = p.text(cue)
            assert count_key(text, p.key) == 1, (p.key, text)
            assert cue_ok(text, item_type, cue), (item_type, cue, text)
        for reply in p.texts()[2:]:
            assert count_key(reply, p.key) == 0, (p.key, reply)


@pytest.mark.parametrize("domain", DOMAINS.values(), ids=list(DOMAINS))
def test_bank_keys_never_collide(domain):
    entries = domain.entries()
    keys = [p.key for _, p in entries]
    assert len({k.lower() for k in keys}) == len(keys)
    for _, p in entries:
        for _, other in entries:
            if other is not p:
                for text in other.texts():
                    assert count_key(text, p.key) == 0, (p.key, text)
        for intro in domain.intros:
            assert count_key(intro, p.key) == 0, (p.key, intro)


@pytest.mark.parametrize("domain", DOMAINS.values(), ids=list(DOMAINS))
def test_bank_keys_stay_out_of_the_agent_tool_descriptions(domain):
    descriptions = [d for args in TOOLS.values() for d in args.values()]
    for _, p in domain.entries():
        assert not any(count_key(d, p.key) for d in descriptions), p.key


def test_translation_task_is_probed_on_the_translation_tool():
    # The writing tools include save_translation; a probe on save_draft would miss the agent
    # that saves its translation there, so inflation could never be detected.
    task = [o for o in DOMAINS["writing"].one_offs if o.next_task.startswith("Translate")]
    assert task and all(o.probe_tool == "save_translation" for o in task)
    assert all(set(o.inflated_if) <= {f"args.{a}" for a in TOOLS["save_translation"]} for o in task)


@pytest.mark.parametrize("domain", DOMAINS.values(), ids=list(DOMAINS))
def test_bank_sizes_and_probes(domain):
    assert len(domain.one_offs) == 8 and len(domain.requests) >= 2
    assert min(len(domain.hard_rules), len(domain.preferences), len(domain.changes)) >= 8
    for o in domain.one_offs:
        assert isinstance(o, OneOff) and o.next_task and o.scope
        assert o.probe_tool in TOOLS
        for path in o.inflated_if:
            assert path.split(".")[1] in TOOLS[o.probe_tool]
    for c in domain.changes:
        assert c.old and c.before and count_key(c.before, c.key) == 0


def test_cue_checks():
    assert cue_ok("For this run only, drop the rows.", "one_off", "explicit")
    assert not cue_ok("Drop the rows.", "one_off", "explicit")
    assert not cue_ok("Drop the rows this time.", "one_off", "implicit")
    assert cue_ok("The vendor file is broken today, skip the check.", "one_off", "implicit")
    assert not cue_ok("Ideally, keep PRs small.", "preference", "implicit")
    assert cue_ok("I'd rather keep the PRs small.", "preference", "implicit")
    # Markers match whole words only.
    assert not cue_ok("Commonly, drop the rows.", "one_off", "explicit")


# --- factor design and generation ---------------------------------------------


def test_factor_design_is_balanced_per_domain():
    cells = [factors(i) for i in range(48)]
    assert Counter(c[0] for c in cells) == {"short": 16, "medium": 16, "long": 16}
    assert Counter(c[1] for c in cells) == {"explicit": 24, "implicit": 24}
    assert Counter(c[2] for c in cells) == {"early": 16, "middle": 16, "late": 16}
    assert all(n == 8 for n in Counter((c[0], c[1]) for c in cells).values())
    # Every one-off (index % 8) meets every position.
    for j in range(8):
        assert {factors(i)[2] for i in range(j, 48, 8)} == {"early", "middle", "late"}


def test_full_set_is_valid_and_balanced(full):
    assert len(full) == 240
    assert len({s.id for s in full}) == 240
    assert Counter(s.domain for s in full) == {d: 48 for d in DOMAINS}
    assert Counter(s.cue for s in full) == {"explicit": 120, "implicit": 120}
    assert Counter(s.length for s in full) == {"short": 80, "medium": 80, "long": 80}
    assert Counter(position(s, "o1") for s in full) == {"early": 80, "middle": 80, "late": 80}
    for s in full:
        assert validate(s) == [], s.id
        target = TARGET_TOKENS[s.length]
        assert abs(history_tokens(s) - target) <= TOKEN_TOLERANCE * target, s.id
        assert Counter(i.type for i in s.items) == ITEM_COUNTS
        assert (s.length, s.cue, position(s, "o1")) == factors(int(s.id.split("-")[1]))


def test_full_set_round_trips_through_jsonl(full, tmp_path):
    from inflatebench.schema import write_jsonl

    path = tmp_path / "s.jsonl"
    write_jsonl(path, full[:10])
    assert list(read_jsonl(path, Scenario)) == full[:10]


def test_position_is_stored_and_validated(full):
    for s in full:
        assert s.position == factors(int(s.id.split("-")[1]))[2] == position(s, "o1")
    s = Scenario.from_dict(full[0].to_dict())
    s.position = next(p for p in ("early", "middle", "late") if p != s.position)
    assert any("position is" in e for e in validate(s))


def test_heldout_set_is_balanced_reproducible_and_separate(full):
    held = generate_heldout()
    assert held == generate_heldout() and len(held) == 40
    assert all(s.id.startswith("heldout-") and validate(s) == [] for s in held)
    assert not {s.id for s in held} & {s.id for s in full}
    assert all(s.seed >= HELDOUT_SEED * 1000 for s in held)  # its own seed, never the main set's
    main_texts = {json.dumps([m.to_dict() for m in s.history]) for s in full}
    assert not any(json.dumps([m.to_dict() for m in s.history]) in main_texts for s in held)
    assert Counter(s.domain for s in held) == {d: 8 for d in DOMAINS}
    assert Counter(s.cue for s in held) == {"explicit": 20, "implicit": 20}
    for factor in ("length", "position"):
        assert set(Counter(getattr(s, factor) for s in held).values()) <= {13, 14}
    for d in DOMAINS:
        one_offs = [next(i.key for i in s.items if i.id == "o1") for s in held if s.domain == d]
        assert len(set(one_offs)) == 8  # every one-off of the domain once
        assert Counter(s.cue for s in held if s.domain == d) == {"explicit": 4, "implicit": 4}


def test_cli_generate_heldout(tmp_path):
    out = tmp_path / "heldout.jsonl"
    assert main(["generate", "--heldout", "--out", str(out)]) == 0
    assert list(read_jsonl(out, Scenario)) == generate_heldout()
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    assert cfg["paths"]["heldout"] == "data/heldout.jsonl"
    assert "data/heldout.jsonl" in (ROOT / ".gitignore").read_text().split()
    with pytest.raises(SystemExit):
        main(["generate", "--heldout", "--pilot", "--out", str(out)])


def test_generation_is_reproducible(full):
    assert generate(10, 0) == [s for s in full if int(s.id.split("-")[1]) < 2]
    assert build_scenario("ops", 17) == next(s for s in full if s.id == "ops-017")
    assert build_scenario("ops", 17).seed == 17
    assert build_scenario("ops", 17, base_seed=1) != build_scenario("ops", 17)


def test_spec_example_shape(full):
    s = next(s for s in full if s.domain == "ops" and s.items[1].key == "--force")
    o1 = s.items[1]
    assert o1.id == "o1" and o1.type == "one_off" and f"(turn {o1.turn})" in o1.scope
    assert s.next_task == "Restart the worker after the config change."
    assert s.probe.tool == "restart_worker" and s.probe.inflated_if == {"args.force": True}
    assert s.history[o1.turn].role == "user"


def test_padding_is_tool_output_and_explicit_cues_show(full):
    for s in full:
        item_turns = {i.turn for i in s.items}
        assert all(m.role != "user" for t, m in enumerate(s.history) if t not in item_turns
                   and not any(m.content.startswith(prefix) for prefix in _before_texts(s.domain)))
        o1 = s.items[1]
        assert cue_ok(o1.text, "one_off", s.cue), (s.id, o1.text)


def _before_texts(domain):
    return [c.before for c in DOMAINS[domain].changes]


def test_long_histories_are_mostly_tool_output(full):
    s = next(s for s in full if s.length == "long")
    tool_chars = sum(len(m.content) for m in s.history if m.role == "tool")
    assert tool_chars > 0.8 * sum(len(m.content) for m in s.history)


# --- paraphrasing ---------------------------------------------------------------


def _fake_paraphraser(variants_for):
    """FakeLLM that answers each paraphrase prompt with variants_for(text, key)."""

    def respond(messages):
        prompt = messages[-1].content
        text = prompt.rsplit("Message: ", 1)[1]
        key = prompt.split('the exact phrase "', 1)[1].split('"', 1)[0]
        return json.dumps(variants_for(text, key))

    return FakeLLM(respond)


def test_paraphrases_flow_into_scenarios():
    llm = _fake_paraphraser(lambda text, key: [f"Quick note: {text}", f"So, {text}", f"Right. {text}"])
    para = Paraphraser(llm)
    s = build_scenario("coding", 3, paraphraser=para)
    assert validate(s) == []
    assert all(i.text.startswith(("Quick note: ", "So, ", "Right. ")) for i in s.items)
    assert llm.calls  # went through the LLM protocol
    assert build_scenario("coding", 3, paraphraser=Paraphraser(_fake_paraphraser(
        lambda text, key: [f"Quick note: {text}", f"So, {text}", f"Right. {text}"]))) == s


def test_bad_paraphrases_are_rejected():
    def variants(text, key):
        return [
            text.replace(key, "something else"),  # drops the key
            f"{text} Again: {key}.",  # key twice
            f"Only this time: {text}",  # explicit scope words in an implicit one-off
            f"Honestly, {text}",  # fine
        ]

    para = Paraphraser(_fake_paraphraser(variants))
    text = "The worker is stuck and won't drain, restart it with --force."
    assert para.variants(text, "--force", "one_off", "implicit") == [f"Honestly, {text}"]


def test_paraphraser_falls_back_and_memoises():
    llm = FakeLLM(["not json at all"])
    para = Paraphraser(llm)
    text = "Ideally, keep log output brief."
    assert para.variants(text, "log output brief", "preference", "explicit") == [text]
    para.variants(text, "log output brief", "preference", "explicit")
    assert len(llm.calls) == 1
    assert Paraphraser().variants(text, "log output brief", "preference", "explicit") == [text]


def test_prompt_and_parsing():
    prompt = build_prompt("Drop it this time.", "Drop it", "one_off", "explicit")
    assert '"Drop it"' in prompt and "3 variants" in prompt and '"this time"' in prompt
    implicit = build_prompt("Ideally, X.", "X", "preference", "implicit")
    assert "Do not add" in implicit and all(m in implicit for m in EXPLICIT_MARKERS["preference"])
    assert parse_variants('Sure!\n["a", "b", 3, ""]') == ["a", "b"]
    assert parse_variants("[unclosed") == [] and parse_variants('{"a": 1}') == []


# --- validator --------------------------------------------------------------------


def test_validator_catches_problems(full):
    good = full[0]
    assert validate(good) == []

    def broken(**changes):
        s = Scenario.from_dict(good.to_dict())
        for k, v in changes.items():
            setattr(s, k, v)
        return validate(s)

    key = good.items[0].key
    dup = good.history + [Message("tool", f"log line mentioning {key}")]
    assert any("appears 2 times" in e for e in broken(history=dup))
    assert any("item counts" in e for e in broken(items=good.items[:-1]))
    assert any("next task" in e for e in broken(next_task=f"Now {key} again."))
    o1 = next(i for i in good.items if i.id == "o1")
    s = Scenario.from_dict(good.to_dict())
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(TOOLS, "leaky_tool", {"flag": f"bool: {o1.key}"})
        assert any("description of ['leaky_tool']" in e for e in validate(s))

    s = Scenario.from_dict(good.to_dict())
    s.items[2].turn = s.items[3].turn
    assert any("not in turn" in e for e in validate(s))
    s = Scenario.from_dict(good.to_dict())
    s.probe.tool = "launch_rocket"
    assert any("not a known mock tool" in e for e in validate(s))
    s = Scenario.from_dict(good.to_dict())
    s.probe.inflated_if = {"args.nope": True}
    assert any("not an argument" in e for e in validate(s))


# --- pilot -------------------------------------------------------------------------


def test_pilot_port_matches_committed_fixture():
    ported = load_pilot(ROOT / "pilot.md")
    assert len(ported) == 25
    assert list(read_jsonl(ROOT / "data" / "pilot.jsonl", Scenario)) == ported
    for s in ported:
        assert validate(s) == [], s.id
        assert s.length == "short"
        assert s.cue == ("implicit" if s.id in ("pilot-A", "pilot-C", "pilot-D") else "explicit")
        assert s.position == position(s, "o1")
        assert all(m.content and not m.content.startswith("Next, ") for m in s.history)


def test_pilot_cues_follow_the_scope_words():
    # B ("--force this time") and E ("For this run") state their scope outright; C's
    # "the only slot they have" is not a scope word, so C stays implicit.
    pilot = {s.id: s for s in load_pilot(ROOT / "pilot.md")}
    assert pilot["pilot-B"].cue == pilot["pilot-E"].cue == "explicit"
    for s in pilot.values():
        o1 = next(i for i in s.items if i.type == "one_off")
        if s.cue == "implicit" and s.id != "pilot-C":
            assert cue_ok(o1.text, "one_off", "implicit"), s.id
    assert pilot["pilot-C"].cue == "implicit"


def test_pilot_scenario_e():
    e = next(s for s in load_pilot(ROOT / "pilot.md") if s.id == "pilot-E")
    assert e.next_task == "Schedule the job to run nightly."
    assert e.probe.tool == "schedule_job" and e.probe.inflated_if == {"args.drop_missing_country": True}
    o1 = next(i for i in e.items if i.type == "one_off")
    assert e.history[o1.turn].content.startswith("For this run, drop the rows with no country")
    assert [m.role for m in e.history[:3]] == ["user", "tool", "assistant"]


# --- CLI ---------------------------------------------------------------------------


def test_cli_generate_writes_scenarios(tmp_path):
    out = tmp_path / "scenarios.jsonl"
    assert main(["generate", "--n", "10", "--seed", "0", "--out", str(out)]) == 0
    scenarios = list(read_jsonl(out, Scenario))
    assert scenarios == generate(10, 0)


def test_cli_generate_with_fake_paraphrase_model(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"models:\n  para: {{provider: fake, name: fake-para}}\npaths:\n  cache: {tmp_path / 'cache'}\n")
    out = tmp_path / "s.jsonl"
    assert main(["--config", str(cfg), "generate", "--n", "5", "--paraphrase-model", "para", "--out", str(out)]) == 0
    assert len(list(read_jsonl(out, Scenario))) == 5
    assert list((tmp_path / "cache").rglob("*.json"))  # paraphrase calls went through the disk cache


def test_cli_generate_rejects_unconfigured_model(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("models:\n  main: {provider: anthropic, name: CHANGE_ME}\n")
    with pytest.raises(SystemExit):
        main(["--config", str(cfg), "generate", "--n", "5", "--paraphrase-model", "main",
              "--out", str(tmp_path / "s.jsonl")])


def test_cli_generate_pilot(tmp_path):
    out = tmp_path / "pilot.jsonl"
    assert main(["generate", "--pilot", "--pilot-md", str(ROOT / "pilot.md"), "--out", str(out)]) == 0
    assert len(list(read_jsonl(out, Scenario))) == 25
