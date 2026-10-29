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
    quote_in_summary,
    read_human_labels,
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


def test_llm_judge_retries_then_fails(pilot):
    llm = FakeLLM(["garbage", reply(GOOD)])
    labels = LLMJudge("j1", llm).label(pilot[2], "text")
    assert len(llm.calls) == 2
    assert "invalid" in llm.calls[1][-1].content
    assert {l.label for l in labels} == {"correct"}
    with pytest.raises(JudgeError):
        LLMJudge("j1", FakeLLM(["garbage"]), retries=1).label(pilot[2], "text")


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
    check = human_check(human, judge)
    assert check["human_vs_judge"]["human:ana"]["kappa"] == 1.0
    assert check["human_vs_judge"]["human:ben"]["agreement"] == pytest.approx(7 / 8)
    assert check["humans"]["human:ana vs human:ben"]["n"] == 8
    assert check["passes"] == (check["human_vs_judge"]["human:ben"]["kappa"] >= 0.7)
