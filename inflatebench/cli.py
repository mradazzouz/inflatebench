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


def _stub(args: argparse.Namespace) -> int:
    print(f"ib {args.command}: not implemented yet", file=sys.stderr)
    return 1


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
    p.add_argument("--model", default=None, help="model key from config")
    p.add_argument("--dry-run", action="store_true", help="estimate cost without calling models")

    p = sub.add_parser("judge", help="write runs/<run_id>/labels.jsonl")
    p.add_argument("--run-id", required=True)

    p = sub.add_parser("probe", help="write runs/<run_id>/probes.jsonl")
    p.add_argument("--run-id", required=True)

    p = sub.add_parser("analyze", help="write runs/<run_id>/report/")
    p.add_argument("--run-id", required=True)

    for name in ("generate", "compact", "judge", "probe", "analyze"):
        sub.choices[name].set_defaults(func=_stub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
