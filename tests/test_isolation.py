"""Tests run the same with or without real provider keys, and never reach a provider."""

import os
import socket
import urllib.request

import pytest
from conftest import PROVIDER_ENV, NetworkBlocked

from inflatebench.cli import main
from inflatebench.models.openai_compatible import OpenAICompatibleLLM
from inflatebench.schema import Message


def test_provider_keys_are_cleared_for_every_test():
    for name in PROVIDER_ENV + ("SOME_PROVIDER_API_KEY",):
        assert name not in os.environ, name
    assert not [k for k in os.environ if k.endswith(("_API_KEY", "_AUTH_TOKEN"))]


def test_a_test_may_still_set_a_fake_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test"


@pytest.mark.parametrize("family, address", [(socket.AF_INET, ("127.0.0.1", 11434)),
                                             (socket.AF_INET, ("160.79.104.10", 443)),
                                             (socket.AF_INET6, ("::1", 443))])
def test_network_connections_are_refused(family, address):
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
    except OSError:
        pytest.skip("address family not available here")
    with sock:
        with pytest.raises(NetworkBlocked):
            sock.connect(address)
        with pytest.raises(NetworkBlocked):
            sock.connect_ex(address)


def test_the_real_transports_cannot_reach_a_provider():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("api.anthropic.com", 443), timeout=1)
    with pytest.raises(NetworkBlocked):
        urllib.request.urlopen("http://localhost:11434/v1/models", timeout=1)
    # The OpenAI-compatible transport (Ollama by default) fails at once: the guard is not an
    # error the retry loop treats as transient.
    with pytest.raises(NetworkBlocked):
        OpenAICompatibleLLM("llama3.1:8b", sleep=pytest.fail).complete([Message("user", "hi")])


def test_a_configured_provider_without_fake_stops_before_any_call(tmp_path):
    """With keys cleared, a stage that would call Anthropic stops on the missing key."""
    import yaml

    cfg = yaml.safe_load(open("config.yaml"))
    cfg["paths"].update(runs=str(tmp_path / "runs"), cache=str(tmp_path / "cache"))
    (tmp_path / "runs" / "r").mkdir(parents=True)
    (tmp_path / "runs" / "r" / "summaries.jsonl").write_text("")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(SystemExit, match="set ANTHROPIC_API_KEY"):
        main(["--config", str(path), "probe", "--run-id", "r", "--model", "main",
              "--scenarios", "data/pilot.jsonl"])
