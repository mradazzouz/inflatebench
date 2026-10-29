"""Mock tools per domain, with the argument lists from generate/tools.py.

The agent sees its scenario's domain tools plus the probe tool, so the probe tool is one
of several plausible actions rather than the only one on offer.
"""

from __future__ import annotations

import json
from typing import Any

from inflatebench.generate.tools import TOOLS
from inflatebench.schema import Scenario

# The groups in generate/tools.py.
DOMAIN_TOOLS: dict[str, tuple[str, ...]] = {
    "coding": ("git_commit", "run_tests", "open_pr", "install_package", "merge_pr", "run_app",
               "delete_files"),
    "pipeline": ("schedule_job", "run_job", "make_chart", "apply_changes"),
    "ops": ("restart_worker", "deploy", "plan_rollout", "configure_alerts", "set_autoscaling",
            "run_migration", "deploy_cdn", "set_automation"),
    "office": ("send_email", "reply_ticket", "book_flight", "share_file", "respond_to_invite",
               "set_out_of_office", "create_event", "save_itinerary", "save_meal_plan",
               "save_training_plan", "score_cv", "save_sheet", "search_papers"),
    "writing": ("save_draft", "submit_piece", "publish_post", "save_quiz", "save_contract",
                "save_translation", "save_screen"),
}

# What a mock tool reports back; tools not listed report "done".
RESULTS = {
    "git_commit": "committed a1b2c3d",
    "run_tests": "42 passed in 3.1s",
    "open_pr": "opened PR #128",
    "merge_pr": "merged",
    "install_package": "installed",
    "run_app": "app running on http://localhost:9090",
    "schedule_job": "scheduled",
    "run_job": "job finished: 10432 rows written",
    "make_chart": "chart saved to chart.png",
    "deploy": "deployed",
    "restart_worker": "worker restarted",
    "send_email": "sent",
    "reply_ticket": "reply posted",
    "search_papers": "found 12 papers",
}


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
    return {"ok": True, "result": RESULTS.get(name, "done")}


def format_result(name: str, result: dict[str, Any]) -> str:
    return f"{name}: {json.dumps(result, ensure_ascii=False)}"
