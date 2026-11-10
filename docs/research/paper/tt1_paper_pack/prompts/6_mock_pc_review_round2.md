# Prompt 6: mock program-committee review of the revision of 2026-11-10

Paste the text below into Claude Science with this pack's folder open as the project. Model Opus 5.5,
background reviewer Sonnet 5.5. It reviews the revised paper from scratch; the first round's review
(`review/mock_pc_review.md`) and the response to it (`review/mock_pc_response.md`) are there for
comparison only.

---

You are the program committee of ACM ASIA CCS 2027 (second review cycle) reviewing an anonymous
submission: `latex/main.pdf`, source `latex/main.tex`. The body limit is 12 pages; references and
appendices come after it and reviewers need not read the appendices. The results the paper reports
are in `results/` and `figure_data/`; the registrations and the amendment are in `protocols/`. The file
`manuscript/thresholds_that_travel_draft_v0_1.md` is an older draft and is not the paper. Do not edit
the paper or any file outside `review/`. Write the reviews to `review/mock_pc_review_r2.md`.

Since the first mock review the paper gained a third registered study (tt1d: the Tennessee Eastman
attack dataset and ProvICS; `results/threshold_transfer_tt1d_result_*.json`,
`protocols/threshold_transfer_tt1d_protocol.json`, `protocols/threshold_transfer_tt1d_amendment_1.md`),
exploratory defence and attack experiments (tt1e: `results/threshold_transfer_tt1e_dev_v1.json`), a
ceiling rule with Proposition 4, and appendices A to E. Two of its registered primary rules failed
(tt1b on BATADAL, tt1d on both datasets) and the paper reports them.

1. **Three independent reviews** in the usual ASIA CCS form (summary, strengths, weaknesses, questions
   for the authors, overall score on a 1 to 5 scale with 3 = weak accept, reviewer confidence):
   - R1, an ICS security researcher who knows SWaT/WADI/HAI/Tennessee Eastman detectors and attacks
     on them;
   - R2, a statistician who works on streaming anomaly detection, extreme-value theory, conformal
     prediction and pre-registration;
   - R3, a systems-security generalist who checks threat models, baselines and whether each claim
     follows from the evidence.
   Each reviewer reads the paper, not this prompt's summary of it. Be as critical as a real committee
   and name the weaknesses that would sink the paper. In particular, judge:
   - whether the abstract and introduction claim more than the registered outcomes support, given the
     failed primary rules and the onset-count results;
   - whether a reader can tell, for every number in the body, if it is registered, secondary,
     post-hoc or exploratory;
   - whether the campaign attacks (score-level injection) are a credible threat model and whether the
     paper says clearly what an attacker needs;
   - whether the paper now tries to do too much in 12 pages, and what should be cut or moved;
   - whether the defence guidance (tighten freely, loosen only inside a fixed band or with approval)
     follows from the evidence, including the cost in false alarms.
2. **Check the evidence behind each weakness** against `results/` and `protocols/` before you write
   it. If a number in the paper disagrees with the result files, quote both and give the JSON path. A
   weakness the paper already answers (give the section) is marked as answered, not dropped.
3. **Compare with round 1.** For each change the first meta-review asked for, say whether the revision
   did it, did it partly, or did not.
4. **Meta-review.** Consolidate the three into a decision (reject / major revision / minor revision /
   accept) and list the changes that would move the decision, ranked by how much each would help.
5. **What can be done without new data.** Every dataset in the paper is spent (one registered access
   each); 53 attack-free Tennessee Eastman runs are still unread and are reserved for a later study.
   Split the requested changes into (a) writing, framing and analysis that needs no new run, (b) runs
   on already-spent data, labelled exploratory, and (c) changes that need new data. For each item in
   (a) and (b) say concretely what to add and where, and what to cut to keep the body at 12 pages.
