import os
import threading

import pytest

from inflatebench.models import BatchHandle, CachedLLM, Completion, DiskCache, FakeLLM, Request
from inflatebench.models import cache as cache_mod
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


def test_fake_batch_ids_are_unique_per_model_and_call():
    reqs = [Request(model="m", messages=MSGS)]
    ids = [llm.submit_batch(reqs).id for llm in (FakeLLM(model="a"), FakeLLM(model="a"), FakeLLM(model="b"))
           for _ in range(2)]
    assert len(set(ids)) == len(ids)


def test_concurrent_batch_writers_with_distinct_handles_never_collide(tmp_path, monkeypatch):
    # Ids that differ only in case, or only in characters unsafe in file names, must still
    # map to distinct files (Windows file names are case-insensitive).
    ids = ["batch_Ab", "batch_aB", "a/b", "a:b", "a?b"] + [f"fake-batch-{i}" for i in range(15)]
    cache = DiskCache(tmp_path)
    targets: list[str] = []
    real_replace = os.replace
    monkeypatch.setattr(cache_mod.os, "replace", lambda src, dst: (targets.append(str(dst).lower()),
                                                                   real_replace(src, dst))[1])
    start = threading.Barrier(len(ids))

    def write(i: int, bid: str) -> None:
        start.wait()
        cache.save_pending(BatchHandle(bid, 1), [Request(model="m", messages=MSGS, params={"repeat": i})])

    threads = [threading.Thread(target=write, args=(i, bid)) for i, bid in enumerate(ids)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(targets)) == len(targets) == len(ids)
    pending = {h.id: reqs[0].params["repeat"] for h, reqs in cache.pending()}
    assert pending == {bid: i for i, bid in enumerate(ids)}
    for bid in ids:
        cache.drop_pending(BatchHandle(bid, 1))
    assert list(cache.pending()) == []


def test_write_atomic_retries_replace_on_permission_error(tmp_path, monkeypatch):
    real_replace = os.replace
    failures = iter([PermissionError(13, "locked"), PermissionError(13, "locked")])

    def flaky(src, dst):
        err = next(failures, None)
        if err:
            raise err
        real_replace(src, dst)

    monkeypatch.setattr(cache_mod.os, "replace", flaky)
    monkeypatch.setattr(cache_mod.time, "sleep", lambda _: None)
    cache_mod._write_atomic(tmp_path / "x.json", {"a": 1})
    assert (tmp_path / "x.json").read_text(encoding="utf-8") == '{"a": 1}'

    monkeypatch.setattr(cache_mod.os, "replace", lambda *_: (_ for _ in ()).throw(PermissionError(13, "locked")))
    with pytest.raises(PermissionError):
        cache_mod._write_atomic(tmp_path / "y.json", {"a": 1})
    assert not list(tmp_path.glob("*.tmp"))  # the temp file is cleaned up


def test_drop_pending_removes_records_named_by_bare_id(tmp_path):
    handle = BatchHandle("old-batch", 1)
    legacy = tmp_path / "_batches" / "old-batch.json"
    legacy.parent.mkdir()
    legacy.write_text('{"id": "old-batch", "size": 1, "requests": []}')
    DiskCache(tmp_path).drop_pending(handle)
    assert not legacy.exists()
