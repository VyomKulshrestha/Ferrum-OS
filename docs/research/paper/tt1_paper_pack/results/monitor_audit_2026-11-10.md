# Monitor and threshold-rule correctness audit, 2026-11-10

Scope: the world-model residual monitor (D1), its calibration, the threshold rules of tt1, tt1b, tt1c, tt1d
and tt1e, and the tt1d / real-telemetry loaders. Every file audited here is frozen by a registered protocol,
so no file was edited. Corrections live in new `*_v2.py` modules that import the frozen module and override
only what is wrong, each with a synthetic regression test that shows the old behaviour and the new one.
No dataset was opened and no registered number was recomputed. Frozen-file digests were checked against
the tt1, tt1b and tt1d protocols after the last commit: all match.

Run all tests from `scripts/`: `python -m pytest -q test_real_telemetry_detect_v2.py test_threshold_online_v2.py test_tt1d_data_v2.py test_threshold_rules_tt1c_v2.py`

## Findings

### 1. `calibrate` can return a threshold far below the first budget break (CONFIRMED mechanism)

`real_telemetry_detect.py:113-124`. The loop visits every candidate from the top and keeps the smallest
one whose false-episode count is within budget. Episode counts are not monotone in the threshold: a low
threshold merges alarms into a few long episodes. Synthetic trigger: three calibration days, the middle one
in a higher regime (level 3 vs 1). The frozen function returns 2.98, with 20% of calibration time above it
(one day-long episode); the version that stops at the first budget break returns 3.38, with 0.002% above.

Fix: `real_telemetry_detect_v2.calibrate` (commit 1857788). Test: `CalibrateTests`.

Effect on reported numbers: tau0 (and p, tau_half, eta, which derive from it) of any score where it
triggers would be too low, so more alarms, higher recall and higher false-alarm rates. The registered D1
calibrations show no sign of it (p between 0.007% and 0.13% on every dataset). The tt1d Tennessee Eastman
D2 (PCA) side score has p = 1.3-2.2% in modes 2, 4 and 5, which fits a non-monotone pick but does not
prove one. Checking it needs the calibration runs, which this audit did not open.

### 2. ProvICS: steps right after a recording gap are scored from forward-filled data but counted as valid (CONFIRMED mechanism)

`tt1d_data.py:190-193` (`_p_grid`), used through `tt1d_final.clean(score, valid)`. Only the grid steps
inside a gap longer than 10 s are invalid. The D1 score at step s reads states back to
s - (w + h + history - 2), which is 36 steps for the ProvICS window of 30. A level change during the gap
therefore shows up as a residual spike on valid steps. Synthetic trigger: a 120 s gap with a 5-unit level
step and a persistence world model. The frozen mask leaves more than 10 alarms, all within 36 steps after
the gap. The v2 mask leaves none and removes exactly 36 steps per gap.

Fix: `tt1d_data_v2.provics_valid_v2(valid, window)` (commit 0051159). Test: `ProvicsGapTests`.

Effect: ProvICS attack-stream false alarms (the frozen rule reports 66 per day) and possibly detections of
events that start right after a gap. The adaptive rules also learn from the spikes. With the fix, false
alarms can only fall. The attack stream has 577 invalid steps; how many gaps they form is unknown here.

### 3. The smoothing head reads later samples and the warm-up zeros (CONFIRMED)

`real_telemetry_core.rolling_mean:144-149` fills its first w - 1 outputs with mean(raw[0:w]). Callers then
blank only the first WARMUP = 10 steps (`threshold_transfer_dev.d1:78-81`, `tt1d_final.fit_scores:151-153`,
`tt1_final.run_episodic.smax:296-297`). As a result, the score at step 10 changes when raw[59] changes
(window 60). The head is also the mean of 60 values of which 10 are the scorer's warm-up zeros.

Fix: `real_telemetry_detect_v2.smooth_after_warmup` (commit d00164c), which is causal, drops the warm-up
first, and matches the frozen output from step WARMUP + w - 1 on. Test: `SmoothingTests`.

Effect: this touches only steps 10 to w - 2 of each scored array (49 steps on HAI, 6 on TEP, 19 on ProvICS)
and the start of every spliced campaign segment. Those head scores are biased low, so v2 can only add alarms
there. No campaign terminal or registered event is expected to fall in a head. Calibration pools shift by
a negligible amount.

### 4. Online `daily` uses the last day's worth of finite scores, not the trailing day (CONFIRMED, no registered number affected)

`threshold_online.py:34-44`. The deque of steps_per_day finite values is never cleared, so after an
invalid stretch the "day" reaches into the previous day. Synthetic trigger: day 2 has 300 invalid steps.
The day-3 threshold differs from `threshold_rules.daily_path` by more than 1.0, because it is built partly
from day 1.

Fix: `threshold_online_v2.Daily` (commit a9a2e9a), which equals `daily_path`. Test: `DailyTests`.

Effect: none on registered results as far as the call sites show. Mid-stream invalid steps occur only on
ProvICS, and both ProvICS streams (37,801 and 23,442 steps) are shorter than one day (43,200 steps), so the
daily rule never recalibrates there. Other streams have -inf only in the warm-up.

### 5. `tracker_hold` episode tracker is off by one against the batch episode definition (CONFIRMED)

`threshold_rules_tt1c.py:40,45` start a new episode when `i - last > GAP`. `threshold_rules._episodes` and
`DailyExcl` merge alarm runs separated by up to GAP quiet steps (`> GAP + 1`), as the tt1c plan specifies.
Synthetic trigger: 40 alarms, exactly 60 quiet steps, then 30 alarms. The batch counter sees one 130-step
event episode. The frozen tracker sees two short episodes, never holds, and ends with a higher threshold.

Fix: `threshold_rules_tt1c_v2._Episodes` / `TrackerHold` (commit e690668). Test: `EpisodeTests`.

Effect: tracker_hold numbers (tt1c, tt1d) change only where two alarm runs are separated by exactly GAP
quiet steps. In that case v2 holds more, so the threshold is lower and recall equal or higher. The
expected size is negligible.

## Confirmed, not fixed

- **`gpd_mle` cold start caps theta at 1000 / mean(y)** (`threshold_rules_tt1c.py:184-185`). In a frog
  campaign the cold fit gives xi = 0.94 with NLL 65,265, against xi = 5.88 and NLL 40,521 from scipy. It is
  not fixed because no reported number reaches it: `SpotGR` fits cold only below 100 peaks or at
  initialisation on calibration data, where theta * mean(y) is about xi / (1 - xi), far below 1000. The
  warm-started refits that follow match scipy (checked: stationary tails, sign changes and the frog). This
  also settles the earlier pass's leads (t_frog.py, t_frog2.py, t_gpd.py): the warm/cold divergence they
  found is the cold fit being wrong, and the warm path the study uses is correct. Cold MLE agrees with
  scipy to 1e-3 NLL for xi in [-0.45, 0.5] and n from 50 to 5000.

## Plausible, not fixed

- **tt1 G2 bootstrap resamples events, not streams** (`tt1_final.paired` -> `real_telemetry_core.paired_event_bootstrap`).
  The 38 HAI 20.07 events share threshold state within a test file, so adaptive-rule misses are serially
  dependent, and an event bootstrap probably makes the reported interval [-0.58, -0.26] too narrow. This is
  the registered design and was not changed. tt1d already resamples by run.

## Areas checked with no defect found

- Residual alignment: R[t+h] = Z[t+h] - the forecast from t, for h = 1 and 5.
- Feature causality: future actions enter as V[t+h], which is known at scoring time.
- WARMUP 10 covers history + horizon (8).
- Scalers are fitted on the fit split only, and residual scales on a separate split. Splits are in time order.
- Tracker sign and rate. Every rule compares against the threshold before updating.
- `daily_path` uses the (1 - p) quantile of the previous day.
- SPOT z_q, the method-of-moments GPD, the genpareto sign convention and the DSPOT residual construction.
- Online and batch paths are identical for tracker, tracker_slow, tighten-only, spot, spot_mle and dspot,
  including warm-up and invalid stretches.
- `DailyExcl` carry-over. `TrackerCapped` cap.
- TEP event extraction and ProvICS event intervals (half-open).
- `cluster_bootstrap` ratio estimator and its seeding. All bootstrap and placement randomness is seeded.
- `play()` reads the threshold before each update. NaN and -inf are mapped to "cannot alarm" consistently.
