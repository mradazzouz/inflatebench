import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from inflatebench.analyze.report import analyze
from inflatebench.judge import ALLOWED_LABELS, LABEL_DEFINITIONS
from inflatebench.judge.rubric import PRECEDENCE
from conftest import synthetic_run

ROOT = Path(__file__).parent.parent
PAPER = ROOT / "paper"
GUIDE = ROOT / "LABEL_GUIDE.md"

spec = importlib.util.spec_from_file_location("make_paper_assets", ROOT / "scripts" / "make_paper_assets.py")
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


def test_label_guide_matches_rubric():
    text = GUIDE.read_text(encoding="utf-8")
    for name, definition in LABEL_DEFINITIONS.items():
        assert f"| {name} | {definition} |" in text
        # One worked example per label.
        assert len(re.findall(rf"^\| {name} \| \w+: ", text, re.M)) == 1, name
    for item_type, allowed in ALLOWED_LABELS.items():
        assert re.search(rf"^\| {item_type} \| [^|]+ \| {', '.join(allowed)} \|$", text, re.M), item_type
    assert " > ".join(PRECEDENCE) in text
    assert "annotation/index.html" in text


def test_label_guide_examples_use_allowed_labels():
    text = GUIDE.read_text(encoding="utf-8")
    for label, item_type in re.findall(r"^\| (\w+) \| (\w+): ", text, re.M):
        assert label in ALLOWED_LABELS[item_type], (label, item_type)


def test_paper_is_anonymous_and_cites_known_keys():
    main = (PAPER / "main.tex").read_text(encoding="utf-8")
    assert re.search(r"^\\usepackage\{tmlr\}", main, re.M)  # no [accepted] or [preprint]
    for name in ("tmlr.sty", "tmlr.bst", "fancyhdr.sty"):
        assert (PAPER / name).exists()
    sections = [re.search(r"\\section\{(.+?)\}", (PAPER / "sections" / f"{s}.tex").read_text()).group(1)
                for s in re.findall(r"\\input\{sections/(\w+)\}", main)]
    assert sections == ["Introduction", "Related Work", "Benchmark", "Experimental Setup", "Results",
                        "Limitations", "Conclusion"]
    keys = set(re.findall(r"@\w+\{(\w+),", (PAPER / "references.bib").read_text(encoding="utf-8")))
    cited = set()
    for tex in PAPER.rglob("*.tex"):
        for group in re.findall(r"\\cite[tp]?\{([^}]+)\}", tex.read_text(encoding="utf-8")):
            cited |= {k.strip() for k in group.split(",")}
    assert cited and cited <= keys
    # The related papers SPEC.md requires; the bibliography may cite more.
    assert {"wang2026lostcompaction", "chen2026governancedecay", "salle2026compactionfriendly",
            "sun2026compactbench", "woolford2026transparentcompaction", "min2026sjc",
            "todo2026revoked", "todo2026forgetting"} <= keys


def _report(tmp_path, pilot):
    scenarios, labels, probes = synthetic_run(pilot, n_scenarios=24)
    analyze(labels, scenarios, probes, tmp_path / "run" / "report", n_boot=50)
    return tmp_path / "run"


def test_make_paper_assets_writes_tables_macros_and_figures(tmp_path, pilot):
    run = _report(tmp_path, pilot)
    out = tmp_path / "generated"
    (out / "tables").mkdir(parents=True)
    (out / "tables" / "stale_from_old_run.tex").write_text("old")
    assert assets.main(["r1", "--run-dir", str(run), "--out", str(out)]) == 0
    tables = {p.stem for p in (out / "tables").glob("*.tex")}
    assert tables == {"inflation_rates", "inflation_rates_unflagged", "controls", "precision_recall",
                      "behaviour", "regression_items", "regression_behaviour", "labels",
                      "allowed_labels", "precedence"}
    infl = (out / "tables" / "inflation_rates.tex").read_text()
    assert infl.startswith("\\begin{tabular}{llrrrr}")  # two models, so a model column
    assert "request\\_promoted" in infl and "keep\\_rules" in infl
    # Conditions in the paper's fixed order, within each model.
    rows = [l.split(" & ")[1] for l in infl.splitlines() if l.startswith("m-a &")]
    assert rows == ["free", "sectioned", "keep\\_rules", "extractor", "pinning"]
    assert re.search(r"\d+\.\d \{\\scriptsize\[\d+\.\d, \d+\.\d\]\}", infl)
    assert "condition: sectioned" in (out / "tables" / "regression_items.tex").read_text()
    labels = (out / "tables" / "labels.tex").read_text()
    assert all(f"\\texttt{{{assets.tex(k)}}}" in labels for k in LABEL_DEFINITIONS)
    macros = (out / "macros.tex").read_text()
    assert "\\newcommand{\\ibRunId}{r1}" in macros and "\\newcommand{\\ibNScenarios}{24}" in macros
    assert sorted(p.name for p in (out / "figures").glob("*.png")) == [
        "behaviour.png", "controls_and_loss.png", "inflation_by_type.png", "precision_recall.png"]


def test_make_paper_assets_without_probes_or_report(tmp_path, pilot):
    scenarios, labels, _ = synthetic_run(pilot, n_scenarios=12)
    analyze(labels, scenarios, None, tmp_path / "run" / "report", n_boot=20, figures=False)
    out = tmp_path / "generated"
    assert assets.main(["r", "--run-dir", str(tmp_path / "run"), "--out", str(out)]) == 0
    assert not (out / "tables" / "behaviour.tex").exists()
    assert assets.main(["r", "--run-dir", str(tmp_path / "missing"), "--out", str(out)]) == 1


def test_tex_escapes_and_formats():
    assert assets.tex("a_b & 50% #1") == "a\\_b \\& 50\\% \\#1"
    assert assets.pct(float("nan")) == "--"
    assert assets.pct(-0.05, -0.1, 0.0, signed=True) == "$-$5.0 {\\scriptsize[$-$10.0, +0.0]}"
    assert assets.term_name("C(condition, Treatment('free'))[T.pinning]") == "condition: pinning"


def _latexmk_runs() -> bool:
    """latexmk can be on PATH but unable to run (MiKTeX without Perl), so try it."""
    if not shutil.which("latexmk"):
        return False
    try:
        return subprocess.run(["latexmk", "-v"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _latexmk_runs(), reason="needs a working LaTeX installation with latexmk")
def test_paper_builds(tmp_path, pilot):
    build = tmp_path / "paper"
    shutil.copytree(PAPER, build, ignore=shutil.ignore_patterns("generated", "main.pdf"))
    assets.main(["r1", "--run-dir", str(_report(tmp_path, pilot)), "--out", str(build / "generated")])
    res = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
                         cwd=build, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout[-3000:]
    assert (build / "main.pdf").exists()
