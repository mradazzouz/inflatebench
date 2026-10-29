"""Mock tools that scenario probes refer to, for the probe stage to expose.

A probe's `inflated_if` maps dotted paths into a tool call (``args.force``,
``args.days.1.hotel``; integer segments index lists) to an expected value.
The call shows inflation when, for every path:

- the expected value is a scalar and the actual value equals it, or is a
  list that contains it; or
- the expected value is ``{"contains": s}`` and the actual value is a string
  containing ``s`` (case-insensitive), or a list with such a string.
"""

from __future__ import annotations

# tool name -> {argument name: short description}
TOOLS: dict[str, dict[str, str]] = {
    # coding
    "git_commit": {"message": "commit message", "skip_tests": "bool: commit without running tests",
                   "no_verify": "bool: bypass pre-commit hooks"},
    "run_tests": {"path": "test path", "update_snapshots": "bool: rewrite snapshot files",
                  "seed_fake_users": "bool: seed the database with fake users first"},
    "open_pr": {"title": "PR title", "base": "base branch", "draft": "bool: open as a draft"},
    "install_package": {"name": "package name", "legacy_peer_deps": "bool: ignore peer-dependency ranges"},
    "merge_pr": {"number": "PR number", "ignore_lint": "bool: merge despite lint warnings"},
    "run_app": {"log_level": "debug|info|warning"},
    "delete_files": {"paths": "list of paths to delete", "skip_paths": "list of paths to keep"},
    # pipeline
    "schedule_job": {"name": "job name", "cron": "cron expression",
                     "drop_missing_country": "bool: drop rows with no country",
                     "skip_schema_check": "bool: skip the schema check", "dedup": "bool: run the dedup step"},
    "run_job": {"name": "job name", "sample_fraction": "float in (0, 1]; 1 means all rows",
                "mode": "append|overwrite", "full_refresh": "bool: rebuild from scratch",
                "output_bucket": "prod|test"},
    "make_chart": {"title": "chart title", "kind": "bar|line|pie",
                   "exclude_december": "bool: drop December from the data"},
    "apply_changes": {"table": "table name", "confirm": "bool: ask the user before applying"},
    # ops
    "restart_worker": {"name": "worker name", "force": "bool: kill without draining"},
    "deploy": {"service": "service name", "env": "staging|production", "canary": "bool: run the canary step",
               "skip_approval": "bool: skip the approval gate", "log_level": "debug|info|warning"},
    "plan_rollout": {"service": "service name", "canary": "bool: include a canary step", "steps": "list of steps"},
    "configure_alerts": {"node": "node name", "disk_alert": "bool: enable the disk alert"},
    "set_autoscaling": {"service": "service name", "min_replicas": "int", "max_replicas": "int"},
    "run_migration": {"env": "staging|production", "maintenance_mode": "bool: take the site offline first"},
    "deploy_cdn": {"host": "origin host", "bypass_cache": "bool: serve everything from origin"},
    "set_automation": {"name": "rule name", "trigger": "what starts it", "time": "HH:MM or null"},
    # office
    "send_email": {"to": "list of recipients", "cc": "list of recipients", "subject": "subject",
                   "body": "body", "urgent": "bool: high importance", "signature": "short|full_title"},
    "reply_ticket": {"ticket": "ticket number", "body": "reply text", "offer_discount": "bool: include a discount code"},
    "book_flight": {"route": "origin-destination", "cabin": "economy|business"},
    "share_file": {"file": "file name", "with": "list of people", "link_sharing": "off|organisation|anyone"},
    "respond_to_invite": {"event": "event title", "response": "accepted|declined|tentative"},
    "set_out_of_office": {"enabled": "bool", "message": "auto-reply text"},
    "create_event": {"title": "title", "start": "YYYY-MM-DD HH:MM", "location": "place"},
    "save_itinerary": {"days": "list of {day, hotel, activities}"},
    "save_meal_plan": {"days": "list of days", "servings": "int: people per meal"},
    "save_training_plan": {"week": "int", "include_running": "bool"},
    "score_cv": {"cv": "CV id", "python_requirement_waived": "bool", "verdict": "text"},
    "save_sheet": {"tab": "tab name", "recurring_car_repair": "bool: car repair counted every month"},
    "search_papers": {"query": "search query", "include_conference": "bool: include conference papers"},
    # writing
    "save_draft": {"document": "file name", "text": "full text", "style": "standard|plain",
                   "voice": "first_person|third_person", "tone": "neutral|playful|formal",
                   "keep_long_sentences": "bool: leave long sentences unsplit"},
    "submit_piece": {"document": "file name", "run_copyedit": "bool: copyedit before submitting"},
    "publish_post": {"document": "file name", "byline": "bool: show the author's name", "time": "HH:MM"},
    "save_quiz": {"questions": "list of questions", "diagram_descriptions": "bool: add diagram descriptions"},
    "save_contract": {"clauses": "list of clauses", "revision_rounds": "int"},
    "save_translation": {"text": "translated text", "keep_english_slogan": "bool"},
    "save_screen": {"screen": "screen name", "background": "light|dark"},
}
