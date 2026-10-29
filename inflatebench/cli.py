"""ib generate | compact | judge | probe | analyze"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _paraphrase_llm(cfg: dict[str, Any], key: str) -> Any:
    from inflatebench.models import CachedLLM, DiskCache, FakeLLM

    model = cfg.get("models", {}).get(key)
    if model is None:
        raise SystemExit(f"ib generate: no model {key!r} in config")
    if model.get("provider") != "fake":
        raise SystemExit(f"ib generate: provider {model.get('provider')!r} is not available yet")
    cache = DiskCache(cfg.get("paths", {}).get("cache", ".cache/requests"))
    return CachedLLM(FakeLLM(model=model["name"]), cache, model=model["name"])


def _generate(args: argparse.Namespace) -> int:
    from inflatebench.generate import Paraphraser, generate, load_pilot
    from inflatebench.schema import write_jsonl

    cfg = load_config(args.config)
    paths = cfg.get("paths", {})
    if args.pilot:
        out = args.out or paths.get("pilot", "data/pilot.jsonl")
        scenarios = load_pilot(args.pilot_md)
    else:
        out = args.out or paths.get("scenarios", "data/scenarios.jsonl")
        llm = _paraphrase_llm(cfg, args.paraphrase_model) if args.paraphrase_model else None
        scenarios = generate(args.n, args.seed, Paraphraser(llm))
    write_jsonl(out, scenarios)
    print(f"wrote {len(scenarios)} scenarios to {out}")
    return 0


def _stub(args: argparse.Namespace) -> int:
    print(f"ib {args.command}: not implemented yet", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ib", description="Constraint inflation benchmark")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="write data/scenarios.jsonl")
    p.add_argument("--out", default=None, help="output path (default from config)")
    p.add_argument("--n", type=int, default=240, help="number of scenarios, spread over the domains")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--paraphrase-model", default=None,
                   help="model key from config used to paraphrase items (default: no paraphrasing)")
    p.add_argument("--pilot", action="store_true", help="port pilot.md to data/pilot.jsonl instead")
    p.add_argument("--pilot-md", default="pilot.md", help="path to pilot.md")

    p = sub.add_parser("compact", help="write runs/<run_id>/summaries.jsonl")
    p.add_argument("--run-id", required=True)
    p.add_argument("--condition", action="append", help="condition name; repeatable")
    p.add_argument("--model", default=None, help="model key from config")
    p.add_argument("--dry-run", action="store_true", help="estimate cost without calling models")

    p = sub.add_parser("judge", help="write runs/<run_id>/labels.jsonl")
    p.add_argument("--run-id", required=True)

    p = sub.add_parser("probe", help="write runs/<run_id>/probes.jsonl")
    p.add_argument("--run-id", required=True)

    p = sub.add_parser("analyze", help="write runs/<run_id>/report/")
    p.add_argument("--run-id", required=True)

    sub.choices["generate"].set_defaults(func=_generate)
    for name in ("compact", "judge", "probe", "analyze"):
        sub.choices[name].set_defaults(func=_stub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
