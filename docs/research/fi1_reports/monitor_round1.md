# fi1 workstream A, round 1: the monitor

Plan: `docs/research/ferrumos_improvement_fi1_plan.md`. Everything here is exploratory: every dataset is spent and
was reread through the registered loaders with ledger reasons that start with `EXPLORATORY fi1`. No registered
result is recomputed or replaced. All numbers are in `docs/research/fi1_monitor_round1.json`.

## Selection rule (written 2026-11-12, after the HAI 21.03, HAI 22.04 and Tennessee Eastman mode 0 results, before modes 1-3)

A candidate survives selection when, on the selection set (HAI 21.03, HAI 22.04, Tennessee Eastman modes 0-3,
three datasets, each weighted equally):

1. mean onset recall is at least 0.02 above the baseline's;
2. mean share of unlabelled time in alarm is not above the baseline's;
3. no selection dataset loses more than 0.05 of onset recall;
4. false alarms on the sealed attack-free Tennessee Eastman runs stay below 1.5 times the budget.

At most three survivors, ranked by mean onset recall, go to the check set, once each. Candidates seen when the rule
was written: d1 (baseline), mad, tail, max, second, stable, loro, h1, h5, clip, and '+'-combinations of them.
The rule was committed in 8803aa6; the outcome below in f6bec59, before any candidate ran on a check dataset.

## Method

- **Residual cache** (`scripts/fi1_monitor_extract.py`). Per unit (a dataset, or one Tennessee Eastman mode) the
  registered monitor is refitted with the registered code (`tt1_final.fit_monitor` on the registered split of the
  registered normal data), and the H1 and H5 world-model residuals of every stream are cached with the scaled
  sensors and actions, labels, events and validity masks. The registered D1 score is exactly
  top3(|R1| / sig1) + top3(|R5| / sig5), smoothed; every candidate is computed from the same cache, so baseline
  and candidates share one world model.
- **Thread settings.** OMP, OpenBLAS and MKL capped at 2 threads; LightGBM `n_jobs` forced to 2 (the registered
  core asks for 4). Under these settings refits are deterministic: refits of BATADAL, HAI 21.03 and HAI 22.04 gave
  bit-identical residual scales, and the ridge refitted without trees equals the ridge inside the full monitor (TEP
  mode 1, both horizons). Thresholds move with the BLAS thread count (up to 0.4 % on BATADAL between settings), the
  same effect found elsewhere in the repository today (the physical-JEPA evidence reproduces bit for bit only with
  24 BLAS threads).
- **Benchmark** (`scripts/fi1_monitor_benchmark.py`). Calibration by `real_telemetry_detect_v2.calibrate` on the
  registered calibration split to the episode budget of each study (HAI and HyGrid 2 per day; BATADAL 1 per week;
  Tennessee Eastman and ProvICS 2 per day; voraus-AD the registered 5 % per-sample quantile). Smoothing as
  registered (60 steps at 1 Hz, 4 on BATADAL, 17 on TEP, 30 on ProvICS, 10 samples on voraus-AD). ProvICS uses the
  audit's extended validity mask (`tt1d_data_v2.provics_valid_v2`) and amendment 1 of tt1d. Metrics per dataset,
  events pooled over units: onset recall (an alarm episode, merged across the gap, starts inside the event),
  any-alarm recall, circular-shift chance references for both (200 shifts per stream, seed 7), share of unlabelled
  time in alarm, false-alarm episodes per unlabelled day and their ratio to the budget, step-level average
  precision of score / tau, median seconds to the first alarm. Added before the check run (commit 2a16175, at the
  coordinator's request, when no check result existed): onset recall net of its chance reference, alarm episodes
  per unlabelled day and per labelled day, and the median episode length. voraus-AD is episodic: an event is an
  anomalous sample; onset = any-alarm = the sample alarms; the alarm share is the false-positive rate of normal
  samples.

## Reproduction check

| What | Harness | Registered | Source |
|---|---|---|---|
| TEP, registered D1 scores (tt1f cache) through the harness metrics | first 116/141, followers 104/104 (onset 44), all 220/245 (onset 160), FA 1.552 x budget, share 0.01689, sealed FA 0.984 x | identical | `threshold_transfer_tt1d_result_tep59.json` |
| TEP modes 0-3, refitted monitor | any 141/153, onset 103; tau0 9.6643 / 9.6329 / 10.1445 / 9.5213 | 141/153, onset 103; tau0 9.6636 / 9.6329 / 10.1468 / 9.5213 | same, per unit |
| HAI 21.03, refitted | 50/50, onset 49, share 0.0076, 0.66 FA/day | 50/50, onset 49, 0.0076, 0.659 | `threshold_transfer_tt1c_dev_v1.json` (exploratory, registered pipeline) |
| HAI 22.04, refitted | 44/58, onset 44, share 0.0027, 1.48 FA/day | 44/58, onset 44, 0.0027, 1.485 | same |
| BATADAL, refitted | 14/14, onset 14, share 0.0138, FA 0.73 x; tau0 9.354 | 14/14, onset 14, 0.0137, 0.70 x; tau0 9.393 | `threshold_transfer_tt1b_result_batadal.json` |
| other check units | see "Check set" | | |

The metric code reproduces the registered record exactly. Refitted monitors reproduce every registered count
checked so far; thresholds differ by 0.0-0.4 % because of the thread settings (the corrected calibration returned
the same threshold as the frozen one on every unit, as the audit's K1 check found).

Disclosure: before the check ledger existed, the baseline was run once on BATADAL (04:11) as the first test of the
harness; that is the BATADAL row above. No candidate touched a check dataset before the check run.

## Diagnosis (selection set and attack-free data; `target/real-telemetry/fi1/monitor/diagnosis.json`)

Units diagnosed: HAI 21.03, HAI 22.04, TEP modes 2 and 3.

| | HAI 21.03 | HAI 22.04 | TEP m2 | TEP m3 |
|---|---|---|---|---|
| unlabelled alarm share (baseline) | 0.0076 | 0.0027 | 0.0086 | 0.0333 |
| unlabelled alarm steps involving the top-5 channels | 85 % | 82 % | 96 % | 99 % |
| alarm share after dropping those 5 (recalibrated) | 0.0068 | 0.0031 | 0.0032 | 0.0223 |
| onset recall after dropping them (baseline) | 0.94 (0.98) | 0.79 (0.76) | 0.52 (0.62) | 0.69 (0.74) |
| max channel residual spread, unlabelled test time / normal scale | 3.4 | 2.4 | 16.8 | 14.2 |
| channels above 2x on unlabelled test time | 5 of 36 | 2 of 38 | 4 of 41 | 8 of 41 |
| max channel spread ratio, attack-free recordings / scale split | 1.04 | 1.62 | 1.08 | 1.09 |
| per-recording calibrated threshold, max / min | 1.12 | 1.13 | 1.08 | 1.10 |
| unlabelled alarm steps with a sensor outside the fit range (quiet steps) | 24 % (0.6 %) | 0 % (0 %) | n/a | n/a |
| alarm share, smoothing window x0.5 / x2 / x4 | 0.0043 / 0.0144 / 0.0293 | 0.0009 / 0.0108 / 0.0306 | 0.0051 / 0.0133 / 0.0185 | 0.0212 / 0.0441 / 0.0499 |

In five lines:

1. Calibration carries over between attack-free recordings of the same dataset (per-recording thresholds within
   8-13 %, channel scales within 1.1x except one channel at 1.6x on HAI 22.04); too little normal data is not the
   cause on these datasets.
2. A few channels make the excess alarm time: the top five appear in 82-99 % of unlabelled alarm steps.
3. On unlabelled test time those channels run far above their normal residual spread (up to 3.4x on HAI, 14-17x on
   TEP after attacks, while the plant is still disturbed), so the score stays above tau0 after an event ends.
4. Operating-regime change explains part of it on HAI 21.03 (a sensor outside the fit range at 24 % of unlabelled
   alarm steps against 0.6 % of quiet ones); clipping the world model's inputs to the fit range removes that but
   also hides attacks that push sensors out of range.
5. Longer smoothing only lengthens alarms (share up 4-11x at four times the window, onset recall not up); max or
   mean combination is no better than top-3.

The selection set does not saturate (alarm share 0.3-3.3 %). The 39 % (HAI 20.07) and 44 % (ProvICS) of the papers
are on check datasets, which were not diagnosed before the check run, so as not to choose on them.

## Candidates (`scripts/fi1_monitor_v3.py`), all static and fitted on attack-free data only

| name | rule |
|---|---|
| d1 | registered D1 (baseline) |
| mad | per-channel centre and scale = median and 1.4826 MAD of the residual-scale split |
| tail | per-channel scale = 99.9th percentile of the absolute residual / 3.29 |
| max | largest standardised residual instead of the top-3 mean |
| second | mean of the 2nd-4th largest standardised residuals: one channel alone cannot alarm |
| stable | drop channels whose residual scale varies more than 2x across attack-free recordings |
| loro | threshold = the largest of the pooled and the per-recording calibrated thresholds |
| h1, h5 | one horizon only |
| clip | world model with sensor-level inputs clipped to the fit range; computed exactly from the cache (ridge correction; trees route out-of-range values like the range edge; tested against a refitted clipped forecaster) |

`a+b` combines them (e.g. `mad+second`: MAD scales, ranks 2-4).

## Selection (`python scripts/fi1_monitor_benchmark.py select mad tail max second stable loro h1 h5 clip mad+second clip+second clip+mad+second second+loro`)

Onset detected / events (unlabelled alarm share):

| monitor | HAI 21.03 | HAI 22.04 | TEP 0-3 | mean onset recall | mean share | TEP sealed FA / budget | outcome |
|---|---|---|---|---|---|---|---|
| d1 | 49/50 (0.0076) | 44/58 (0.0027) | 103/153 (0.0186) | 0.804 | 0.0096 | 1.02 | baseline |
| mad+second | 47/50 (0.0068) | 45/58 (0.0028) | 128/153 (0.0043) | 0.851 | 0.0046 | 0.97 | survives |
| second | 47/50 (0.0078) | 45/58 (0.0027) | 127/153 (0.0160) | 0.849 | 0.0088 | 0.95 | survives |
| second+loro | 47/50 (0.0076) | 45/58 (0.0027) | 122/153 (0.0155) | 0.838 | 0.0086 | 0.66 | survives |
| mad | 47/50 (0.0072) | 39/58 (0.0021) | 127/153 (0.0036) | 0.814 | 0.0043 | 0.89 | out: gain < 0.02; HAI 22.04 -0.086 |
| stable | 49/50 (0.0076) | 45/58 (0.0046) | 103/153 (0.0186) | 0.810 | 0.0103 | 1.02 | out: gain < 0.02; share up |
| max | 49/50 (0.0075) | 46/58 (0.0031) | 90/153 (0.0197) | 0.787 | 0.0101 | 0.97 | out: TEP -0.085; share up |
| h5 | 47/50 (0.0080) | 46/58 (0.0030) | 95/153 (0.0176) | 0.785 | 0.0096 | 0.95 | out: TEP -0.052 |
| loro | 49/50 (0.0075) | 44/58 (0.0027) | 93/153 (0.0181) | 0.782 | 0.0094 | 0.72 | out: TEP -0.065 (higher threshold) |
| clip+mad+second | 47/50 (0.0070) | 33/58 (0.0017) | 128/153 (0.0026) | 0.782 | 0.0037 | 0.97 | out: HAI 22.04 -0.190 |
| clip+second | 47/50 (0.0079) | 33/58 (0.0017) | 126/153 (0.0119) | 0.777 | 0.0072 | 0.92 | out: HAI 22.04 -0.190 |
| clip | 49/50 (0.0077) | 36/58 (0.0018) | 103/153 (0.0151) | 0.758 | 0.0082 | 0.98 | out: HAI 22.04 -0.138 |
| tail | 46/50 (0.0079) | 42/58 (0.0035) | 88/153 (0.0349) | 0.740 | 0.0154 | 0.93 | out: all three |
| h1 | 43/50 (0.0067) | 30/58 (0.0039) | 105/153 (0.0191) | 0.688 | 0.0099 | 1.02 | out: all three |

Where the selection gain comes from: every survivor gains only on Tennessee Eastman, and only on follower events
(onset 25/63 for d1; 55, 52 and 52 of 63 for the survivors). On TEP first events they lose (onset 78/90 for d1;
73, 75 and 70). On HAI 21.03 they lose 2 onsets; on HAI 22.04 they gain 1. The TEP onset count against its chance
reference: d1 103 against 60.6 [52, 70]; mad+second 128 against 72.0 [61, 85]; second 127 against 72.2 [61, 84];
second+loro 122 against 63.2 [52, 75]. Net of chance, TEP onset recall rises from 0.277 to 0.366 / 0.358 / 0.384,
about half the raw gain: shorter alarms also make chance onsets more likely.

## Check set (run once, 2026-11-12 08:23-08:25 UTC; `python scripts/fi1_monitor_benchmark.py check mad+second second second+loro`)

All eight check units were extracted (no failure; voraus-AD took 56 minutes). Check ledger:
`target/real-telemetry/fi1/monitor/check_ledger.jsonl`, one row per monitor. Nothing was changed after the run.

### Reproduction on the check units (baseline d1, refitted)

| dataset | harness | registered |
|---|---|---|
| HAI 20.07 | any 36/38, onset 26, share 0.3910, 2.23 FA/day; tau0 17.2595 | 36/38, onset 26, 0.3910, 2.23; tau0 17.2588 |
| HAI 23.05 | 31/52, onset 31, share 0.0071, 1.27 FA/day | 31/52, onset 31, 0.0071, 1.27 (tt1c, exploratory) |
| HyGrid-ICS | 27/91, onset 3, share 0.0407, 19.20 FA/day | 27/91, onset 3, 0.0407, 19.20 |
| ProvICS (extended mask) | 23/32, onset 3, share 0.4399, FA 33.71 x, sealed 0.92 x | 23/32, onset 3, 0.4399, 33.71 x, sealed 0.92 x |
| TEP modes 4-6 | any 79/92, onset 57, share 0.0136; sealed FA 0.93 x | 79/92, onset 57, 0.0136 (registered units mode_4..6) |
| voraus-AD | 243/755 anomalous samples, FPR 0.0811; tau0 9.798 | 252/755, FPR 0.0811; tau0 9.776 |

Every count reproduces except voraus-AD (243 instead of 252 detected samples at the same false-positive rate). Its
threshold is 0.2 % higher because of the thread settings; with 755 per-sample maxima close together, 9 samples sit
between the two thresholds.

### Before and after

Onset detected / events, onset recall net of its circular-shift chance reference in brackets, then the share of
unlabelled time in alarm. voraus-AD: detected anomalous samples, and the false-positive rate of normal samples as
its alarm share (no chance reference for samples).

| dataset | d1 (baseline) | mad+second | second | second+loro |
|---|---|---|---|---|
| HAI 20.07 | 26/38 (+0.645), 0.3910 | 26/38 (+0.643), 0.3910 | 26/38 (+0.645), 0.3908 | 26/38 (+0.647), 0.3906 |
| HAI 23.05 | 31/52 (+0.568), 0.0071 | 30/52 (+0.548), 0.0066 | 31/52 (+0.567), 0.0067 | 31/52 (+0.567), 0.0067 |
| BATADAL | 14/14 (+0.661), 0.0138 | 14/14 (+0.523), 0.0127 | 14/14 (+0.614), 0.0101 | 14/14 (+0.622), 0.0100 |
| HyGrid-ICS | 3/91 (-0.021), 0.0407 | 14/91 (+0.018), 0.0368 | 15/91 (+0.021), 0.0067 | 15/91 (+0.021), 0.0067 |
| voraus-AD | 243/755, 0.0811 | 324/755, 0.1480 | 277/755, 0.0979 | 277/755, 0.0979 |
| TEP modes 4-6 | 57/92 (+0.222), 0.0136 | 70/92 (+0.313), 0.0066 | 64/92 (+0.256), 0.0129 | 59/92 (+0.253), 0.0125 |
| ProvICS | 3/32 (-0.038), 0.4399 | 3/32 (-0.053), 0.4224 | 3/32 (-0.041), 0.3889 | 3/32 (-0.041), 0.3889 |
| mean onset recall | 0.478 | 0.528 (+0.050) | 0.514 (+0.036) | 0.507 (+0.028) |
| mean alarm share | 0.1410 | 0.1463 (+0.0053) | 0.1305 (-0.0105) | 0.1305 (-0.0105) |
| largest onset loss on one dataset | | -0.019 (HAI 23.05) | 0 | 0 |

Other columns of the check output (all in the JSON):
- False alarms against the budget went above 1 on BATADAL for mad+second (1.21 x; baseline 0.73 x), and on voraus-AD
  for every monitor (FPR 1.62 x the 5 % target for d1, 2.96 x for mad+second, 1.96 x for second and second+loro).
- On TEP modes 4-6 every survivor loses first events (onset 38/51 for d1; 32, 33 and 29) and gains followers (19/41
  for d1; 38, 31 and 30). Median alarm-episode length on TEP stays at 50-68 s.
- On HyGrid-ICS the onset gain (3 to 14-15 of 91) sits at its chance level (chance 12-13, against 4.9 for d1).

### Verdict (the plan's definition, applied as written)

| candidate | mean onset recall up >= 0.05 | mean alarm share not higher | no dataset loses > 0.05 | improved |
|---|---|---|---|---|
| mad+second | yes (+0.0500) | no (+0.0053, from voraus-AD) | yes | no |
| second | no (+0.036) | yes | yes | no |
| second+loro | no (+0.028) | yes | yes | no |

**Not improved.** No candidate meets the definition on the check set. The alarm share on HAI 20.07 stays at 0.391
for every candidate; on ProvICS it falls from 0.440 to 0.389 (second, second+loro) or 0.422 (mad+second). Onset
recall on both is unchanged. Where onset recall rose (TEP, HyGrid-ICS, voraus-AD), half or more of the rise is the
higher chance level of shorter alarms, and on TEP it is bought with first-event detections.

## Post-check description of the two saturating recordings (not used to choose anything)

`python scripts/fi1_monitor_diagnose.py hai-20.07 provics`, run after the check; no candidate was changed or rerun.
Running it exposed a bug in `labels_and_events` for ProvICS development segments (they carry no validity mask); the
check run never passes those segments through it, so no check number is affected. Fixed in the final commit.

- **HAI 20.07.** 94 % of unlabelled alarm steps have a sensor outside the world-model fit range (6.7 % of quiet
  steps). On unlabelled test time 18 of 31 channels run above twice their normal residual spread (median 2.3x, max
  38x), and several carry a constant offset (mean residual up to 27 normal scales). The attack-free training
  recordings already disagree: one runs at 3.3x on some channel, and thresholds calibrated on each recording alone
  span a factor 2.2. Dropping the five busiest channels (chosen on the test alarms, so an oracle, not a candidate)
  would cut the share from 0.39 to 0.11 and raise onsets from 26 to 34 of 38.
- **ProvICS.** The attack-free recordings agree (thresholds within 1 %), but on the attack recording every one of
  the 13 channels has a residual spread above twice normal (median 14x, max 90x). The unlabelled time of the attack
  recording is not in the regime of the benign recording; no static recombination of the residuals brings its alarm
  share down far.

## What to try next

1. A regime check in front of the residual score: time when sensors leave the fit range (94 % of the HAI 20.07
   alarm time) is flagged as "outside the model's competence" with its own budget, instead of as an attack alarm.
   The clipped model (`clip`, exact and cheap) could score inside that state.
2. Normal data that covers the test regime for HAI 20.07: its own training recordings already differ by a factor 2.2
   in calibrated threshold.
3. Keep the ranks 2-4 combination (`second`) only as a second score for follower attacks on TEP, not as a
   replacement: it trades first events for followers.
4. In later rounds, count onset gains net of chance and report first and follower events separately.

## Commands

    python scripts/fi1_monitor_extract.py <unit>                 # residual cache (units: fi1_monitor_extract.UNITS)
    python scripts/fi1_monitor_extract.py coefs batadal hai-22.04 hai-21.03
    python scripts/fi1_monitor_extract.py tep-add-sensors tep-m0
    python scripts/fi1_monitor_benchmark.py tep-cache             # metric code against the registered TEP record
    python scripts/fi1_monitor_benchmark.py registered
    python scripts/fi1_monitor_diagnose.py hai-21.03 hai-22.04 tep-m2 tep-m3
    python scripts/fi1_monitor_benchmark.py select mad tail max second stable loro h1 h5 clip mad+second clip+second clip+mad+second second+loro
    python scripts/fi1_monitor_benchmark.py check mad+second second second+loro
    python scripts/fi1_monitor_diagnose.py hai-20.07 provics      # post-check, descriptive
    python scripts/fi1_monitor_collect.py                         # docs/research/fi1_monitor_round1.json
    python -m pytest -q scripts/test_fi1_monitor_v3.py            # 11 tests

Process notes: the first TEP mode 1 extraction ran out of memory while fitting (LightGBM "bad allocation" at 0.8 GB
free) and was redone; the session restarted once, and the cut-off HAI 20.07 cache was deleted and rebuilt.
