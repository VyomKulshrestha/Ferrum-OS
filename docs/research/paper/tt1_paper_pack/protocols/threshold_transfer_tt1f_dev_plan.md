# tt1f development plan: matched operating points, BATADAL under the stronger rules, SPOT under the frog, process-level campaigns

Status: **exploratory and post-hoc**. Every dataset used here is spent; nothing in this plan is registered,
and no result of it can change a registered outcome. Written on 2026-11-10 after the second mock review of
the paper (`docs/research/paper/tt1_paper_pack/review/mock_pc_review_r2.md`) and committed before any run.
Every access to recorded attack data or to sealed runs is written to the ledger with a reason that starts
with `EXPLORATORY`.

## A. Matched operating points on Tennessee Eastman (`scripts/tt1f_tep_dev.py`)

Question: do the rules that kept every follower attack (tighten-only, the excluding recalibration, the
capped tracker, the tracker under a ceiling) detect more than a frozen threshold set lower, at the same
false-alarm rate?

- `scores`: refit each mode's monitor with the registered code (`tt1d_final.fit_scores`, same development
  runs) and write the D1 score of every sealed attack-free run and every attack run to
  `target/real-telemetry/tt1f/` (second access to both, ledgered).
- `analyse`: for each target rule R in {tracker, tracker_ceil_1.25, daily_excl, tighten_only,
  tracker_capped}, find one multiplier c, applied to every mode's tau0, at which the static threshold
  c tau0 raises the number of false-alarm episodes on the 56 sealed runs closest to R's registered number
  (episodes merged across 17 steps, as registered; grid of c from 0.50 to 1.50 in steps of 0.001; ties go to
  the larger c). The match is in-sample on the sealed runs, so the comparison is descriptive.
- Report for each matched static threshold, on the attack runs: first events and followers detected under
  both counts, false-alarm episodes over the budget on unlabelled time, and the paired difference against
  R and against the frozen threshold (bootstrap over runs, 10,000 resamples, R's per-event outcomes taken
  from the registered result file).
- No expectation is stated. If a matched static threshold detects at least as many events as R, R's extra
  detections are an operating-point effect and the paper will say so.

## B. One Tennessee Eastman trace

For a figure: score, tau0, tracker and events of one noise-attack run. The run is fixed here, before any
score is looked at: the type-24 run of mode 0 with the lowest id.

## C. SPOT under the frog on the sealed placements

The 56 registered placements (same seeds), 24 h frog at 0.97 of the deployed threshold, for the registered
standard SPOT (`spot_gr`) and two variants that were exploratory on HAI and not registered: shape bounded
to |xi| <= 0.5 (`spot_gr_bounded`) and runs declustering (`spot_gr_declust`). Recorded per placement: the
fitted shape xi and scale sigma, the number of peaks and the threshold over tau0 at the end of the
campaign and at the same step without it, and the terminal bumps caught at the four registered magnitudes.

## D. BATADAL from the stored trace (`scripts/tt1f_batadal_trace.py`)

`figure_data/threshold_trajectories.csv` holds the 15-minute D1 score and the attack labels of both test
files, so no new access to the dataset is needed. The registered tracker's step there is 6.9 tau0 per
sample; the question is whether its loss survives a step in tau0 units and the stronger rules.

- Durations are scaled as tt1b scaled them (60 s on HAI is 1 h on BATADAL): event length 4 steps, episode
  gap 4 steps, hold-off 240 steps, capped rise 0.1 tau0 per day of 96 steps. Thresholds and rates are the
  registered ones (`threshold_transfer_tt1b_result_batadal.json`, `scores.D1.thresholds`).
- Each test file starts from a fresh rule state. Checks: frozen must give 14 of 14 and the registered
  tracker 6 of 14; otherwise the script stops.
- Rules: tracker with eta = 0.01 tau0, tracker_slow, daily_excl, tracker_hold, tracker_capped, static 1.1
  and 1.25 tau0, the tracker and daily recalibration under ceilings of 1.1 and 1.25 tau0. Standard SPOT is
  left out: it needs the calibration scores, which the trace does not hold.
- Reported: events detected under both counts (of 14), false-alarm episodes over the weekly budget, the
  threshold over tau0 at event onsets.

## E. Process-level campaigns on HAI normal data (`scripts/tt1f_process_dev.py`)

The registered campaigns write the score. Here the attacker writes three sensor readings (the three most
coupled to one setpoint channel, as in the physically realizable frog of tt1b) and the real monitor scores
the result. Normal data of HAI 21.03, 22.04 and 23.05, the deployment segment of the r4 split, 10 placements
per release (seed 7 + 909), 30 in all. The terminal attack is the setpoint step of the earlier campaigns at
1, 1.5, 2 and 3 times the smallest magnitude the frozen threshold detects on the clean stream; the result
tables give that magnitude in the scaled units of the setpoint channel. Control: the same steps without a
campaign.

1. **Frog that reads the threshold** (6 h, as tt1b, now against the standard SPOT): every 300 s the
   attacker reads tau_t and picks, by bisection on the real monitor, the largest noise scale whose score
   stays at or below 0.97 tau_t.
2. **Frog that does not read the threshold** (6 h): the attacker sees only whether an alarm was raised.
   It starts at a noise scale of 0.001, multiplies it by 1.25 after every 300 s block without an alarm and
   halves it after a block with one. Reported with the alarm steps and episodes it spends.
3. **Sub-event pulses through sensors** (24 h, every 30 minutes): 20 s of noise on the three sensors, its
   scale chosen by bisection as the largest for which at most 45 steps of the smoothed score exceed the
   rule's current threshold. Against the excluding recalibration and the hold-off tracker.
4. **Replay concealment** (no campaign): during the terminal step the attacker overwrites the three
   sensors with their clean values. Reported: terminal steps the frozen threshold still detects. This is the
   comparison the paper says it did not make; if replay hides the step, poisoning buys this attacker
   nothing it could not have directly.

Rules: frozen in every campaign; `spot_gr` in 1 and 2; `daily_excl` and `tracker_hold` in 3. A campaign that
is not silent is reported as such.

## Not in this round

- Matched operating points on HAI: the development releases have no attack-free stream that is separate
  from calibration and long enough to match alarm rates on.
- A published detector from the literature and a comparison of `spot_gr` with the reference SPOT code:
  both need code and models this repository does not hold.
- The 53 unread attack-free Tennessee Eastman runs stay unread.

## Amendment 1 (2026-11-10)

Written after part D had run and before any analysis of parts A, B, C and E (only the score cache of part
A was being built). Part D's result is in `threshold_transfer_tt1f_batadal_v1.json` and is not changed by
this amendment: with a step of 0.01 tau0 the tracker detected 14 of 14 BATADAL attacks under both counts,
so the registered loss there (6 of 14) belongs to the spread-scaled step of 6.9 tau0 per sample.

The second mock review (Claude Science, `mock_pc_review_r2_claude_science.md`), finished after this plan
was committed, asks for further analyses of the same data. Added, all exploratory and post-hoc:

- **F. Chance reference for the any-alarm count.** On the Tennessee Eastman attack runs, for frozen,
  tracker, daily, daily_excl, tracker_capped and tighten_only: shift the rule's alarm sequence circularly
  within each run by a random offset (200 shifts per run, seed 7) and recount first events and followers
  detected under both counts, by attack type. Reported: the mean and the central 95 % range of the shifted
  counts beside the observed ones. The same for frozen and tracker on HAI 20.07 and BATADAL, from the stored
  trajectories. No expectation is stated; if an observed count sits inside the shifted range, the paper
  says that the count does not show detection.
- **G. Time to clear.** For each Tennessee Eastman noise sequence and for frozen, tracker, tracker_slow,
  tracker_tau and daily: hours from the start of the sequence to the first alarm, the share of the
  sequence spent in alarm, and hours from the start to the last alarm step inside the sequence.
- **H. A fixed tau0 monitor beside the attacked rule.** In part C's frog runs: the number of campaign
  steps on which the attacker's score exceeds tau0 and the hours until the first one. It says whether the
  frog is silent to anything but the rule it attacks.
- **I. Peak score over tau0** of every recorded event: Tennessee Eastman from the cache, HAI 20.07 and
  BATADAL from the stored trajectories. Reported as quantiles and as the share of events whose peak stays
  below 1.1, 1.25, 1.5 and 2 tau0.
- **J. BATADAL, the tau0-scaled tracker under ceilings** of 1.1 and 1.25 tau0. The ceilings of part D
  used the registered step and ran at 36 to 43 times the budget.
- A per-mode tabulation of the registered campaign outcomes (no run).

Not added: robust-statistic baselines, a recalibration rule and a threshold-watch detector (they need rule
designs of their own and a separate plan).

## Amendment 2 (2026-11-10)

Written after the code audit (`docs/research/monitor_audit_2026-11-10.md`) and before any analysis of parts
A, B, C, E, F, G, H, I and J. The audit found five defects in frozen analysis files and fixed them in `_v2`
modules. Registered numbers stay as they are. Every analysis of this plan keeps the registered code, so
that it can be compared with the registered outcomes. Two checks say whether a defect could have moved a
registered number:

- **K1. Calibration.** For each Tennessee Eastman mode, recompute the D1 threshold from the calibration
  scores (the pooled calibration scores in the cache, split back into the four calibration runs) with the
  registered `calibrate` and with `real_telemetry_detect_v2.calibrate`, which stops at the first budget
  break. Reported: both thresholds per mode and the number of candidate thresholds above the registered one
  that break the budget. The same for the three HAI development releases inside part E, where the
  calibration scores are recomputed anyway.
- **K2. ProvICS validity mask** (`scripts/tt1f_provics_mask.py`, a third, ledgered access to the ProvICS
  attack recording and sealed rows). Refit the monitor with the registered code and amendment 1 of tt1d,
  then score frozen and tracker twice: with the registered validity mask and with `provics_valid_v2`, which
  also invalidates the 36 steps after every recording gap. Reported for both: events detected under both
  counts, false-alarm episodes over the budget, share of unlabelled time in alarm, and the number of gaps.
  The registered ProvICS outcome (no loss, 44 % of unlabelled time in alarm) is not replaced; the paper
  reports how much of the alarm time the corrected mask removes.

Part E keeps the registered calibration and smoothing, for comparison with the earlier development tables.
