import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from inflatebench.analyze.report import analyze
from inflatebench.judge import ALLOWED_LABELS, LABEL_DEFINITIONS
from inflatebench.judge.rubric import ENTRY_RULES, PRECEDENCE, system_prompt
from inflatebench.schema import LABELS
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
    # The rules for an item presented in several entries, each with its worked example, are the
    # judges' words (labels in backticks instead of quotes), in the same order.
    positions = []
    for rule, example in ENTRY_RULES:
        for part in (rule, example):
            assert _backticked(part) in text, part[:60]
            positions.append(text.index(_backticked(part)))
    assert positions == sorted(positions)
    # The retired rules are gone: a heading no longer excuses a preference, and one entry
    # marking a value replaced no longer clears a stale entry elsewhere.
    for retired in ("under a heading that says", "some place marks the old value as replaced"):
        assert retired not in text and retired not in system_prompt()


def _backticked(text):
    for label in LABELS:
        text = text.replace(f'"{label}"', f"`{label}`")
    return text


def test_judge_prompt_states_each_entry_rule_with_its_example():
    prompt = system_prompt()
    for k, (rule, example) in enumerate(ENTRY_RULES, 1):
        assert f"{k}. {rule}\n   Example: {example}" in prompt
    assert len(ENTRY_RULES) == 4


def test_entry_rules_examples_use_allowed_labels():
    # Each worked example names labels its item type allows (one_off, changed_value,
    # preference, request in rule order).
    types = ("one_off", "changed_value", "preference", "request")
    for (_, example), item_type in zip(ENTRY_RULES, types):
        named = {label for label in LABELS if f'"{label}"' in example}
        assert named and named <= set(ALLOWED_LABELS[item_type]), (item_type, named)


def test_headings_rule_covers_every_unhedged_form():
    # Rule 3 hardens a preference in any unhedged form, not only a bare imperative, under any
    # heading; the hardened definition says the same on the judge prompt, guide and page.
    rule, example = ENTRY_RULES[2]
    for form in ("bare imperative", "bare noun phrase", "flat statement"):
        assert form in rule, form
    for hedge in ("prefer", "ideally", "if possible", "where possible"):
        assert hedge in rule, hedge
    assert "whatever heading" in rule
    # The worked example labels a noun phrase and a flat statement hardened, their hedged
    # versions correct.
    assert '"Short variable names." (a noun phrase)' in example
    assert '"Variable names are short." (a flat statement) is "hardened"' in example
    assert '"Short variable names where possible." or "Ideally, variable names are short." is "correct"' in example
    assert "noun phrase or flat statement" in LABEL_DEFINITIONS["hardened"]
    assert "Headings and unhedged forms" in GUIDE.read_text(encoding="utf-8")
    assert "only a bare imperative" not in system_prompt()


def test_label_guide_examples_use_allowed_labels():
    text = GUIDE.read_text(encoding="utf-8")
    for label, item_type in re.findall(r"^\| (\w+) \| (\w+): ", text, re.M):
        assert label in ALLOWED_LABELS[item_type], (label, item_type)


def test_paper_is_anonymous_and_cites_known_keys():
    main = (PAPER / "main.tex").read_text(encoding="utf-8")
    assert re.search(r"^\\usepackage\{tmlr\}", main, re.M)  # no [accepted] or [preprint]
    for name in ("tmlr.sty", "tmlr.bst", "fancyhdr.sty"):
        assert (PAPER / name).exists()
    sections = [re.search(r"\\section\{(.+?)\}", (PAPER / "sections" / f"{s}.tex").read_text(encoding="utf-8")).group(1)
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
    infl = (out / "tables" / "inflation_rates.tex").read_text(encoding="utf-8")
    assert infl.startswith("\\begin{tabular}{llrrrr}")  # two models, so a model column
    assert "request\\_promoted" in infl and "keep rules" in infl
    # Conditions in the paper's fixed order, within each model.
    rows = [l.split(" & ")[1] for l in infl.splitlines() if l.startswith("m-a &")]
    assert rows == ["free", "sectioned", "keep rules", "extractor", "pinning"]
    assert re.search(r"\d+\.\d \{\\scriptsize\[\d+\.\d, \d+\.\d\]\}", infl)
    assert "condition: sectioned" in (out / "tables" / "regression_items.tex").read_text(encoding="utf-8")
    labels = (out / "tables" / "labels.tex").read_text(encoding="utf-8")
    assert all(f"\\texttt{{{assets.tex(k)}}}" in labels for k in LABEL_DEFINITIONS)
    macros = (out / "macros.tex").read_text(encoding="utf-8")
    assert "\\newcommand{\\ibRunId}{r1}" in macros and "\\newcommand{\\ibNScenarios}{24}" in macros
    figures = ["behaviour", "controls_and_loss", "inflation_by_type", "precision"]
    assert sorted(p.name for p in (out / "figures").iterdir()) == sorted(
        f"{f}.{ext}" for f in figures for ext in ("pdf", "png"))
    assert not (out / "tables" / "hypotheses.tex").exists()  # a single run has no hypothesis tests


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
    assert assets.p_value(0.0) == "$<10^{-300}$"
    assert assets.p_value(5e-324) == "$<10^{-300}$"  # subnormal: underflowed too
    assert assets.p_value(1.5e-30) == "$1.5\\times 10^{-30}$"
    assert assets.p_value(0.0123) == "0.012"
    assert assets.p_value(float("nan")) == "--"


def test_tables_use_model_display_names():
    rates = pd.DataFrame({"model": ["claude-haiku-5-5", "glm-5.3-flash"], "condition": "free",
                          "type": "promoted", "rate": 0.1, "lo": 0.05, "hi": 0.2})
    table = assets.rates_table(rates, ("promoted",))
    assert "Claude Haiku 5.5 & free" in table and "GLM-5.3-Flash & free" in table
    assert "claude-haiku" not in table and "glm-5.3-flash" not in table
    bm = pd.DataFrame({"test": "H1", "model": ["claude-haiku-5-5", "glm-5.3-flash"],
                       "rate_diff": 0.1, "rate_diff_lo": 0.0, "rate_diff_hi": 0.2})
    assert "Test & Comparison & Claude Haiku 5.5 & GLM-5.3-Flash" in assets.hypotheses_by_model_table(bm)


def test_paper_figures_without_titles(tmp_path, pilot):
    import matplotlib.pyplot as plt
    from inflatebench.analyze import plots

    run = _report(tmp_path, pilot)
    titles = {}
    real = plots.save

    def save(fig, path):
        titles[Path(path).stem] = fig._suptitle.get_text() if fig._suptitle else None
        return real(fig, path)

    plots.save = save
    try:
        out = tmp_path / "generated"
        assert assets.main(["r1", "--run-dir", str(run), "--out", str(out), "--no-titles"]) == 0
    finally:
        plots.save = real
    figures = ["behaviour", "controls_and_loss", "inflation_by_type", "precision"]
    assert titles == {f: None for f in figures}
    assert sorted(p.name for p in (out / "figures").iterdir()) == sorted(
        f"{f}.{ext}" for f in figures for ext in ("pdf", "png"))
    # The report's own figures keep their titles (unchanged by the paper's run).
    report_png = plt.imread(run / "report" / "figures" / "precision.png")
    paper_png = plt.imread(out / "figures" / "precision.png")
    assert report_png.shape != paper_png.shape or (report_png != paper_png).any()


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
