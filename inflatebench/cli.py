"""ib generate | compact | judge | probe | analyze"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from inflatebench.schema import Message, Scenario, Summary, read_jsonl, write_jsonl

if TYPE_CHECKING:
    from inflatebench.models import LLM, Completion

# Assumed output length per call for `ib compact --dry-run`: a 250-word summary is about 350 tokens.
DRY_RUN_OUTPUT_TOKENS = 400


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _stub(args: argparse.Namespace) -> int:
    print(f"ib {args.command}: not implemented yet", file=sys.stderr)
    return 1


class _Logged:
    """Passes calls through to an LLM and keeps every Completion for calls.jsonl."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.completions: list[Completion] = []

    def complete(self, messages: list[Message], **kw: Any) -> Completion:
        completion = self.llm.complete(messages, **kw)
        self.completions.append(completion)
        return completion


def _fake_responder(messages: list[Message]) -> str:
    from inflatebench.conditions._common import prompt

    if messages[0].content in (prompt("extract"), prompt("pin_extract")):
        return "NONE"
    return "Fake summary."


def _make_llm(cfg: dict[str, Any], model_key: str, fake: bool) -> tuple[LLM, str]:
    """The provider for a model key in config.yaml, and the model name to record."""
    from inflatebench import models

    if fake:
        return models.FakeLLM(_fake_responder), "fake"
    spec = cfg["models"][model_key]
    factory = getattr(models, "make_llm", None)
    if factory is None:
        raise SystemExit(f"provider {spec['provider']!r} is not available yet; use --fake")
    return factory(spec), spec["name"]


def _compact(args: argparse.Namespace) -> int:
    from inflatebench.conditions import get_condition
    from inflatebench.models import CachedLLM, DiskCache, FakeLLM

    cfg = load_config(args.config)
    conditions = [get_condition(n) for n in args.condition or cfg["conditions"]]
    scenarios = list(read_jsonl(args.scenarios or cfg["paths"]["scenarios"], Scenario))[: args.limit]
    repeats = args.repeats or cfg["repeats"]

    if args.dry_run:
        model = "fake" if args.fake else cfg["models"][args.model]["name"]
        counter = FakeLLM(lambda msgs: "x " * DRY_RUN_OUTPUT_TOKENS)
        for scenario in scenarios:
            for condition in conditions:
                condition.compact(scenario.history, counter)
        calls = len(counter.calls) * repeats
        # About four characters per token.
        tokens_in = sum(len(m.content) for msgs in counter.calls for m in msgs) // 4 * repeats
        tokens_out = calls * DRY_RUN_OUTPUT_TOKENS
        print(f"{len(scenarios)} scenarios x {len(conditions)} conditions x {repeats} repeats: {calls} calls")
        print(f"~{tokens_in:,} input tokens, ~{tokens_out:,} output tokens")
        price = cfg.get("prices", {}).get(model)
        if price:
            cost = (tokens_in * price["input"] + tokens_out * price["output"]) / 1e6
            print(f"~${cost:,.2f} for {model}")
        else:
            print(f"no price for {model!r} in config.yaml")
        return 0

    llm, model = _make_llm(cfg, args.model, args.fake)
    cache = DiskCache(cfg["paths"]["cache"])
    summaries, calls = [], []
    for repeat in range(repeats):
        # The repeat is part of the cache key, so repeats are fresh samples that still resume.
        logged = _Logged(CachedLLM(llm, cache, model=f"{model}#repeat{repeat}"))
        for scenario in scenarios:
            for condition in conditions:
                start = len(logged.completions)
                messages = condition.compact(scenario.history, logged)
                summaries.append(Summary(scenario.id, condition.name, model, repeat, messages))
                for c in logged.completions[start:]:
                    calls.append(
                        {
                            "scenario_id": scenario.id,
                            "condition": condition.name,
                            "repeat": repeat,
                            "model": c.model,
                            "date": c.date or date.today().isoformat(),
                            "input_tokens": c.input_tokens,
                            "output_tokens": c.output_tokens,
                            "cost": c.cost,
                            "cached": c.cached,
                        }
                    )

    run_dir = Path(cfg["paths"]["runs"]) / args.run_id
    write_jsonl(run_dir / "summaries.jsonl", summaries)
    with (run_dir / "calls.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(c) + "\n" for c in calls)
    print(f"wrote {len(summaries)} summaries to {run_dir / 'summaries.jsonl'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ib", description="Constraint inflation benchmark")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="write data/scenarios.jsonl")
    p.add_argument("--out", default=None, help="output path (default from config)")
    p.add_argument("--seed", type=int, default=None)

    p = sub.add_parser("compact", help="write runs/<run_id>/summaries.jsonl")
    p.add_argument("--run-id", required=True)
    p.add_argument("--condition", action="append", help="condition name; repeatable")
    p.add_argument("--model", default="main", help="model key from config")
    p.add_argument("--scenarios", default=None, help="scenarios path (default from config)")
    p.add_argument("--repeats", type=int, default=None, help="repeats per scenario (default from config)")
    p.add_argument("--limit", type=int, default=None, help="use only the first N scenarios")
    p.add_argument("--fake", action="store_true", help="use FakeLLM instead of a provider")
    p.add_argument("--dry-run", action="store_true", help="estimate cost without calling models")

    p = sub.add_parser("judge", help="write runs/<run_id>/labels.jsonl")
    p.add_argument("--run-id", required=True)

    p = sub.add_parser("probe", help="write runs/<run_id>/probes.jsonl")
    p.add_argument("--run-id", required=True)

    p = sub.add_parser("analyze", help="write runs/<run_id>/report/")
    p.add_argument("--run-id", required=True)

    for name in ("generate", "compact", "judge", "probe", "analyze"):
        sub.choices[name].set_defaults(func=_stub)
    sub.choices["compact"].set_defaults(func=_compact)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
