import pytest
import yaml

from inflatebench.cli import build_parser, load_config, main
from inflatebench.models import FakeLLM, Request
from inflatebench.schema import Message


def test_fake_llm_cycles_and_records():
    llm = FakeLLM(["a", "b"])
    msgs = [Message("user", "hi there")]
    assert [llm.complete(msgs).text for _ in range(3)] == ["a", "b", "a"]
    assert len(llm.calls) == 3
    assert llm.complete(msgs).input_tokens == 2


def test_fake_llm_callable_and_batch():
    llm = FakeLLM(lambda msgs: msgs[-1].content.upper())
    reqs = [Request("m", [Message("user", "x")]), Request("m", [Message("user", "y")])]
    handle = llm.submit_batch(reqs)
    assert handle.size == 2
    results = llm.batch_results(handle)
    assert [results[r.key()].text for r in reqs] == ["X", "Y"]


@pytest.mark.parametrize("command", ["judge", "probe", "analyze"])
def test_cli_stage_needs_an_existing_run(command, tmp_path):
    cfg = load_config("config.yaml")
    cfg["paths"]["runs"] = str(tmp_path)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(SystemExit, match="run the earlier stages first"):
        main(["--config", str(path), command, "--run-id", "r1"])


def test_cli_requires_a_subcommand():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_config_loads():
    cfg = load_config("config.yaml")
    assert cfg["repeats"] == 3
    assert cfg["conditions"] == ["free", "sectioned", "keep_rules", "extractor", "pinning"]
