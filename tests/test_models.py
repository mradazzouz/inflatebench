import importlib.util
import json
from types import SimpleNamespace as NS

import pytest
import yaml

from inflatebench.cli import main
from inflatebench.models import (
    BatchError,
    BatchHandle,
    CachedLLM,
    Completion,
    DiskCache,
    FakeLLM,
    Prices,
    Request,
    UsageLog,
    from_config,
    retry,
)
from inflatebench.models.anthropic import AnthropicLLM
from inflatebench.models.chat import to_chat
from inflatebench.models.openai_compatible import HTTPStatusError, OpenAICompatibleLLM
from inflatebench.schema import Message

HISTORY = [
    Message("system", "You compact histories."),
    Message("user", "Never edit legacy/."),
    Message("tool", "ls: a.py b.py"),
    Message("user", "Summarise the session."),
]
PRICES = Prices({"m": {"input": 1.0, "output": 5.0}})
# Most Anthropic tests use a fake client; only building a real one needs the optional SDK.
needs_anthropic_sdk = pytest.mark.skipif(
    importlib.util.find_spec("anthropic") is None,
    reason="optional anthropic package not installed (pip install -e '.[dev]')",
)


class StatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def no_sleep(_):
    pass


# --- pricing, retries, usage, chat format -------------------------------------------------


def test_prices_cost_defaults_and_batch_discount():
    p = PRICES.get("m")
    assert (p.cache_write, p.cache_read, p.batch_discount) == (1.25, 0.1, 0.5)
    assert PRICES.cost("m", input_tokens=1_000_000, output_tokens=1_000_000) == pytest.approx(6.0)
    assert PRICES.cost("m", cache_write_tokens=1_000_000, cache_read_tokens=1_000_000) == pytest.approx(1.35)
    assert PRICES.cost("m", input_tokens=1_000_000, batch=True) == pytest.approx(0.5)
    assert PRICES.cost("unpriced", input_tokens=10**9) == 0.0
    with pytest.raises(ValueError):
        Prices({"m": {"input": 1, "output": 1, "typo": 2}})


def test_retry_backs_off_on_transient_errors():
    errors = [StatusError(529), StatusError(429), ConnectionError("reset")]
    delays = []

    def flaky():
        if errors:
            raise errors.pop(0)
        return "done"

    assert retry(flaky, sleep=delays.append) == "done"
    assert len(delays) == 3 and all(d <= 60 for d in delays)


def test_retry_does_not_retry_client_errors_and_gives_up():
    calls = []

    def bad():
        calls.append(1)
        raise StatusError(400)

    with pytest.raises(StatusError):
        retry(bad, sleep=no_sleep)
    assert len(calls) == 1

    calls.clear()

    def down():
        calls.append(1)
        raise StatusError(503)

    with pytest.raises(StatusError):
        retry(down, attempts=3, sleep=no_sleep)
    assert len(calls) == 3


def test_to_chat_moves_system_and_marks_tool_output():
    system, turns = to_chat(HISTORY)
    assert system == "You compact histories."
    assert [t["role"] for t in turns] == ["user", "user", "user"]
    assert turns[1]["content"].startswith("[tool output]") and "a.py" in turns[1]["content"]


def test_usage_log_writes_jsonl_and_totals(tmp_path):
    path = tmp_path / "calls.jsonl"
    usage = UsageLog(path)
    usage.record(Completion("t", "m", input_tokens=10, output_tokens=2, cost=0.5, date="d"), key="k1")
    usage.record(Completion("t", "m", input_tokens=10, output_tokens=2, cost=0.5, cached=True), key="k1")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["cached"] for r in rows] == [False, True]
    assert rows[0]["model"] == "m" and rows[0]["input_tokens"] == 10 and rows[0]["date"] == "d"
    assert "text" not in rows[0]
    assert usage.summary() == {"calls": 2, "cache_hits": 1, "input_tokens": 10, "output_tokens": 2,
                               "cache_write_tokens": 0, "cache_read_tokens": 0, "cost": 0.5}


# --- Anthropic ------------------------------------------------------------------------------


def message(text="summary", inp=100, out=20, cw=0, cr=0):
    return NS(
        content=[NS(type="thinking", thinking=""), NS(type="text", text=text)],
        model="m",
        stop_reason="end_turn",
        usage=NS(input_tokens=inp, output_tokens=out, cache_creation_input_tokens=cw, cache_read_input_tokens=cr),
    )


class FakeAnthropic:
    """Mimics the parts of anthropic.Anthropic the provider uses."""

    def __init__(self, failures=()):
        self.failures = list(failures)
        self.created = []
        self.batches = {}
        self.outcomes = {}  # custom_id -> result namespace, overrides success
        self.messages = NS(create=self._create, batches=NS(
            create=self._batch_create, retrieve=self._retrieve, results=self._results))
        self.polls = 0

    def _create(self, **params):
        if self.failures:
            raise self.failures.pop(0)
        self.created.append(params)
        return message()

    def _batch_create(self, requests):
        bid = f"msgbatch_{len(self.batches)}"
        self.batches[bid] = list(requests)
        return NS(id=bid, processing_status="in_progress")

    def _retrieve(self, bid):
        self.polls += 1
        return NS(id=bid, processing_status="ended" if self.polls > 1 else "in_progress")

    def _results(self, bid):
        for r in self.batches[bid]:
            cid = r["custom_id"]
            yield NS(custom_id=cid, result=self.outcomes.pop(cid, NS(type="succeeded", message=message(cid[:4]))))


def test_anthropic_params_use_prompt_caching_and_strip_repeat():
    llm = AnthropicLLM("m", client=FakeAnthropic(), max_tokens=512)
    p = llm.params(HISTORY, {"repeat": 2, "temperature": 0.5})
    assert "repeat" not in p and p["temperature"] == 0.5 and p["max_tokens"] == 512
    assert p["system"] == [{"type": "text", "text": "You compact histories.", "cache_control": {"type": "ephemeral"}}]
    marked = ["cache_control" in m["content"][-1] for m in p["messages"]]
    assert marked == [False, True, True]
    assert sum(marked) + 1 <= 4  # API limit on breakpoints

    no_cache = AnthropicLLM("m", client=FakeAnthropic(), prompt_cache=False).params(HISTORY, {})
    assert "cache_control" not in json.dumps(no_cache)
    ttl = AnthropicLLM("m", client=FakeAnthropic(), cache_ttl="1h").params(HISTORY, {})
    assert ttl["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_anthropic_complete_logs_tokens_and_cost_and_retries():
    client = FakeAnthropic(failures=[StatusError(529)])
    client.messages.create = lambda **p: message(inp=1_000_000, out=1_000_000, cw=1_000_000, cr=1_000_000)
    llm = AnthropicLLM("m", client=client, prices=PRICES, sleep=no_sleep)
    c = llm.complete(HISTORY)
    assert c.text == "summary" and c.stop_reason == "end_turn" and not c.batch
    assert (c.input_tokens, c.output_tokens, c.cache_write_tokens, c.cache_read_tokens) == (10**6,) * 4
    assert c.cost == pytest.approx(1 + 5 + 1.25 + 0.1)
    assert c.date

    flaky = FakeAnthropic(failures=[StatusError(529), StatusError(500)])
    assert AnthropicLLM("m", client=flaky, sleep=no_sleep).complete(HISTORY).text == "summary"
    with pytest.raises(StatusError):
        AnthropicLLM("m", client=FakeAnthropic(failures=[StatusError(400)]), sleep=no_sleep).complete(HISTORY)


def test_anthropic_batch_through_cached_llm(tmp_path):
    client = FakeAnthropic()
    llm = CachedLLM(AnthropicLLM("m", client=client, prices=PRICES), DiskCache(tmp_path), model="anthropic:m")
    reqs = [llm.request(HISTORY, repeat=i) for i in range(3)]
    out = llm.run_batch(reqs + [reqs[0]], sleep=no_sleep)
    assert [c.text for c in out] == [r.key()[:4] for r in reqs] + [reqs[0].key()[:4]]
    assert all(c.batch for c in out)
    (body,) = client.batches.values()
    assert len(body) == 3  # duplicates are sent once
    assert all("repeat" not in r["params"] and len(r["custom_id"]) == 64 for r in body)
    assert not list((tmp_path / "_batches").glob("*.json"))
    assert llm.usage.calls == 3
    # A rerun is served entirely from disk.
    again = CachedLLM(AnthropicLLM("m", client=FakeAnthropic()), DiskCache(tmp_path), model="anthropic:m")
    assert [c.text for c in again.run_batch(reqs, sleep=no_sleep)] == [c.text for c in out[:3]]
    assert again.llm.client.batches == {}
    # So is a single call for the same request.
    assert again.complete(HISTORY, repeat=1).cached


def test_batch_resubmits_transient_failures_and_raises_on_invalid(tmp_path):
    client = FakeAnthropic()
    llm = CachedLLM(AnthropicLLM("m", client=client), DiskCache(tmp_path), model="anthropic:m")
    reqs = [llm.request(HISTORY, repeat=i) for i in range(2)]
    client.outcomes[reqs[0].key()] = NS(type="expired")
    client.outcomes[reqs[1].key()] = NS(type="errored", error=NS(type="error", error=NS(type="overloaded_error", message="busy")))
    assert len(llm.run_batch(reqs, sleep=no_sleep)) == 2
    assert [len(b) for b in client.batches.values()] == [2, 2]

    bad = llm.request(HISTORY, repeat=9)
    client.outcomes[bad.key()] = NS(type="errored", error=NS(type="error", error=NS(type="invalid_request_error", message="no")))
    with pytest.raises(RuntimeError, match="cannot succeed"):
        llm.run_batch([bad], sleep=no_sleep)


def test_batch_resumes_after_crash(tmp_path):
    client = FakeAnthropic()
    provider = AnthropicLLM("m", client=client)
    cache = DiskCache(tmp_path)
    first = CachedLLM(provider, cache, model="anthropic:m")
    reqs = [first.request(HISTORY, repeat=i) for i in range(2)]
    # Simulate a crash after submitting: the batch is recorded but never collected.
    handle = provider.submit_batch(reqs)
    cache.save_pending(handle, reqs)

    provider.submit_batch = lambda _: pytest.fail("resubmitted a batch that was already paid for")
    out = CachedLLM(provider, DiskCache(tmp_path), model="anthropic:m").run_batch(reqs, sleep=no_sleep)
    assert [c.text for c in out] == [r.key()[:4] for r in reqs]
    assert list(cache.pending()) == []


def test_fake_llm_batches_through_cached_llm(tmp_path):
    llm = CachedLLM(FakeLLM(lambda m: m[-1].content.upper()), DiskCache(tmp_path), model="fake")
    reqs = [llm.request([Message("user", w)]) for w in ("a", "b")]
    assert [c.text for c in llm.run_batch(reqs)] == ["A", "B"]


# --- OpenAI-compatible / Ollama -------------------------------------------------------------


def ollama_reply(text="local summary"):
    return {
        "model": "llama3.1:8b",
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 7},
    }


def test_openai_compatible_talks_to_ollama_without_a_key():
    sent = []

    def transport(url, headers, body):
        sent.append((url, headers, body))
        return ollama_reply()

    llm = OpenAICompatibleLLM("llama3.1:8b", transport=transport)
    c = llm.complete(HISTORY, repeat=1)
    url, headers, body = sent[0]
    assert url == "http://localhost:11434/v1/chat/completions"
    assert "Authorization" not in headers
    assert body["model"] == "llama3.1:8b" and "repeat" not in body and "max_tokens" not in body
    assert body["messages"][0] == {"role": "system", "content": "You compact histories."}
    assert [m["role"] for m in body["messages"]] == ["system", "user", "user", "user"]
    assert (c.text, c.input_tokens, c.output_tokens, c.cost, c.stop_reason) == ("local summary", 50, 7, 0.0, "stop")


def test_openai_compatible_key_from_env_cost_and_retry(monkeypatch):
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TEST_LLM_KEY"):
        OpenAICompatibleLLM("m", base_url="https://api.example.com/v1", api_key_env="TEST_LLM_KEY")
    monkeypatch.setenv("TEST_LLM_KEY", "sk-test")
    failures = [HTTPStatusError(429, "slow down"), ConnectionError("refused")]
    seen = []

    def transport(url, headers, body):
        seen.append(headers)
        if failures:
            raise failures.pop(0)
        reply = ollama_reply()
        reply["usage"] = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000,
                          "prompt_tokens_details": {"cached_tokens": 400_000}}
        return reply

    llm = OpenAICompatibleLLM("m", base_url="https://api.example.com/v1/", api_key_env="TEST_LLM_KEY",
                              prices=PRICES, transport=transport, sleep=no_sleep)
    c = llm.complete(HISTORY)
    assert seen[-1]["Authorization"] == "Bearer sk-test" and len(seen) == 3
    assert (c.input_tokens, c.cache_read_tokens) == (600_000, 400_000)
    assert c.cost == pytest.approx(0.6 + 5 + 0.04)

    def reject(url, headers, body):
        raise HTTPStatusError(404, "model not found")

    with pytest.raises(HTTPStatusError):
        OpenAICompatibleLLM("m", transport=reject, sleep=no_sleep).complete(HISTORY)


def test_openai_compatible_run_batch_is_sequential_and_resumable(tmp_path):
    replies = []

    def transport(url, headers, body):
        replies.append(body)
        if len(replies) == 2:
            raise HTTPStatusError(400, "bad request")
        return ollama_reply(f"r{len(replies)}")

    llm = CachedLLM(OpenAICompatibleLLM("llama3.1:8b", transport=transport), DiskCache(tmp_path), model="ollama")
    reqs = [llm.request(HISTORY, repeat=i) for i in range(3)]
    with pytest.raises(HTTPStatusError):
        llm.run_batch(reqs)
    # The first call was cached before the crash, so the rerun only makes the remaining two.
    out = llm.run_batch(reqs)
    assert [c.text for c in out] == ["r1", "r3", "r4"]
    assert out[0].cached and len(replies) == 4


# --- config factory and CLI -----------------------------------------------------------------


def test_from_config_builds_cached_logged_provider(tmp_path, monkeypatch):
    cfg = {
        "models": {"t": {"provider": "fake", "name": "f", "responses": ["hi"]},
                   "todo": {"provider": "anthropic", "name": "CHANGE_ME"},
                   "claude": {"provider": "anthropic", "name": "m"}},
        "paths": {"cache": str(tmp_path / "cache")},
    }
    llm = from_config(cfg, "t", usage_path=tmp_path / "calls.jsonl")
    assert llm.complete([Message("user", "x")]).text == "hi"
    assert (tmp_path / "calls.jsonl").exists()
    with pytest.raises(ValueError, match="set its name"):
        from_config(cfg, "todo")
    with pytest.raises(KeyError):
        from_config(cfg, "missing")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        from_config(cfg, "claude")


def scenario(i, history_chars=4000):
    return {"id": f"s-{i}", "domain": "ops", "seed": i, "length": "short", "cue": "explicit", "items": [],
            "history": [{"role": "user", "content": "x" * history_chars}], "next_task": "t",
            "probe": {"tool": "t", "inflated_if": {}}}


def test_compact_dry_run_estimates_cost(tmp_path, capsys):
    scen = tmp_path / "s.jsonl"
    scen.write_text("".join(json.dumps(scenario(i)) + "\n" for i in range(10)))
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["models"]["main"]["name"] = "m"
    cfg["models"]["strong"]["name"] = "m"
    cfg["models"]["strong"]["subset"] = 4
    cfg["prices"] = {"m": {"input": 1.0, "output": 5.0}}
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))

    assert main(["--config", str(cfg_path), "compact", "--run-id", "r", "--dry-run", "--scenarios", str(scen)]) == 0
    out = capsys.readouterr().out
    # 10 scenarios x (1+1+1+2+2) calls x 3 repeats; (1000 + 400) input and 1000 output tokens per call.
    assert "model calls:   210" in out
    assert "input tokens:  ~294,000" in out and "output tokens: ~210,000" in out
    assert "$0.67 (batch discount applied)" in out  # (0.294 + 1.05) / 2

    assert main(["--config", str(cfg_path), "compact", "--run-id", "r", "--dry-run", "--scenarios", str(scen),
                 "--model", "strong", "--condition", "free"]) == 0
    out = capsys.readouterr().out
    assert "scenarios:     4" in out and "model calls:   12" in out and "batch discount" not in out


def test_compact_dry_run_without_price_or_scenarios(tmp_path, capsys):
    scen = tmp_path / "s.jsonl"
    scen.write_text(json.dumps(scenario(0)) + "\n")
    assert main(["compact", "--run-id", "r", "--dry-run", "--scenarios", str(scen)]) == 0
    assert "unknown: add 'CHANGE_ME' under prices" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="not found"):
        main(["compact", "--run-id", "r", "--dry-run", "--scenarios", str(tmp_path / "none.jsonl")])
    with pytest.raises(SystemExit, match="no model 'nope'"):
        main(["compact", "--run-id", "r", "--dry-run", "--model", "nope", "--scenarios", str(scen)])


def test_batch_error_and_handle_types():
    assert BatchError("x").retryable and not BatchError("x", retryable=False).retryable
    assert BatchHandle("id", 1).size == 1
    assert Request.from_dict(Request("m", HISTORY, {"repeat": 1}).to_dict()) == Request("m", HISTORY, {"repeat": 1})


# --- cache key covers provider settings; make_llm; ib compact through a configured provider --


def test_changing_provider_settings_misses_the_cache(tmp_path):
    def cached(**kw):
        return CachedLLM(AnthropicLLM(kw.pop("model", "m"), client=FakeAnthropic(), **kw), DiskCache(tmp_path), model="label")

    first = cached(max_tokens=512)
    assert not first.complete(HISTORY).cached
    assert cached(max_tokens=512).complete(HISTORY).cached
    assert not cached(max_tokens=1024).complete(HISTORY).cached  # new setting, new answer
    assert not cached(model="other", max_tokens=512).complete(HISTORY).cached  # same label, other model
    assert cached(max_tokens=512, prompt_cache=False).complete(HISTORY).cached  # caching changes cost only

    def ollama(url):
        return CachedLLM(OpenAICompatibleLLM("llama3.1:8b", base_url=url, transport=lambda *a: ollama_reply()),
                         DiskCache(tmp_path), model="local")

    assert not ollama("http://a/v1").complete(HISTORY).cached
    assert not ollama("http://b/v1").complete(HISTORY).cached
    assert ollama("http://a/v1").complete(HISTORY).cached


def test_run_batch_keys_requests_by_provider_settings(tmp_path):
    llm = CachedLLM(FakeLLM(["x"]), DiskCache(tmp_path), model="fake")
    bare = Request("fake", [Message("user", "hi")])  # built without settings
    llm.run_batch([bare])
    assert llm.complete([Message("user", "hi")]).cached
    other = CachedLLM(FakeLLM(["y"], model="other"), DiskCache(tmp_path), model="fake")
    assert other.run_batch([bare])[0].text == "y"


def test_make_llm_builds_each_provider(monkeypatch):
    from inflatebench.models import make_llm

    fake = make_llm({"provider": "fake", "name": "f", "responses": ["hi"]})
    assert fake.complete([Message("user", "x")]).text == "hi"
    local = make_llm({"provider": "openai_compatible", "name": "llama3.1:8b", "base_url": "http://localhost:11434/v1"},
                     {"llama3.1:8b": {"input": 0, "output": 0}})
    assert isinstance(local, OpenAICompatibleLLM) and local.url == "http://localhost:11434/v1/chat/completions"
    with pytest.raises(ValueError, match="set its name"):
        make_llm({"provider": "anthropic", "name": "CHANGE_ME"})
    with pytest.raises(ValueError, match="provider"):
        make_llm({"provider": "nope", "name": "x"})


@needs_anthropic_sdk
def test_make_llm_builds_anthropic_provider(monkeypatch):
    from inflatebench.models import make_llm

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    claude = make_llm({"provider": "anthropic", "name": "m", "max_tokens": 256}, {"m": {"input": 1, "output": 5}})
    assert isinstance(claude, AnthropicLLM) and claude.max_tokens == 256 and "m" in claude.prices


def compact_config(tmp_path, main_model):
    scen = tmp_path / "s.jsonl"
    scen.write_text("".join(json.dumps(scenario(i, 40)) + "\n" for i in range(5)))
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["models"]["main"] = main_model
    cfg["paths"].update(scenarios=str(scen), runs=str(tmp_path / "runs"), cache=str(tmp_path / "cache"))
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return str(path)


def test_ib_compact_runs_the_configured_provider_without_fake(tmp_path):
    path = compact_config(tmp_path, {"provider": "fake", "name": "f", "responses": ["NONE"], "subset": 3})
    assert main(["--config", path, "compact", "--run-id", "r", "--condition", "free", "--repeats", "1"]) == 0
    lines = (tmp_path / "runs/r/summaries.jsonl").read_text().splitlines()
    assert len(lines) == 3  # the model's subset
    assert all(json.loads(line)["model"] == "f" for line in lines)
    calls = [json.loads(line) for line in (tmp_path / "runs/r/calls.jsonl").read_text().splitlines()]
    assert {"cache_write_tokens", "cache_read_tokens", "cost"} <= set(calls[0])


def test_ib_compact_reports_unconfigured_provider(tmp_path, monkeypatch):
    path = compact_config(tmp_path, {"provider": "anthropic", "name": "CHANGE_ME"})
    with pytest.raises(SystemExit, match="set its name"):
        main(["--config", path, "compact", "--run-id", "r"])
    path = compact_config(tmp_path, {"provider": "anthropic", "name": "m"})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        main(["--config", path, "compact", "--run-id", "r"])
