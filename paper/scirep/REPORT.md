# Scientific Reports version: build notes and report

## Files

| File | Content |
| --- | --- |
| `main.tex` | Main paper on the `wlscirep` class |
| `supplementary.tex` | Supplementary Information (Appendices A–C, planted items, behaviour rates, constraint precision, full preregistered test results) |
| `references.bib` | Bibliography: numbered Nature style (`naturemag-doi.bst`, as in the template) |
| `abstract.txt` | Abstract text. `main.tex` holds the same words, and the zip script checks that they match |
| `wlscirep.cls`, `naturemag-doi.bst`, `jabbrv.sty`, `jabbrv-ltwa-*.ldf` | Template files. The class loads `jabbrv` and sets `naturemag-doi` |
| `latexmkrc` | `latexmk` builds both documents into `build/`, which is git-ignored |
| `../../scripts/make_scirep_zip.py` | Builds the upload zip |

## Building

The figures and the hypothesis tables are not in the repository: `paper/generated/` and `runs/` are git-ignored. Create them from the combined run first:

```bash
python scripts/make_paper_assets.py combined --no-titles
```

```bash
cd paper/scirep && latexmk
```

```bash
python scripts/make_scirep_zip.py
```

The script writes `paper/scirep/build/inflatebench-scirep.zip`. It does the following:

1. Checks the abstract against `abstract.txt`.
2. Builds with `latexmk` and stops on any undefined reference or citation, or a missing figure.
3. Test-compiles the zip's own file set in a scratch directory with `pdflatex` and the shipped `.bbl`, without BibTeX, as a journal or arXiv would.
4. Checks that exactly the figures named by `\includegraphics` were loaded.

The zip holds 14 files:
- `main.tex`, `supplementary.tex` and `main.bbl`
- `wlscirep.cls`, plus the three `jabbrv` files the class loads
- `figures/` with `inflation_by_type.pdf`, `hypotheses_forest.pdf`, `behaviour.pdf`, `controls_and_loss.pdf` and `precision.pdf`
- `tables/` with `hypotheses.tex` and `hypotheses_by_model.tex`

It holds no build artifacts.

**Verification done here.** The real run outputs were not available in this environment. I checked the build with assets from the offline `--fake` pipeline on the 25 pilot scenarios: two fake runs (the second with its model field renamed, so that `ib analyze --runs` pools two "models" and writes the hypothesis tables), then `make_paper_assets.py combined --no-titles`. Those assets are git-ignored and were not committed, and their numbers are meaningless.

`python scripts/make_scirep_zip.py` passed: both documents compiled with `latexmk` with no undefined references or citations and no overfull boxes, and the zip's own file set recompiled from the shipped `.bbl`. Two underfull lines remain (one reference entry, one narrow table cell in Supplementary Table S3). The compiled PDFs show:
- Figures 1–4 in `main.pdf` (13 pages), on pages 4, 5, 7 and 8
- Tables 1–3, on pages 3, 4 and 10
- Supplementary Tables S1–S8 and Supplementary Figure S1 in `supplementary.pdf`

Rerun the two commands above once the real assets are in `paper/generated/`.

## Counts

| Item | Count |
| --- | --- |
| Main text (Introduction + Results + Discussion, without abstract, Methods, references, legends, table contents or headings) | **3,727 words** (Introduction 1,304; Results 1,342; Discussion 1,081). Headings add 41 words. The run-in headings *Related work.*, *Limitations.* and *Conclusion.* and the bold paragraph leads are counted as text. Against the previous 3,718: the display-item citations add 24 words, the longer condition names 10, the run-in headings 4 (moved from the headings), and the removed OpenAI text takes away 29 |
| Abstract | **194 words** |
| Display items in the main paper | **7**: Figures 1–4 and Tables 1–3 (limit 8) |
| Supplementary items | Supplementary Tables S1–S8, Supplementary Figure S1 |

Figure and table mapping:
- Figures:
  - Manuscript Figure 1 → Fig. 1
  - Figure 3 → Fig. 2
  - Figure 4 → Fig. 3
  - Figure 5 → Fig. 4
  - Figure 2 → Supplementary Figure S1
- Main tables:
  - The Section 3 types table → Table 1
  - Manuscript Table 2 → Table 2
  - The conditions table → Table 3

  (The previous version of this report had Tables 2 and 3 the wrong way round. LaTeX numbers the tables in source order, and the conditions table is in Methods.)
- Supplementary tables:
  - The pilot table → S1
  - The label definitions, allowed labels and worked examples → S2–S4
  - The planted items → S5
  - Manuscript Table 3 → S6
  - `hypotheses.tex` and `hypotheses_by_model.tex` → S7 and S8

## Wording changes beyond the requested restructuring

- **Section numbers.** Scientific Reports sections are unnumbered, so four cross-references were reworded:
  - "the entry-by-entry rule from Section 3" → "from *Constraint inflation* (Results)"
  - "the entry-by-entry rule of Section 3" → "of *Constraint inflation* (Results)"
  - "reported in Section 5.4" → "reported in Methods (*Human validation*)"
  - "described in Section 5" (Use of AI tools) → "described above" (Use of AI tools is the last subsection of Methods)
- **Planted items.** "…each tied to one user turn:" introduced the table, which is now in the Supplementary Information. The sentence now ends "…each tied to one user turn (Supplementary Table S5)."
- **"(Table 2)"** became `Table~\ref{tab:combined}`, which renders as Table 2.
- **Citations.** Parenthetical author–year citations became superscript numbers, for example "(Chen, 2026)" → `\cite{...}`. Names that the sentence uses grammatically were kept: "Wang et al. evaluate…", "AuthMem-Bench shows…", "(MemPABench)", "(OP-Bench)", "(CAPTURE)".
- **OpenAI report removed.** The clause "and OpenAI has described models writing new rules into their own compaction summaries during training" (Introduction) and the sentence "OpenAI has reported models adding rules of their own to compaction summaries during training." (Related work) were removed, with the OpenAI reference.
- **Display-item citations.** Every display item is now cited, in this order of first citation:
  - Supplementary Table S1: end of the pilot sentence ("…into the nightly job's strategy (Supplementary Table S1).")
  - Table 1: "We distinguish four types (Table 1), and pair them…"
  - Fig. 1: "**Summaries kept almost every instruction but inflated many of them** (Fig. 1)." The period now follows the citation, outside the bold
  - Table 2 (already cited) and Supplementary Fig. S1: "…ranged from 88% down to 40% (Table 2; Supplementary Fig. S1)."
  - Fig. 2 and Supplementary Tables S7 and S8: in H1, "(odds ratio 1.63, Holm p < 10⁻⁴³; Fig. 2; Supplementary Tables S7 and S8)"
  - Supplementary Table S6: "…in 0.7% of episodes (Supplementary Table S6)." (H5)
  - Fig. 3: in H5, "(odds ratios 4.2, 6.0 and 8.1; Holm p < 10⁻¹¹; Fig. 3)"
  - Fig. 4: "Softening stayed at or below 0.3% in all 14 cells (Fig. 4)." (H6)
  - Supplementary Table S5 (already cited): planted items
  - Table 3: "We compact every session in seven ways (Table 3)."
  - Supplementary Tables S2–S4: "…with the same definitions as the judges (Supplementary Tables S2–S4)." (Human validation)

  Supplementary items are cited as plain text, since they are in a separate document.
- **Headings.** *Related work*, *Limitations* and *Conclusion* are bold run-in headings ("**Related work.**") at the start of their first paragraph, not subsections. In Related work and Limitations that first paragraph already opens with its own bold lead, so the two stand side by side: "**Related work.** **What compaction loses.** A fast-growing…".
- **Results opening.** The paragraph "Each model produced 5,040 summaries…" now opens Results, before *Constraint inflation*.
- **Condition names.** The running text and Table 3 use the display names of the figures and generated tables: *free (250 words)*, *sectioned (no Constraints)* and *keep rules*, in place of `free_limited`, `sectioned_noconstraints` and `keep_rules`. Italics are kept where the text italicised a method name.
- **Legends.** Each placeholder's text became the figure legend. The italic legend titles are set in bold.
- **New captions.** Some tables had no caption in the manuscript and now have short title-only ones, written from their column headings or their bold headings in Appendix C:
  - Main Tables 1 and 2
  - Supplementary Tables S1–S5
- **New legends for S7 and S8.** These describe the generated tables' columns, taken from the description in `make_paper_assets.py`.

## Ambiguities and points to check

1. **Subheadings and the template.** The template's guidance says the Introduction "should not include subheadings" and the Discussion "must not contain subheadings". *Related work*, *Limitations* and *Conclusion* are now bold run-in paragraph headings, not subsections, so the Introduction and Discussion have no subheadings.
2. **The first paragraph of Section 6** ("Each model produced 5,040 summaries…") now opens Results, before *Constraint inflation*.
3. **Display items.** Every display item is now cited in the text (see *Display-item citations* above). Figs. 1–4 and Tables 1–3 are first cited in numerical order. The Supplementary items are first cited in the order S1, S7, S8, S6, S5, S2–S4, which follows the main text, not the Supplementary Information.
4. **Methods headings.** "Sections 4 and 5 with their subsection headings": the top-level headings *The InflateBench benchmark* and *Experimental setup* were dropped. The Section 4 intro paragraph opens Methods, followed by the twelve subsections and *Use of AI tools*.
5. **Appendix B** is two Markdown lists with different bullet markers (`-` and `*`). They are merged into one list.
6. **References:**
   - *Zhan et al. (2026)* has no initials, so it is set as `author = {Zhan and others}`, with a `% TODO` for the full author list.
   - The *Zhang, Q., Hu, C., et al.* entry is set the same way, with "and others" and a `% TODO`.
   - Venues given in the manuscript (CIKM 2026, NeurIPS 2026, ICLR 2026) are kept.
   - Kolagar and Zarcone (2024) and Maynez et al. (2020) have no URL or DOI in the manuscript, and none was added.
   - The OpenAI entry was removed with the two sentences that cited it.
   - The ten "[Authors to add]" entries now have their authors (arXiv 2606.18471, 2609.08258, 2609.04875, 2610.30485, 2601.13722, 2609.02265, 2609.01836, 2608.12599, 2605.09268, 2607.27080). No entry prints "TODO" any more.
   - "Mitrović" is written `Mitrovi{\'{c}}`.
7. **Data availability.** The manuscript says all model outputs are released, but `runs/` is git-ignored and no archive is named. The statement gives the GitHub repository and leaves a red TODO for the archived location (DOI). The licences are taken from `data/LICENSE.md` (CC BY 4.0) and `LICENSE` (MIT). The private held-out set is mentioned, as in Methods.
8. **ORCID.** `wlscirep` has no ORCID field, so the ORCID and the email link are in an *Author information* section after Funding. The email also appears under the affiliations, as in the template.
9. **Template source.** Overleaf is blocked from this environment. `wlscirep.cls` (v1.3, 27/02/2017) and its companion files come from a public GitHub copy of the Overleaf template (`mmelgui/Scientific-Report`). It matches the header and version in other copies. You may want to diff it against a fresh download from Overleaf.
10. **arXiv.** The zip has two top-level `.tex` files. If arXiv's processing should show only the paper, choose `main.tex` as the main file, or upload the supplement separately.
11. **Characters.** Both documents load `\usepackage[T1]{fontenc}` after the class, so Times is set in T1 and accented letters are real glyphs (they also copy and search correctly in the PDF). "Műegyetem" is written `M\H{u}egyetem` and "Mitrović" `Mitrovi{\'{c}}`. Unicode minus signs, superscripts, ± and α are written in math mode.
