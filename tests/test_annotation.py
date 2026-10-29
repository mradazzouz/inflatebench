import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from inflatebench.judge import LABEL_DEFINITIONS, make_annotation_sample, read_human_labels
from inflatebench.judge.run import read_rows, write_rows

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "annotation" / "index.html"


def test_page_is_offline_and_matches_rubric():
    html = PAGE.read_text(encoding="utf-8")
    # No external resources: the page must work from a USB stick.
    assert not re.search(r"""(src|href)=["']?(https?:)?//""", html)
    for name, definition in LABEL_DEFINITIONS.items():
        assert f'["{name}", "{definition}"]' in html


def _node_playwright() -> bool:
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _node_playwright(), reason="needs node with playwright")
def test_page_labels_and_saves_jsonl(tmp_path, pilot, summaries):
    sample, key = make_annotation_sample(pilot, summaries, n=5, seed=0)
    write_rows(tmp_path / "sample.jsonl", sample)
    write_rows(tmp_path / "key.jsonl", key)
    out = tmp_path / "saved.jsonl"
    run = subprocess.run(["node", str(Path(__file__).parent / "annotation_e2e.js"), str(PAGE),
                          str(tmp_path / "sample.jsonl"), str(out)],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout.strip().splitlines()[-1])
    assert result["errors"] == []
    assert result["first"] == f"“{sample[0]['item_text']}”"
    assert result["pressed"] == "true"
    assert result["progress"].endswith("2 labelled")
    assert result["filename"] == "sample.labels.ana.jsonl"

    rows = read_rows(out)
    assert [(r["uid"], r["label"], r["annotator"]) for r in rows] == [
        (sample[0]["uid"], "promoted", "ana"), (sample[1]["uid"], "hardened", "ana")]
    assert rows[1]["quote"] == "Disable the canary step"
    labels = read_human_labels(out, tmp_path / "key.jsonl")
    assert [l.judge for l in labels] == ["human:ana", "human:ana"]
    assert labels[0].item_id == sample[0]["item_id"]
