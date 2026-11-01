"""Build the Scientific Reports / arXiv upload zip for paper/scirep/.

    python scripts/make_scirep_zip.py [--out paper/scirep/build/inflatebench-scirep.zip]

Steps:
1. Check that the abstract in main.tex is the text of abstract.txt, word for word.
2. Compile main.tex and supplementary.tex with latexmk in paper/scirep/ (output in build/) and
   stop on any undefined reference or citation or missing figure.
3. Collect the upload files: main.tex, supplementary.tex, main.bbl with references.bib and
   naturemag-doi.bst (so a build that runs BibTeX regenerates the same .bbl instead of an
   empty one), wlscirep.cls and the jabbrv files the class loads, exactly the figure files that \\includegraphics names (as
   figures/<name>) and the generated tables supplementary.tex inputs (as tables/<name>.tex).
   Figures and tables come from paper/scirep/figures|tables/ if present, else from
   paper/generated/ (python scripts/make_paper_assets.py RUN_ID --no-titles).
4. Compile that file set in a scratch copy twice, with the shipped .bbl and no BibTeX (arXiv)
   and with BibTeX (Overleaf, journal systems), and check each: no undefined citations and a
   reference entry for every cited key.
5. Write the zip with only those files: no build artifacts.

Everything it writes goes under paper/scirep/build/, which is git-ignored.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCIREP = ROOT / "paper" / "scirep"
GENERATED = ROOT / "paper" / "generated"
BUILD = SCIREP / "build"
TEX = ("main.tex", "supplementary.tex")
CLASS_FILES = ("wlscirep.cls", "jabbrv.sty", "jabbrv-ltwa-all.ldf", "jabbrv-ltwa-en.ldf")
# Shipped next to main.bbl: a system that runs BibTeX (Overleaf, a journal's build) rewrites
# main.bbl from these, and without them BibTeX would leave it empty.
BIB_FILES = ("references.bib", "naturemag-doi.bst")
LOG_PROBLEMS = re.compile(r"(LaTeX Warning: (Reference|Citation) .* undefined"
                          r"|There were undefined references"
                          r"|LaTeX Warning: Label\(s\) may have changed"
                          r"|File `[^']*' not found"
                          r"|! LaTeX Error)")


def fail(msg: str) -> None:
    print(f"make_scirep_zip: {msg}", file=sys.stderr)
    raise SystemExit(1)


def check_abstract() -> None:
    main = (SCIREP / "main.tex").read_text(encoding="utf-8")
    m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", main, re.S)
    if not m:
        fail("no abstract environment in main.tex")
    tex_words = m.group(1).replace("\\%", "%").split()
    txt_words = (SCIREP / "abstract.txt").read_text(encoding="utf-8").split()
    if tex_words != txt_words:
        fail("the abstract in main.tex differs from abstract.txt")
    print(f"abstract matches abstract.txt ({len(txt_words)} words)")


def strip_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", text)


def used_assets() -> tuple[list[Path], list[Path]]:
    """(figure files, table files) the .tex files use, resolved to existing paths."""
    figures, tables = [], []
    for name in TEX:
        text = strip_comments((SCIREP / name).read_text(encoding="utf-8"))
        for fig in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", text):
            figures.append(resolve(fig, "figures"))
        for tab in re.findall(r"\\gentable\{([^}]+)\}", text):
            if tab != "#1":
                tables.append(resolve(f"{tab}.tex", "tables"))
    return figures, tables


def resolve(name: str, kind: str) -> Path:
    for base in (SCIREP / kind, GENERATED / kind):
        if (base / name).is_file():
            return base / name
    fail(f"{kind[:-1]} {name} not found in paper/scirep/{kind}/ or paper/generated/{kind}/; "
         "run python scripts/make_paper_assets.py RUN_ID --no-titles")
    raise AssertionError


def check_logs(directory: Path, label: str) -> None:
    for name in TEX:
        log = directory / name.replace(".tex", ".log")
        if not log.exists():
            fail(f"{label}: {log} missing")
        problems = [line for line in log.read_text(encoding="latin-1").splitlines()
                    if LOG_PROBLEMS.search(line)]
        if problems:
            fail(f"{label}: {log.name}:\n  " + "\n  ".join(problems))


def check_bibliography(directory: Path, label: str) -> None:
    """Every key main.tex cites has an entry in main.bbl (an empty .bbl leaves no reference list)."""
    text = strip_comments((SCIREP / "main.tex").read_text(encoding="utf-8"))
    cited = {k.strip() for group in re.findall(r"\\cite\{([^}]+)\}", text) for k in group.split(",")}
    bbl = (directory / "main.bbl").read_text(encoding="utf-8") if (directory / "main.bbl").exists() else ""
    entries = set(re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", bbl))
    if not cited or cited - entries:
        fail(f"{label}: main.bbl lacks entries for {sorted(cited - entries) or 'all citations'}")
    print(f"{label}: {len(entries)} references for {len(cited)} cited keys")


def run(cmd: list[str], cwd: Path) -> None:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        fail(f"{' '.join(cmd)} failed in {cwd}:\n{res.stdout[-3000:]}\n{res.stderr[-2000:]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default=str(BUILD / "inflatebench-scirep.zip"))
    args = p.parse_args(argv)

    check_abstract()
    figures, tables = used_assets()

    # 2. Build in place (latexmkrc puts everything in build/).
    run(["latexmk", "-interaction=nonstopmode", "-halt-on-error", *TEX], SCIREP)
    check_logs(BUILD, "repository build")
    check_bibliography(BUILD, "repository build")

    # 3. The upload file set: archive name -> source path.
    files: dict[str, Path] = {name: SCIREP / name for name in (*TEX, *CLASS_FILES, *BIB_FILES)}
    files["main.bbl"] = BUILD / "main.bbl"
    files.update({f"figures/{f.name}": f for f in figures})
    files.update({f"tables/{t.name}": t for t in tables})
    for arc, src in files.items():
        if not src.is_file():
            fail(f"{src} missing (for {arc})")

    # 4. Compile the file set alone, both ways a journal, Overleaf or arXiv may build it:
    #    pdflatex with the shipped main.bbl (arXiv), and pdflatex + BibTeX (Overleaf, journals).
    for with_bibtex in (False, True):
        label = "upload file set, " + ("pdflatex + bibtex" if with_bibtex else "pdflatex with shipped .bbl")
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            for arc, src in files.items():
                (scratch / arc).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, scratch / arc)
            for name in TEX:
                run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", name], scratch)
                if with_bibtex and name == "main.tex":
                    run(["bibtex", "main"], scratch)
                for _ in range(2):
                    run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", name], scratch)
            check_logs(scratch, label)
            check_bibliography(scratch, label)
            loaded = {Path(m).name for name in TEX
                      for m in re.findall(r"<(figures/[^,>]+\.pdf)",
                                          (scratch / name.replace(".tex", ".log")).read_text(encoding="latin-1"))}
            if loaded != {f.name for f in figures}:
                fail(f"{label}: figures loaded {sorted(loaded)} != figures named {sorted(f.name for f in figures)}")

    # 5. Zip.
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for arc in sorted(files):
            z.write(files[arc], arc)
    print(f"wrote {out} with {len(files)} files:")
    for arc in sorted(files):
        print(f"  {arc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
