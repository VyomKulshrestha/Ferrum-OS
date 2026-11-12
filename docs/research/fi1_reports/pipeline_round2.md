# fi1 workstream B, round 2: the code behind the PINP report

Date 2026-11-12. Branch `improve/fi1-pipeline2`, based on main at 4d626cc. Round 1 audited the threshold studies
(tt1 to tt1g, tw1). This round audits the code behind the other numbers in *Prediction Is Not Permission*
(PINP, Zenodo v1.2 and v1.3): the cross-domain architecture study, the incident-dynamics studies v2 to v4, the
real-telemetry studies rt1 and rt2, and the Safety-Gymnasium attribution and output-ablation studies. No
registered result was recomputed or replaced. No frozen file was edited.

Two second readers worked read-only on parts of the scope: one on the cross-domain study (Tables 3 to 7, D1),
and one on Safety-Gymnasium (Tables 11 to 15). I checked the arithmetic of their two strongest findings myself
(X2 and P1, below). Their reproduction scripts are in the session scratchpad (`xd/`, `sg/`). Their other
findings are reported as theirs.

Tests: from `scripts/`, `python -m pytest -q test_fi1_pipeline2.py` (15 tests, about 2 minutes; most of that is
importing lightgbm and sklearn). Exploratory data runs: `python fi1_rt_calibration_check.py [rt1-hai]
[hai-21.03] [hai-23.05] [rt1-posthoc]`. Output: `target/real-telemetry/fi1/pipeline2/rt_calibration_check.json`.

## Map: published tables to code

| PINP v1.3 | Producer | Stored result | Verifier |
|---|---|---|---|
| Tables 3, 4, D1 (matched architectures) | `cross_domain_world_model_models.py`, `evaluate_cross_domain_world_models.py` | `cross_domain_world_model_selection_v1.json`, `..._architecture_result_v1.json` | `verify_cross_domain_world_models.py` |
| Table 5 (common episodes) | `evaluate_cross_domain_world_model_posthoc_sensitivity_v1.py` | `..._posthoc_sensitivity_result_v1.json` | `verify_..._posthoc_sensitivity_v1.py` |
| Tables 6, 7, Section 6.2 | `evaluate_cross_domain_learned_contribution.py` | `cross_domain_learned_contribution_{selection,result}_v1.json` | `verify_cross_domain_learned_contribution.py` |
| Tables 11 to 15 | `run_physical_jepa_safety_gymnasium.py`, `prepare_/evaluate_..._attribution_v1.py`, `run_..._output_ablation_v1.py`, `recover_..._v2.py` | `physical_jepa_safety_gymnasium_*` | `verify_physical_jepa_safety_gymnasium_*` |
| Tables 17 to 19 (incident dynamics v2) | `run_incident_dynamics_study.py --version 2`, `incident_dynamics_{data,metrics}.py`, `evaluate_incident_dynamics_development.py` | `incident_dynamics_result_v2.json` | the runner's `verify` stage |
| Tables 21 to 24 (v3) | `run_incident_dynamics_v3_study.py`, `incident_dynamics_v3_{data,dev,warning,eval,gbr,models}.py` | `incident_dynamics_result_v3.json` | the runner's `verify` stage (48 checks) |
| Tables 25 to 27 (v4) | `run_incident_dynamics_v4_study.py` (thin wrapper around v3) | `incident_dynamics_result_v4.json` | the same, 46 checks |
| Tables 28, 29 (rt1) | `real_telemetry_final.py`, `real_telemetry_detect.py` (develop, calibrate) | `real_telemetry_result_v1.json` | `verify_real_telemetry.py` |
| Table 30 (rt1 post-hoc) | `real_telemetry_posthoc_rt1.py` | `real_telemetry_posthoc_rt1.json` | none |
| Tables 31, 32 (rt2) | `real_telemetry_rt2.py` | `real_telemetry_result_rt2.json` | `verify_real_telemetry.py` |

Every number in Tables 17 to 32 that I compared matches its stored JSON at the printed precision. The second
readers report the same for Tables 3 to 7, D1 and 11 to 15. `real_telemetry_detection_v2.py`,
`real_telemetry_wm_v2*.py` and `real_telemetry_calibration_transfer.py` produce no number in PINP. The first two
feed the tt1 paper and are frozen by its protocol.

## Findings, ordered by effect on published numbers

| # | file:line | What is wrong | Reproduction | Published number it touches, and by how much | Fix or sentence | Test |
|---|---|---|---|---|---|---|
| R1 | `real_telemetry_posthoc_rt1.py:47-55` (as committed in 20f2ea6), not frozen | The matched-rate search visits every candidate threshold and keeps the lowest one within the false-episode budget. Episode counts are not monotone in the threshold, so the search can pass the first budget break. The 2026-11-10 audit fixed the same pattern in `calibrate` (`real_telemetry_detect_v2`), but this file codes its own loop, so that fix did not reach it. | Synthetic: `PosthocMatchedRateTests`. HAI 22.04, exploratory rescoring (ledger row "EXPLORATORY fi1 pipeline2 ..."): the stored rule reproduces every cell of the stored file. Stopping at the first break changes these cells: at 0.5 false episodes per day, D1 drops from 43/58 to 25/58 (threshold 16.1 vs 29.1) and D3 from 42 to 36; at 1.0, D0 drops from 22 to 20. The 1.0 and 2.0 rows are otherwise unchanged, and so is every D2 cell. | **Table 30**, 0.5 row: D1 43 vs 25, D3 42 vs 36. 1.0 row: D0 22 vs 20. The text's comparison at one per day (D2 47, D1 44, D3 43) is unchanged. Both rules meet the budget. They differ because the recall-versus-budget curve is not monotone, so "matched rate" does not name one threshold. | The search is now `matched_threshold(..., rule)`. The default `"lowest"` reproduces the stored file byte for byte, and `"first_break"` is the conservative rule. Suggested sentence under Table 30: "Each threshold is the lowest candidate within the budget. False-episode counts are not monotone in the threshold; stopping at the first budget break instead gives D1 25/58 and D3 36/58 at 0.5 per day, and D0 20/58 at 1.0." | `PosthocMatchedRateTests` (3) |
| R2 | `real_telemetry_detect.py:113-124` (`calibrate`), frozen; rt1 DR threshold | The 2026-11-10 audit established the mechanism and checked only D1. I rebuilt the clean calibration scores of every rt1 HAI and rt2 detector from normal training data, with no test access. The frozen routine reproduces all 15 stored thresholds exactly. In 14 of them the first-break rule gives the same threshold. The exception is rt1 HAI DR: the frozen pick is 4.34 (0.28 % of calibration seconds in alarm), and the first-break pick is 5.48 (0.14 %). | `fi1_rt_calibration_check.py rt1-hai hai-21.03 hai-23.05`, then `rt1-posthoc` for the test effect. | **Table 28/29, rt1 HAI DR only.** Registered DR 24/58 at 0.99 false episodes/day. With the first-break threshold: 23/58 at 0.74. "D1 versus DR" would be +36.2 points instead of +34.5. No gate depends on DR in rt1. rt2 (Tables 31, 32) is unaffected: all 10 thresholds and the D2c alarm fraction agree under both rules. SMD was not checked (335 MB bundle). | None needed for the registered result. Optional footnote: "The rt1 DR threshold was set by the lowest-within-budget calibration rule; the first-break rule gives 23/58 at 0.74 false episodes per day." | Reproduction in the JSON; mechanism covered by round-1 `CalibrateTests` |
| P1 | `prepare_physical_jepa_safety_gymnasium_attribution_v1.py:56-62` (`choose_threshold`), not frozen by digest, registered by the attribution protocol | The registered rule is "match the full adapter's validation FPR, then fewer FN, then the higher threshold". The sort key is the float `abs(fpr - target)`. The target is 14/3471. A threshold with 13 FP and one with 15 FP are exactly tied, but the float key ranks 13/3471 closer by 4e-17, so the FN tie-break never runs. | Checked: `abs(13/3471 - 14/3471) < abs(15/3471 - 14/3471)` is True. Second reader, on validation seeds 4096-4127: for "local sensing without JEPA" the stored choice is 0.751 (FP 13, FN 4); the exact rule gives 0.726 (FP 15, FN 3). The other two sources are unaffected. | **Table 13, "local, no JEPA" row** (second reader, rescoring the stored common catalog): common recall would be 92.40 % instead of 90.49 %, equal to the full adapter's, at 3.03 % FPR instead of 2.41 %. This weakens the sentence that the full adapter has the higher dangerous-trajectory warning recall against the local source. Table 12's local row would move too, but that needs a closed-loop rerun. | `physical_jepa_threshold_choice_v2.choose_threshold_exact` (exact fractions). Thresholds are registered and seeds 8000-8127 are spent, so this calls for a sentence, not a rerun: "The local-only threshold 0.751 resolves an exact FPR tie by floating-point rounding; the registered FN tie-break selects 0.726 (92.40 % common recall at 3.03 % FPR)." | `AttributionThresholdTieTests` (2) |
| X1 | `cross_domain_world_model_models.py:358-429`, frozen (bound in the incident-dynamics selections) | Second reader. In the FerrumOS base test data, `after[k]` is never equal to `before[k+1]`: 1,447 of 1,447 consecutive pairs differ, mainly in `screen_hash`. The H>1 rollout target therefore contains between-step changes that no one-step model is trained to predict. Physical rows are continuous, 0 of 17,920. | A perfect one-step model scores 0.0084 (H=3) and 0.0112 (H=5) on the base episodes. The real ensembles on the 522 base-test episodes reproduce the stored per-source values exactly. | **Table 4/5/D1, FerrumOS H=3 and H=5**: the levels are inflated, by about 37 % at H=3 and 14 % at H=5 for the GRU. The ranking and the sign of every contrast are unchanged (GRU-JEPA at H=3: -0.00444 vs about -0.00437). | Sentence: "FerrumOS base observations change between transitions, so H>1 targets include changes no one-step model predicts; a perfect one-step model scores 0.0084 (H=3) and 0.0112 (H=5) on base episodes. Rankings are unchanged." | none (needs target/ data from the main checkout) |
| X2 | `evaluate_cross_domain_learned_contribution.py:438, 524-549` | Second reader; arithmetic checked by me. Under the frozen Platt fit, p >= 0.99 needs a raw score of at least 11.07 (FerrumOS) or 1.63 (Physical). The largest scores, development or final, are 0.19 and 0.35. All thresholds from 0.51 (0.64) up to 0.99 tie on development at FP 0 and FN 1.0. The stored selection shows TP = 0 at 0.99. | `StoredLearnedContributionTests`. | **Table 7** (learned-only TP = FP = 0, 0/256 marginal) is guaranteed by calibration and threshold before final access. It is not an empirical property of the final catalog. The text calls it "a thresholded latent-hazard coverage negative", which is correct but does not say the outcome was fixed in advance. | Sentence: "Under the development Platt fit, p >= 0.99 requires a score of at least 11.07 (FerrumOS) or 1.63 (Physical), against observed maxima of 0.19 and 0.35, so the learned branch could not intervene on any case." | `StoredLearnedContributionTests` |
| X3 | `evaluate_cross_domain_learned_contribution.py:552-570` | Second reader. ECE uses 10 equal-mass bins (output key `ece_equal_mass`). The paper says only "ECE". | With 10 equal-width bins: FerrumOS 0.0060 instead of 0.238, Physical 0.101 instead of 0.293. | **Section 6.2** ECE values, which depend on the binning. | "ECE with 10 equal-mass bins". |  |
| X4 | `cross_domain_world_model_models.py:438-481` | Second reader. The mean is episode-macro (each episode weighs 1); the paper describes a per-row mean. 80 single-endpoint `hybrid` episodes get 25 % of the weight at H=3. | Row-micro at H=3: GRU 0.007598, JEPA 0.007623; the gap shrinks from 0.00444 to 0.000025. | **Table 4, FerrumOS H=3**: the GRU lead depends on episode weighting. | "Errors are averaged within each episode, then across episodes." |  |
| I1 | presentation of `incident_dynamics_result_v2.json` in Table 19 | Not a code defect. Table 19's recall gains (+80.97 and +45.85 points) are measured against the old paper ensembles. The same result file stores warning results for every control. The same-data retrained JEPA reaches 84.57 % physical recall at 1.33 % FPR, against 85.44 % at 1.42 % for the selected ensemble. On OS, the retrained MLP reaches 83.38 % at 1.38 % and persistence 69.59 % at 1.24 %, against 94.14 % for the selected ridge. | `StoredIncidentDynamicsTests.test_v2_physical_warning_gain_is_mostly_same_data_retraining`. | **Table 19 / Section 8.7**: the physical warning gain is almost entirely what same-data retraining gives. Table 18 shows this for prediction but not for warnings. | Add the two control rows to Table 19, or: "A JEPA retrained on the same data reaches 84.6 % physical recall at 1.33 % FPR, within one point of the selected ensemble." | yes |
| P2 | `evaluate_cross_domain_world_model_posthoc_sensitivity_v1.py:515-526`; PINP Section 8.5 | Second reader. The JEPA-only minus full hazard contrast (-25 steps) rests on 6 discordant episodes out of 128. A percentile bootstrap is anti-conservative at that size. | With all 64 sign assignments of the observed differences, the 98.33 % interval excludes zero in 3.1 % of them (nominal 1.67 %). The exact sign-flip p is 0.031, or 0.094 after Bonferroni over 3 contrasts. The intervention contrast has randomization p 0.059 after adjustment. | **Section 8.5** ("Both exclude zero"): under exact paired tests neither survives the three-contrast adjustment. | Report exact sign-flip and randomization p next to the intervals. |  |
| P3, P4 | output ablation (Tables 14, 15) | Second reader. Precision's survivor status depends on the method (randomization p 0.034 after ×7, while the Bonferroni bootstrap interval includes 0). The registered output `mean_episode_steps` (+0.84, pointwise [0.09, 1.69]) is missing from Table 14. | — | No table value changes. Completeness only. | One sentence each. |  |
| V1 | `verify_real_telemetry.py:87-91, 116-120` | Each gate is recomputed from the gate's own stored fields, never tied to the comparison it summarises. False alarms per day are not recomputable from the stored file. | `StoredRealTelemetryTests` ties the rt1 gate fields to `D2_vs_D1` and the rt2 gate to the primary comparisons. Both hold. | None. | The verifier itself is unchanged, so its check count (62) stays the same. |  |
| V2 | Cross-domain and Safety-Gymnasium verifiers | Second readers. `verify_cross_domain_world_models.py` and `verify_cross_domain_learned_contribution.py` recompute no metric. `rule_blocks_never_erased` and `final_catalog_digests_recorded` are always true by construction. `verify_cross_domain_world_model_improvement_study.py:194` asserts the expected outcome. The attribution verifier does not re-derive thresholds from development data (this is how P1 passed). The output-ablation and paired-uncertainty verifiers rerun the producer's own functions. | — | None. | Re-derive thresholds and rebuild summaries in the verifiers. Proposed for round 3. |  |

Smaller items, none of which moves a number:

- `incident_dynamics_metrics.bootstrap_difference` and `paired_warning_difference` use the same seed for both
  domains. Each domain has 1,024 episodes, so the two domains get identical resample indices. Each interval is
  valid on its own, and Bonferroni does not need independence.
- The rt2 calibrations rest on 2.1 days of normal data each, so every threshold is set by its 4th false episode
  (the budget allows 4.27 and 4.15). That is a thin basis, but it is the registered design.
- `real_telemetry_detection_v2.evaluate` and `d1_scores` (frozen by tt1) do not blank the warm-up after
  smoothing, while rt1/rt2 and the ensemble arm do. An event starting in the first 60 s of a stream could be
  credited from the smoothing head (monitor-audit finding 3). This has no effect unless an event starts there;
  that was not checked.
- `real_telemetry_calibration_transfer.py` records `target_fa_per_day: 1.0` but calibrates to a per-step FPR of
  1e-3, and `calibrate_threshold` is dead code. Not cited in any paper.
- Second reader: the protocol v14 text defines "intervention" differently from the runner (`planner_tangent`,
  only effective changes counted). In Table 11, 95.625 is printed as 95.62 because Python rounds half to even.

## Examined and found correct

- **Incident dynamics v2 to v4.**
  - Generators: train, validation, calibration and final RNG streams are hash-derived from (domain, partition,
    seed, episode) and are disjoint. Final seeds 281014, 391014/5 and 391024/5 are fresh.
  - Held-out mechanism families can be generated only for the final partition (`mechanism_rows` refuses
    otherwise). RSI probes use development families only.
  - Windows: complete five-step windows only, no future state in the inputs, history padding is causal. The
    history-3 and longer-history variants are asserted to share targets and episodes.
  - `calibrate`: the 1 % empirical-FPR cutoff sits strictly above the first excluded negative, which is
    conservative under ties (`IncidentCalibrationTests`).
  - Labels and warning scores: risk score and labels match the paper's constraint definitions.
  - Gates: v2 and v3/v4 use 98.75 % and 99.375 % intervals, which matches Bonferroni over 4 and 8 endpoints.
    Relative reduction is computed on episode-macro means, and the bootstrap estimate equals the macro difference
    (`IncidentMetricTests`).
  - Historical guards compare against the best paper or v2 ensemble on the same windows, with the same valid
    mask.
  - k selection: ties go to the smaller k, as registered.
  - The v4 wrapper reuses v3 archives only after a prediction-identity check.
  - Verifiers: they regenerate catalogs, recompute inference (atol 1e-7) and recompute statistics from the
    retained evidence.
  - Stored values: every cell of Tables 21, 23, 25, 26 and 27 matches the JSON.
- **rt1 and rt2.**
  - Events and pairing: event extraction, per-event pairing order across detectors, and the comparison
    direction (`b_vs_a` = b relative to a) are correct.
  - Normal-period world-model error: the windows exclude any labelled step (rt1 by slice, rt2 by cumulative sum).
  - False episodes and warm-up: an episode counts as false only if it touches no label, and the warm-up is
    blanked before alarms.
  - rt2 time split: chronological, with the scaler fitted on the fit part only.
  - D2c: its matched fraction reproduces from the bundles.
  - HAI 23.05 label alignment (minute-resolution, row-order rule): any row offset would fail at minute
    boundaries, so the check enforces alignment.
  - The verifier's recomputation of counts and bootstraps is correct.
- **Cross-domain (second reader).**
  - Data and leakage: there is no leakage. Splits are episode-disjoint, the scales are constants, Platt fit and
    threshold use development data only.
  - Model output: rollouts are causal and predictions are averaged before error (Section 4.3).
  - Statistics: the Wilson bounds (1.478 %) and the threshold tie rule are correct. Tables 3 to 6 and D1
    reproduce exactly.
- **Safety-Gymnasium (second reader).** Seed partitions are disjoint. All cells of Tables 11 to 15 recompute,
  including the Bonferroni and 11-output intervals. The independently rebuilt attribution and ablation catalogs
  show 0 summary mismatches.

## Verifiers and CI checks

- `verify_real_telemetry.py`: 62 of 62, pass. It rewrites its JSON with CRLF line endings on Windows; I restored
  the file, and the content was unchanged.
- CI physical verifiers, local run: `verify_physical_incident_sources`, `_incident_dataset`,
  `_jepa_v3_protocol`, `_stress_scenarios`, `_simulation_caution` and `_deployment_qualification` pass.
  `verify_physical_jepa_robustness.py` fails ("robustness report reproduces byte-for-byte") on this machine. It
  also fails on unmodified origin/main in the same environment: I stashed this branch's changes and reran. It
  imports nothing I changed. It probably depends on the CI-pinned numpy (2.2.6); I did not investigate further.
- I did not rerun the incident-dynamics `verify` stages (about 30 CPU-minutes each, needing the
  `target/incident-dynamics-*` work folders) or the cross-domain verifiers. No file they import was changed.
- Round-1 tests (`test_fi1_pipeline.py` and the four monitor-audit test files): 57 of 57 pass on this branch.
- Ruff: new files pass `ruff format --check` and `ruff check`. `real_telemetry_posthoc_rt1.py` passes
  `ruff check`. It was not ruff-formatted before this change either, and it is not in CI's lint lists, so I did
  not reformat it.

Proposed CI lines (ci.yml unchanged):

```yaml
      - name: Analysis pipeline tests (fi1 round 2)
        run: |
          python -m pip install --disable-pip-version-check pytest scipy scikit-learn lightgbm pandas
          cd scripts && python -m pytest -q test_fi1_pipeline2.py
      # add to the ruff check / ruff format --check lists:
      #   scripts/test_fi1_pipeline2.py scripts/fi1_rt_calibration_check.py scripts/physical_jepa_threshold_choice_v2.py
```

## Not reached

- rt1 SMD calibrations (335 MB bundle; the machine had under 1 GB of free memory) and the SMD part of Table 28.
  SMD is reported as inconclusive anyway.
- The closed-loop effect of P1 on Table 12 (needs the simulator, and a new registered run).
- The physical HAI replay and PyBullet tables (9, 10), the cross-version HAI transfer studies
  (`train_physical_hai_*`, `evaluate_physical_hai_*`), and the world-model v3.x selection scripts. They were not
  read in this round.
- Line coverage was not measured this round. The 15 new tests run on synthetic data and stored JSON.
