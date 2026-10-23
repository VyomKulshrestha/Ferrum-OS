# Prompt 1: review every number and citation in the draft

Paste the text below into Claude Science with this pack's folder open as the project. Turn on the
background reviewer.

---

You are reviewing a security paper draft before submission. The draft is
`manuscript/thresholds_that_travel_draft_v0_1.md`. Every number in it should come from a file in
`results/`, `figure_data/` or `protocols/`. Nothing in this folder may be recomputed from raw data: the
raw datasets are not here, and the registered studies allowed one access per dataset, already used.

Do these five checks and write the report to `review/review_report.md`.

1. **Trace every number.** For each number in the draft (abstract, text, tables, captions), find the file
   and JSON field or CSV cell it comes from. Report a table with: draft location, the number as written,
   source file, field or cell, value in the source, and match / mismatch / untraceable. Treat rounding
   as a match only when the draft's rounding is correct. Recall values such as 36/38 should match
   `detected` and `events`.
2. **Registered versus exploratory.** The registered results are in
   `results/threshold_transfer_tt1_result_*.json` (study tt1) and
   `results/threshold_transfer_tt1b_result_batadal.json` (study tt1b); their gates are listed under
   `gates`. Everything from `*_dev_*`, `*_posthoc*` or `figure_data/attack_campaigns.csv` rows marked
   exploratory is exploratory. Flag any sentence that presents an exploratory number as registered, or
   that reports a failed gate as passed. tt1b's primary rule failed (H3); check that the draft says so.
3. **Citations.** For each reference, confirm the authors, title, venue and year, and that the cited
   paper supports the sentence that cites it. Give a DOI or arXiv ID where one exists. The entries marked
   [VERIFY] need the most attention. Flag any claim about prior work that the cited paper does not make.
4. **Claims against limitations.** Check that each caveat in `manuscript/threshold_transfer_tt1_findings.md`
   appears in the draft: the G1 caveat (adaptive rules were already blind in the controls on HAI 20.07),
   the failed H3 on BATADAL, the dependence of SPOT on its tail estimator and on heavy tails, the
   score-level attacker as an upper bound, the white-box assumption of the physical attacker, and the
   fragility of spread-scaled parameters on heavy-tailed scores.
5. **Internal consistency.** Flag numbers that disagree between sections, tables that disagree with the
   text, and dataset or event counts that change between mentions.

Do not edit the draft. Propose replacement sentences in the report, each next to the problem it fixes.
End the report with a count of matches, mismatches and untraceable numbers.
