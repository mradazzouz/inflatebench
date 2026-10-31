"""Bugs found in the independent review (REVIEW.md): outputs that used to pass silently."""

import json
from dataclasses import replace

import pytest

from inflatebench.analyze import analyze_run
from inflatebench.cli import main
from inflatebench.models import CachedLLM, DiskCache, FakeLLM
from inflatebench.models.cache import ReplyError
from inflatebench.schema import Message, Scenario, read_jsonl, write_jsonl
from test_batch import RecordingFake, compact, config, use_fake  # noqa: F401 - config is a fixture
from test_conditions import responder
from test_probe import PILOT


class BadReplies(RecordingFake):
    """Answers every free summary with `text` and stop reason `stop`, everything else normally."""

    def __init__(self, text, stop, **kw):
        super().__init__(responder, **kw)
        self.text, self.stop = text, stop

    def complete(self, messages, **kw):
        c = super().complete(messages, **kw)
        if "five headings" not in messages[0].content and "compacting" in messages[0].content:
            return replace(c, text=self.text, stop_reason=self.stop)
        return c


@pytest.mark.parametrize("text, stop", [("", "end_turn"), ("## Goal\nShip the rel", "max_tokens"),
                                        ("Shipped the release; next", "length")])
@pytest.mark.parametrize("batch", [True, False])
def test_empty_or_truncated_summaries_raise_instead_of_being_stored(config, monkeypatch, text, stop, batch):
    path, tmp = config
    use_fake(monkeypatch, BadReplies(text, stop))
    with pytest.raises(RuntimeError, match="empty reply|token limit"):
        compact(path, "--condition", "free", *([] if batch else ["--no-batch"]))
    assert not (tmp / "runs/r1/summaries.jsonl").exists()
    # Nothing unusable was cached: a rerun with a working model pays for the summaries again.
    good = RecordingFake(responder)
    use_fake(monkeypatch, good)
    assert compact(path, "--condition", "free", "--no-batch") == 0
    assert len(good.calls) == 2 * 2


def test_unusable_reply_already_in_the_cache_is_refused(tmp_path):
    cache = DiskCache(tmp_path)
    fake = FakeLLM(["fine"])
    llm = CachedLLM(fake, cache, model="m")
    request = llm.request([Message("user", "hi")])
    cache.put(request, replace(fake.complete(request.messages), stop_reason="max_tokens"))
    with pytest.raises(ReplyError, match="token limit"):
        llm.complete([Message("user", "hi")])


def test_agent_reply_cut_off_is_a_truncated_probe_not_an_uninflated_one(tmp_path):
    """A JSON tool call cut off mid-way parses as no call, which would count as not inflated;
    after one retry it is recorded as truncated, which the analysis leaves out."""
    from inflatebench.probe import probe_summary
    from inflatebench.schema import Summary

    scenario = next(s for s in read_jsonl(PILOT, Scenario) if s.probe.tool == "restart_worker")
    cut = FakeLLM(['{"tool": "restart_worker", "args": {"name": "w1", "fo'])
    cut.complete = lambda m, _c=cut.complete, **kw: replace(_c(m, **kw), stop_reason="max_tokens")
    agent = CachedLLM(cut, DiskCache(tmp_path), model="agent")
    summary = Summary(scenario.id, "free", "m", 0, [Message("system", "Summary: worker was restarted.")])
    res = probe_summary(agent, scenario, summary)
    assert res.truncated == "max_tokens" and res.retries == [0] and not res.tool_calls
    assert len(cut.calls) == 2 and not list(tmp_path.rglob("*.json"))  # retried once, never cached


def test_compact_rejects_a_condition_listed_twice(config, monkeypatch):
    path, tmp = config
    use_fake(monkeypatch, RecordingFake(responder))
    with pytest.raises(SystemExit, match="more than once"):
        compact(path, "--condition", "free", "--condition", "free")


@pytest.fixture
def pilot_config(config):
    """The batch tests' config, on two real pilot scenarios (their probes have mock tools)."""
    path, tmp = config
    write_jsonl(tmp / "scenarios.jsonl", list(read_jsonl(PILOT, Scenario))[:2])
    return path, tmp


def fake_run(path, *conditions):
    args = [a for c in conditions for a in ("--condition", c)]
    assert compact(path, *args) == 0
    for stage in ("judge", "probe"):
        assert main(["--config", str(path), stage, "--run-id", "r1", "--fake"]) == 0


def analyze(path):
    return main(["--config", str(path), "analyze", "--run-id", "r1", "--no-figures", "--n-boot", "10"])


def test_analyze_refuses_labels_and_probes_from_an_earlier_compact(pilot_config, monkeypatch):
    path, tmp = pilot_config
    use_fake(monkeypatch, RecordingFake(responder))
    fake_run(path, "free")
    assert analyze(path) == 0
    # Recompacting the run id replaces the summaries; the old labels and probes no longer apply.
    assert compact(path, "--condition", "sectioned") == 0
    with pytest.raises(SystemExit, match="do not match summaries.jsonl"):
        analyze(path)


@pytest.mark.parametrize("which, edit", [("labels", "drop"), ("labels", "duplicate"),
                                         ("probes", "drop"), ("probes", "duplicate")])
def test_analyze_refuses_partial_or_duplicated_labels_and_probes(pilot_config, monkeypatch, which, edit):
    path, tmp = pilot_config
    use_fake(monkeypatch, RecordingFake(responder))
    fake_run(path, "free", "pinning")
    f = tmp / f"runs/r1/{which}.jsonl"
    lines = f.read_text(encoding="utf-8").splitlines()
    final = next(k for k, line in enumerate(lines) if '"judge": "final"' in line or which == "probes")
    lines = lines[:final] + lines[final + 1:] if edit == "drop" else lines + [lines[final]]
    f.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="missing" if edit == "drop" else "duplicate"):
        analyze_run(tmp / "runs/r1", tmp / "scenarios.jsonl", n_boot=10, figures=False)


def test_analyze_of_a_single_judge_still_works(pilot_config, monkeypatch):
    """The coverage check uses the panel's final labels, so --judge on one judge is allowed."""
    path, tmp = pilot_config
    use_fake(monkeypatch, RecordingFake(responder))
    fake_run(path, "free")
    assert main(["--config", str(path), "analyze", "--run-id", "r1", "--judge", "fake-a",
                 "--no-figures", "--n-boot", "10"]) == 0
    assert json.loads((tmp / "runs/r1/report/summary.json").read_text(encoding="utf-8"))["judge"] == "fake-a"
