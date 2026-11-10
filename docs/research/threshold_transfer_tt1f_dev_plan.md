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
