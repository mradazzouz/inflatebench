import json

import pytest

from inflatebench.judge import (
    FINAL,
    LABEL_DEFINITIONS,
    JudgeError,
    LLMJudge,
    PanelJudge,
    agreement_report,
    build_prompt,
    cohen_kappa,
    human_check,
    judge_run,
    make_annotation_sample,
    parse_verdict,
    per_label_kappa,
    quote_in_summary,
    read_human_labels,
    sample_weights,
)
from inflatebench.judge.run import write_rows
from inflatebench.models import FakeLLM
from inflatebench.schema import LABELS, Label, read_jsonl, write_jsonl

# What a careful judge says about the two fixture summaries of pilot-05.
GOOD = {"h1": ("correct", "Never deploy on Fridays."),
        "c1": ("correct", "Staging cluster is stg-eu-3"),
        "o1": ("correct", "canary step disabled for that run only"),
        "s1": ("correct", "Prefer brief log output where possible."),
        "r1": ("correct", "Migration 0042 applied on staging."),
        "r2": ("correct", "Error rate 0.2%, normal.")}
BAD = {"h1": ("correct", "Never deploy on Fridays."),
       "c1": ("stale", "Use stg-eu-2 for staging."),
       "o1": ("promoted", "Disable the canary step in deployments."),
       "s1": ("hardened", "Keep log output brief."),
       "r1": ("request_promoted", "Always run database migrations before deploying."),
       "r2": ("correct", "Error rates checked (0.2%).")}


def reply(items, invented=()):
    return json.dumps({"items": [{"item_id": k, "label": v[0], "quote": v[1]} for k, v in items.items()],
                       "invented": [{"quote": q} for q in invented]})


def oracle(overrides=None, invented=("Always notify the on-call channel.",)):
    """A fake judge that answers from the summary text in the prompt."""
    overrides = overrides or {}

    def respond(messages):
        if "stg-eu-2 for staging" in messages[1].content:
            return reply(BAD | overrides, invented)
        return reply(GOOD | overrides)
    return respond


def test_rubric_covers_every_label_and_item(pilot):
    msgs = build_prompt(pilot[2], "SUMMARY TEXT")
    assert set(LABEL_DEFINITIONS) == set(LABELS)
    for label in LABELS:
        assert f"- {label}:" in msgs[0].content
    for item in pilot[2].items:
        assert f'"item_id": "{item.id}"' in msgs[1].content
    assert "the staging deployment run" in msgs[1].content
    assert "<summary>\nSUMMARY TEXT\n</summary>" in msgs[1].content


def test_parse_accepts_fenced_json_with_prose(pilot):
    text = "Here you go:\n```json\n" + reply(BAD, ["x is required"]) + "\n```\nDone."
    v = parse_verdict(text, pilot[2])
    assert v.items["o1"] == ("promoted", "Disable the canary step in deployments.")
    assert v.invented == ["x is required"]


@pytest.mark.parametrize("bad", [
    "no json here",
    json.dumps({"labels": []}),
    reply({k: v for k, v in GOOD.items() if k != "r2"}),
    reply(GOOD | {"o1": ("inflated", "")}),
    json.dumps({"items": [{"item_id": "zz", "label": "correct", "quote": ""}]}),
])
def test_parse_rejects_invalid_replies(bad, pilot):
    with pytest.raises(JudgeError):
        parse_verdict(bad, pilot[2])


def test_llm_judge_labels_summary(pilot, summaries):
    judge = LLMJudge("j1", FakeLLM(oracle()))
    labels = judge.label(pilot[2], summaries[1])
    by_item = {l.item_id: l for l in labels}
    assert by_item["o1"].label == "promoted"
    assert by_item["o1"].condition == "free" and by_item["o1"].judge == "j1"
    assert by_item[None].label == "invented"
    for lab in labels:
        assert quote_in_summary(lab.quote, summaries[1].text)


GOOD_TEXT = "\n".join(q for _, q in GOOD.values())  # a summary holding every GOOD quote


def test_llm_judge_retries_then_fails(pilot):
    llm = FakeLLM(["garbage", reply(GOOD)])
    labels = LLMJudge("j1", llm).label(pilot[2], GOOD_TEXT)
    assert len(llm.calls) == 2
    assert "invalid" in llm.calls[1][-1].content
    assert {l.label for l in labels} == {"correct"}
    with pytest.raises(JudgeError):
        LLMJudge("j1", FakeLLM(["garbage"]), retries=1).label(pilot[2], GOOD_TEXT)


def test_quotes_are_checked_reasked_once_then_flagged(pilot):
    spaced = "  NEVER deploy   on\nFridays. " + GOOD_TEXT.split("\n", 1)[1]  # case and spacing differ
    llm = FakeLLM([reply(GOOD)])
    labels = LLMJudge("j1", llm).label(pilot[2], spaced)
    assert len(llm.calls) == 1 and not any(l.quote_flagged for l in labels)

    made_up = GOOD | {"o1": ("promoted", "Always disable the canary step.")}
    fixed = FakeLLM([reply(made_up, ["Rule nobody wrote."]), reply(GOOD)])
    labels = LLMJudge("j1", fixed).label(pilot[2], GOOD_TEXT)
    assert len(fixed.calls) == 2  # re-asked once
    reask = fixed.calls[1][-1].content
    assert "Always disable the canary step." in reask and "Rule nobody wrote." in reask
    assert not any(l.quote_flagged for l in labels)

    stubborn = FakeLLM([reply(made_up, ["Rule nobody wrote."])])
    labels = LLMJudge("j1", stubborn).label(pilot[2], GOOD_TEXT)
    assert len(stubborn.calls) == 2  # only one re-ask, then flagged
    flagged = {(l.item_id, l.quote) for l in labels if l.quote_flagged}
    assert flagged == {("o1", "Always disable the canary step."), (None, "Rule nobody wrote.")}
    absent = FakeLLM([reply(GOOD | {"r1": ("correct", "")})])
    assert not any(l.quote_flagged for l in LLMJudge("j1", absent).label(pilot[2], GOOD_TEXT))


def test_panel_final_labels_keep_quote_flags(pilot):
    made_up = GOOD | {"o1": ("promoted", "Always disable the canary step.")}
    panel = PanelJudge(LLMJudge("a", FakeLLM([reply(made_up)])), LLMJudge("b", FakeLLM([reply(GOOD)])),
                       LLMJudge("c", FakeLLM([reply(made_up)])))
    labels = panel.label(pilot[2], GOOD_TEXT)
    final = {l.item_id: l for l in labels if l.judge == FINAL}
    assert final["o1"].label == "promoted" and final["o1"].quote_flagged  # decided by the flagged c
    assert not any(l.quote_flagged for l in labels if l.judge == "b")


def test_judge_sees_one_neutral_format_whatever_the_condition(pilot):
    from inflatebench.conditions import NEUTRAL_HEADER, NEUTRAL_LIST_HEADER, get_condition
    from inflatebench.conditions._common import prompt
    from inflatebench.schema import Summary

    def respond(messages):
        if "constraint" in messages[0].content:
            return "- Never deploy on Fridays."
        return "## Goal\nShip the release.\n\n## Constraints & Preferences\n- Never deploy on Fridays."

    seen = []

    def judge(msgs):
        seen.append(msgs[1].content.split("<summary>\n", 1)[1].split("\n</summary>", 1)[0])
        return reply({k: (label, "") for k, (label, _) in GOOD.items()})  # no quotes, no re-ask

    judge_llm = FakeLLM(judge)
    s = pilot[2]
    for name in ("sectioned", "extractor", "pinning"):
        messages = get_condition(name).compact(s.history, FakeLLM(respond))
        LLMJudge("j", judge_llm).label(s, Summary(s.id, name, "m", 0, messages))
    for body in seen:
        assert body.startswith(NEUTRAL_HEADER + "\n\n")
        assert body.count(NEUTRAL_HEADER) == 1
        assert not any(prompt(h) in body for h in ("summary_header", "pinned_header"))
        for word in ("pinned", "verbatim", "extract", "sectioned", "condition"):
            assert word not in body.lower()
    # Every condition's constraint text survives the merge; only the headers go.
    assert len(seen) == 3 and all("Never deploy on Fridays." in t for t in seen)
    assert seen[1].count("- Never deploy on Fridays.") == seen[2].count("- Never deploy on Fridays.") == 2
    # Extracted and pinned lists look alike and are still marked as constraints.
    assert NEUTRAL_LIST_HEADER not in seen[0]
    assert seen[1] == seen[2] and seen[1].count(NEUTRAL_LIST_HEADER + "\n- Never deploy") == 1


def test_neutral_format_keeps_appended_lists_out_of_the_last_section():
    """Without a header, an extracted one-off would read as one more Next Step to the judge."""
    from inflatebench.conditions import NEUTRAL_LIST_HEADER, neutral_context
    from inflatebench.conditions._common import bullets, prompt, summary_message

    summary = "## Next Steps\n- Schedule the job nightly."
    for header in ("extracted_header", "pinned_header"):
        messages = [summary_message(summary + "\n\n" + bullets(prompt(header), ["Drop rows with no country"]))]
        text = neutral_context(messages)
        assert text.endswith("- Schedule the job nightly.\n\n" + NEUTRAL_LIST_HEADER
                             + "\n- Drop rows with no country")


def test_panel_agreement_skips_tiebreak(pilot, summaries):
    tie = FakeLLM(oracle())
    panel = PanelJudge(LLMJudge("a", FakeLLM(oracle())), LLMJudge("b", FakeLLM(oracle())),
                       LLMJudge("c", tie))
    labels = panel.label(pilot[2], summaries[0])
    assert tie.calls == []
    assert {l.judge for l in labels} == {"a", "b", FINAL}
    assert all(l.label == "correct" for l in labels if l.judge == FINAL)


def test_panel_tiebreak_decides_disputed_items(pilot, summaries):
    panel = PanelJudge(
        LLMJudge("a", FakeLLM(oracle())),
        LLMJudge("b", FakeLLM(oracle({"o1": ("widened", "Disable the canary step in deployments.")},
                                     invented=("Always notify the on-call channel", "Be nice")))),
        LLMJudge("c", FakeLLM(oracle({"s1": ("correct", "")}, invented=()))),
    )
    labels = panel.label(pilot[2], summaries[1])
    final = {l.item_id: l.label for l in labels if l.judge == FINAL}
    assert final["o1"] == "promoted"   # a and c agree; c decides
    assert final["s1"] == "hardened"   # a and b agree; c's dissent is ignored
    assert final[None] == "invented"   # both list the on-call rule
    assert sum(1 for l in labels if l.judge == FINAL and l.item_id is None) == 1
    tie_items = {l.item_id for l in labels if l.judge == "c"}
    assert tie_items == {"o1"}


def test_panel_requires_distinct_names():
    j = LLMJudge("a", FakeLLM())
    with pytest.raises(ValueError):
        PanelJudge(j, j, LLMJudge("c", FakeLLM()))


def test_cohen_kappa_known_values():
    assert cohen_kappa(list("aabb"), list("aabb")) == 1.0
    assert cohen_kappa(list("aaaa"), list("aaaa")) == 1.0
    # Classic 2x2 example: 20/5/10/15 -> po 0.7, pe 0.5, kappa 0.4.
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)
    with pytest.raises(ValueError):
        cohen_kappa(["a"], [])


def test_judge_run_and_agreement_report(tmp_path, pilot, summaries):
    run = tmp_path / "run"
    write_jsonl(run / "summaries.jsonl", summaries)
    write_jsonl(tmp_path / "scenarios.jsonl", pilot)
    panel = PanelJudge(LLMJudge("a", FakeLLM(oracle())),
                       LLMJudge("b", FakeLLM(oracle({"r2": ("lost", "")}))),
                       LLMJudge("c", FakeLLM(oracle())))
    out = judge_run(panel, tmp_path / "scenarios.jsonl", run)
    labels = list(read_jsonl(out, Label))
    report = agreement_report(labels, raters=["a", "b", "c", FINAL])
    ab = report["pairs"]["a vs b"]
    assert ab["n"] == 12 and ab["agreement"] == pytest.approx(10 / 12)
    assert ab["confusion"]["correct|lost"] == 2
    assert report["pairs"]["a vs final"]["kappa"] == 1.0
    assert report["tiebreak"] == {"items": 12, "disputed": 2, "rate": pytest.approx(2 / 12)}


def test_annotation_sample_is_blind_and_round_trips(tmp_path, pilot, summaries):
    sample, key = make_annotation_sample(pilot, summaries, n=8, seed=1)
    assert len(sample) == 8 and len({r["uid"] for r in sample}) == 8
    for row in sample:
        assert "condition" not in row and "model" not in row
        assert row["summary"] and row["history"][0]["role"] == "user"
        assert row["summary"].startswith("Context carried over from the earlier conversation:")
        assert "Summary of the earlier conversation:" not in row["summary"]  # neutral format
    assert make_annotation_sample(pilot, summaries, n=8, seed=1)[0] == sample
    # Two annotators label the sample as the page would save it.
    truth = {"sectioned": GOOD, "free": BAD}
    keyed = {k["uid"]: k for k in key}
    saved = []
    for ann in ("ana", "ben"):
        for row in sample:
            k = keyed[row["uid"]]
            lab = truth[k["condition"]][row["item_id"]][0]
            if ann == "ben" and row is sample[0]:
                lab = "lost" if lab != "lost" else "correct"
            saved.append({"uid": row["uid"], "annotator": ann, "label": lab, "quote": ""})
    write_rows(tmp_path / "human.jsonl", saved)
    write_rows(tmp_path / "key.jsonl", key)
    human = read_human_labels(tmp_path / "human.jsonl", tmp_path / "key.jsonl")
    assert {h.judge for h in human} == {"human:ana", "human:ben"}

    judge = [Label(scenario_id="pilot-05", condition=c, model="fake", repeat=0, judge=FINAL,
                   item_id=i, label=v[0]) for c, t in truth.items() for i, v in t.items()]
    check = human_check(human, judge, weights=sample_weights(tmp_path / "key.jsonl"))
    ana, ben = check["human_vs_judge"]["human:ana"], check["human_vs_judge"]["human:ben"]
    assert ana["unweighted_sample"]["kappa"] == 1.0 and ana["weighted_population"]["kappa"] == 1.0
    assert ben["unweighted_sample"]["agreement"] == pytest.approx(7 / 8)
    assert check["humans"]["human:ana vs human:ben"]["n"] == 8
    assert check["gate_on"] == "unweighted_sample"
    assert check["passes"] == (ben["unweighted_sample"]["kappa"] >= 0.7)


def test_off_type_labels_are_reasked_once_then_flagged(pilot):
    from inflatebench.judge import ALLOWED_LABELS

    s = pilot[2]
    types = {i.id: i.type for i in s.items}
    assert "hardened" not in ALLOWED_LABELS[types["o1"]] and "promoted" not in ALLOWED_LABELS[types["r1"]]
    off = GOOD | {"o1": ("hardened", GOOD["o1"][1]), "r1": ("promoted", GOOD["r1"][1])}

    fixed = FakeLLM([reply(off), reply(GOOD)])
    labels = LLMJudge("j1", fixed).label(s, GOOD_TEXT)
    assert len(fixed.calls) == 2
    reask = fixed.calls[1][-1].content
    assert "not allowed for the item's type" in reask and "o1 (one_off) is 'hardened'" in reask
    assert "allowed: correct, promoted, widened" in reask
    assert not any(l.type_flagged for l in labels)

    stubborn = FakeLLM([reply(off)])
    labels = LLMJudge("j1", stubborn).label(s, GOOD_TEXT)
    assert len(stubborn.calls) == 2  # one re-ask, then the label is kept and flagged
    flagged = {l.item_id: l.label for l in labels if l.type_flagged}
    assert flagged == {"o1": "hardened", "r1": "promoted"}
    assert not any(l.quote_flagged for l in labels)


def test_one_reask_covers_quotes_and_types_together(pilot):
    both = GOOD | {"o1": ("hardened", "Made-up quote.")}
    llm = FakeLLM([reply(both)])
    labels = LLMJudge("j1", llm).label(pilot[2], GOOD_TEXT)
    assert len(llm.calls) == 2
    reask = llm.calls[1][-1].content
    assert "not in the summary" in reask and "not allowed" in reask
    o1 = next(l for l in labels if l.item_id == "o1")
    assert o1.quote_flagged and o1.type_flagged


def test_panel_final_labels_keep_type_flags(pilot):
    off = GOOD | {"o1": ("hardened", GOOD["o1"][1])}
    panel = PanelJudge(LLMJudge("a", FakeLLM([reply(off)])), LLMJudge("b", FakeLLM([reply(GOOD)])),
                       LLMJudge("c", FakeLLM([reply(off)])))
    final = {l.item_id: l for l in panel.label(pilot[2], GOOD_TEXT) if l.judge == FINAL}
    assert final["o1"].label == "hardened" and final["o1"].type_flagged


def test_rubric_lists_allowed_labels_precedence_and_hides_turns(pilot):
    from inflatebench.judge import ALLOWED_LABELS, PRECEDENCE

    s = pilot[2]
    system, user = build_prompt(s, "SUMMARY")
    for item_type, allowed in ALLOWED_LABELS.items():
        assert f"- {item_type}: {', '.join(allowed)}" in system.content
    assert " > ".join(PRECEDENCE) in system.content
    assert "never listed as invented" in system.content
    rows = [json.loads(line) for line in user.content.split("\n\n")[0].splitlines()[1:]]
    for row in rows:
        assert row["allowed_labels"] == list(ALLOWED_LABELS[row["type"]])
        assert "(turn" not in row.get("scope", "")
    from inflatebench.generate import build_scenario

    gen = build_scenario("ops", 0)
    o1 = next(i for i in gen.items if i.type == "one_off")
    assert o1.scope.endswith(f"(turn {o1.turn})")  # the scenario keeps it; the judge does not see it
    shown = build_prompt(gen, "SUMMARY")[1].content
    assert o1.scope.rsplit(" (turn", 1)[0] in shown and f"(turn {o1.turn})" not in shown


def _pool(pilot, summaries, conditions, per_condition):
    """Summaries of many scenarios (clones of the pilot fixtures) under several conditions."""
    from dataclasses import replace

    scenarios = [replace(pilot[k % len(pilot)], id=f"syn-{k:03d}") for k in range(60)]
    base = summaries[0]
    summs = [replace(base, scenario_id=scenarios[k % 60].id, condition=c, repeat=k // 60)
             for c in conditions for k in range(per_condition[c])]
    return scenarios, summs


def test_annotation_sample_is_stratified_by_item_type_and_condition(pilot, summaries):
    from collections import Counter

    conds = ["free", "sectioned", "keep_rules", "extractor", "pinning"]
    scenarios, summs = _pool(pilot, summaries, conds, dict.fromkeys(conds, 60))
    sample, key = make_annotation_sample(scenarios, summs, n=200, seed=0)
    assert len(sample) == 200
    assert len({(k["scenario_id"], k["condition"], k["repeat"], k["item_id"]) for k in key}) == 200
    # Requests are a third of the pool (two per scenario), yet every item type gets 40 items.
    assert Counter(r["item_type"] for r in sample) == dict.fromkeys(
        ["one_off", "preference", "request", "hard_rule", "changed_value"], 40)
    cells = Counter((r["item_type"], k["condition"]) for r, k in zip(sample, key))
    assert len(cells) == 25 and max(cells.values()) - min(cells.values()) <= 1
    assert Counter(k["condition"] for k in key) == dict.fromkeys(conds, 40)
    # Weights reweight to the pool: pairs in the stratum over pairs drawn from it.
    for k in key:
        item_type = k["stratum"].split("/")[0]
        assert k["stratum"] == f"{item_type}/{k['condition']}"
        assert k["weight"] == pytest.approx((120 if item_type == "request" else 60) / cells[(item_type, k["condition"])])
    # Shuffled, so the order gives away neither the stratum nor the condition.
    assert [k["stratum"] for k in key] != sorted(k["stratum"] for k in key)
    assert make_annotation_sample(scenarios, summs, n=200, seed=0) == (sample, key)
    assert make_annotation_sample(scenarios, summs, n=200, seed=1)[1] != key


def test_annotation_sample_splits_equally_over_models(pilot, summaries):
    from collections import Counter
    from dataclasses import replace

    conds = ["free", "sectioned", "keep_rules", "extractor", "pinning", "free_limited",
             "sectioned_noconstraints"]
    scenarios, summs = _pool(pilot, summaries, conds, dict.fromkeys(conds, 60))
    # The local model has fewer summaries than main; each still gets half the sample.
    both = ([replace(s, model="main-m") for s in summs]
            + [replace(s, model="local-m") for s in summs[::3]])
    sample, key = make_annotation_sample(scenarios, both, n=200, seed=0)
    assert len(sample) == 200
    assert Counter(k["model"] for k in key) == {"main-m": 100, "local-m": 100}
    for model in ("main-m", "local-m"):
        rows = [(r, k) for r, k in zip(sample, key) if k["model"] == model]
        cells = Counter((r["item_type"], k["condition"]) for r, k in rows)
        assert len(cells) == 35 and max(cells.values()) - min(cells.values()) <= 1
        assert all(k["stratum"] == f"{model}/{r['item_type']}/{k['condition']}" for r, k in rows)
    # Weights stay pairs in the stratum over pairs drawn from it.
    pool = Counter((s.model, item.type, s.condition) for s in both
                   for item in next(x for x in scenarios if x.id == s.scenario_id).items)
    drawn = Counter(tuple(k["stratum"].split("/")) for k in key)
    assert all(k["weight"] == pytest.approx(pool[t] / drawn[t])
               for k in key for t in [tuple(k["stratum"].split("/"))])
    assert make_annotation_sample(scenarios, both, n=200, seed=0) == (sample, key)


def test_small_strata_pass_their_share_on(pilot, summaries):
    from collections import Counter

    # One condition has only 2 summaries (12 pairs): it gives what it has, the other takes the rest.
    scenarios, summs = _pool(pilot, summaries, ["free", "pinning"], {"free": 60, "pinning": 2})
    sample, key = make_annotation_sample(scenarios, summs, n=100, seed=3)
    assert len(sample) == 100
    by_cond = Counter(k["condition"] for k in key)
    assert by_cond["pinning"] == 12 and by_cond["free"] == 88
    # The 88 left are split evenly over the five item types of the other condition.
    free = Counter(r["item_type"] for r, k in zip(sample, key) if k["condition"] == "free")
    assert set(free.values()) <= {17, 18}
    # Asking for more than the pool holds returns the whole pool once.
    everything, _ = make_annotation_sample(scenarios, summs, n=10_000, seed=0)
    assert len(everything) == 62 * 6


def test_allocate_splits_evenly_within_capacity():
    import random

    from inflatebench.judge.run import allocate

    take = allocate({"a": 100, "b": 100, "c": 3}, 50, random.Random(0))
    assert take["c"] == 3 and {take["a"], take["b"]} <= {23, 24} and sum(take.values()) == 50
    assert allocate({"a": 2, "b": 1}, 10, random.Random(0)) == {"a": 2, "b": 1}
    assert allocate({"a": 5, "b": 5}, 0, random.Random(0)) == {"a": 0, "b": 0}


def test_per_label_kappa_is_one_label_against_the_rest():
    a = ["correct"] * 6 + ["promoted", "promoted", "hardened", "lost"]
    b = ["correct"] * 6 + ["promoted", "correct", "hardened", "hardened"]
    per = per_label_kappa(a, b)
    assert set(per) == {"correct", "promoted", "hardened", "lost"}  # labels either rater used
    # promoted: 2 by a, 1 by b, agreeing on 1 -> p_o = 0.9, p_e = 0.2*0.1 + 0.8*0.9 = 0.74
    assert per["promoted"] == pytest.approx((0.9 - 0.74) / (1 - 0.74))
    assert per["hardened"] == pytest.approx(cohen_kappa(
        [x if x == "hardened" else "other" for x in a], [y if y == "hardened" else "other" for y in b]))
    assert per["lost"] == 0.0  # only one rater ever used it
    # The common label agrees well, the rare ones do not: what the overall kappa hides.
    assert per["correct"] > per["promoted"]


def test_weighted_kappa_counts_items_by_weight():
    a, b = ["x", "x", "y", "y"], ["x", "y", "y", "y"]
    assert cohen_kappa(a, b, [1, 1, 1, 1]) == pytest.approx(cohen_kappa(a, b))
    # Weight 2 on an item is the same as listing it twice.
    assert cohen_kappa(a, b, [2, 1, 1, 1]) == pytest.approx(cohen_kappa(["x"] + a, ["x"] + b))
    with pytest.raises(ValueError):
        cohen_kappa(a, b, [1, 1])


def _labels(judge, labs, condition="free"):
    return [Label(scenario_id=f"s{k}", condition=condition, model="m", repeat=0, judge=judge,
                  item_id="o1", label=lab) for k, lab in enumerate(labs)]


def test_human_check_reports_unweighted_gate_and_weighted_population_estimate():
    # A stratified sample over-represents rare one-offs: 4 sampled items stand for few pool
    # pairs (weight 1) where the human and judge disagree on inflation, and 4 for many
    # (weight 10) where they agree on "correct".
    human = _labels("human:ana", ["promoted", "promoted", "widened", "correct"] + ["correct"] * 4)
    judge = _labels(FINAL, ["correct", "promoted", "promoted", "correct"] + ["correct"] * 4)
    weights = {(f"s{k}", "free", "m", 0, "o1"): (1.0 if k < 4 else 10.0) for k in range(8)}
    check = human_check(human, judge, weights=weights)
    pair = check["human_vs_judge"]["human:ana"]
    sample, population = pair["unweighted_sample"], pair["weighted_population"]
    assert sample["agreement"] == pytest.approx(6 / 8)
    assert population["agreement"] == pytest.approx(42 / 44)
    assert population["kappa"] > sample["kappa"]  # the pool is mostly easy agreement
    assert sample["per_label_kappa"]["promoted"] == pytest.approx(
        cohen_kappa(["p", "p", "o", "o", "o", "o", "o", "o"], ["o", "p", "p", "o", "o", "o", "o", "o"]))
    assert set(population["per_label_kappa"]) == {"correct", "promoted", "widened"}
    # The gate is on the unweighted sample kappa, and the result says so.
    assert check["gate_on"] == "unweighted_sample" and "gate" in check["basis"]["unweighted_sample"]
    assert check["passes"] == (sample["kappa"] >= 0.7)
    # Without weights there is no population estimate; with gaps in them, an error.
    assert human_check(human, judge)["human_vs_judge"]["human:ana"]["weighted_population"] is None
    with pytest.raises(ValueError, match="no sample weight"):
        human_check(human, judge, weights={k: w for k, w in list(weights.items())[:3]})


def test_agreement_report_gives_per_label_kappa_for_judge_pairs():
    a = _labels("a", ["correct", "promoted", "correct"])
    b = _labels("b", ["correct", "promoted", "hardened"])
    pair = agreement_report(a + b)["pairs"]["a vs b"]
    assert pair["per_label_kappa"]["promoted"] == 1.0 and "kappa" in pair
