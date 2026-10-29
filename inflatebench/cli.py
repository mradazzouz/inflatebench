"""ib generate | compact | judge | probe | analyze"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from inflatebench.schema import Label, Message, Scenario, Summary, read_jsonl, write_jsonl

if TYPE_CHECKING:
    from inflatebench.models import LLM, Completion


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _paraphrase_llm(cfg: dict[str, Any], key: str) -> LLM:
    from inflatebench.models.factory import from_config

    try:
        return from_config(cfg, key)
    except (KeyError, ValueError, RuntimeError) as e:  # unknown key, placeholder name, missing SDK or key
        raise SystemExit(f"ib generate: {e}") from None


def _generate(args: argparse.Namespace) -> int:
    from inflatebench.generate import HELDOUT_SEED, Paraphraser, generate, generate_heldout, load_pilot

    cfg = load_config(args.config)
    paths = cfg.get("paths", {})
    if args.pilot and args.heldout:
        raise SystemExit("ib generate: use --pilot or --heldout, not both")
    if args.pilot:
        out = args.out or paths.get("pilot", "data/pilot.jsonl")
        scenarios = load_pilot(args.pilot_md)
    else:
        llm = _paraphrase_llm(cfg, args.paraphrase_model) if args.paraphrase_model else None
        if args.heldout:
            out = args.out or paths.get("heldout", "data/heldout.jsonl")
            seed = HELDOUT_SEED if args.seed is None else args.seed
            scenarios = generate_heldout(seed, Paraphraser(llm))
        else:
            out = args.out or paths.get("scenarios", "data/scenarios.jsonl")
            scenarios = generate(args.n, 0 if args.seed is None else args.seed, Paraphraser(llm))
    write_jsonl(out, scenarios)
    print(f"wrote {len(scenarios)} scenarios to {out}")
    return 0


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


def _fake_judge_responder(messages: list[Message]) -> str:
    """Labels from the prompt alone: active items are kept if the summary quotes them, else lost."""
    from inflatebench.analyze.metrics import ACTIVE

    user = messages[-1].content
    summary = user.split("<summary>\n", 1)[1].rsplit("\n</summary>", 1)[0]
    items = []
    for line in user.split("\n\n", 1)[0].splitlines()[1:]:
        row = json.loads(line)
        kept = row["user_said"] in summary
        label = "lost" if row["type"] in ACTIVE and not kept else "correct"
        items.append({"item_id": row["item_id"], "label": label,
                      "quote": row["user_said"] if kept else ""})
    return json.dumps({"items": items, "invented": []})


def _fake_agent_responder(messages: list[Message]) -> str:
    """Calls every listed tool once with default arguments, then reports done."""
    if messages[-1].role == "tool":
        return "Done."
    tools = re.findall(r"^- (\w+)\(", messages[0].content, re.MULTILINE)
    return "\n".join(json.dumps({"tool": t, "args": {}}) for t in tools)


def _make_llm(cfg: dict[str, Any], model_key: str, fake: bool, stage: str = "compact") -> tuple[LLM, str]:
    """The provider for a model key in config.yaml, and the model name to record."""
    from inflatebench import models
    from inflatebench.models.factory import check_entry

    if fake:
        return models.FakeLLM(_fake_responder), "fake"
    if model_key not in cfg["models"]:
        raise SystemExit(f"ib {stage}: no model {model_key!r} in config; have {sorted(cfg['models'])}")
    spec = cfg["models"][model_key]
    try:
        check_entry(spec, model_key)
        return models.make_llm(spec, cfg.get("prices")), spec["name"]
    except (ValueError, RuntimeError) as e:  # placeholder name, missing API key or SDK
        raise SystemExit(f"ib {stage}: {e}") from None


def _call_row(c: Completion, scenario_id: str, condition: str, repeat: int) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "condition": condition,
        "repeat": repeat,
        "model": c.model,
        "date": c.date or date.today().isoformat(),
        "input_tokens": c.input_tokens,
        "output_tokens": c.output_tokens,
        "cache_write_tokens": c.cache_write_tokens,
        "cache_read_tokens": c.cache_read_tokens,
        "cost": c.cost,
        "cached": c.cached,
        "batch": c.batch,
    }


def _stage_info(path: Path, info: dict[str, Any]) -> None:
    """Record what a stage ran with (models, settings, date, spend) next to its output."""
    from inflatebench.models.chat import now

    path.write_text(json.dumps({"date": now()} | info, indent=2) + "\n", encoding="utf-8")


def _compact(args: argparse.Namespace) -> int:
    from inflatebench.conditions import get_condition
    from inflatebench.models import CachedLLM, Deferred, DiskCache, Pending, provider_settings, run_phases

    cfg = load_config(args.config)
    if args.model not in cfg["models"]:
        raise SystemExit(f"ib compact: no model {args.model!r} in config; have {sorted(cfg['models'])}")
    names = args.condition or cfg["conditions"]
    if len(set(names)) != len(names):
        # Each would be written again under the same key and counted twice by every later stage.
        raise SystemExit(f"ib compact: conditions listed more than once: {names}")
    conditions = [get_condition(n) for n in names]
    path = Path(args.scenarios or cfg["paths"]["scenarios"])
    if not path.exists():
        raise SystemExit(f"ib compact: {path} not found; run ib generate or pass --scenarios")
    scenarios = list(read_jsonl(path, Scenario))
    # The strong model runs on a fixed subset (config models.<key>.subset), then --limit applies.
    subset = None if args.fake else cfg["models"][args.model].get("subset")
    scenarios = scenarios[:subset][: args.limit]
    repeats = args.repeats or cfg["repeats"]

    if args.dry_run:
        from inflatebench.models.estimate import estimate
        from inflatebench.models.pricing import Prices

        entry = {"name": "fake"} if args.fake else cfg["models"][args.model]
        est = estimate(
            scenarios,
            entry,
            [c.name for c in conditions],
            repeats,
            Prices(cfg.get("prices")),
            output_tokens=args.output_tokens,
        )
        print(f"ib compact --dry-run ({'fake' if args.fake else args.model})")
        print("\n".join("  " + line for line in est.lines()))
        return 0

    llm, model = _make_llm(cfg, args.model, args.fake)
    # Batch API when the model asks for it (--fake always batches, to exercise that path).
    batch = (args.fake or bool(cfg["models"][args.model].get("batch"))) and not args.no_batch
    # The repeat is part of the cache key, so repeats are fresh samples that still resume.
    deferred = Deferred(CachedLLM(llm, DiskCache(cfg["paths"]["cache"]), model=model), batch=batch)
    llms = [deferred.view(f"{model}#repeat{repeat}") for repeat in range(repeats)]

    def step() -> tuple[list[Summary], list[dict[str, Any]]]:
        summaries, calls = [], []
        for repeat, repeat_llm in enumerate(llms):
            logged = _Logged(repeat_llm)
            for scenario in scenarios:
                for condition in conditions:
                    start = len(logged.completions)
                    try:
                        messages = condition.compact(scenario.history, logged)
                    except Pending:
                        continue  # answered in the next phase
                    summaries.append(Summary(scenario.id, condition.name, model, repeat, messages))
                    calls += [_call_row(c, scenario.id, condition.name, repeat)
                              for c in logged.completions[start:]]
        return summaries, calls

    # Phase 1 sends every first call (the summaries, pinning's extraction); phase 2 the calls
    # that come after it (the extractor's list, pinning's summary).
    phases = run_phases(step, [deferred])
    summaries, calls = step()

    run_dir = Path(cfg["paths"]["runs"]) / args.run_id
    write_jsonl(run_dir / "summaries.jsonl", summaries)
    # Later stages read the same scenarios without being told the path again.
    run_info = {"scenarios": str(path), "model": model, "conditions": [c.name for c in conditions],
                "repeats": repeats, "n_scenarios": len(scenarios),
                "settings": provider_settings(llm), "batch": batch, "calls": len(calls),
                "cost": sum(c["cost"] for c in calls if not c["cached"])}  # spent in this run
    _stage_info(run_dir / "run.json", run_info)
    with (run_dir / "calls.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(c) + "\n" for c in calls)
    print(f"wrote {len(summaries)} summaries to {run_dir / 'summaries.jsonl'} "
          f"({phases} phases of {'batched' if batch else 'single'} calls)")
    return 0


def _run_dir(cfg: dict[str, Any], args: argparse.Namespace, needs: str) -> Path:
    run_dir = Path(cfg["paths"]["runs"]) / args.run_id
    if not (run_dir / needs).exists():
        raise SystemExit(f"ib {args.command}: {run_dir / needs} not found; run the earlier stages first")
    return run_dir


def _scenarios_for(cfg: dict[str, Any], args: argparse.Namespace, run_dir: Path) -> Path:
    """--scenarios, else the path ib compact recorded in run.json, else the config default."""
    if args.scenarios:
        path = Path(args.scenarios)
    elif (run_dir / "run.json").exists():
        path = Path(json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["scenarios"])
    else:
        path = Path(cfg["paths"]["scenarios"])
    if not path.exists():
        raise SystemExit(f"ib {args.command}: {path} not found; pass --scenarios")
    return path


def _usage(path: Path):
    from inflatebench.models import UsageLog

    path.unlink(missing_ok=True)  # one log per stage run, like calls.jsonl from ib compact
    return UsageLog(path)


def _judge_llm(cfg: dict[str, Any], ref: Any, usage: Any, no_batch: bool = False) -> tuple[LLM, str]:
    """A judge from config: a key under models:, or an inline {provider, name, ...} entry.

    Every judge runs in phases (models.Deferred); those with `batch: true` use the Batch API.
    """
    from inflatebench.models import CachedLLM, Deferred, DiskCache, Prices
    from inflatebench.models.factory import PLACEHOLDER, build_provider, check_entry, model_entry

    if ref in (None, PLACEHOLDER):
        raise SystemExit("ib judge: set judges and tiebreak in config.yaml (or use --fake)")
    try:
        entry = check_entry(ref) if isinstance(ref, dict) else model_entry(cfg, ref)
        llm = build_provider(entry, Prices(cfg.get("prices")))
    except (KeyError, ValueError, RuntimeError) as e:
        raise SystemExit(f"ib judge: {e}") from None
    cached = CachedLLM(llm, DiskCache(cfg["paths"]["cache"]),
                       model=f"{entry['provider']}:{entry['name']}", usage=usage)
    return Deferred(cached, batch=bool(entry.get("batch")) and not no_batch), entry["name"]


def _judge(args: argparse.Namespace) -> int:
    from inflatebench.judge import FINAL, LLMJudge, PanelJudge, judge_run, quote_flag_rates
    from inflatebench.judge.run import QUOTE_FLAG_LIMIT
    from inflatebench.models import CachedLLM, Deferred, DiskCache, FakeLLM

    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args, "summaries.jsonl")
    scenarios = _scenarios_for(cfg, args, run_dir)
    usage = _usage(run_dir / "judge_calls.jsonl")
    if args.fake:
        cache = DiskCache(cfg["paths"]["cache"])
        judges = [LLMJudge(f"fake-{k}", Deferred(CachedLLM(FakeLLM(_fake_judge_responder), cache,
                                                           model=f"fake-judge-{k}", usage=usage),
                                                 batch=not args.no_batch))
                  for k in "abc"]
    else:
        refs = list(cfg.get("judges") or []) + [cfg.get("tiebreak")]
        if len(refs) != 3:
            raise SystemExit("ib judge: config.yaml needs exactly two judges and a tiebreak")
        judges = []
        for ref in refs:
            llm, name = _judge_llm(cfg, ref, usage, args.no_batch)
            judges.append(LLMJudge(name, llm))
    try:
        panel = PanelJudge(*judges)
    except ValueError as e:
        raise SystemExit(f"ib judge: {e}") from None
    out = judge_run(panel, scenarios, run_dir)
    flags = quote_flag_rates(read_jsonl(out, Label))
    _stage_info(run_dir / "judge.json", {
        "scenarios": str(scenarios),
        "judges": [{"name": j.name, "role": role, "settings": j.llm.llm.settings, "batch": j.llm.batch}
                   for j, role in zip(panel.judges, ("first", "second", "tiebreak"))],
        "usage": usage.summary(), "quote_flags": flags, "quote_flag_limit": QUOTE_FLAG_LIMIT})
    final = flags.get(FINAL, {"rate": 0.0})
    print(f"wrote labels to {out} ({usage.calls} judge calls, {usage.cache_hits} from cache, "
          f"${usage.cost:.4f}; {final['rate']:.1%} of final quotes not found in the summary)")
    if final["rate"] > QUOTE_FLAG_LIMIT:
        print(f"warning: the flag rate is above {QUOTE_FLAG_LIMIT:.0%}; fix the judge instructions "
              "before the main run", file=sys.stderr)
    return 0


def _probe(args: argparse.Namespace) -> int:
    from inflatebench.models import CachedLLM, DiskCache
    from inflatebench.probe import probe_run

    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args, "summaries.jsonl")
    scenarios = _scenarios_for(cfg, args, run_dir)
    key = args.model or cfg.get("agent", "main")
    if args.fake:
        from inflatebench.models import FakeLLM

        llm, name = FakeLLM(_fake_agent_responder, model="fake-agent"), "fake-agent"
    else:
        llm, name = _make_llm(cfg, key, fake=False, stage="probe")
    usage = _usage(run_dir / "probe_calls.jsonl")
    agent = CachedLLM(llm, DiskCache(cfg["paths"]["cache"]), model=f"{name}#agent", usage=usage)
    out = probe_run(agent, scenarios, run_dir, agent_name=name, max_steps=args.max_steps)
    _stage_info(run_dir / "probe.json", {"scenarios": str(scenarios), "agent": name,
                                         "settings": agent.settings, "max_steps": args.max_steps,
                                         "usage": usage.summary()})
    print(f"wrote probes to {out} ({usage.calls} agent calls, {usage.cache_hits} from cache, "
          f"${usage.cost:.4f})")
    return 0


def _analyze(args: argparse.Namespace) -> int:
    from inflatebench.analyze import analyze_run

    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args, "labels.jsonl")
    scenarios = _scenarios_for(cfg, args, run_dir)
    try:
        summary = analyze_run(run_dir, scenarios, judge=args.judge, n_boot=args.n_boot,
                              seed=args.seed, figures=not args.no_figures)
    except ValueError as e:
        raise SystemExit(f"ib analyze: {e}") from None
    probes = "with" if "behaviour" in summary else "without"
    print(f"wrote report for {summary['n_items']} items over {summary['n_scenarios']} scenarios "
          f"({probes} probes) to {run_dir / 'report'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ib", description="Constraint inflation benchmark")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="write data/scenarios.jsonl")
    p.add_argument("--out", default=None, help="output path (default from config)")
    p.add_argument("--n", type=int, default=240, help="number of scenarios, spread over the domains")
    p.add_argument("--seed", type=int, default=None,
                   help="base seed (default 0; for --heldout, its own default 1000)")
    p.add_argument("--paraphrase-model", default=None,
                   help="model key from config used to paraphrase items (default: no paraphrasing)")
    p.add_argument("--pilot", action="store_true", help="port pilot.md to data/pilot.jsonl instead")
    p.add_argument("--heldout", action="store_true",
                   help="write the 40 balanced held-out scenarios to data/heldout.jsonl instead")
    p.add_argument("--pilot-md", default="pilot.md", help="path to pilot.md")

    p = sub.add_parser("compact", help="write runs/<run_id>/summaries.jsonl")
    p.add_argument("--run-id", required=True)
    p.add_argument("--condition", action="append", help="condition name; repeatable")
    p.add_argument("--model", default="main", help="model key from config")
    p.add_argument("--scenarios", default=None, help="scenarios path (default from config)")
    p.add_argument("--repeats", type=int, default=None, help="repeats per scenario (default from config)")
    p.add_argument("--limit", type=int, default=None, help="use only the first N scenarios")
    p.add_argument("--fake", action="store_true", help="use FakeLLM instead of a provider")
    p.add_argument("--dry-run", action="store_true", help="estimate tokens and cost without calling models")
    p.add_argument("--output-tokens", type=int, default=1000, help="assumed output tokens per call (dry run)")
    no_batch = "single calls even when the model has batch: true in config.yaml"
    p.add_argument("--no-batch", action="store_true", help=no_batch)

    scen_help = "scenarios path (default: the one ib compact used for this run)"
    p = sub.add_parser("judge", help="write runs/<run_id>/labels.jsonl")
    p.add_argument("--run-id", required=True)
    p.add_argument("--scenarios", default=None, help=scen_help)
    p.add_argument("--fake", action="store_true", help="use fake judges instead of providers")
    p.add_argument("--no-batch", action="store_true", help=no_batch)

    p = sub.add_parser("probe", help="write runs/<run_id>/probes.jsonl")
    p.add_argument("--run-id", required=True)
    p.add_argument("--scenarios", default=None, help=scen_help)
    p.add_argument("--model", default=None, help="agent model key from config (default: config agent)")
    p.add_argument("--max-steps", type=int, default=8, help="agent replies per probe")
    p.add_argument("--fake", action="store_true", help="use a fake agent instead of a provider")

    p = sub.add_parser("analyze", help="write runs/<run_id>/report/")
    p.add_argument("--run-id", required=True)
    p.add_argument("--scenarios", default=None, help=scen_help)
    p.add_argument("--judge", default="final", help="whose labels to analyse (default: the panel's final)")
    p.add_argument("--n-boot", type=int, default=2000, help="bootstrap resamples")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-figures", action="store_true", help="tables only")

    for name, func in [("generate", _generate), ("compact", _compact), ("judge", _judge),
                       ("probe", _probe), ("analyze", _analyze)]:
        sub.choices[name].set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
