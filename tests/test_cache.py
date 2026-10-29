from inflatebench.models import CachedLLM, Completion, DiskCache, FakeLLM, Request
from inflatebench.schema import Message

MSGS = [Message("user", "summarise this")]


def test_request_key_is_stable_and_order_independent():
    a = Request(model="m", messages=MSGS, params={"temperature": 1, "max_tokens": 10})
    b = Request(model="m", messages=list(MSGS), params={"max_tokens": 10, "temperature": 1})
    assert a.key() == b.key()
    assert len(a.key()) == 64


def test_request_key_changes_with_content():
    base = Request(model="m", messages=MSGS)
    assert base.key() != Request(model="other", messages=MSGS).key()
    assert base.key() != Request(model="m", messages=[Message("user", "different")]).key()
    assert base.key() != Request(model="m", messages=MSGS, params={"max_tokens": 5}).key()


def test_disk_cache_get_put(tmp_path):
    cache = DiskCache(tmp_path)
    req = Request(model="m", messages=MSGS)
    assert cache.get(req) is None
    assert req not in cache
    done = Completion(text="hello", model="m", input_tokens=3, output_tokens=1, cost=0.01)
    cache.put(req, done)
    assert req in cache
    assert cache.get(req) == done
    assert not list(tmp_path.rglob("*.tmp"))


def test_disk_cache_persists_across_instances(tmp_path):
    req = Request(model="m", messages=MSGS)
    DiskCache(tmp_path).put(req, Completion(text="hello", model="m"))
    assert DiskCache(tmp_path).get(req).text == "hello"


def test_cached_llm_calls_provider_once(tmp_path):
    fake = FakeLLM(["first", "second"])
    llm = CachedLLM(fake, DiskCache(tmp_path), model="m")
    one = llm.complete(MSGS, max_tokens=10)
    two = llm.complete(MSGS, max_tokens=10)
    assert len(fake.calls) == 1
    assert one.text == two.text == "first"
    assert not one.cached and two.cached


def test_cached_llm_resumes_after_restart(tmp_path):
    CachedLLM(FakeLLM(["saved"]), DiskCache(tmp_path), model="m").complete(MSGS)
    fresh = FakeLLM(["new"])
    again = CachedLLM(fresh, DiskCache(tmp_path), model="m").complete(MSGS)
    assert again.text == "saved"
    assert fresh.calls == []


def test_cached_llm_misses_on_different_params(tmp_path):
    fake = FakeLLM(["a", "b"])
    llm = CachedLLM(fake, DiskCache(tmp_path), model="m")
    assert llm.complete(MSGS, max_tokens=10).text == "a"
    assert llm.complete(MSGS, max_tokens=20).text == "b"
    assert len(fake.calls) == 2
