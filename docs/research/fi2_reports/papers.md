# fi2 workstream D: the papers' next versions

Date 2026-11-12. Branch `docs/fi2-papers`, from main at 685df31. Nothing was uploaded to Zenodo, HotCRP,
arXiv or anywhere else; publication is the owner's step. No number was recomputed and no training or
evaluation was rerun. Every added number is copied from an fi1 report, an fi1 JSON record, or a result
file v1.3 already binds.

## Second pass (coordinator's items A to D)

### A. "When Agents Control the Kernel" v1.2 to v1.3

How v1.2 was built: `scripts/build_world_model_technical_report_v1_2.py` (ReportLab, invariant mode) at
commit 8db5211 (sha256 ef7c45ca..., the digest in `world_model_technical_report_freeze_v1_2.json`), output
`output/pdf/FerrumOS_WorldModel_Technical_Report_v1.2.pdf` (untracked); verifier
`scripts/verify_world_model_technical_report_v1_2.py` against that freeze. The builder in the repository
has been edited 16 times since (for PINP), so today's file no longer matches the freeze and the v1.2
verifier also cannot find its untracked PDF; both are pre-existing. Extracted from 8db5211, the frozen
builder rebuilds the v1.2 PDF byte for byte (sha256 6f335f48..., equal to the freeze).

New files: `docs/research/paper/when_agents_control_kernel_technical_report_v1_3.md`,
`docs/research/paper/FerrumOS_WorldModel_Technical_Report_v1.3.pdf` (19 pages; v1.2 had 18),
`scripts/build_world_model_technical_report_v1_3.py` (the 8db5211 builder with version strings and default
paths changed, then ruff-formatted; the PDF is byte-identical before and after formatting),
`scripts/verify_world_model_technical_report_v1_3.py` (57 of 57: the v1.2 checks plus v1.2 source
unchanged, every v1.2 word kept apart from the date line, the added statements present in source and PDF,
and the added numbers equal to `fi1_pipeline_round3.json`), `docs/research/world_model_technical_report_freeze_v1_3.json`
(prepublication; version DOI a marked placeholder). The source stays ASCII and has no generative-AI
statement, as in v1.2.

What v1.2 quotes, and what it does not:

- It quotes the H=3 rollout error of the selected JEPA, 3.87% (Section 6.2 table), which is the committed
  seed-17 transition model's 0.0387; the 0.039 to 0.041 range covers seeds 17, 42 and 91.
- It quotes the per-action-mean comparison and declines to claim it. Its own words (Section 8.2): "The
  per-action mean differs from selected JEPA on only three correctness outcomes: JEPA is uniquely correct
  twice and the mean model once, exact McNemar p=1.0. The 0.2-point balanced-accuracy difference does not
  establish a material JEPA safety advantage." Section 14.2: "Neither the original per-action mean
  comparison nor the new final rules-only ablation establishes JEPA superiority for thresholded safety
  decisions." Limitation 8 and the conclusion say the same.
- It does **not** quote the 216 safe-replay false alarms. It lists the 1,969-row safe replay as an arm of
  the protocol (Section 7) and gives no count. The 216 (109.7 alerts per 1,000) is in
  `docs/research/WORLD_MODEL_PAPER_EVALUATION.md` and `docs/research/WORLD_MODEL_RESEARCH.md`, not in
  either published report. I added it in Section 8.2 next to the other thread-count numbers because the
  replay is an arm of the protocol the report describes.

| Where in v1.3 | Added statement | Source and field |
|---|---|---|
| Section 6.2 | encoder and seed-17 transition reproduce byte for byte at 24 threads; every retrained model differs at 4 and 1; H=3 rollout 0.039 to 0.041 committed (3.87% = seed 17) against 0.064 to 0.085 | J3 `os_world_model/runs/t24_run1/digests_match`; R3 section 1.5 table (rollout per seed: 0.0387 / 0.0411 / 0.0399; 0.0847 / 0.0840 / 0.0808; 0.0675 / 0.0640 / 0.0663) |
| Section 8.2 | rules + JEPA 185 / 65 / 31 / 219 (4 threads), 199 / 51 / 41 / 209 (1 thread), balanced accuracy 80.8% and 81.6% | J3 `runs/{t4_run1,t1_run1}/gates` "verifier: rules_plus_jepa confusion" and the claim gates' `value` |
| Section 8.2 | rules + calibrated JEPA 204 / 46 / 40 / 210 at 4 threads, unchanged at 1 | J3 "verifier: rules_plus_validation_calibrated_jepa confusion" |
| Section 8.2 | rules + per-action mean and rules only unchanged | R3 section 1.5 table ("identical") |
| Section 8.2 | 81.4% against 81.2% becomes 80.8% against 81.2% at 4 threads, holds at 1 | J3 claim gate "rules_plus_jepa balanced accuracy at least rules_plus_mean_delta" (`value`, `threshold`, `passed`) |
| Section 8.2 | above rules only and above rules + autoencoder at every count; rules-versus-combined accuracy difference 0.062 [0.030, 0.094], 0.056 [0.030, 0.084], 0.064 [0.032, 0.096] | J3 claim gates (all `passed`); intervals from R3 section 1.5 table (not stored in J3) |
| Section 8.2 | safe-replay false alarms 216 against 50 and 58 | J3 "verifier: untouched QEMU safe replay rules_plus_jepa fp is 216" |
| Limitation 13; "Changes in version 1.3" | summary of the above | as above |

Other fi1 findings on this report's tables (not added, listed for you): R3 row W1 and the "world-model v3
selection" margins (every safety check of the v3 selection passed for all 30 candidates; selection decided
by rollout error; selected incident ratio 0.0027237 against 0.0030814) concern the OS world-model v3.x
selection, which is likely the v3 to v3.4 lineage of Sections 11 and 12. R3 marks them as the second
reader's and not checked by the round's agent, so they stay out. The five complete pipelines of Section 9.1
were not rerun at other thread counts. R2 does not cover this report.

### B. PINP v1.4 corrections

1. Section 4.2: `scripts/cross_domain_world_model_models.py` line 435 computes the per-row error
   (`np.mean(np.abs(predicted - actual) / spec.scale, axis=1)`); `episode_bootstrap` averages it within each
   episode (line 442) and reports the mean of the episode means (line 447); `evaluate_cross_domain_world_models.py`
   line 619 uses that estimate for the ensemble rows of Table 4. Both wordings are partly right: the error
   is per row, the average is per episode. One sentence after the v1.3 statement says so, names the file
   and lines and points to Section 5.2; it is Changes item 12, "correction of a description".
2. "belong to one training run, not to the method" is now "describe one training run" in Section 11 and in
   Changes item 2; limitation 28 did not use the construction. The verifier now fails if either old phrase
   returns.
3. The manifest binding: the coordinator's figure is incomplete. Since the v1.3 lock (5029572),
   `real_telemetry_data_manifest_v1.json` changed in three commits, not one: d74a4fd (22 October, +61
   lines), f657b6d (22 October, +13) and ef693f0 (23 October, +25), 99 added lines in total and 0 removed or
   changed (`git show` of each; `git diff 5029572 HEAD` shows 99 insertions and 0 deletions). The v1.3
   freeze digest dd20597c... is the CRLF form of the file at 5029572. The sentence in Section 11 names the
   three commits and the 99 lines; it is Changes item 13.
4. Rebuilt: 52 pages (unchanged). Verifier refreshed (status prepublication) and passes read-only.

### C. Thresholds That Travel

1. `scripts/tt1_build_artifact.py` now copies `fi1_monitor_round1.json`, `fi1_monitor_round2.json` and
   `fi1_reports/monitor_round1.md`, `monitor_round2.md` (round 2 holds the 5%-of-span definition). The
   anonymizer already rewrites JSON string values: it works on the file text, and its `(?i)ferrum[- ]?os`
   pattern turned `ferrumos_improvement_fi1_plan.md` in the `plan` field into `[project]_improvement_fi1_plan.md`
   (ANONYMIZATION.md lists it), so no extension or test was needed. Built locally into the scratchpad
   (140 files); the builder's own scan passed, and my independent search found nothing:

   ```
   grep -r -i -a -n -E 'ferrum|vyom|kulshrestha|hardik|marcu|VyomKulsh|github\.com/vyom|0009-0009-1434-7148|orcid\.org|@gmail|vyomkulshrestha2004|C:[\\/]+Users|/c/Users|cursor-os|heliox|dovel|zenodo\.(2346936|2347318|2209232|2209235|2182919|2211639|2403541|2412321)' --exclude-dir=.git .
   (no output; exit status 1)
   ```

   Nothing was pushed to the artifact's private repository or force-updated on anonymous.4open.science.
   `ruff check` passes on the builder; it was never ruff-formatted and I did not reformat it.
2. USENIX copy: `sync_body` is not in the repository. Before my paragraph the USENIX body and appendices
   were identical to the ACM source from `\section{Introduction}` to the end, apart from the bibliography
   style line; I copied those two regions. Built with tectonic: 25 pages before and after, body ends on
   page 14 (references start there) before and after, 0 overfull, 0 undefined. The pack records no USENIX
   page limit and I did not check the 2027 call; if the limit is USENIX Security's usual 13 pages of body,
   the copy was already one page over before this change.
3. `publish/zenodo_metadata_v1_2.json` (DRAFT) and `publish/zenodo_metadata_v1_2_DRAFT_NOTE.md`. The
   description keeps v1.1's three abstract paragraphs (the abstract did not change) and replaces the version
   paragraph with one covering the tt1g round, the appendix headings and the fitted-range paragraph. No
   generative-AI statement, as in v1.1.

### D. PINP Zenodo record

`docs/research/prediction_is_not_permission_zenodo_v1_4_DRAFT.json`, in the form of
`prediction_is_not_permission_zenodo_v1_3.json`. The DOI, record URL, reservation date and tag are marked
PLACEHOLDER. The dataset record is reused unchanged.

### Verifiers after the second pass

PINP v1.4 verifier: pass (read-only, after refresh). Kernel v1.3 verifier: 57 of 57. tt1 27 of 27, tt1b 8 of
8, repository discovery, public JSON schemas, public evidence contract: pass. The first-pass items 3, 5, 6
and 7 below are now addressed by B1, C1, C3 and C2.

## Ready (first pass)

| Document | New files | Pages | Builds clean |
|---|---|---|---|
| Prediction Is Not Permission v1.4 | `docs/research/paper/prediction_is_not_permission_technical_report_v1_4.md`, `docs/research/paper/Prediction_Is_Not_Permission_Technical_Report_v1.4.pdf`, `scripts/build_prediction_is_not_permission_v1_4.py`, `scripts/verify_cross_domain_world_model_paper_v1_4.py`, `docs/research/cross_domain_world_model_paper_freeze_v1_4.json`, `docs/research/cross_domain_world_model_paper_verification_v1_4.json` | 52 (v1.3: 48) | yes; v1.4 verifier passes read-only |
| Thresholds That Travel, preprint v1.2 | `docs/research/paper/tt1_paper_pack/publish/Thresholds_That_Travel_preprint_v1.2.pdf` (byte copy of the regenerated `latex_named/main.pdf`; sha256 04fdcb8c...50b7, 384,784 bytes) | 21 | 0 overfull boxes, 0 undefined references |
| Thresholds That Travel, ASIA CCS copy | `docs/research/paper/tt1_paper_pack/latex/main.tex` and `main.pdf` (edited in place, the pack's single edit point) | 21; body ends on page 12, references from page 12, as before | 0 overfull boxes, 0 undefined references |

## How each PDF is built

- **PINP.** `scripts/build_prediction_is_not_permission_v1_3.py` calls the frozen ReportLab builder
  `scripts/build_prediction_report_layout_v1_2.py` (invariant mode, embedded Vera and DejaVu fonts). I
  rebuilt v1.3 into the scratchpad with it: the result is byte-identical to the committed v1.3 PDF (sha256
  215AAE5D...). v1.4 uses a copy of that script with the paths and the version strings changed. The v1.3
  verifier binds manuscript, PDF and evidence in a freeze manifest and refuses to rewrite a published
  freeze; the v1.4 verifier is a copy with the same checks plus eleven new ones (below), and its
  freeze status is "prepublication v1.4 candidate", with no version DOI and no tag, so `--refresh` stays
  open until the owner locks it.
- **Thresholds That Travel.** `latex/main.tex` (acmart sigconf, review, anonymous) is the only file to edit;
  `scripts/tt1_named_version.py` generates `latex_named/` (named preprint, no generative-AI section);
  both are compiled with tectonic 0.17.0. The published v1.1 PDF is a copy of `latex_named/main.pdf`
  stored in `publish/`. I followed that path and stored v1.2 the same way, and updated
  `publish/working_copy.json` to the new hash.

## Additions to PINP v1.4, sentence to source

R2 = `docs/research/fi1_reports/pipeline_round2.md`, R3 = `fi1_reports/pipeline_round3.md`, R1 =
`fi1_reports/pipeline_round1.md`, J3 = `docs/research/fi1_pipeline_round3.json`.

| # | Where in v1.4 | Added statement (numbers) | Source and field |
|---|---|---|---|
| 1 | Section 11, new paragraph; limitation 28; Changes item 1 | 24 threads reproduce byte for byte; at 4 and 1 thread candidate 0 instead of 3; promotion fails: OOD false negatives 1 against 0 (4 threads), OOD one-step error 0.003870 against 0.003777 (1 thread); machine 24 CPUs, OpenBLAS 0.3.29, NumPy 2.2.6 | J3 `physical_jepa_v3_sweep/runs/{committed,t24_run1,t4_run1,t1_run1}/selection/selected_index`, `promotion_passed`, gates "promotion: OOD false negatives not increased" and "promotion: OOD one-step error <= 0.95 x current" (`value`, `threshold`); `t24_run1/checkpoint_identical_to_deployed`; J3 `machine`; R3 section 1.1 |
| 1 | same paragraph | Physical JEPA v5 is anchored on the v3-selected checkpoint | `physical_jepa_v5_selection.json` `baseline_artifact_sha256` = `physical_jepa_v3_selection.json` `candidate_artifact_sha256` (f267dc09...) |
| 1 | same | float32 OpenBLAS products add in a different order; early stopping and gates pick another model; fixed count repeats bit for bit | R3 section 2 |
| 2 | Section 11 | OS study: encoder and selected transition reproduce at 24 threads; every model differs at 4 and 1; replay false alarms 216 of 1,969 against 50 and 58; H=3 rollout error 0.039 to 0.041 against 0.064 to 0.085; 0.814 against 0.812 flips to 0.808 against 0.812 at 4 threads | J3 `os_world_model/runs/*/gates` "verifier: untouched QEMU safe replay rules_plus_jepa fp is 216" and "claim: rules_plus_jepa balanced accuracy at least rules_plus_mean_delta" (`value`, `threshold`, `passed`), `digests_match`; rollout errors from R3 section 1.5 table (not stored in J3) |
| 2 | same | the FerrumOS encoder protected in Appendix B.2 comes from that study | protected digest 9fb5f08b... in `cross_domain_world_model_improvement_verification_v1.json` equals the JEPA encoder digest named in R3 section 1.5 |
| 2 | same | archived cross-domain inference at 1 and 4 Torch threads: at most 1e-6 relative, no table entry changes; incident v3/v4 physical inference: no gate, count or interval changes | R3 summary table and sections 1.3, 1.4 |
| 3 | Section 8.5, after Table 13 | target 14 of 3,471; 13 and 15 tied, float ranks 13 closer by about 4e-17; stored 0.751 (FP 13, FN 4); registered tie-break 0.726 (FP 15, FN 3); common recall 92.40% at 3.03% FPR instead of 90.49% at 2.41%; Table 12 row would need a closed-loop run | R2 row P1 |
| 4 | Section 6.3, after Table 7 text | p = 0.99 needs raw score 11.07 (FerrumOS) or 1.63 (Physical); largest observed 0.19 and 0.35 | R2 row X2 |
| 5 | Section 8.10, after Table 29 | lowest-within-budget calibration; 14 of 15 thresholds equal under first-break; rt1 DR 23 of 58 at 0.74 instead of 24 of 58 at 0.99; D1 versus DR +36.2 instead of +34.5; no rt1 gate depends on DR | R2 row R2 |
| 5 | after Table 30 | first-break gives D1 25/58 and D3 36/58 at 0.5, D0 20/58 at 1.0; other cells unchanged; comparison at one per day unchanged | R2 row R1 |
| 6 | Table 19, six control rows, and a paragraph | OS persistence 1009/109/8681/441, 69.59%, 1.24%, 0.039113; OS retrained JEPA 1202/114/8676/248, 82.90%, 1.30%, 0.027917; OS retrained MLP 1209/121/8669/241, 83.38%, 1.38%, 0.027436; Physical persistence 2423/61/6491/1265, 65.70%, 0.93%, 0.079220; Physical retrained JEPA 3119/87/6465/569, 84.57%, 1.33%, 0.040207; Physical retrained MLP 3132/98/6454/556, 84.92%, 1.50%, 0.043997 | `incident_dynamics_result_v2.json` `domains/{ferrumos,physical}/methods/{persistence,retrained-jepa,retrained-mlp}/warning/{tp,fp,tn,fn,recall,fpr,brier}` (rounded to the table's precision); text numbers match R2 row I1 |
| 7 | Section 8.10, after Table 32 | 0/0 scored as no reduction; DR 46 of 50, D1 50 of 50; 1.67% of resamples against the 0.625% tail; interval [0.0, 1.0], [1.0, 1.0] without them; gate fails because of the convention; recall interval reaches zero; rt1, HAI 23.05 and D1 versus D0 unaffected | R1 row F0; fi1 report section 2 round 1 |
| 8 | Section 5.2, after Table 5 | 1,447 of 1,447 pairs differ, mainly `screen_hash`; perfect one-step model 0.0084 (H=3), 0.0112 (H=5); levels up about 37% and 14% for the GRU; rankings and signs unchanged; Physical 0 of 17,920 | R2 row X1 |
| 9 | Section 5.2 | episode-macro averaging; 80 single-endpoint `hybrid` episodes carry 25% of the weight at H=3; row-micro GRU 0.007598, JEPA 0.007623; lead 0.00444 to 0.000025 | R2 row X4 |
| 9 | Section 6.2 | ten equal-mass bins; equal-width gives 0.0060 and 0.101 instead of 0.238 and 0.293 | R2 row X3 |
| 10 | Section 8.5 | 6 discordant of 128; 64 sign assignments, interval excludes zero in 3.1% against nominal 1.67%; exact sign-flip p = 0.031, 0.094 adjusted; intervention randomization p 0.059 adjusted | R2 row P2 |
| 10 | Section 8.6, after Table 15 text | mean episode steps +0.84, pointwise [0.09, 1.69], missing from Table 14; precision randomization p = 0.034 after x7 while the Bonferroni interval includes zero | R2 rows P3, P4 |
| 11 | Section 8.2, after Table 9 text | post-hoc threshold at the 99th percentile of clean non-attack errors, fixed across conditions; row FPR 1.00%, 1.29%, 1.20%, 1.33%, 1.01%, 1.95%; 17.5 to 32.8 false alerts per hour | R3 row H1 (checked by that round); I re-read `physical_jepa_recorded_hil_replay_result_v1.json` `replay/conditions[*]/post_hoc_detection/{false_positive_rate,false_alerts_per_hour,threshold_source}`: equal |
| 11 | Section 8.3, after Table 10 text | clearance at most 0.271 m, median 0.061 m; rule blocks the 265 cases below 0.2 m; learned branch blocks all 288; no shielded trajectory simulated | R3 row M1 (checked by that round); I re-read `physical_jepa_multi_embodiment_3d_result_v1.json` `cases[*]` counts: 288 learned blocks, 265 rule blocks, 265 below 0.2, max 0.271, median 0.061 |
| | Section 12.3, one added paragraph; "Changes in version 1.4" section before Appendix A | lists the eleven items; states that no number, registered result or evidence binding of v1.3 changes | this report |

Version strings changed (the only edits to v1.3 text): the date line ("Technical Report v1.4 - 12
November 2026"), the two script names in Section 11 (`..._v1_4.py`), and "execute the v1.4 paper
verifier" in Appendix C.1. The builder's running header and PDF subject say v1.4. The author line,
affiliation ("Independent Researcher, India"), ORCID, e-mail and the generative-AI statement are as in
v1.3 (v1.3 has one, so v1.4 keeps it and adds none).

Not added: R3 rows H2 (memoryless recovery, the reader's finding, unchecked; v1.3 already says the
recovery is not a physical recovery claim), T1, W1 and S1 (they concern studies or records outside
PINP's tables), and the reader's chance estimate for Table 9 (about 65%, unchecked).

## Addition to Thresholds That Travel

One paragraph in Section 5.2 after "Time in alarm and onset recall (post-hoc)", in the conference
source and therefore in the generated named copy. No table.

| Number | Source and field |
|---|---|
| HAI 20.07: 41% of unlabelled time outside the fitted range | `fi1_monitor_round2.json` `check/baseline_round2_rescore/hai-20.07/unlabelled_share_outside_range` = 0.4102; `monitor_round2.md` rule-5 table |
| 94% of its alarm time outside | `fi1_monitor_round1.json` `diagnosis/hai-20.07/regime/alarm` = 0.9446; `monitor_round1.md` post-check description |
| 3.7% in alarm inside the range | `fi1_monitor_round2.json` `.../hai-20.07/alarm_share_inside_range` = 0.0367 |
| 39.1% overall | `fi1_monitor_round1.json` `diagnosis/hai-20.07/baseline/unlabelled_alarm_share` = 0.39096 |
| ProvICS 56% outside, 9.1% inside, 44.0% overall | `fi1_monitor_round2.json` `.../provics/unlabelled_share_outside_range` = 0.5586, `alarm_share_inside_range` = 0.0909; `fi1_monitor_round1.json` `diagnosis/provics/baseline/unlabelled_alarm_share` = 0.43989 |
| definition (a scaled sensor more than 5% of its fit span beyond the fit range); the refit reproduced the registered counts | `monitor_round2.md` Method and rule 5; `ferrumos_improvement_fi1_report.md` section 6 |

The figures agree across the two reports and the JSON (consistency: 0.4102 outside and 0.0367 inside
at 0.391 overall imply about 94% of alarm time outside). The paragraph is marked "exploratory, post hoc"
in its heading and says it ran after every result was known, on spent data. The two-channel monitor is
not mentioned.

Page limit: the first version of the paragraph (nine source lines) pushed three lines of the conclusion
onto page 13. I shortened the paragraph, not other content, to six source lines; the body again ends on
page 12 and the references start there, 21 pages in total, as before. Two body tables (7 and 8) moved
from page 7 to page 8; no float lands after the references.

## Disagreements and points that need the owner's eye

1. **Items 1 and 2 are not quoted in PINP v1.3.** The fi1 report (section 2, round 3, and section 7)
   says the report quotes the replay false alarms and the rollout error. It does not: 216, 1,969-row
   replay and 3.87% rollout error are in [15], "When Agents Control the Kernel" v1.2. PINP binds the
   affected artifacts only through Physical JEPA v5 (anchored on the v3-selected checkpoint) and the
   protected FerrumOS encoder (Appendix B.2). I placed both statements in Section 11 as lineage
   statements and did not attribute the "does not establish that JEPA outperforms the per-action mean"
   wording to any report. The owner may prefer to put item 2 in a new version of [15] instead.
2. **The DOI, the tag and "this version is published" are still v1.3's.** The front matter, Section
   12.3, Appendix B.4 and the Declarations name version DOI 10.5281/zenodo.23473173 and tag
   `prediction-is-not-permission-v1.3`, and Section 11 says "This version is published, so the refresh
   path is closed for it". I left them unchanged because they are not plain version strings and the
   v1.4 DOI does not exist yet. Before upload: reserve a v1.4 DOI on Zenodo (New version of the
   concept record 23469362), replace the DOI and tag in those places, rebuild with
   `python scripts/build_prediction_is_not_permission_v1_4.py`, add the substitutions to
   `VERSION_SUBSTITUTIONS` in the v1.4 verifier, run it with `--refresh`, then lock the freeze as v1.3 was
   locked (status and tag).
3. **Section 4.2 versus the new Section 5.2 sentence.** Section 4.2 still says "per-row mean"; the
   added sentence says the implementation averages per episode. I did not edit the existing sentence.
4. **Table 13 tie.** The added sentence says the full adapter's common recall would no longer exceed the
   local source's (92.40% each). That is the arithmetic of R2's numbers; R2 calls it "weakens". Section
   8.5's sentence about full against JEPA-only is unaffected.
5. **Thresholds That Travel, conference copy.** The paragraph cites `docs/research/fi1_monitor_round1.json`
   and `round2.json`. The anonymized artifact (`scripts/tt1_build_artifact.py`, `DOC_PATTERNS`) does not
   copy those files, and `fi1_monitor_round2.json` contains the string `ferrumos` in its `plan` field. Before
   submission: add the two files to the artifact's patterns, rebuild, check that the anonymizer replaces
   the project name, and Force update on anonymous.4open.science. I did not change the artifact builder.
6. **Preprint v1.2 contains more than this paragraph.** `latex_named/main.pdf` was already a working copy
   newer than the published v1.1 (commits 3d4ec15, tt1g round, and 7217f5f, appendix headings). v1.2 =
   that working copy plus my paragraph. No `zenodo_metadata_v1_2.json` was prepared: its description must
   cover the tt1g changes, which are not mine to summarise.
7. **USENIX copy not synced** (`latex_usenix/`); the pack says to run `sync_body` for it. Out of scope.
8. **Page count of PINP grew from 48 to 52.** The v1.3 verifier allowed 20 to 50 pages; the v1.4 verifier
   allows up to 56, with a comment.

## Verifier results

| Check | Result |
|---|---|
| v1.3 PDF rebuilt from v1.3 source | byte-identical (sha256 215AAE5D...) |
| `verify_cross_domain_world_model_paper_v1_3.py` | all paper checks pass; the freeze comparison fails on main before and after this branch because `real_telemetry_data_manifest_v1.json` changed in ef693f0 (tt1b) after the v1.3 lock. Pre-existing; v1.3 files are not mine to change |
| `verify_cross_domain_world_model_paper_v1_4.py` (read-only) | overall pass. New checks: v1.3 manuscript and PDF digests equal the v1.3 freeze; every v1.3 word survives in order apart from the version substitutions; 23 added phrases present; cited audit files exist; thread statements equal J3; v5 baseline equals the v3 candidate; Table 9 alarm rates, Table 10 case counts and the Table 19 control rows equal their result files. Negative controls: changing one v1.3 number or one control-row value makes the matching check fail |
| `verify_tt1.py` | 27 of 27 |
| `verify_tt1b.py` | 8 of 8 (SWaT, WADI pending as before) |
| `verify_tt1d.py provics` | 22 of 22 |
| `verify_tt1d.py tep59` | not run: needs the 3.9 GB raw `attacks.zip` in this worktree's `target/`; it imports nothing this branch changed |
| `verify_repository_discovery.py`, `verify_public_json_schemas.py`, `verify_public_evidence_contract.py` | pass |
| `python -m unittest discover -s scripts -p "test_prediction_report*.py"` | 12 of 12 |
| `ruff check`, `ruff format --check` on the two new Python files | pass |

The tt1 verifiers need `target/real-telemetry/final_access.jsonl`; I copied that one file from the main
checkout into this worktree's ignored `target/`. They rewrote their verification JSONs with fi1's ledger
rows and CRLF line endings; I restored the committed files.

## Commits on `docs/fi2-papers`

- 7dd0c17: Thresholds That Travel (conference source and PDF, named copy, preprint v1.2 PDF, working copy record)
- a955140: Prediction Is Not Permission v1.4 (source, PDF, builder, verifier, freeze, verification)
- this report
