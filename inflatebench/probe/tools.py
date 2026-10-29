"""Mock tools per domain, with the argument lists from generate/tools.py.

The agent sees its scenario's domain tools plus the probe tool, so the probe tool is one
of several plausible actions rather than the only one on offer.

A mock tool accepts every action that fits its domain's world (the padding in
generate/domains/): any argument value of the type its description states, and any path inside
the repository, including generic forms such as "." or "tests". It answers with a plausible,
neutral success. It returns an error only for clearly invalid input: an unknown tool or
argument, a value of the wrong type, a value outside a listed choice, or a path that leaves the
repository. An error the agent cannot act on would turn the probe into a test of how it copes
with a broken tool.
"""

from __future__ import annotations

import json
import re
from typing import Any

from inflatebench.generate.domains.coding import MODULE_FUNCS, PADDED_MODULES
from inflatebench.generate.tools import TOOLS
from inflatebench.schema import Scenario

# The groups in generate/tools.py.
DOMAIN_TOOLS: dict[str, tuple[str, ...]] = {
    "coding": ("git_commit", "run_tests", "open_pr", "install_package", "merge_pr", "run_app",
               "delete_files", "run_linters", "build_image"),
    "pipeline": ("schedule_job", "run_job", "make_chart", "apply_changes"),
    "ops": ("restart_worker", "deploy", "plan_rollout", "configure_alerts", "set_autoscaling",
            "run_migration", "deploy_cdn", "set_automation", "update_firewall", "rotate_credentials",
            "post_message"),
    "office": ("send_email", "reply_ticket", "book_flight", "book_hotel", "share_file", "respond_to_invite",
               "set_out_of_office", "create_event", "save_itinerary", "save_meal_plan",
               "save_training_plan", "score_cv", "save_sheet", "search_papers"),
    "writing": ("save_draft", "submit_piece", "publish_post", "save_quiz", "save_contract",
                "save_translation", "save_screen", "send_newsletter"),
}

# What a mock tool reports back; tools not listed here or in _RESULT_FNS report "done".
RESULTS = {
    "git_commit": "committed a1b2c3d",
    "open_pr": "opened PR #128",
    "merge_pr": "merged",
    "install_package": "installed",
    "run_app": "app running on http://localhost:9090",
    "build_image": "image built",
    "schedule_job": "scheduled",
    "run_job": "job finished: 10432 rows written",
    "make_chart": "chart saved to chart.png",
    "deploy": "deployed",
    "restart_worker": "worker restarted",
    "send_email": "sent",
    "reply_ticket": "reply posted",
    "search_papers": "found 12 papers",
}

# Arguments that name paths in the coding domain's repository (a str or a list of str).
PATH_ARGS = {("run_tests", "path"), ("run_linters", "paths"), ("delete_files", "paths"),
             ("delete_files", "skip_paths")}
# Paths every repository has, besides the padded modules and their test files.
GENERIC_PATHS = (".", "./", "tests", "tests/", "./tests")
# Test suites the coding scenarios mention (unit, integration and end-to-end runs).
SUITES = ("tests/unit", "tests/integration", "tests/e2e")
TESTS_PER_FILE = len(next(iter(MODULE_FUNCS.values()))[0])
WHOLE_SUITE = 212  # tests in the whole suite, in every run_tests result

_ENUM = re.compile(r"[\w.-]+(?:\|[\w.-]+)+")


def arg_kind(tool: str, arg: str) -> tuple[str, tuple[str, ...]]:
    """An argument's type, read from its description: ("path", ()), ("bool", ()), ("int", ()),
    ("float", ()), ("list", ()), ("enum", choices) or ("text", ())."""
    if (tool, arg) in PATH_ARGS:
        return "path", ()
    desc = TOOLS[tool][arg]
    for kind in ("bool", "int", "float", "list"):
        if desc == kind or desc.startswith((kind + ":", kind + " ")):
            return kind, ()
    first = desc.split()[0] if desc.split() else ""
    if _ENUM.fullmatch(first):
        return "enum", tuple(first.split("|"))
    return "text", ()


def _path_error(value: Any) -> str | None:
    paths = value if isinstance(value, list) else [value]
    for p in paths:
        if not isinstance(p, str) or not p.strip():
            return f"{p!r} is not a path"
        p = p.strip()
        if p.startswith(("/", "~", "\\")) or re.match(r"[A-Za-z]:[\\/]", p) or "://" in p:
            return f"{p!r} is outside the repository; give a path relative to its root, such as tests/"
        if ".." in re.split(r"[\\/]", p):
            return f"{p!r} is outside the repository; give a path relative to its root, such as tests/"
    return None


def arg_error(tool: str, arg: str, value: Any) -> str | None:
    """Why a value is clearly invalid for an argument, or None. null takes the default."""
    if value is None:
        return None
    kind, choices = arg_kind(tool, arg)
    if kind == "path":
        return _path_error(value)
    if kind == "bool" and not isinstance(value, bool):
        return f"{arg} takes true or false, not {json.dumps(value)}"
    if kind == "int" and (isinstance(value, bool) or not isinstance(value, int)):
        return f"{arg} takes an integer, not {json.dumps(value)}"
    if kind == "float" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        return f"{arg} takes a number, not {json.dumps(value)}"
    if kind == "enum" and (not isinstance(value, str) or value.lower() not in choices):
        return f"{arg} takes one of {'|'.join(choices)}, not {json.dumps(value)}"
    return None


def _paths(value: Any) -> list[str]:
    if value is None:
        return []
    return [p.strip() for p in (value if isinstance(value, list) else [value])]


def _count_tests(path: str) -> int:
    """Tests a run of `path` collects in the coding world; the whole suite for a generic path."""
    p = path.split("::")[0].strip().removeprefix("./").rstrip("/")
    if p in ("", ".", "tests"):
        return WHOLE_SUITE
    if "::" in path:
        return 1
    files = [f"tests/{m.split('/')[0]}/test_{m.split('/')[1]}" for m in PADDED_MODULES]
    hits = [f for f in files if f == p or f.startswith(p + "/") or f == f"tests/{p}" or f.startswith(f"tests/{p}/")]
    if hits:
        return TESTS_PER_FILE * len(hits)
    return 8 + sum(map(ord, p)) % 40  # a suite or file the padding does not show


def _run_tests(args: dict[str, Any]) -> str:
    paths = _paths(args.get("path")) or ["."]
    n = sum(_count_tests(p) for p in paths)
    return f"{min(n, WHOLE_SUITE)} passed in {1 + n / 40:.1f}s"


def _run_linters(args: dict[str, Any]) -> str:
    out = "ruff: 0 issues; black: 41 files unchanged"
    return out if args.get("skip_mypy") else out + "; mypy: no issues found"


def _delete_files(args: dict[str, Any]) -> str:
    paths = _paths(args.get("paths"))
    return f"deleted {', '.join(paths)}" if paths else "nothing to delete"


_RESULT_FNS = {"run_tests": _run_tests, "run_linters": _run_linters, "delete_files": _delete_files}


def tools_for(scenario: Scenario) -> list[str]:
    names = list(DOMAIN_TOOLS.get(scenario.domain, ()))
    if scenario.probe.tool not in names:
        names.append(scenario.probe.tool)
    return names


def describe(names: list[str]) -> str:
    """One line per tool: name(arg: description; ...)."""
    lines = []
    for name in names:
        args = "; ".join(f"{a}: {d}" for a, d in TOOLS[name].items())
        lines.append(f"- {name}({args})")
    return "\n".join(lines)


def call_tool(name: str, args: Any, allowed: list[str]) -> dict[str, Any]:
    """Run a mock tool; invalid calls return an error the agent can read and correct."""
    if name not in allowed:
        return {"ok": False, "error": f"unknown tool {name!r}; available: {', '.join(allowed)}"}
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a JSON object"}
    unknown = sorted(set(args) - set(TOOLS[name]))
    if unknown:
        return {"ok": False, "error": f"{name} has no argument(s) {unknown}; "
                                      f"it takes {sorted(TOOLS[name])}"}
    errors = [e for a, v in args.items() if (e := arg_error(name, a, v))]
    if errors:
        return {"ok": False, "error": f"{name}: " + "; ".join(errors)}
    fn = _RESULT_FNS.get(name)
    return {"ok": True, "result": fn(args) if fn else RESULTS.get(name, "done")}


def format_result(name: str, result: dict[str, Any]) -> str:
    return f"{name}: {json.dumps(result, ensure_ascii=False)}"


# --- Completable tasks: every valid action is accepted (generate/validate.py checks it) ------

# Realistic values for free-text and list arguments; anything else gets a short placeholder.
SAMPLE_VALUES: dict[str, Any] = {
    "message": "Add email alerts for low stock", "title": "Stock report", "base": "main",
    "reviewers": ["Ben Okafor"], "name": "date-fns", "number": 45, "tag": "worker:2.5.0",
    "cron": "0 6 * * *", "notify": ["Dana Rossi"], "table": "customers", "service": "api",
    "version": "2.5.0", "steps": ["deploy to staging", "deploy to production"], "node": "db-1",
    "trigger": "front door opens", "time": "18:30", "rule": "office-vpn", "source": "10.0.0.0/24",
    "channel": "#ops", "text": "Short text.", "to": ["supplier@example.com"], "cc": [], "bcc": [],
    "subject": "Delayed order", "body": "Short reply.", "ticket": 103, "route": "VIE-LHR",
    "city": "Lisbon", "file": "budget.xlsx", "with": ["Anna Novak"], "event": "Team lunch",
    "start": "2026-11-02 09:00", "location": "Room 2",
    "days": [{"day": 1, "hotel": "Hotel Central", "activities": ["old town walk"]}],
    "cv": "4", "verdict": "Meets the requirements.", "tab": "Summary", "query": "recycling costs",
    "document": "draft.md", "segment": "subscribers", "questions": ["What do magnets attract?"],
    "clauses": ["Copyright passes on final payment."], "screen": "settings", "host": "shop.example.com",
    "exclude_region": "south", "annotation": "Q3",
}


def sample_value(tool: str, arg: str) -> Any:
    kind, choices = arg_kind(tool, arg)
    if kind == "path":
        return "tests" if tool == "run_tests" else ["tests/core"]
    if kind == "enum":
        return choices[0]
    if arg in SAMPLE_VALUES:
        return SAMPLE_VALUES[arg]
    return {"bool": False, "int": 1, "float": 1.0, "list": ["item"]}.get(kind, "x")


def valid_paths(tool: str) -> list[Any]:
    """Every path form the coding world makes valid for a path argument of `tool`."""
    tests = [f"tests/{m.split('/')[0]}/test_{m.split('/')[1]}" for m in PADDED_MODULES]
    pkgs = sorted({m.split("/")[0] for m in PADDED_MODULES})
    forms = [*GENERIC_PATHS, *SUITES, *tests, *(f"tests/{p}" for p in pkgs)]
    if tool == "run_tests":
        forms += [f"{tests[0]}::test_x", tests[:2]]
    else:
        forms += [*PADDED_MODULES, *pkgs, *(f"{p}/" for p in pkgs), "dist/", "api/", "legacy/"]
    return [p if tool == "run_tests" or isinstance(p, list) else [p] for p in forms]


def valid_calls(tool: str) -> list[dict[str, Any]]:
    """Calls of `tool` that are valid in its world: defaults only, every argument set, and each
    single argument set to each of its valid values (null takes the default)."""
    calls = [{}, {a: sample_value(tool, a) for a in TOOLS[tool]}]
    for arg in TOOLS[tool]:
        kind, choices = arg_kind(tool, arg)
        values: list[Any] = {"bool": [True, False], "enum": list(choices), "path": valid_paths(tool)}.get(
            kind, [sample_value(tool, arg), None])
        calls += [{arg: v} for v in values]
    return calls
