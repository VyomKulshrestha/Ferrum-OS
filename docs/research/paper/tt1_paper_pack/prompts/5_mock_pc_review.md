# Prompt 5: mock program-committee review

Paste the text below into Claude Science with this pack's folder open as the project. Model Opus 5.5,
background reviewer Sonnet 5.5. Run it after prompt 4, so the reviewers can use
`review/literature_report.md`.

---

You are the program committee of ACM ASIA CCS 2027 reviewing an anonymous submission:
`latex/main.pdf` (source `latex/main.tex`; the longer draft it was made from is
`manuscript/thresholds_that_travel_draft_v0_1.md`). The results it reports are in `results/` and
`figure_data/`; the registrations are in `protocols/`. If `review/literature_report.md` exists, use it
for related work. Do not edit the paper. Write the reviews to `review/mock_pc_review.md`.

1. **Three independent reviews**, in the usual ASIA CCS form (summary, strengths, weaknesses, questions
   for the authors, overall score on a 1 to 5 scale with 3 = weak accept, reviewer confidence):
   - R1, an ICS security researcher who knows SWaT/WADI/HAI detectors and attacks on them;
   - R2, a statistician who works on streaming anomaly detection, extreme-value theory and conformal
     prediction;
   - R3, a systems-security generalist who checks threat models, baselines and whether the claims follow
     from the evidence.
   Each reviewer reads the paper, not this prompt's summary of it. Be as critical as a real committee:
   name the weaknesses that would sink the paper.
2. **Check the evidence behind each weakness** against `results/` and `protocols/` before you write it.
   A weakness that the paper already answers (with a page or section) should be marked as such, not
   dropped silently.
3. **Meta-review.** Consolidate the three into a decision (reject / major revision / accept) and a list
   of the changes that would move the decision, ranked by how much each would help.
4. **What can be done without new data.** The raw datasets allowed one access each and that access is
   used; SWaT and WADI are not yet available. Split the requested changes into (a) writing, framing and
   analysis that needs no new data, (b) experiments on the already-spent development data (HAI 21.03,
   22.04, 23.05 normal and attack files), and (c) changes that need new data. For each item in (a) and
   (b), say concretely what to add and where.
