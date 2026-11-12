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

## Check set

(filled in after the single check run)
