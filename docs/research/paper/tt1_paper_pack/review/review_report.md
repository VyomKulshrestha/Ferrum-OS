# Review report: *Thresholds That Travel* (draft v0.1, 23 October 2026)

Reviewer pass over `manuscript/thresholds_that_travel_draft_v0_1.md` against the files in `results/`,
`figure_data/` and `protocols/`. Nothing was recomputed from raw data: no raw dataset is in the pack and
each registered study's single access is spent. Every value below was read out of the pack's own JSON and
CSV files; the draft was not edited.

Verdict in one line: the arithmetic is in very good shape (126 of 138 traced numbers match exactly or to
correct rounding), but five presentation problems need fixing before submission - the voraus-AD unit
("runs" where the registration and the result files say "samples"), the failed tt1b primary rule missing
from the abstract, SPOT/DSPOT listed among the registered rules, the static margin described as a rule
that "held" when BATADAL put it at 3/14, and three numbers with no source in the pack.

---

## 1. Number trace

Columns: where it appears in the draft, the number as written, the file it comes from, the field or cell,
the value in that source, and the verdict. Rounding counts as a match only where the draft's rounding is
correct. Where one draft table cell carries several numbers, the row lists them in the draft's order.
`*` in a field path stands for the per-release or per-rule keys of that file.

| Draft location | As written | Source file | Field / cell | Value in source | Verdict |
|---|---|---|---|---|---|
| Abstract | 38 attacks (HAI 20.07) | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.frozen.events` | 38 | **match** |
| Abstract | frozen detected 36 | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.frozen.detected` | 36 | **match** |
| Abstract | 2.23 false-alarm episodes/day | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.frozen.fa_per_day` | 2.225380672625055 | **match** <br>*rounds to 2.23* |
| Abstract | tracker detected 20 | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.tracker.detected` | 20 | **match** |
| Abstract | difference -0.42 | `results/threshold_transfer_tt1_result_hai-20.07.json` | `gates.G2_tracker_vs_frozen.recall_difference` | -0.42105263157894735 | **match** |
| Abstract | 95% interval [-0.58, -0.26] | `results/threshold_transfer_tt1_result_hai-20.07.json` | `gates.G2_tracker_vs_frozen.recall_difference_interval` | [-0.5789473684210527, -0.26315789473684204] | **match** |
| Abstract | median 12.9 times above calibration | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.tracker.median_onset_inflation` | 12.928409597459869 | **match** |
| Abstract | eleven threshold rules | `protocols/threshold_transfer_tt1_protocol.json` | `frozen_components.threshold_rules` | frozen, margin, daily, tracker, tracker_slow + 6 one_sided = 11 | **match** <br>*matches tt1 only if SPOT/DSPOT excluded; see Sec. 5 of this report* |
| Abstract | Twelve two-minute nuisance alarms a day | `results/threshold_transfer_tt1_result_hai-20.07.json` | `E4_pulse_campaign.pulses / .pulse_s` | 12 / 120 | **match** <br>*count and length match; the blinding claim is development-only (see Sec. 2)* |
| Abstract | BATADAL 6 of 14 attacks | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.tracker.detected / .events` | 6 / 14 | **match** |
| Abstract | 14 for the frozen threshold | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.frozen.detected` | 14 | **match** |
| Abstract | Across seven datasets ... tighten-only matched frozen every time | `all 7 result files` | `one_sided:none recall vs frozen recall` | equal on hai-21.03/22.04/23.05/20.07, hygrid-ics, voraus-ad, batadal (D1 and D0) | **match** <br>*verified across both scores* |
| Sec. 1 bullet 1 | cost the tracker 16 of 38 attacks | `results/threshold_transfer_tt1_result_hai-20.07.json` | `frozen.detected - tracker.detected` | 36 - 20 = 16 | **match** <br>*derived; tracker itself missed 18 of 38* |
| Sec. 1 bullet 2 | frozen caught it every time (pulses) | `results/threshold_transfer_dev_v3.json` | `E4_pulse_campaign.rules.frozen.terminal_detected_after_campaign` | 1.0 on all three releases (30/30) | **match** |
| Sec. 3 | holding s_t at 0.97 tau_t | `protocols/threshold_transfer_tt1b_protocol.json` | `frozen_components.frog` | "the attacker sets s_t = max(clean s_t, 0.97 tau_t)" | **match** |
| Sec. 4 | 60 trees, history 3 | `protocols/threshold_transfer_tt1_protocol.json` | `frozen_components.monitor.definition` | 60 trees, 31 leaves, lr 0.1, history 3 | **match** |
| Sec. 4 | smoothed over 60 s | `protocols/threshold_transfer_tt1_protocol.json` | `frozen_components.monitor.smoothing_window` | 60 steps for 1 Hz streams | **match** |
| Sec. 4 | most recent 20% of normal training data | `protocols/threshold_transfer_tt1_protocol.json` | `frozen_components.normal_data_split` | fit 60 / scale 20 / calibration 20 % | **match** |
| Sec. 4 | 2 false-alarm episodes per day (both scores) | `protocols/threshold_transfer_tt1_protocol.json` | `frozen_components.monitor.budget` | 2/day for stream datasets; 0.05 per-sample for voraus-AD | **mismatch** <br>*voraus-AD uses a per-sample 0.05 target and BATADAL 1 episode/week* |
| Sec. 4 | margin = tau_0 + 0.25 x (99.9th pct - median) | `results/threshold_transfer_tt1_result_hai-20.07.json` | `thresholds.tau_half vs tau0+0.25*spread` | 20.32613423132735 = 17.25877276390233 + 0.25*12.269445869700089 | **match** <br>*voraus-AD uses q0.99 - median (protocol), not stated in the draft* |
| Sec. 4 | tracker eta = 0.01 x spread | `results/threshold_transfer_tt1_result_voraus-ad.json` | `thresholds.eta / thresholds.spread` | 0.15548293707370694 / 3.1096587414741386 = 0.05 | **mismatch** <br>*0.01 holds for HAI/HyGrid/BATADAL; voraus-AD is 0.05 x spread* |
| Sec. 4 | eta / 10 for tracker_slow | `protocols/threshold_transfer_tt1_protocol.json` | `frozen_components.threshold_rules.tracker_slow` | "the same tracker with eta / 10" | **match** |
| Sec. 4 data table | 547,624 s normal | `results/threshold_transfer_tt1_result_hai-20.07.json` | `normal_training_seconds (fit+scale+calib)` | 328574 + 109525 + 109525 = 547624 | **match** |
| Sec. 4 data table | 31 sensors, 20 actions | `protocols/threshold_transfer_tt1_protocol.json` | `data.hai-20.07.development` | "31 sensors and 20 actions" | **match** |
| Sec. 4 data table | test1 + test2, 5.15 days | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.total_days` | 5.145833333333333 | **match** |
| Sec. 4 data table | HyGrid 5 Hz to 1 Hz | `protocols/threshold_transfer_tt1_data_access.json` | `datasets.hygrid-ics.development_data` | 173,427 of 433,568 rows -> 34,743 s at 1 Hz (i.e. ~5 Hz source) | **match** <br>*derived; 5 Hz confirmed by the dataset repository* |
| Sec. 4 data table | HyGrid 9.6 h / 14.5 h | `protocols/threshold_transfer_tt1_protocol.json` | `data.hygrid-ics.development / .final` | "34,743 s (9.6 h ...)" / "about 14.5 h" | **match** |
| Sec. 4 data table | HyGrid 91 attacks | `results/threshold_transfer_tt1_result_hygrid-ics.json` | `real_events.rules.frozen.events` | 91 | **match** |
| Sec. 4 data table | voraus 100 Hz to 10 Hz | `protocols/threshold_transfer_tt1_data_access.json` | `datasets.voraus-ad.source / development` | 100 Hz parquet; 10 Hz (frequency divider 10) | **match** |
| Sec. 4 data table | 948 normal runs | `protocols/threshold_transfer_tt1_protocol.json` | `data.voraus-ad.development` | "948 normal samples" | **mismatch** <br>*record says samples, not runs* |
| Sec. 4 data table | 1174 runs | `results/threshold_transfer_tt1_result_voraus-ad.json` | `samples.test` | 1174 | **mismatch** <br>*record field is samples.test* |
| Sec. 4 data table | 50, 58, 52 attacks (dev releases) | `results/threshold_transfer_tt1b_dev_v1.json` | `releases.*.scores.D1.rules.frozen.events` | 50 / 58 / 52 | **match** |
| Sec. 4 data table | BATADAL 384 days normal | `protocols/threshold_transfer_tt1b_protocol.json` | `data.batadal` | "train_dataset.csv (384 days, normal)" | **match** |
| Sec. 4 data table | two test files, 260 days | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.normal_days` | 259.5625 | **match** <br>*rounds to 260* |
| Sec. 4 data table | BATADAL 14 attacks | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.frozen.events` | 14 | **match** |
| Sec. 4 | 27 of 27 checks pass | `results/threshold_transfer_tt1_verification.json` | `checks (list length), passed` | 27 checks, all pass = True | **match** |
| Sec. 5 item 1 | spread permit: 3 of 30 | `results/threshold_transfer_dev_v2.json` | `releases.*.E4_pulse_campaign.rules.one_sided:spread.terminal_detected_after_campaign` | 0.1 / 0.0 / 0.2 over 10 placements each = 3/30 (round r3) | **match** <br>*round r4 (dev_v3) gives 5/30 for the same rule; name the round* |
| Sec. 5 item 2 | cost 4 to 10 points of recall | `results/threshold_transfer_margin_dev_v1.json` | `releases.*.candidates.q2.vs_frozen.recall_difference` | -0.04 / -0.0862 / -0.0962 | **match** <br>*4.0 to 9.6 points* |
| Sec. 5 item 2 | interval lower bounds down to -0.17 | `results/threshold_transfer_margin_dev_v1.json` | `releases.*.candidates.q2.vs_frozen.recall_difference_interval` | [-0.10,0.0] / [-0.1724,-0.0172] / [-0.1731,-0.0192] | **match** |
| Sec. 5 item 2 | held the budget on pseudo-deployment splits | `results/threshold_transfer_margin_dev_v1.json` | `releases.hai-20.07.candidates.q2.fa_per_day` | 3.7865396695542928 (1.89x the 2/day budget) | **mismatch** <br>*above the 2/day budget, though below the 4/day gate; frozen on the same split is 4.42/day* |
| Sec. 5 item 3 | 0.66, 1.48 and 1.27 episodes per day | `results/threshold_transfer_tt1b_dev_v1.json` | `releases.*.scores.D1.rules.frozen.fa_per_day` | 0.659445 / 1.484664 / 1.265860 | **match** |
| Sec. 5 item 3 | tracker lost 22, 31 and 37 points | `results/threshold_transfer_tt1b_dev_v1.json` | `releases.*.scores.D1.rules.tracker.vs_frozen.recall_difference` | -0.22 / -0.3103 / -0.3654 | **match** |
| Sec. 6.1 G1 | 12 x 120 s per day at twice the terminal magnitude | `results/threshold_transfer_tt1_result_hai-20.07.json` | `E4_pulse_campaign.pulses / pulse_s / pulse_mult` | 12 / 120 / 2.0 | **match** |
| Sec. 6.1 G1 | frozen at least 0.8 / (frozen - 0.5) | `protocols/threshold_transfer_tt1_protocol.json` | `gates.G1_pulses_blind_adaptive_rules` | registered text matches | **match** |
| Sec. 6.1 G1 | frozen 10/10, each adaptive rule 0/10 | `results/threshold_transfer_tt1_result_hai-20.07.json` | `gates.G1_terminal_detected_after_campaign.*, E4_pulse_campaign.placements_used` | frozen 1.0, daily 0.0, tracker 0.0, tracker_slow 0.0; 10 placements | **match** |
| Sec. 6.1 G2 | 0.526 vs 0.947, -0.42 [-0.58, -0.26] | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.{tracker,frozen}.recall; gates.G2_tracker_vs_frozen` | 0.5263157894736842 / 0.9473684210526315; -0.421 [-0.579, -0.263] | **match** |
| Sec. 6.1 G3 | at most 4 / 2.23 / above the 2.0 budget | `results/threshold_transfer_tt1_result_hai-20.07.json` | `gates.G3_frozen_fa_per_day, .G3_frozen_within_budget_2_per_day` | 2.225380672625055, False | **match** |
| Sec. 6.1 | thresholds 7 to 26 times above tau_0 | `results/threshold_transfer_tt1_result_hai-20.07.json` | `E4_pulse_campaign.rules.{tracker_slow,tracker,daily}.median_threshold_inflation` | 7.225263233105436 / 18.32599268159833 / 25.564345428287332 | **match** <br>*7.2 to 25.6* |
| Sec. 6.1 | frozen 30/30; daily 4/30, tracker 1/30, tracker_slow 3/30 | `results/threshold_transfer_dev_v3.json` | `releases.*.E4_pulse_campaign.rules.*.terminal_detected_after_campaign` | 30/30, 4/30, 1/30, 3/30 summed over three releases | **match** |
| Sec. 6.2 table, HAI 20.07 | 0.947 (frozen) | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.frozen.recall` | 0.9473684210526315 | **match** |
| Sec. 6.2 table, HAI 20.07 | 0.474 (daily) | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.daily.recall` | 0.47368421052631576 | **match** |
| Sec. 6.2 table, HAI 20.07 | 0.526 (tracker) | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.tracker.recall` | 0.5263157894736842 | **match** |
| Sec. 6.2 table, HAI 20.07 | 0.711 (tracker_slow) | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.tracker_slow.recall` | 0.7105263157894737 | **match** |
| Sec. 6.2 table, HAI 20.07 | 0.947 (tighten-only) | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.one_sided:none.recall` | 0.9473684210526315 | **match** |
| Sec. 6.2 table, HAI 20.07 | [-0.63, -0.32] (daily) | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.paired.daily_vs_frozen.recall_difference_interval` | [-0.631578947368421, -0.3157894736842105] | **match** |
| Sec. 6.2 table, HAI 20.07 | [-0.58, -0.26] (tracker) | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.paired.tracker_vs_frozen.recall_difference_interval` | [-0.5789473684210527, -0.26315789473684204] | **match** |
| Sec. 6.2 table, HAI 20.07 | [-0.37, -0.11] (tracker_slow) | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.paired.tracker_slow_vs_frozen.recall_difference_interval` | [-0.368421052631579, -0.10526315789473684] | **match** |
| Sec. 6.2 table, HyGrid | 0.297 (frozen, daily, tighten-only) | `results/threshold_transfer_tt1_result_hygrid-ics.json` | `real_events.rules.{frozen,daily,one_sided:none}.recall` | 0.2967032967032967 | **match** |
| Sec. 6.2 table, HyGrid | 0.154 [-0.22, -0.08] (tracker) | `results/threshold_transfer_tt1_result_hygrid-ics.json` | `real_events.rules.tracker.recall; paired.tracker_vs_frozen...interval` | 0.15384615384615385; [-0.21978021978021978, -0.07692307692307693] | **match** |
| Sec. 6.2 table, HyGrid | 0.165 [-0.21, -0.07] (tracker_slow) | `results/threshold_transfer_tt1_result_hygrid-ics.json` | `real_events.rules.tracker_slow.recall; paired...interval` | 0.16483516483516483; [-0.20879120879120877, -0.06593406593406592] | **match** |
| Sec. 6.2 table, voraus | 0.334 / 0.148 / 0.082 / 0.213 / 0.334 | `results/threshold_transfer_tt1_result_voraus-ad.json` | `rules.*.tpr` | 0.3337748344370861 / 0.14834437086092717 / 0.08211920529801324 / 0.21324503311258278 / 0.3337748344370861 | **match** <br>*values match; "anomalous runs" should read samples* |
| Sec. 6.2 table, voraus | [-0.21, -0.16] / [-0.28, -0.22] / [-0.14, -0.10] | `results/threshold_transfer_tt1_result_voraus-ad.json` | `paired.{daily,tracker,tracker_slow}_vs_frozen.recall_difference_interval` | [-0.2132,-0.1563] / [-0.2834,-0.2212] / [-0.1444,-0.0980] | **match** |
| Sec. 6.2 | 25.6 / 12.9 / 6.4 tau_0 at onsets | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.{daily,tracker,tracker_slow}.median_onset_inflation` | 25.564345428287332 / 12.928409597459869 / 6.438117658750423 | **match** |
| Sec. 6.3, HAI row | 2.23 / 2.23 / 0.20 / 1.01 / 2.23 | `results/threshold_transfer_tt1_result_hai-20.07.json` | `real_events.rules.*.fa_per_day` | 2.225381 / 2.225381 / 0.202307 / 1.011537 / 2.225381 | **match** |
| Sec. 6.3, HyGrid row | 19.2 / 0.0 / 19.2 / 19.2 / 19.2 | `results/threshold_transfer_tt1_result_hygrid-ics.json` | `real_events.rules.*.fa_per_day` | 19.20213357039671 / 0.0 / 19.202134 / 19.202134 / 19.202134 | **match** |
| Sec. 6.3, HyGrid row | 2.5 h unlabelled | `results/threshold_transfer_tt1_result_hygrid-ics.json` | `real_events.normal_days` | 0.10415509259259259 (= 2.50 h) | **match** |
| Sec. 6.3, voraus row | 0.081 / 0.033 / 0.086 / 0.012 / 0.014, target 0.05 | `results/threshold_transfer_tt1_result_voraus-ad.json` | `rules.*.fpr; spec.alpha` | 0.081146 / 0.033413 / 0.085919 / 0.011933 / 0.014320; 0.05 | **match** <br>*"FPR per run" should read per sample* |
| Sec. 6.3 | cost of 12 points of recall (voraus margin) | `results/threshold_transfer_tt1_result_voraus-ad.json` | `paired.margin_vs_frozen.recall_difference` | -0.1218543046357616 | **match** |
| Sec. 7.1 table, spent releases | frozen 1.00 / 0.76 / 0.60 | `results/threshold_transfer_tt1b_dev_v1.json` | `releases.*.scores.D1.rules.frozen.recall` | 1.0 / 0.7586206896551724 / 0.5961538461538461 | **match** |
| Sec. 7.1 table, spent releases | tracker 0.78 / 0.45 / 0.23 | `results/threshold_transfer_tt1b_dev_v1.json` | `releases.*.scores.D1.rules.tracker.recall` | 0.78 / 0.4482758620689655 / 0.23076923076923078 | **match** |
| Sec. 7.1 table, spent releases | SPOT moments 1.00 / 0.79 / 0.58 | `results/threshold_transfer_tt1b_dev_v1.json` | `releases.*.scores.D1.rules.spot.recall` | 1.0 / 0.7931034482758621 / 0.5769230769230769 | **match** |
| Sec. 7.1 table, spent releases | SPOT MLE 1.00 / 0.79 / 0.60 | `results/threshold_transfer_tt1b_dev_v1.json` | `releases.*.scores.D1.rules.spot_mle.recall` | 1.0 / 0.7931034482758621 / 0.5961538461538461 | **match** |
| Sec. 7.1 table, spent releases | DSPOT 1.00 / 0.79 / 0.60 | `results/threshold_transfer_tt1b_dev_v1.json` | `releases.*.scores.D1.rules.dspot.recall` | 1.0 / 0.7931034482758621 / 0.5961538461538461 | **match** |
| Sec. 7.1 table, HAI 20.07 post-hoc | 0.947 / 0.526 / 0.947 / 0.921 [-0.08, 0.00] / 0.947 | `results/threshold_transfer_tt1b_posthoc_v1.json` | `datasets.hai-20.07.scores.D1.rules.*.recall (+ spot_mle.vs_frozen)` | 0.9474 / 0.5263 / 0.9474 / 0.9211 [-0.0789, 0.0] / 0.9474 | **match** |
| Sec. 7.1 | HyGrid moments SPOT lost 9 points ([-0.15, -0.03]) | `results/threshold_transfer_tt1b_posthoc_v1.json` | `datasets.hygrid-ics.scores.D1.rules.spot.vs_frozen` | -0.0879120879120879; [-0.15384615384615383, -0.03296703296703296] | **match** |
| Sec. 7.1 | 190 calibration runs | `results/threshold_transfer_tt1_result_voraus-ad.json` | `samples.calib` | 190 | **mismatch** <br>*record says 190 calibration samples* |
| Sec. 7.1 | about four tail points | `protocols/threshold_transfer_tt1b_protocol.json` | `frozen_components.rules ("SPOT base level: calibration 98th percentile")` | 190 x 0.02 = 3.8 | **match** <br>*derived, not stored; state the derivation* |
| Sec. 7.1 | SPOT 32% false positives against a 5% target | `results/threshold_transfer_tt1b_posthoc_v1.json` | `datasets.voraus-ad.scores.D1.rules.spot.fpr; spec.alpha (voraus result)` | 0.3221957040572792; 0.05 | **match** |
| Sec. 7.2 | D0 [-0.38, -0.14], [-0.21, -0.05], [-0.19, -0.02] | `results/threshold_transfer_tt1b_dev_v1.json` | `releases.*.scores.D0.rules.tracker.vs_frozen.recall_difference_interval` | [-0.38,-0.14] / [-0.2069,-0.0513] / [-0.1923,-0.0192] | **match** |
| Sec. 7.2 | D0 [-0.32, -0.08] on HAI 20.07 | `results/threshold_transfer_tt1b_posthoc_v1.json` | `datasets.hai-20.07.scores.D0.rules.tracker.vs_frozen.recall_difference_interval` | [-0.3157894736842105, -0.07894736842105254] | **match** |
| Sec. 7.2 | D0 [-0.12, -0.02] on HyGrid | `results/threshold_transfer_tt1b_posthoc_v1.json` | `datasets.hygrid-ics.scores.D0.rules.tracker.vs_frozen.recall_difference_interval` | [-0.12087912087912088, -0.02197802197802197] | **match** |
| Sec. 7.3 | within 6 h of the previous attack | `protocols/threshold_transfer_tt1b_protocol.json` | `frozen_components.settings ("close events: within 24 steps (6 h)")` | 6 h | **match** |
| Sec. 7.3 | 0.75 / 1.00, 0.41 / 1.00, 0.20 / 0.67 | `results/threshold_transfer_tt1b_dev_v1.json` | `releases.*.scores.D1.rules.tracker.recall_close / .recall_isolated` | 0.75/1.0, 0.4074/1.0, 0.2041/0.6667 | **match** |
| Sec. 7.3 | 0.48 / 0.71 on HAI 20.07 | `results/threshold_transfer_tt1b_posthoc_v1.json` | `datasets.hai-20.07.scores.D1.rules.tracker.recall_close / .recall_isolated` | 0.4839 / 0.7143 | **match** |
| Sec. 7.3 | 31 close, 7 isolated | `results/threshold_transfer_tt1b_posthoc_v1.json` | `datasets.hai-20.07.scores.D1.rules.tracker.n_close / .n_isolated` | 31 / 7 | **match** |
| Sec. 7.3 | frozen detected close attacks less often on two releases | `results/threshold_transfer_tt1b_dev_v1.json` | `releases.*.scores.D1.rules.frozen.recall_close vs recall_isolated` | 1.00/1.00, 0.741/1.00, 0.592/0.667 | **match** |
| Sec. 7.4 row 1 | 30/30, 4/30, 1/30, 3/30 (frozen, daily, tracker, tracker_slow) | `results/threshold_transfer_dev_v3.json` | `releases.*.E4_pulse_campaign.rules.*.terminal_detected_after_campaign` | 1.0, 0.0/0.0/0.4, 0.0/0.1/0.0, 0.0/0.2/0.1 over 10 placements each | **match** |
| Sec. 7.4 row 1 | SPOT 29/30, DSPOT 23/30 (control 25/30) | `results/threshold_transfer_tt1b_attacks_dev_v1.json` | `releases.*.E4.rules.{spot,dspot}.terminal_after_campaign / .terminal_control` | 29/30; 23/30 with control 25/30 | **match** <br>*controls for daily (21/30), tracker (23/30), tracker_slow (25/30) are omitted from this row* |
| Sec. 7.4 row 2 | 30/30, 23/30 (23/30), 19/30 (21/30), 23/30, 29/30, 22/30 (24/30) | `results/threshold_transfer_tt1b_attacks_dev_v1.json` | `releases.*.E6.rules.*.terminal_after_campaign / .terminal_control` | frozen 30/30; daily 23/30 ctl 23/30; tracker 19/30 ctl 21/30; tracker_slow 23/30 ctl 23/30; spot 29/30; dspot 22/30 ctl 24/30 | **match** |
| Sec. 7.4 row 2 | 24 x 300 s per day | `results/threshold_transfer_tt1b_attacks_dev_v1.json` | `E6.pulses / E6.pulse_s` | 24 / 300 | **match** |
| Sec. 7.4 | SPOT threshold fell (0.82 to 0.98 tau_0) | `results/threshold_transfer_tt1b_attacks_dev_v1.json` | `releases.*.E6.rules.spot.median_inflation` | 0.979 / 0.822 / 0.979 | **match** |
| Sec. 7.5 | 10 placements each | `results/threshold_transfer_tt1b_frog_dev_v1.json` | `releases.*.variants.* (10 placements per release)` | 10 per release, 3 releases = 30 | **match** |
| Sec. 7.5 | 0.97 tau_t, 1.05 tau_0 bump | `protocols/threshold_transfer_tt1b_protocol.json` | `frozen_components.frog` | 0.97 tau_t; 1.05 tau0 | **match** |
| Sec. 7.5 | 600 s bump | `protocols/threshold_transfer_tt1_protocol.json` | `frozen_components.E4_pulse_campaign ("lagged response, 600 s")` | 600 s appears as the terminal-step response window, not as a bump length for the score-level frog | **untraceable** <br>*no field gives the frog bump duration on the HAI streams* |
| Sec. 7.5 table | frozen / tracker / tracker_slow / tighten-only: as control (24 h, 6 h, 1 h) | `results/threshold_transfer_tt1b_frog_dev_v1.json` | `variants.closed_{24h,6h,1h}.*.terminal_after_campaign vs .terminal_control` | frozen 30/30 vs 30/30; tracker 20/30 vs 20/30; tracker_slow 23/30 vs 23/30; one_sided:none 30/30 vs 30/30 | **match** |
| Sec. 7.5 table | frozen / tracker / tracker_slow / tighten-only: as control (fixed level, 24 h) | `results/threshold_transfer_tt1b_frog_dev_v1.json` | `variants.fixed_24h.tracker.terminal_after_campaign / .terminal_control` | 16/30 vs control 20/30 | **mismatch** <br>*the open-loop fixed-level tracker is 4 placements below its control, not "as control"* |
| Sec. 7.5 table | SPOT (moments) 0/30, 0/30, 0/30 | `results/threshold_transfer_tt1b_frog_dev_v1.json` | `variants.closed_{24h,6h,1h}.spot.terminal_after_campaign` | 0.0 on every release | **match** |
| Sec. 7.5 table | DSPOT 0/30, 0/30, 0/30 | `results/threshold_transfer_tt1b_frog_dev_v1.json` | `variants.closed_{24h,6h,1h}.dspot.terminal_after_campaign` | 0.0 on every release | **match** |
| Sec. 7.5 table | SPOT (MLE) 8/30, 8/30, 13/30, 11/30 | `results/threshold_transfer_tt1b_frog_dev_v1.json` | `variants.*.spot_mle.terminal_after_campaign` | closed_24h 8/30, closed_6h 8/30, closed_1h 13/30, fixed_24h 11/30 | **match** |
| Sec. 7.5 table | refit every 2048 peaks | `protocols/threshold_transfer_tt1b_protocol.json` | `frozen_components.rules` | "refit every 2048 peaks at 1 Hz, 16 at 15 min" | **match** |
| Sec. 7.5 | frozen and both SPOT controls 30/30, DSPOT 24/30 | `results/threshold_transfer_tt1b_frog_dev_v1.json` | `variants.closed_24h.{frozen,spot,spot_mle,dspot}.terminal_control` | 30/30, 30/30, 30/30, 24/30 | **match** |
| Sec. 7.5 | moments SPOT 1.1 to 4.5 tau_0 after 1 h | `results/threshold_transfer_tt1b_frog_dev_v1.json` | `variants.closed_1h.spot.median_inflation` | 1.144 / 1.210 / 4.542 | **match** <br>*findings quote 1.1-4.7, which is DSPOT's range* |
| Sec. 7.5 | more than five orders of magnitude after 24 h | `results/threshold_transfer_tt1b_frog_dev_v1.json` | `variants.closed_24h.spot.median_inflation` | 4.157e5 / 8.248e6 / 8.248e15 | **match** |
| Sec. 7.5 | MLE fit left the floating-point range on one release | `results/threshold_transfer_tt1b_frog_dev_v1.json` | `variants.closed_24h.spot_mle.median_inflation` | inf on hai-22.04 | **match** |
| Sec. 7.5 | light-tailed synthetic scores: 0.94 to 0.97 tau_0 after 24 h | `none` | `-` | no file in the pack reports a synthetic-score SPOT run | **untraceable** |
| Sec. 7.5 phys | every 5 minutes, 6 h campaign, 12 placements | `results/threshold_transfer_tt1b_physfrog_dev_v1.json` | `releases.*.campaign_hours / .placements_used` | 6.0 h; 4 placements x 3 releases = 12 | **match** <br>*the 5-minute re-choice interval is not stored in the result file* |
| Sec. 7.5 phys table | frozen 12 / 12; threshold 1.0 tau_0 | `results/threshold_transfer_tt1b_physfrog_dev_v1.json` | `releases.*.rules.frozen.terminal_after_campaign / .terminal_control / .median_inflation` | 12/12 attack, 12/12 control; 1.0 | **match** |
| Sec. 7.5 phys table | SPOT (MLE) 4 / 12 | `results/threshold_transfer_tt1b_physfrog_dev_v1.json` | `releases.*.rules.spot_mle.terminal_after_campaign / .terminal_control` | 4/12 attack; 12/12 control | **match** <br>*column header reads "attack / control"; this cell is attack-only* |
| Sec. 7.5 phys table | SPOT (MLE) 1.04 to 1.59 tau_0 | `results/threshold_transfer_tt1b_physfrog_dev_v1.json` | `releases.*.rules.spot_mle.median_inflation` | 1.041 / 1.595 / 1.123 | **match** |
| Sec. 7.5 phys table | SPOT (moments) 6 / 12 | `results/threshold_transfer_tt1b_physfrog_dev_v1.json` | `releases.*.rules.spot.terminal_after_campaign / .terminal_control` | 6/12 attack; 12/12 control | **match** <br>*same header problem* |
| Sec. 7.5 phys table | SPOT (moments) up to 7.6 tau_0 | `results/threshold_transfer_tt1b_physfrog_dev_v1.json` | `releases.*.rules.spot.median_inflation` | 0.775 / 1.416 / 1.034 (no max_inflation field in the file) | **untraceable** <br>*largest stored value is 1.42; 7.6 appears nowhere in the pack* |
| Sec. 7.5 phys table | DSPOT 9 / 9 | `results/threshold_transfer_tt1b_physfrog_dev_v1.json` | `releases.*.rules.dspot.terminal_after_campaign / .terminal_control` | 9/12 attack; 9/12 control | **mismatch** <br>*denominator is 12, not 9* |
| Sec. 7.5 phys table | DSPOT 0.88 to 1.12 tau_0 | `results/threshold_transfer_tt1b_physfrog_dev_v1.json` | `releases.*.rules.dspot.median_inflation` | 0.875 / 0.943 / 1.116 | **match** |
| Sec. 7.5 phys | HAI 22.04: both SPOT variants missed all four placements, no alarm | `results/threshold_transfer_tt1b_physfrog_dev_v1.json` | `releases.hai-22.04.rules.{spot,spot_mle}.terminal_after_campaign / .median_campaign_alarm_steps` | 0.0 / 0.0; 0.0 / 0.0 | **match** |
| Sec. 7.5 phys | spoofed noise scale 0.02 to 0.04 robust units | `results/threshold_transfer_tt1b_physfrog_dev_v1.json` | `releases.*.rules.*.median_noise_sigma` | frozen/SPOT/MLE 0.0227-0.0421; DSPOT 0.0532-0.1164 | **mismatch** <br>*DSPOT's spoofed noise is 0.05-0.12* |
| Sec. 7.6 | 1 h smoothing, 1 h episode merging, 1 episode/week, one-day DSPOT mean | `results/threshold_transfer_tt1b_result_batadal.json` | `settings.window / .gap / .budget / .depth` | 4 / 4 / 0.14285714285714285 / 96 (15-min steps) | **match** |
| Sec. 7.6 | 14 attacks in 260 days | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.frozen.events; .normal_days` | 14; 259.5625 | **match** |
| Sec. 7.6 H1 | 6/14 vs 14/14, -0.57 [-0.79, -0.29] | `results/threshold_transfer_tt1b_result_batadal.json` | `gates.H1_tracker_vs_frozen; rules.{tracker,frozen}.detected` | -0.5714285714285714 [-0.7857142857142857, -0.2857142857142857]; 6; 14 | **match** |
| Sec. 7.6 H2 | 14/14, difference 0; tolerance -max(0.10, 2/N) | `results/threshold_transfer_tt1b_result_batadal.json` | `gates.H2_spot_mle_vs_frozen.recall_difference; gates.H2_tolerance` | 0.0; -0.14285714285714285 | **match** |
| Sec. 7.6 H3 | DSPOT already 0/10 in the control: fail | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.frog.variants.closed_24h.dspot.terminal_control; gates.H3_placements; gates.H3_...` | 0.0; 10; False | **match** |
| Sec. 7.6 | threshold 24 times above tau_0; detected 6 of 14 | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.dspot.median_onset_inflation / .detected` | 24.063129 / 6 | **match** |
| Sec. 7.6 rule table | frozen: 14/14, 0.70, 1.0 | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.frozen.detected / .fa_ratio_to_budget / .median_onset_inflation` | 14/14, 0.7012, 1.0 | **match** |
| Sec. 7.6 rule table | tighten-only: 14/14, 2.43, 1.0 | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.one_sided:none.detected / .fa_ratio_to_budget / .median_onset_inflation` | 14/14, 2.4272, 1.0 | **match** |
| Sec. 7.6 rule table | SPOT (MLE): 14/14, 0.81, 1.0 | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.spot_mle.detected / .fa_ratio_to_budget / .median_onset_inflation` | 14/14, 0.8091, 1.0106 | **match** |
| Sec. 7.6 rule table | daily: 14/14, 6.34, 0.69 | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.daily.detected / .fa_ratio_to_budget / .median_onset_inflation` | 14/14, 6.3376, 0.687 | **match** |
| Sec. 7.6 rule table | tracker: 6/14, 1.83, 409 | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.tracker.detected / .fa_ratio_to_budget / .median_onset_inflation` | 6/14, 1.8339, 409.2694 | **match** |
| Sec. 7.6 rule table | tracker_slow: 5/14, 0.70, 74 | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.tracker_slow.detected / .fa_ratio_to_budget / .median_onset_inflation` | 5/14, 0.7012, 74.2525 | **match** |
| Sec. 7.6 rule table | SPOT (moments): 6/14, 0.13, 26 | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.spot.detected / .fa_ratio_to_budget / .median_onset_inflation` | 6/14, 0.1348, 25.6444 | **match** |
| Sec. 7.6 rule table | DSPOT: 6/14, 0.13, 24 | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.dspot.detected / .fa_ratio_to_budget / .median_onset_inflation` | 6/14, 0.1348, 24.0631 | **match** |
| Sec. 7.6 rule table | margin: 3/14, 0.05, 173 | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.margin.detected / .fa_ratio_to_budget / .median_onset_inflation` | 3/14, 0.0539, 172.9823 | **match** |
| Sec. 7.6 | D0 MLE SPOT 9/14, [-0.64, -0.14] | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D0.real_events.rules.spot_mle.detected; paired.spot_mle_vs_frozen.recall_difference_interval` | 9; [-0.6428571428571428, -0.1428571428571429] | **match** |
| Sec. 7.6 | margin sat 173 times above tau_0 | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.margin.median_onset_inflation` | 172.98227273549142 | **match** |
| Sec. 8 item 3 | 0.66 to 2.23 episodes/day on four HAI test periods | `results/threshold_transfer_tt1b_dev_v1.json + results/threshold_transfer_tt1_result_hai-20.07.json` | `frozen.fa_per_day (21.03/22.04/23.05) and real_events.rules.frozen.fa_per_day` | 0.659445 / 1.484664 / 1.265860 / 2.225381 | **match** |
| Sec. 8 | tighten-only 5.98x budget vs frozen 4.05x (HAI 23.05 development) | `results/threshold_transfer_dev_v3.json` | `releases.hai-23.05.E1_budget_adherence["one_sided:none@eta0.01"].ratio_to_budget / ["frozen"].ratio_to_budget` | 5.976 / 4.048 | **match** |
| Sec. 8 | static margin 0.58x the budget (HAI 23.05 development) | `results/threshold_transfer_dev_v3.json` | `releases.hai-23.05.E1_budget_adherence.margin.ratio_to_budget` | 0.578 | **match** <br>*"halves that cost" understates a 7x reduction* |
| Sec. 8 | voraus-AD: 12 points | `results/threshold_transfer_tt1_result_voraus-ad.json` | `paired.margin_vs_frozen.recall_difference` | -0.1218543046357616 | **match** |
| Sec. 9 | BATADAL has 14 attacks | `results/threshold_transfer_tt1b_result_batadal.json` | `scores.D1.real_events.rules.frozen.events` | 14 | **match** |
| Sec. 9 | 2.5 h of unlabelled final time (HyGrid) | `results/threshold_transfer_tt1_result_hygrid-ics.json` | `real_events.normal_days` | 0.10415509259259259 | **match** |

### 1.1 The nine mismatches, with proposed replacements

**M1. Section 4, calibration budget.** Draft: "Both are calibrated on the most recent 20% of normal
training data to 2 false-alarm episodes per day (episodes merged across 60 s gaps)." The registration
sets a different budget for two of the five datasets: `threshold_transfer_tt1_protocol.json`
`frozen_components.monitor.budget` reads "2 false-alarm episodes per day, episodes merged across gaps of
60 s (stream datasets); per-sample false-alarm target 0.05 (voraus-AD)", and
`threshold_transfer_tt1b_result_batadal.json` `settings.budget` is 0.1428... per day (one episode per
week).

*Proposed replacement:* "Both are calibrated on the most recent 20% of normal training data: to 2
false-alarm episodes per day on the 1 Hz stream datasets (episodes merged across 60 s gaps), to a
per-sample false-alarm target of 0.05 on voraus-AD, and to one false-alarm episode per week on BATADAL
(episodes merged across 1 h)."

**M2. Section 4, tracker step size.** Draft: "tracker (eta = 0.01 x spread)". True for HAI, HyGrid-ICS
and BATADAL, but `threshold_transfer_tt1_result_voraus-ad.json` gives `thresholds.eta` 0.15548... on
`thresholds.spread` 3.10966..., i.e. 0.05 x spread, as registered in
`frozen_components.threshold_rules.tracker` ("eta = 0.01 x spread (stream) or 0.05 x spread (voraus)").
The same paragraph also omits two other registered per-dataset variations: the margin spread is
q0.99 - median on voraus-AD (not q0.999 - median), and `daily` re-sets every 50 samples there rather than
once per day.

*Proposed replacement:* "tracker (eta = 0.01 x spread on the stream datasets, 0.05 x spread on voraus-AD)
and tracker_slow (eta / 10, the best false-alarm adherence among trackers in development); on voraus-AD
the spread is the calibration 99th percentile minus the median and `daily` re-sets every 50 samples."

**M3-M4. Section 4 data table, voraus-AD units.** Draft: "948 normal runs" and "1174 runs". The
registration says "948 normal samples" (`threshold_transfer_tt1_protocol.json` `data.voraus-ad.development`)
and the result file counts `samples.fit` 568, `samples.scale` 190, `samples.calib` 190, `samples.test`
1174. The dataset's own paper (Brockmann et al. 2024) also calls these samples. A voraus-AD sample is one
recorded robot motion, so "run" is not absurd, but it conflicts with the record and with the source
paper, and it propagates into the false-alarm claim (M6, C5 below).

*Proposed replacement (table cells):* "948 normal samples" / "1174 samples" / "755 anomalous samples".

**M5. Section 5 item 2, the half-rate margin and the budget.** Draft: "A margin at half the calibration
exceedance rate held the budget on pseudo-deployment splits." On the HAI 20.07 pseudo-deployment split the
q2 candidate ran at 3.787 false-alarm episodes per day (`threshold_transfer_margin_dev_v1.json`
`releases.hai-20.07.candidates.q2.fa_per_day`) against a 2/day budget - 1.89x the budget. It was below the
4/day gate, and below frozen's 4.418/day on the same split, but it did not hold the budget.

*Proposed replacement:* "A margin at half the calibration exceedance rate cut the false-alarm rate on
pseudo-deployment splits without reaching the budget (HAI 20.07 development: 3.79 episodes per day against
frozen's 4.42, budget 2), but cost 4 to 10 points of recall on the spent attacks (interval lower bounds
down to -0.17), so we registered a smaller margin and made it secondary."

**M6. Section 6.3 table header and Section 7.1, "per run".** Draft: "voraus-AD (FPR per run, target 0.05)"
and "190 calibration runs". Both are per sample in the record (`frozen_components.monitor.budget`:
"per-sample false-alarm target 0.05 (voraus-AD)"; `samples.calib` = 190).

*Proposed replacement:* "voraus-AD (per-sample FPR, target 0.05)" and "190 calibration samples leave about
four tail points above SPOT's base level (the calibration 98th percentile), and SPOT ran at 32% false
positives against a 5% target."

**M7. Section 7.5 table, open-loop fixed-level column.** Draft puts "as control" in the fixed-level column
for frozen, tracker, tracker_slow and tighten-only. `threshold_transfer_tt1b_frog_dev_v1.json`
`variants.fixed_24h.tracker` gives 16/30 after the campaign against 20/30 in the control; frozen (30/30),
tracker_slow (23/30) and one_sided:none (30/30) are indeed at their controls.

*Proposed replacement (row 1 of the table):* "frozen, tracker_slow, tighten-only | as control | as control
| as control | as control" with a second row "tracker | as control | as control | as control | 16/30
(control 20/30)", or a footnote: "the open-loop fixed-level campaign cost the tracker 4 of 30 placements
(16/30 against 20/30 in the control); the closed-loop campaigns cost it none."

**M8. Section 7.5 physical-frog table, DSPOT denominator.** Draft: "DSPOT | 9 / 9". The column header is
"Terminal caught (attack / control), 12 placements" and the file gives
`releases.*.rules.dspot.terminal_after_campaign` = 9 of 12 and `.terminal_control` = 9 of 12. The cell also
reads inconsistently against the rows above it, where "4 / 12" and "6 / 12" are attack counts out of 12
placements and the controls (12/12 for both SPOT variants) are not shown at all.

*Proposed replacement (whole column):* give both numbers explicitly - "frozen 12/12 attack, 12/12 control;
SPOT (MLE) 4/12 attack, 12/12 control; SPOT (moments) 6/12 attack, 12/12 control; DSPOT 9/12 attack, 9/12
control" - and rename the column "Terminal caught after campaign / in control (12 placements)".

**M9. Section 7.5, spoofed noise scale.** Draft: "The spoofed noise had a scale of 0.02 to 0.04 robust
units." That is the range for frozen and the two SPOT variants (`median_noise_sigma` 0.0227 to 0.0421);
against DSPOT the attacker needed 0.0532 to 0.1164, because DSPOT's moving mean absorbs the rise.

*Proposed replacement:* "The spoofed noise had a scale of 0.02 to 0.04 robust units against frozen and the
SPOT variants, and 0.05 to 0.12 against DSPOT, whose moving mean absorbs part of the rise."

### 1.2 The three untraceable numbers

**U1. Section 7.5: "On light-tailed synthetic scores SPOT did not run away (0.94 to 0.97 tau_0 after 24 h)."**
No file in the pack reports a synthetic-score SPOT run. `threshold_transfer_tt1b_frog_dev_v1.json` holds
only the three spent HAI releases; a search of every key and string value in `results/` and `protocols/`
for "synthetic" or "light" returns nothing matching. The claim carries weight - it is the draft's evidence
that the runaway depends on the heavy tail - so it needs either a ledgered file or removal.

*Proposed replacement if no file is found:* "The runaway tracks the tail of the score: the releases whose
moments-SPOT threshold grew most are those with the heaviest residual tails. We did not register a
light-tailed control, so we state this as an observation rather than a measured contrast."

**U2. Section 7.5 physical-frog table: "SPOT (moments) | up to 7.6 tau_0".**
`threshold_transfer_tt1b_physfrog_dev_v1.json` stores only `median_inflation` per release (0.775, 1.416,
1.034) with no maximum; 7.6 appears nowhere in the pack. The MLE row beside it is correctly reported as a
median per release.

*Proposed replacement:* "SPOT (moments) | 6 / 12 | 0.78 to 1.42 tau_0 (median per release)" - or, if a
per-placement maximum of 7.6 exists outside the pack, label it as a maximum and cite the file.

**U3. Section 7.5: "then 1 h later a 600 s bump at 1.05 tau_0 follows."** The level (1.05 tau_0) and the
lead (1 h) are registered in `threshold_transfer_tt1b_protocol.json` `frozen_components.frog` and
`frozen_components.settings`; the 600 s duration is not. 600 s appears in the tt1 protocol only as the
lagged-response window used to size the terminal setpoint step in E4.

*Proposed replacement:* "then, after a one-hour lead, a terminal bump at 1.05 tau_0 follows" - with the
duration restored only if a frozen file records it.

---

## 2. Registered versus exploratory

The draft's section-level labelling is right: Sections 6 and 7.6 are registered, Section 5 is development,
Section 7 is headed "(exploratory)" and 7.1's HAI 20.07 row is marked "(post-hoc)". The status column of
`figure_data/recall_and_false_alarms_by_rule.csv` agrees with every per-section assignment I checked
(33 rows "registered tt1", 18 "registered tt1b", 54 "exploratory (spent data)", 54 "post-hoc (after
finals)"). Four problems remain.

**R1. The abstract presents tt1b as a clean replication and never says its primary rule failed.**
The abstract reads: "A second registered study on the BATADAL water network replicated the tracker's loss
(6 of 14 attacks against 14 for the frozen threshold) and found that slow, days-long attacks also inflated
SPOT and DSPOT." The registered success rule is the conjunction:
`threshold_transfer_tt1b_protocol.json` `hypotheses.primary_success_rule` = "H1 and H2 and H3 on the
dataset", and `threshold_transfer_tt1b_result_batadal.json` `gates.primary_success` is **false**
(`gates.H3_frog_blinds_dspot_not_frozen_or_tighten_only` false). Section 7.6 shows "fail" in the H3 row and
explains the cause, but nowhere in the draft does the sentence "the registered primary rule of tt1b did not
pass" appear - and a reader of the abstract alone would conclude the replication passed.

*Proposed replacement (abstract):* "A second registered study on the BATADAL water network replicated the
tracker's loss (6 of 14 attacks against 14 for the frozen threshold) and showed that slow, days-long
attacks also inflate SPOT and DSPOT. Its pre-registered primary rule nevertheless fails: the third
hypothesis, that a closed-loop frog blinds DSPOT, could not be tested because real attacks had already
blinded DSPOT in all ten controls."

*Proposed addition (end of the Section 7.6 gate table):* "Primary rule (H1 and H2 and H3): fail. We retain
the rule as registered and report H3 as uninformative rather than refuted."

**R2. Section 4 lists SPOT and DSPOT among the rules of the registered study.** The "Rules" paragraph
ends "...; SPOT and DSPOT with method-of-moments and maximum-likelihood tail fits", inside the section that
describes the registration, and the abstract and contribution 1 both say "eleven threshold rules". The tt1
registration freezes exactly eleven rules (`frozen_components.threshold_rules`: frozen, margin, daily,
tracker, tracker_slow and six `one_sided` variants) and no extreme-value rule; SPOT, SPOT-MLE and DSPOT
first appear in `threshold_transfer_tt1b_protocol.json` `frozen_components.rules`, and in tt1 they exist
only post-hoc. As written, Section 4 reads as though the registered comparison covered thirteen or fourteen
rules including the extreme-value family.

*Proposed replacement (end of the Rules paragraph):* "...and an oracle permit that simulates an operator
who refuses to loosen while an event is under way: eleven rules in all. The streaming extreme-value rules
(SPOT and DSPOT, with method-of-moments and maximum-likelihood tail fits [Hosking and Wallis 1987; Siffer
et al. 2017]) were not part of the tt1 registration; they enter in Section 7 as post-hoc analyses and are
registered only in tt1b."

**R3. The abstract's pulse-campaign sentence inherits the G1 caveat without carrying it.** "Twelve
two-minute nuisance alarms a day blinded every rule that learns from exceedances to a later,
just-detectable setpoint attack." The registered G1 passed, but on the registered stream the adaptive rules
also missed the terminal step in the controls (`E4_pulse_campaign.rules.{daily,tracker,tracker_slow}
.terminal_detected_control` = 0.0), so the pulse-specific effect rests on development data
(`threshold_transfer_dev_v3.json`: frozen 30/30 against daily 4/30, tracker 1/30, tracker_slow 3/30, with
controls at 21/30, 23/30 and 25/30). Sections 6.1 and 7.4 say this; the abstract and the Section 1 bullet
do not.

*Proposed replacement (abstract):* "Twelve two-minute nuisance alarms a day blinded every rule that learns
from exceedances to a later, just-detectable setpoint attack; on the registered stream the real attacks had
already done the same, so the pulse-specific effect is measured on attack-free development data."

**R4. Two registered reporting commitments are not discharged anywhere in the draft.** Both protocols
require them: `threshold_transfer_tt1_protocol.json` `gates.reporting` ends "No claim of runtime authority,
deployment safety or real-incident prevention follows", and `data.hygrid-ics.known_limits` promises that
attack contamination of the label-blind development portion "is measured and reported after it". The
measurement exists (`threshold_transfer_tt1_posthoc.json`: `development_attack_fraction` 0.00147,
`development_attack_runs` 251, `final_attack_fraction` 0.826) and is in the findings record, but neither the
contamination numbers nor the no-claim sentence appears in the draft.

*Proposed addition (Section 9, two bullets):* "Post-hoc, 0.15% of HyGrid-ICS's label-blind development rows
(251 short runs) carry an attack label, against 83% of its final rows; the calibration is therefore very
slightly contaminated." and "No claim of runtime authority, deployment safety or incident prevention follows
from these results."

---

## 3. Citations

Authors, title, venue and year were checked for every entry. DOIs and arXiv identifiers below are the ones
I confirmed against publisher or preprint records in this review; where I could not confirm one, the row
says so rather than guessing.

| Reference | Authors / title / venue / year | DOI or arXiv | Supports the citing sentence? |
|---|---|---|---|
| Ahmed et al., WADI, CySWATER 2017 | consistent with the published record | DOI not confirmed in this review | yes - cited only as the WADI dataset |
| Chan-Tin et al., frog-boiling, SecureComm 2009 | consistent | DOI not confirmed in this review | yes - the paper is about staying inside the rejection threshold while the system drifts |
| Erba et al., Constrained concealment attacks, ACSAC 2020 | confirmed: ACSAC '20, pp. 480-495 | 10.1145/3427228.3427660; arXiv:1907.07487 | partly - see C1 |
| Gibbs and Candes, Adaptive conformal inference, NeurIPS 2021 | consistent | arXiv:2106.00170 (NeurIPS 34); DOI not applicable | yes - ACI does raise the level after an exceedance and lower it otherwise |
| Goh et al., SWaT, CRITIS 2016 | consistent | DOI not confirmed in this review | yes - cited only as the SWaT dataset |
| Hong, The boiling frog threshold, arXiv:2603.08455, 2026 | confirmed: title and identifier match the arXiv record (submitted 9 March 2026) | arXiv:2603.08455 | yes - simulation study of gradual observation drift against world-model monitors with fixed detector families |
| Hosking and Wallis, Technometrics 29(3), 1987 | consistent | DOI not confirmed in this review | yes - the standard reference for moment-based GPD estimation |
| Hundman et al., Telemanom, KDD 2018 | confirmed: KDD '18, pp. 387-395 | 10.1145/3219819.3219845; arXiv:1802.04431 | yes - nonparametric dynamic thresholding on a trailing window of smoothed errors |
| ISA, ANSI/ISA-18.2-2016 **[VERIFY]** | confirmed: ANSI/ISA-18.2-2016, *Management of Alarm Systems for the Process Industries*, ANSI-approved 2016 | no DOI; ISA/ANSI standard | partly - see C2 |
| Kloft and Laskov, AISTATS 2010 | confirmed: PMLR vol. 9, pp. 405-412 | no DOI (PMLR) | yes - poisoning of online centroid anomaly detection |
| Kravchik and Shabtai, arXiv:2002.02741, 2020 | consistent | arXiv:2002.02741 | yes - online-retrained autoencoder detectors on SWaT resisted their poisoning |
| Rubinstein et al., ANTIDOTE, IMC 2009 | confirmed: IMC '09, pp. 1-14; the draft's eight-author list matches | DOI not confirmed in this review | yes - boiling-frog poisoning of a PCA-based detector |
| Shin et al., HAI 1.0, CSET 2020 | consistent | no DOI (USENIX); preprint arXiv:2005.02315 | partly - see C3 |
| Siffer et al., SPOT/DSPOT, KDD 2017 | confirmed: KDD '17, pp. 1067-1075 | 10.1145/3097983.3098144 | yes - SPOT and DSPOT as described |
| Taormina et al., BATADAL, JWRPM 144(8), 2018 | confirmed: 144(8), article 04018048 | 10.1061/(ASCE)WR.1943-5452.0000969 | yes - the dataset and its attack design |
| Brockmann et al., voraus-AD, IEEE T-RO 2024 | confirmed: IEEE T-RO vol. 40, pp. 438-451, 2024 | 10.1109/TRO.2023.3332224; arXiv:2311.04765 | yes - and the paper's own unit is "samples", supporting M3-M4 |
| HyGrid-ICS v1.1.1, Zenodo 2026, doi:10.5281/zenodo.23250890 | **could not confirm** - see C4 | the dataset's companion repository advertises 10.5281/zenodo.23250468 | yes for the dataset description (~433,568 samples at ~5 Hz over ~24 h, which matches the access log) |
| Wu and Keogh, IEEE TKDE, 2021 **[VERIFY]** | **year needs fixing** - see C5 | 10.1109/TKDE.2021.3112126 | yes - benchmark pitfalls |

**C1. Section 7.6, the BATADAL re-simulation.** Draft: "the C-Town network of BATADAL [Taormina et al.
2018], re-simulated without the original concealment [Erba et al. 2020]". Erba et al.'s ACSAC paper *adds*
concealment to attacks; what the draft actually used is the no-concealment re-simulation published in that
work's artifact repository, which is what the pack's own access log records
(`threshold_transfer_tt1b_data_access.json`: "github.com/scy-phy/ICS-Evasion-Attacks at commit 56ce090...,
Data/BATADAL (the C-Town network re-simulated without concealment by Erba et al., ACSAC 2020)"). The
original concealment is Taormina et al.'s, not Erba et al.'s.

*Proposed replacement:* "the C-Town network of BATADAL [Taormina et al. 2018], whose original attacks
conceal themselves in the SCADA readings, re-simulated without that concealment in the artifact repository
of Erba et al. [2020] (commit 56ce090), put on a 15-minute grid."

**C2. Section 2, ISA-18.2.** Draft: "Alarm-management practice in process plants [ISA-18.2] treats nuisance
alarms as an operational hazard because operators learn to ignore them." The standard defines and manages
nuisance alarms and sets performance metrics for alarm rates; the causal clause ("because operators learn
to ignore them") is the authors' reading rather than a statement of the standard.

*Proposed replacement:* "Alarm-management practice in process plants treats nuisance and chattering alarms
as a condition to be eliminated, with explicit rate targets [ANSI/ISA-18.2-2016, clauses on alarm
performance and nuisance-alarm handling]; operators who acknowledge such alarms without investigating are
the failure mode this exploits."

**C3. Section 2, the HAI citation covers one release.** Draft: "the HAI releases [Shin et al. 2020]". The
CSET 2020 paper documents HAI 1.0, i.e. the 20.07 release; 21.03, 22.04 and 23.05 came later and are not
described there, and the pack's access log cites the dataset repository for them
(`threshold_transfer_tt1_data_access.json`: "github.com/icsdataset/hai at pinned commit 2a814ce...").

*Proposed replacement:* "the HAI releases [Shin et al. 2020 for HAI 1.0 / 20.07; later releases documented
in the dataset repository]".

**C4. The HyGrid-ICS DOI needs confirming before submission.** The draft and the access log both use
10.5281/zenodo.23250890 (v1.1.1); the dataset's companion repository advertises 10.5281/zenodo.23250468. One
is plausibly the concept record and the other a version record, but I could not resolve 23250890 directly,
and the entry also has no creators, which a dataset citation needs.

*Proposed replacement:* "Yolcu, F. et al. HyGrid-ICS: a hybrid cyber-physical security dataset for
SCADA-based industrial control systems, v1.1.1. Zenodo, 2026. doi:10.5281/zenodo.23250468 (concept),
doi:10.5281/zenodo.23250890 (v1.1.1) - confirm both records and the creator list against the Zenodo page."

**C5. Wu and Keogh year.** Early access was 2021; the article of record is IEEE TKDE 35(3):2421-2429, 2023.

*Proposed replacement:* "Wu, R., Keogh, E. Current time series anomaly detection benchmarks are flawed and
are creating the illusion of progress. IEEE TKDE 35(3):2421-2429, 2023. doi:10.1109/TKDE.2021.3112126."

No reference in the list is missing from the text, and no citation in the text lacks a reference entry. I
found no claim about prior work that the cited paper contradicts; C1 to C3 are attribution and scope
problems, not false claims.

---

## 4. Claims against the limitations in the findings record

All six caveats named in `manuscript/threshold_transfer_tt1_findings.md` appear in the draft. Two appear
only in the body and are contradicted or weakened elsewhere.

| Caveat in the findings | In the draft? | Note |
|---|---|---|
| G1: the adaptive rules were already blind in the controls on HAI 20.07 | yes - Section 6.1, paragraph after the gate table | stated fully and correctly; the abstract and the Section 1 bullet do not carry it (R3) |
| H3 failed on BATADAL | yes - Section 7.6 gate table and the paragraph below it | the consequence for the registered primary rule is missing (R1) |
| SPOT depends on its tail estimator and on heavy tails | yes - Section 9 bullet 4, Sections 7.1 and 7.5 | supported by the record |
| The score-level attacker is an upper bound | yes - Section 3 (A2) and Section 9 bullet 3 | supported |
| The physical attacker is white-box | yes - Section 7.5 ("This attacker is white-box: it can run the monitor") | Section 9 states only "the frog assumes the attacker can read the threshold", which understates it (L1) |
| Spread-scaled parameters are fragile on heavy tails | yes - Section 7.6, final paragraph | contradicted by Section 8 (L2) and absent from Section 9 |

**L1. Section 9 understates the physical attacker's assumption.** Reading the threshold is the weaker half;
the attacker in Section 7.5 also runs the real world model on its own spoofed history to pick each noise
scale.

*Proposed replacement (Section 9 bullet 3):* "The pulse campaigns and both frogs are synthetic. The
score-level frog sets the score directly and reads tau_t; the physically realizable version additionally
runs the monitor itself on the spoofed history to choose each noise scale, so both are white-box upper
bounds."

**L2. Section 8 recommends the static margin as a rule that held, which BATADAL contradicts.** Draft:
"The rules that held were the ones that never loosen themselves: frozen, static margin, and tighten-only
without a permit or with an operator-gated one." On BATADAL the static margin caught 3 of 14 attacks
(`threshold_transfer_tt1b_result_batadal.json` `scores.D1.real_events.rules.margin.detected` = 3;
`paired.margin_vs_frozen.recall_difference` = -0.7857, interval [-1.0, -0.5714]) because its spread-scaled
offset sat 173 times above tau_0 - the single largest recall loss anywhere in the pack. It also lost 12
points on voraus-AD. Section 7.6 says this; Section 8 then recommends it, and Section 9 does not list the
fragility at all.

*Proposed replacement (Section 8, paragraph 1, last sentence):* "The rules that held were the ones that
never loosen themselves: frozen, and tighten-only without a permit or with an operator-gated one. A static
margin never loosens either, but it is not safe by construction: on BATADAL its spread-scaled offset sat
173 times above tau_0 and it caught 3 of 14 attacks, the largest recall loss we measured."

*Proposed addition (Section 9, new bullet):* "Parameters scaled by a calibration spread (the static margin
and the tracker step) are fragile on heavy-tailed scores: on BATADAL the margin sat 173 times above tau_0
and lost 11 of 14 events."

*Proposed replacement (Section 8, final paragraph):* "A static margin can cut that cost on some plants
(HAI 23.05 development: 0.58 times the budget against 4.05 for frozen) but costs recall on others
(voraus-AD: 12 points; BATADAL: 11 of 14 events), and should not be used where the calibration spread is
set by a heavy tail."

One further caveat in the findings has no counterpart in the draft: SWaT and WADI are registered under tt1b
but pending (`threshold_transfer_tt1b_verification.json` `pending_datasets` = ["swat", "wadi"]), and the
registration states that "the paper's replication claim is the set of per-dataset outcomes". A reader
cannot tell from the draft that two more datasets are already registered under the same protocol.

*Proposed addition (Section 7.6, after the gate table):* "SWaT and WADI are registered under the same
protocol and were requested on 2026-10-23; they will run once their loaders are added by amendment, and the
replication claim is the set of per-dataset outcomes."

---

## 5. Internal consistency

**I1. "Eleven threshold rules" against the Section 4 rule list.** The abstract and contribution 1 say
eleven; the Section 4 paragraph enumerates frozen, margin, daily, tracker, tracker_slow, tighten-only with
four automatic permits and an oracle permit (eleven so far), and then adds SPOT and DSPOT with two tail
fits, which would make fourteen. Same fix as R2.

**I2. Section 7.4 row 1 shows controls for DSPOT but not for the exceedance learners.** The row gives
"23/30 (control 25/30)" for DSPOT while leaving daily, tracker and tracker_slow bare, although their
controls are the point of the comparison: 21/30, 23/30 and 25/30 respectively
(`threshold_transfer_tt1b_attacks_dev_v1.json` `releases.*.E4.rules.*.terminal_control`). Row 2 of the same
table does give them.

*Proposed replacement (row 1):* "| 12 x 120 s supra-threshold pulses per day | 30/30 (control 30/30) | 4/30
(control 21/30) | 1/30 (control 23/30) | 3/30 (control 25/30) | 29/30 (control 30/30) | 23/30 (control
25/30) |".

**I3. "This cost the tracker 16 of 38 attacks" invites a wrong reading.** Section 1 bullet 1. The tracker
missed 18 of 38; 16 is the number of events the frozen threshold caught and the tracker did not (36 - 20).

*Proposed replacement:* "On fresh HAI 20.07 data the tracker missed 18 of 38 attacks, 16 of them attacks the
frozen threshold caught."

**I4. The two "spread permit" counts in the pack differ and the draft does not say which round it quotes.**
Section 5 item 1 gives 3 of 30, which is round r3 (`threshold_transfer_dev_v2.json`); the later round r4
(`threshold_transfer_dev_v3.json`) gives 5 of 30 for the same rule and campaign.

*Proposed replacement:* "(spread permit: 3 of 30 terminal attacks caught in development round r3, 5 of 30
in r4)".

**I5. Section 6.3's "bought them with the recall losses" has one counterexample in its own table.** On
HyGrid-ICS the margin raised 0.0 false alarms per day against frozen's 19.2 with identical recall
(interval [0, 0]). The sentence says "Where an adaptive rule raised fewer false alarms than frozen...",
and the margin is static, so the claim is defensible as written, but the table sits directly above it and
invites the objection.

*Proposed replacement:* "Where an *adaptive* rule raised fewer false alarms than frozen, it bought them
with the recall losses of Section 6.2; the one rule that cut false alarms for free, the static margin on
HyGrid-ICS (0.0 against 19.2 per day at identical recall), does not adapt at all."

**I6. Day counts for HAI 20.07 shift between sections without explanation.** Section 4 gives the final data
as "5.15 days" (`real_events.total_days` = 5.1458), G3 reports 2.23 false-alarm episodes per day computed on
unlabelled time only (`real_events.normal_days` = 4.9430), the Section 6.1 caveat refers to a "3.4-day
test1 stream" (the findings' wording; `injection_stream_days` = 3.375), and Section 8 counts "four HAI test
periods". Each number is right on its own basis; nothing in the draft says the false-alarm denominator is
the 4.94 unlabelled days rather than the 5.15 total.

*Proposed addition (Section 6.1, G3 row or a footnote):* "false-alarm episodes per day are counted over the
4.94 days of unlabelled time inside the 5.15-day test streams."

I found no table that disagrees with its own text on a value, and no event or dataset count that changes
between mentions: 38 attacks on HAI 20.07, 91 on HyGrid-ICS, 755 anomalous voraus-AD samples, 14 on
BATADAL, 50/58/52 on the development releases, and 36/38, 20/38, 18/38, 27/38 detections are identical
everywhere they appear, and they match `detected` and `events` in the result files and the `recall` column
of `figure_data/recall_and_false_alarms_by_rule.csv`. The threshold-trajectory traces reproduce the
registered thresholds exactly (`figure_data/trajectory_consistency.json`: relative difference 0.0 for both
HAI 20.07 and BATADAL) and the event counts quoted in the pack README agree with the result files
(MLE SPOT 35/38 = recall 0.9211; DSPOT 36/38 = 0.9474).

Two further notes, outside the five checks. The draft still carries the author block and ORCID and refers
to "our earlier registered studies" (Section 4); both venues are double-blind, so these and the repository
references need removing at submission. And Section 4's claim that the harness "computes the registered
gates itself" is confirmed by the verifier for both studies (`threshold_transfer_tt1_verification.json`
check 8 and `threshold_transfer_tt1b_verification.json` check 8: "stored gates equal gates recomputed from
the result").

---

## 6. Count

| Verdict | Count |
|---|---|
| Match (exact or correctly rounded) | 126 |
| Mismatch | 9 |
| Untraceable | 3 |
| **Total numeric claims traced** | **138** |

The nine mismatches are M1-M9 in Section 1.1; the three untraceable numbers are U1-U3 in Section 1.2. Six
of the nine mismatches are unit or scope labels rather than wrong arithmetic (M1-M4, M6, M9); three are
wrong as printed (M5's "held the budget", M7's "as control" for the fixed-level tracker, M8's 9/9
denominator). Of the three untraceable numbers, one (U1, the light-tailed synthetic SPOT run) supports a
load-bearing claim and needs a file or a rewrite; the other two are a maximum reported where only medians
exist (U2) and an unrecorded duration (U3).
