# Anonymous LaTeX submission

Converted from `manuscript/thresholds_that_travel_draft_v0_1.md` (draft v0.1 as revised after
`review/review_report.md`), with the figures from `figures/` and the captions from
`figures/captions.md` shortened for print. No number was recomputed or re-rounded: every value in
the body, the tables and the captions is reproduced as the draft and the captions wrote it. A
token-by-token comparison of the draft body against `main.tex` leaves only citation years and
section cross-references (now `\cite` and `\ref`) and LaTeX length fractions such as
`p{0.33\textwidth}` unmatched; no result-bearing number differs.

| File | What it is |
|---|---|
| `main.tex` | ACM `acmart` `[sigconf,review,anonymous]`, the ASIA CCS 2027 submission |
| `refs.bib` | 18 references, identifiers as listed in the draft and corrected in the review |
| `figures/` | the five figure PDFs, copied from `../figures/` |
| `main.pdf` | compiled output (tectonic 0.17.0, XeTeX) |

`../latex_usenix/` holds the same body for the USENIX Security template (`article`, two-column,
10 pt), with the official `usenix-2020-09.sty` picked up automatically if dropped beside it and a
geometry fallback otherwise.

## Compiling

```
tectonic main.tex
```

or `xelatex main && bibtex main && xelatex main && xelatex main`. `acmart.cls` and
`ACM-Reference-Format.bst` must be on the TeX path; use the latest sigconf template from the ACM author
site, as the call for papers requires. The committed `main.pdf` was built with tectonic 0.17.0 (XeTeX).

Ten of the sixteen floats are full-width. With the class defaults the float queue jams and the last
tables and figures land after the references, so the preamble relaxes the float limits and a
`\FloatBarrier` (package `placeins`) before the conclusion flushes every float ahead of it. The USENIX
copy carries the same settings.

## Page count (from the committed PDFs, 2026-11-01)

| | ACM sigconf | USENIX |
|---|---|---|
| Total pages | 11 | 13 |
| Body text ends | page 10 (conclusion; references begin there) | page 11 |
| Ethical considerations and Open science appendices | page 11 | page 12 |

ASIA CCS 2027 allows 12 pages excluding the bibliography and well-marked appendices, plus up to 10
further pages for them. The body ends on page 10.

## Still to do before submission

1. Replace both `https://anonymous.4open.science/...` placeholders (contribution 5 and the Open
   science appendix); each is marked with a `% TODO` comment.
2. Done on 2026-11-01: recompiled with the float settings (no float lands after the references) and
   added an `Ethical considerations` appendix before the Open science appendix.
3. Done on 2026-11-01: Section 3.1 (how long a threshold remembers: Propositions 1 to 3) and the
   post-hoc time-in-alarm, onset-recall and attacks-only analyses in Sections 6.2, 6.3 and 7.3, from
   `results/threshold_transfer_tt1_memory_check.json` and
   `results/threshold_transfer_tt1_posthoc_alarm_time.json`.
4. Confirm the HyGrid-ICS version and concept DOIs on the Zenodo record (review finding C4); both
   are in `refs.bib` as the draft gives them.

## Anonymization record

Removed: the author line and affiliation, the ORCID, the drafting header (target venues, draft
date, the review-status note) and the reference-list preamble that pointed at
`review/review_report.md`.

Rewritten: "the world-model residual monitor of our earlier registered studies on HAI" became
"... of earlier registered studies on HAI [anonymized]" (Section 4). The artifact pointer in
contribution 5 and in the Open science appendix became an `anonymous.4open.science` placeholder.

Checked absent from both `main.tex` files and both `refs.bib` files: author name, ORCID, any
GitHub URL, any Zenodo DOI of the authors' own artifacts, and the "FerrumOS" project name - which
the revised draft never used, so nothing had to be removed for it.

Kept deliberately: the third-party dataset identifiers, i.e. the HyGrid-ICS Zenodo DOIs
(10.5281/zenodo.23250890 and the concept record 10.5281/zenodo.23250468), the BATADAL DOI
(10.1061/(ASCE)WR.1943-5452.0000969) and the voraus-AD DOI (10.1109/TRO.2023.3332224), together
with the first-person voice, which is normal in a double-blind submission.

## Where the figures and tables sit

Figure numbers follow document order, so the file names and the printed numbers differ.

| Printed | File | Section | Data status in the caption |
|---|---|---|---|
| Figure 1 | `fig1_learning_regions.pdf` | 3, threat model | schematic, no data |
| Figure 2 | `fig2_trajectories_hai2007.pdf` | 5.2, threshold inflation | post-hoc |
| Figure 3 | `fig4_recall_forest.pdf` | 5.2, recall against frozen | registered, exploratory and post-hoc blocks |
| Figure 4 | `fig5_attack_campaigns.pdf` | 6.4, pulse campaigns | exploratory |
| Figure 5 | `fig3_trajectories_batadal.pdf` | 6.6, BATADAL replication | post-hoc |

Tables 1-11 carry their status in the caption as well: registered for Tables 3, 4, 5, 10 and 11
(tt1 and tt1b), exploratory for Tables 7, 8 and 9, exploratory plus post-hoc for Table 6, and no
status for Tables 1 and 2, which describe the rules and the datasets rather than results.

## About the preview

No TeX toolchain was reachable from the Claude Science sandbox this was converted in, so it built a
template-metric layout preview without TeX (`preview_build.py`, `preview_asiaccs.pdf`). The compiled
`main.pdf` replaces it, and the preview files are not committed.
