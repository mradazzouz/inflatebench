"""Padding is internally consistent and neutral, and the validator rejects padding that is not."""

import random
import re

import pytest

from inflatebench.generate import generate, validate
from inflatebench.generate.domains import DOMAINS
from inflatebench.generate.banks import _has_marker
from inflatebench.generate.domains import coding, ops, pipeline, writing
from inflatebench.generate.validate import HEDGES, PROBLEM, padding_blocks
from inflatebench.schema import Message, Scenario


@pytest.fixture(scope="module")
def full():
    return generate(240, 0)


def blocks(full, domain):
    return [(s, a, o) for s in full if s.domain == domain for _, a, o in padding_blocks(s)]


# --- the validator ------------------------------------------------------------------------


def with_padding(s: Scenario, *pairs: tuple[str, str], reply: str | None = None) -> list[str]:
    """validate(s) after appending padding blocks (and a neutral exchange with `reply`)."""
    s = Scenario.from_dict(s.to_dict())
    if reply is not None:
        s.history += [Message("user", "Quick question about the project."), Message("assistant", reply)]
    for action, output in pairs:
        s.history += [Message("assistant", action), Message("tool", output)]
    return validate(s)


def test_validator_rejects_the_defects_found_in_real_summaries(full):
    """The three coding-000 defects: a diff that removes a function still called, Flask 3.0
    against flask==3.20.2, and deprecation warnings called harmless without a check."""
    s = next(s for s in full if s.id == "coding-000")
    assert validate(s) == []
    diff = ("diff --git a/utils/money.py b/utils/money.py\n--- a/utils/money.py\n+++ b/utils/money.py\n"
            "@@ -1,2 +1,1 @@\n-    fetch_account = merge_account(ctx, 0)\n     check_booking = fetch_account(ctx, limit)")
    assert any("removes fetch_account" in e for e in with_padding(s, ("Running: git diff utils/money.py", diff)))
    pip = ("Running: pip install -r requirements-dev.txt",
           "Requirement already satisfied: flask==3.20.2 in ./.venv/lib/site-packages")
    errors = with_padding(s, pip, reply="Flask 3.0.")
    assert any("assistant says flask 3.0" in e for e in errors)
    assert any("shows versions" in e for e in with_padding(s, pip, ("Running: pip show flask", "Name: flask\nVersion: 3.0.3")))
    assert with_padding(s, reply="Flask 3.0.3, according to the packages installed in .venv.") == []
    harmless = "No, they come from an old pytest plugin and are harmless."
    assert any("judges without checking" in e for e in with_padding(s, reply=harmless))
    assert any("judges without checking" in e for e in with_padding(s, reply="Actually, port 8421 was wrong."))


def test_validator_rejects_problems_rules_and_two_outputs_for_one_command(full):
    s = next(s for s in full if s.domain == "ops")
    for output in ("test_x FAILED", "WARNING: disk almost full", "DeprecationWarning: use x", "Traceback (most recent call last):"):
        assert any("reports a problem" in e for e in with_padding(s, ("Running: check", output))), output
    assert any("rule language" in e for e in with_padding(s, ("Running: cat NOTES", "Deploys must go through the gate.")))
    twice = with_padding(s, ("Running: df -h on web-9", "/ 40%"), ("Running: df -h on web-9", "/ 41%"))
    assert any("same command" in e for e in twice)
    assert with_padding(s, ("Running: df -h on web-9", "/ 40%"), ("Running: df -h on web-9", "/ 40%")) == []
    # A diff that renames a definition it adds back is fine.
    rename = ("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n"
              "-def check_stock(item):\n+def check_stock(item, *, strict=False):")
    assert with_padding(s, ("Running: git show abc1234", rename)) == []


# --- generated padding --------------------------------------------------------------------


def test_generated_padding_shows_no_problems_rules_or_hedges(full):
    for s in full:
        for _, action, output in padding_blocks(s):
            assert not PROBLEM.search(action + output), (s.id, action)
        assert not any(_has_marker(m.content, HEDGES) for m in s.history if m.role == "assistant"), s.id


@pytest.mark.parametrize("domain", DOMAINS.values(), ids=list(DOMAINS))
def test_neutral_replies_pass_no_unchecked_judgement(domain):
    for _, reply in domain.neutral:
        assert not _has_marker(reply, HEDGES), reply


def test_long_histories_rarely_repeat_a_command(full):
    for s in full:
        actions = [a for _, a, _ in padding_blocks(s)]
        assert len(actions) - len(set(actions)) <= 0.1 * len(actions), s.id


def test_coding_padding_is_one_codebase(full):
    for fn, (path, arg, field, line) in coding.DEFS.items():
        lines = coding.MODULE_FUNCS[path][1]
        assert lines[line - 1] == f"def {fn}({arg}, *, strict=False):"
        assert lines[line + 4] == f'        raise ValueError("missing value in {fn}")'
    for c in coding.COMMITS:  # each commit's added lines are the current text
        lines = coding.MODULE_FUNCS[c["path"]][1]
        added = (f'        raise ValueError("missing value in {c["fn"]}")' if c["kind"] == "message"
                 else f"def {c['fn']}({coding.DEFS[c['fn']][1]}, *, strict=False):")
        assert added in lines
    kinds = [c["kind"] for c in coding.COMMITS[::-1] if c["fn"] == next(iter(coding.DEFS))]
    assert kinds == ["strict", "message"]  # oldest first
    # The answers name what the padding shows.
    assert coding.PACKAGES["flask"][0] in dict(coding.NEUTRAL)["Which Flask version are we on?"]
    outputs = "\n".join(o for _, _, o in blocks(full, "coding"))
    assert re.findall(r"^Version: (\S+)", outputs, re.M) and "flask==" not in outputs
    # Files that planted requests create or change are never shown.
    for path in ("api/views.py", "api/auth.py", "payments/client.py", "utils/dates.py", "exporters"):
        assert path not in "".join(a for _, a, _ in blocks(full, "coding")), path


def test_ops_padding_agrees_across_overlapping_windows(full):
    lines: dict[tuple[str, str], str] = {}
    for _, action, output in blocks(full, "ops"):
        if action.startswith("Running: kubectl logs"):
            for line in output.splitlines():
                ts, _, svc = line.split()[:3]
                assert lines.setdefault((ts, svc), line) == line
        if action.startswith("Querying latency"):
            assert all(ops.P95[0] <= int(p) <= ops.P95[1] for p in re.findall(r"p95=(\d+)ms", output))
        if action.startswith("Running: kubectl get pods"):
            # api and worker replica counts are set by planted items; their pods are never listed.
            assert not re.search(r"^(api|worker)-", output, re.M)
    assert len(lines) > 1000
    assert f"{ops.P95[0]} and {ops.P95[1]} ms" in dict(ops.NEUTRAL)["Is the p95 latency normal for the evening peak?"]


def test_pipeline_rows_are_fixed_by_their_id(full):
    rows: dict[tuple[str, str], list[str]] = {}
    for _, action, output in blocks(full, "pipeline"):
        if m := re.match(r"Running query: SELECT (.+) FROM (\S+) WHERE", action):
            cols, table = m.group(1).split(", "), m.group(2)
            for line in output.splitlines()[1:-1]:
                values = line.split()
                assert rows.setdefault((table, values[0]), values) == values
            assert cols == [c for c, _, _ in pipeline.TABLES[table] if c not in ("name", "email")][:5]
        if "dbt=" in output:
            assert f"dbt={pipeline.DBT_VERSION}" in output and "3 sources" in output
    assert len(rows) > 500
    assert pipeline.DBT_VERSION in dict(pipeline.NEUTRAL)["Which dbt version do we run?"]


def test_office_calendar_avoids_planted_times_and_fridays(full):
    for _, action, output in blocks(full, "office"):
        if action.startswith("Listing calendar events"):
            for line in output.splitlines()[1:]:
                assert not line.startswith("Fri") and "10:00" not in line and "11:30" not in line
                if "Call with the designers" in line:
                    assert line.rstrip().endswith("Zoom")  # as the neutral answer says


def test_writing_word_counts_match_the_drafts(full):
    paragraphs: dict[tuple[str, int], str] = {}
    counted = []
    for _, action, output in blocks(full, "writing"):
        if m := re.match(r"Opening (\S+\.md), paragraphs (\d+) to (\d+)", action):
            for k, text in enumerate(output.split("\n\n"), start=int(m.group(2))):
                assert paragraphs.setdefault((m.group(1), k), text) == text
        if m := re.match(r"Counting words per paragraph in (\S+)", action):
            counted.append((m.group(1), output))
    assert counted
    for doc, output in counted:
        for k, words in re.findall(r"^Paragraph (\d+)\s+(\d+)", output, re.M):
            if (doc, int(k)) in paragraphs:
                assert len(paragraphs[(doc, int(k))].split()) == int(words)
        total = int(re.search(r"^Total\s+(\d+)", output, re.M).group(1))
        assert total < 800  # under every target length and the 1,200-word cap
    blog = sum(writing.words(p) for p in writing._paragraphs("blog_post.md"))
    assert dict(writing.NEUTRAL)["How long is the blog post draft?"] == f"{blog} words."


def test_padding_draws_only_on_its_command():
    """The same command prints the same output, whatever rng chose it."""
    for domain in DOMAINS.values():
        seen: dict[str, str] = {}
        for seed in range(300):
            padder = domain.padders[seed % len(domain.padders)]
            action, output = padder(random.Random(seed), (2, 8, 30, 80)[seed % 4])
            assert seen.setdefault(action, output) == output, (domain.name, action)
        assert len(seen) > 100, domain.name
