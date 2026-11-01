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
3. Test-compiles the zip's own file set in a scratch directory twice: with `pdflatex` and the shipped `.bbl` (as arXiv does), and with `pdflatex` + BibTeX (as Overleaf and journal systems may). Each time it checks that there are no undefined citations and that `main.bbl` has an entry for every cited key.
4. Checks that exactly the figures named by `\includegraphics` were loaded.

The zip holds 16 files:
- `main.tex`, `supplementary.tex` and `main.bbl`
- `references.bib` and `naturemag-doi.bst`. Without them, a build that runs BibTeX overwrites `main.bbl` with an empty file, and the reference list disappears
- `wlscirep.cls`, plus the three `jabbrv` files the class loads
- `figures/` with `inflation_by_type.pdf`, `hypotheses_forest.pdf`, `behaviour.pdf`, `controls_and_loss.pdf` and `precision.pdf`
- `tables/` with `hypotheses.tex` and `hypotheses_by_model.tex`

It holds no build artifacts.

**Verification done here.** The real run outputs were not available in this environment. I checked the build with assets from the offline `--fake` pipeline, on the pilot scenarios, using `make_paper_assets.py --no-titles`. Those assets are git-ignored and were not committed, and their numbers are meaningless.

Both documents compiled with `latexmk` with no undefined references or citations and no overfull boxes. The compiled PDFs show:
- Figures 1–4 in `main.pdf`, on pages 4, 5, 7 and 8
- Tables 1–3, on pages 3, 4 and 10
- Supplementary Figure S1 in `supplementary.pdf`

Rerun the two commands above once the real assets are in `paper/generated/`.

## Counts

| Item | Count |
| --- | --- |
| Main text (Introduction + Results + Discussion, without abstract, Methods, references, legends, table contents or headings) | **3,718 words** (Introduction 1,328; Results 1,313; Discussion 1,077). Headings add 45 words |
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
  - The conditions table → Table 2
  - Manuscript Table 2 → Table 3
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
  - "described in Section 5" (Use of AI tools) → "described in Methods"
- **Planted items.** "…each tied to one user turn:" introduced the table, which is now in the Supplementary Information. The sentence now ends "…each tied to one user turn (Supplementary Table S5)."
- **"(Table 2)"** became `Table~\ref{tab:combined}`, which renders as Table 3.
- **Citations.** Parenthetical author–year citations became superscript numbers, for example "(Chen, 2026)" → `\cite{...}`. Names that the sentence uses grammatically were kept: "Wang et al. evaluate…", "AuthMem-Bench shows…", "(MemPABench)", "(OP-Bench)", "(CAPTURE)".
- **New citations.** The two sentences on the OpenAI report, in the Introduction and in Related work, had no link in the manuscript. Each now cites the OpenAI entry at the end of the sentence.
- **Legends.** Each placeholder's text became the figure legend. The italic legend titles are set in bold.
- **New captions.** Some tables had no caption in the manuscript and now have short title-only ones, written from their column headings or their bold headings in Appendix C:
  - Main Tables 1 and 2
  - Supplementary Tables S1–S5
- **New legends for S7 and S8.** These describe the generated tables' columns, taken from the description in `make_paper_assets.py`.

## Ambiguities and points to check

1. **Subheadings and the template.** The template's guidance says the Introduction "should not include subheadings" and the Discussion "must not contain subheadings". Following the prompt, the Introduction has *Related work*, and the Discussion has *Limitations* and *Conclusion*. The journal may ask for these to be removed.
2. **The first paragraph of Section 6** follows the *Constraint inflation* subsection, as requested. With no heading of its own, it reads as the last paragraph of that subsection.
3. **Display items never cited in the text.** The manuscript never refers to its figures, the types table, the conditions table, Table 3 or Figure 2 by number. To keep sentences word for word I added no citations, so these items are not cited in the text:
   - Figs. 1–4
   - Tables 1 and 2
   - Supplementary Table S6 and Supplementary Figure S1

   Scientific Reports expects every display item to be cited. Natural places would be:
   - Fig. 1 after "inflated many of them"
   - Fig. 2 at H1–H5
   - Fig. 3 in the H5 paragraph
   - Fig. 4 in the H6 paragraph
   - Table 1 after "We distinguish four types"
   - Table 2 after "seven ways"
4. **Methods headings.** "Sections 4 and 5 with their subsection headings": the top-level headings *The InflateBench benchmark* and *Experimental setup* were dropped. The Section 4 intro paragraph opens Methods, followed by the twelve subsections and *Use of AI tools*.
5. **Appendix B** is two Markdown lists with different bullet markers (`-` and `*`). They are merged into one list.
6. **References:**
   - *Zhan et al. (2026)* has no initials, so it is set as `author = {Zhan and others}`.
   - The *Zhang, Q., Hu, C., et al.* entry is set the same way, with "and others".
   - Venues given in the manuscript (CIKM 2026, NeurIPS 2026, ICLR 2026) are kept.
   - Kolagar and Zarcone (2024) and Maynez et al. (2020) have no URL or DOI in the manuscript, and none was added.
   - The OpenAI entry points to the secondary coverage the manuscript links. It is marked "primary source to add" and carries a `% TODO`.
   - The 11 "[Authors to add]" entries have `author = {TODO}` and a `% TODO` comment. They print as "TODO" in the reference list.
7. **Data availability.** The manuscript says all model outputs are released, but `runs/` is git-ignored and no archive is named. The statement gives the GitHub repository and leaves a red TODO for the archived location (DOI). The licences are taken from `data/LICENSE.md` (CC BY 4.0) and `LICENSE` (MIT). The private held-out set is mentioned, as in Methods.
8. **ORCID.** `wlscirep` has no ORCID field, so the ORCID and the email link are in an *Author information* section after Funding. The email also appears under the affiliations, as in the template.
9. **Template source.** Overleaf is blocked from this environment. `wlscirep.cls` (v1.3, 27/02/2017) and its companion files come from a public GitHub copy of the Overleaf template (`mmelgui/Scientific-Report`). It matches the header and version in other copies. You may want to diff it against a fresh download from Overleaf.
10. **arXiv.** The zip has two top-level `.tex` files. If arXiv's processing should show only the paper, choose `main.tex` as the main file, or upload the supplement separately.
11. **Characters.** "Műegyetem" is written `M\H{u}egyetem`, because the class uses OT1 Times. Unicode minus signs, superscripts, ± and α are written in math mode.
