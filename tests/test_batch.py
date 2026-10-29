"""Two-phase Batch API runs of ib compact and ib judge, with FakeLLM standing in for the API."""

import json
from pathlib import Path

import pytest
import yaml

from inflatebench import cli
from inflatebench.cli import main
from inflatebench.conditions._common import prompt
from inflatebench.judge import FINAL, LLMJudge, PanelJudge, judge_summaries
from inflatebench.models import CachedLLM, Deferred, DiskCache, FakeLLM, Pending, run_phases
from inflatebench.models.anthropic import AnthropicLLM
from inflatebench.schema import Message, Scenario, Summary, read_jsonl, write_jsonl
from test_conditions import SCENARIO, responder
from test_judge import oracle
from test_models import FakeAnthropic, no_sleep


class RecordingFake(FakeLLM):
    """FakeLLM that records the system prompt of every batched request, per batch."""

    def __init__(self, *args, log=None, crash_on_batch=None, **kw):
        super().__init__(*args, **kw)
        self.submitted: list[list[str]] = []
        self.handles: list[str] = []
        self.log = log if log is not None else []
        self.crash_on_batch = crash_on_batch  # batch index whose collection raises once

    def submit_batch(self, requests):
        self.submitted.append([r.messages[0].content for r in requests])
        self.log.append((self.model, len(requests)))
        handle = super().submit_batch(requests)
        self.handles.append(handle.id)
        return handle

    def batch_results(self, handle):
        if self.crash_on_batch is not None and handle.id in self.handles[self.crash_on_batch:][:1]:
            self.crash_on_batch = None
            raise KeyboardInterrupt("crash while waiting for the batch")
        return super().batch_results(handle)


@pytest.fixture
def config(tmp_path):
    scenarios = tmp_path / "scenarios.jsonl"
    # Distinct histories, so no request is shared between the two scenarios.
    other = {**SCENARIO, "id": "pilot-02",
             "history": SCENARIO["history"] + [{"role": "user", "content": "Also add SMS alerts."}]}
    write_jsonl(scenarios, [Scenario.from_dict(SCENARIO), Scenario.from_dict(other)])
    cfg = yaml.safe_load(Path("config.yaml").read_text())
    cfg["paths"].update(scenarios=str(scenarios), runs=str(tmp_path / "runs"), cache=str(tmp_path / "cache"))
    # The phase counts below are for the five main conditions (the ablations add single calls).
    cfg["conditions"] = ["free", "sectioned", "keep_rules", "extractor", "pinning"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path, tmp_path


def use_fake(monkeypatch, fake):
    monkeypatch.setattr(cli, "_make_llm", lambda cfg, key, is_fake, stage="compact": (fake, "fake"))


def compact(path, *extra):
    return main(["--config", str(path), "compact", "--run-id", "r1", "--repeats", "2", *extra])


def summaries(tmp):
    return sorted((s.scenario_id, s.condition, s.repeat, s.text)
                  for s in read_jsonl(tmp / "runs/r1/summaries.jsonl", Summary))


def test_compact_sends_first_calls_then_dependent_calls(config, monkeypatch, capsys):
    path, tmp = config
    fake = RecordingFake(responder)
    use_fake(monkeypatch, fake)
    assert compact(path) == 0
    assert "2 phases of batched calls" in capsys.readouterr().out
    first, second = fake.submitted
    # Phase 1: every condition's first call, 2 scenarios x 2 repeats; extractor's summary is
    # sectioned's request, so it is sent once.
    assert sorted(set(first)) == sorted({prompt("free"), prompt("sectioned"),
                                         prompt("sectioned") + "\n\n" + prompt("keep_rules"),
                                         prompt("pin_extract")})
    assert len(first) == 2 * 2 * 4
    # Phase 2: the extractor's constraint list and pinning's summary (of the history without
    # the pinned block, which is sectioned's request again, already answered).
    assert second == [prompt("extract")] * 4
    assert len(fake.calls) == 16 + 4  # every distinct call paid once

    rows = [json.loads(line) for line in (tmp / "runs/r1/calls.jsonl").read_text().splitlines()]
    assert len(rows) == 2 * 2 * (3 + 2 + 2)
    assert sum(not r["cached"] for r in rows) == 20 and all(r["batch"] or r["cached"] for r in rows)

    # Same summaries as single calls, from a fresh cache.
    batched = summaries(tmp)
    cfg = yaml.safe_load(path.read_text())
    cfg["paths"]["cache"] = str(tmp / "cache2")
    path.write_text(yaml.safe_dump(cfg))
    single = RecordingFake(responder)
    use_fake(monkeypatch, single)
    assert compact(path, "--no-batch") == 0
    assert single.submitted == [] and len(single.calls) == 20
    assert summaries(tmp) == batched


def test_compact_resumes_a_crashed_second_phase_without_paying_twice(config, monkeypatch):
    path, tmp = config
    fake = RecordingFake(responder, crash_on_batch=1)
    use_fake(monkeypatch, fake)
    with pytest.raises(KeyboardInterrupt):
        compact(path)
    assert len(fake.submitted) == 2 and len(fake.calls) == 20
    assert len(list((tmp / "cache/_batches").glob("*.json"))) == 1  # phase 2's batch id

    # Rerun: phase 1 comes from the disk cache, phase 2 from the recorded batch.
    assert compact(path) == 0
    assert len(fake.submitted) == 2 and len(fake.calls) == 20
    assert not list((tmp / "cache/_batches").glob("*.json"))
    assert len(summaries(tmp)) == 2 * 5 * 2


def test_compact_single_calls_through_openai_compatible(config, monkeypatch):
    """`local` (Ollama, no batch API) still runs, one call at a time, in the same phases."""
    from inflatebench.models import openai_compatible

    path, tmp = config
    sent = []

    def transport(url, headers, body):
        sent.append(body)
        text = responder([Message(**body["messages"][0])])
        return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {}}

    monkeypatch.setattr(openai_compatible, "urllib_transport", lambda: transport)
    assert compact(path, "--model", "local") == 0
    assert len(sent) == 20 and all(b["model"] == "llama3.1:8b" for b in sent)
    assert len(summaries(tmp)) == 2 * 5 * 2
    assert compact(path, "--model", "local") == 0  # rerun from cache
    assert len(sent) == 20


def panel(tmp_path, batch=True, crash_tie=False):
    log = []
    cache = DiskCache(tmp_path / "cache")

    def judge(name, respond, **kw):
        fake = RecordingFake(respond, model=name, log=log, **kw)
        return LLMJudge(name, Deferred(CachedLLM(fake, cache, model=name), batch=batch)), fake

    a, fa = judge("a", oracle())
    good, widened = oracle(), oracle({"o1": ("widened", "Disable the canary step in deployments.")})
    # b agrees with a on the good summary and disputes o1 on the bad one.
    b, fb = judge("b", lambda m: widened(m) if "stg-eu-2 for staging" in m[1].content else good(m))
    c, fc = judge("c", oracle(), crash_on_batch=0 if crash_tie else None)
    return PanelJudge(a, b, c), (fa, fb, fc), log


def test_judge_sends_both_judges_then_only_tiebreaks(tmp_path, pilot, summaries):
    p, (fa, fb, fc), log = panel(tmp_path)
    labels = judge_summaries(p, pilot, summaries)
    # Phase 1: both judges score both summaries; phase 2: the tie-break on the disputed one.
    assert log[:2] in ([("a", 2), ("b", 2)], [("b", 2), ("a", 2)]) and log[2:] == [("c", 1)]
    assert "stg-eu-2 for staging" in fc.calls[0][1].content  # the bad summary is disputed

    reference, _, _ = panel(tmp_path / "plain")
    for j in reference.judges:  # same judges on their plain cached LLMs, no phases
        j.llm = j.llm.llm
    assert labels == judge_summaries(reference, pilot, summaries)
    final = {(l.condition, l.item_id): l.label for l in labels if l.judge == FINAL}
    assert final[("free", "o1")] == "promoted"


def test_judge_without_batch_makes_single_calls(tmp_path, pilot, summaries):
    p, fakes, log = panel(tmp_path, batch=False)
    judge_summaries(p, pilot, summaries)
    assert log == [] and [len(f.calls) for f in fakes] == [2, 2, 1]


def test_judge_resumes_crashed_tiebreak_phase(tmp_path, pilot, summaries):
    p, fakes, log = panel(tmp_path, crash_tie=True)
    with pytest.raises(KeyboardInterrupt):
        judge_summaries(p, pilot, summaries)
    p2, _, _ = panel(tmp_path)
    for old, new in zip(p.judges, p2.judges):
        new.llm.llm.llm = old.llm.llm.llm  # same provider (its batches), fresh run
    judge_summaries(p2, pilot, summaries)
    assert len(log) == 3 and [len(f.calls) for f in fakes] == [2, 2, 1]


def test_cli_judge_fake_batches(config, monkeypatch):
    path, tmp = config
    use_fake(monkeypatch, RecordingFake(responder))
    compact(path)
    assert main(["--config", str(path), "judge", "--run-id", "r1", "--fake"]) == 0
    batched = (tmp / "runs/r1/labels.jsonl").read_text()
    calls = (tmp / "runs/r1/judge_calls.jsonl").read_text().splitlines()
    paid = [json.loads(c) for c in calls if not json.loads(c)["cached"]]
    assert paid and all(c["batch_id"] and c["batch"] for c in paid)
    assert main(["--config", str(path), "judge", "--run-id", "r1", "--fake", "--no-batch"]) == 0
    assert (tmp / "runs/r1/labels.jsonl").read_text() == batched


def test_deferred_queues_misses_and_hands_fresh_results_over_once(tmp_path):
    llm = CachedLLM(FakeLLM(lambda m: m[-1].content.upper()), DiskCache(tmp_path), model="f")
    d = Deferred(llm)
    with pytest.raises(Pending):
        d.complete([Message("user", "a")])
    assert run_phases(lambda: None, [d]) == 1
    first = d.complete([Message("user", "a")])
    again = d.complete([Message("user", "a")])
    assert first.text == "A" and first.batch and not first.cached and again.cached
    assert llm.usage.calls == 2 and llm.usage.cache_hits == 1


def test_anthropic_batch_sends_the_provider_model_not_the_cache_label(tmp_path):
    client = FakeAnthropic()
    d = Deferred(CachedLLM(AnthropicLLM("m", client=client), DiskCache(tmp_path), model="m"))
    views = [d.view(f"m#repeat{i}") for i in range(2)]

    def step():
        for v in views:
            try:
                v.complete([Message("user", "hi")])
            except Pending:
                pass

    run_phases(step, views, sleep=no_sleep, poll_interval=0)
    (body,) = client.batches.values()  # both repeats in one batch
    assert len(body) == 2 and {r["params"]["model"] for r in body} == {"m"}
