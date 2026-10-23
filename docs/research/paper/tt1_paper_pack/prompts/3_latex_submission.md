# Prompt 3: convert the draft to an anonymous LaTeX submission

Run this after prompts 1 and 2, once the review fixes are in the draft. Check the current call for papers
for the page limit and template version before submitting.

---

Convert `manuscript/thresholds_that_travel_draft_v0_1.md` into an anonymous LaTeX submission in
`latex/`, using the ACM `acmart` class with `\documentclass[sigconf,review,anonymous]{acmart}` (ACM
AsiaCCS). Keep a second copy ready for the USENIX template in `latex_usenix/`.

- Remove the author block, the ORCID, every GitHub link, every Zenodo DOI of the author's own artifacts,
  and the "FerrumOS" project name. Replace the artifact link with `\url{https://anonymous.4open.science/...}`
  and a TODO comment.
- Keep every number exactly as written in the draft after the review in prompt 1. Do not round again.
- Tables in `booktabs` style; figures from `figures/` with their captions; keep the status (registered,
  exploratory, post-hoc) in each caption.
- References as a BibTeX file with DOIs, using the entries verified in `review/review_report.md`.
- Add `\section*{Open science}` stating that the protocols, access ledger, harnesses and verifiers are
  available in the anonymized artifact, and that the raw datasets are available from their publishers.
- Render a preview, report the page count of the main text and of the references, and list anything
  that does not fit the page limit.
