# tt1f findings (exploratory and post-hoc), 2026-11-10/11

Plan with two amendments: `threshold_transfer_tt1f_dev_plan.md`. Result files: `threshold_transfer_tt1f_tep_v1.json`,
`threshold_transfer_tt1f_batadal_v1.json`, `threshold_transfer_tt1f_provics_mask_v1.json`,
`threshold_transfer_tt1f_process_v1.json` (part E, when its runs finish). Nothing here is registered and no
registered outcome changes. This file is the digest the paper revision works from; every number below is in
one of the result files or in a registered result file.

## 1. Tennessee Eastman, what the registered follower loss is

Tabulated from the registered per-event records (`threshold_transfer_tt1d_result_tep59.json`):

| Events | n | frozen any / onset | tracker any / onset |
|---|---|---|---|
| type 21 (integrity) first | 34 | 34 / 34 | 34 / 34 |
| type 22 (three denial-of-service attacks) first | 30 | 18 / 18 | 18 / 18 |
| type 22 followers | 45 | 45 / 38 | 45 / 36 |
| type 23 (one denial-of-service attack, 10 h) first | 41 | 28 / 28 | 28 / 28 |
| type 24 (four noise attacks) first | 36 | 36 / 36 | 36 / 36 |
| type 24 followers | 59 | 59 / 6 | 21 / 1 |

- All 38 followers the tracker lost are noise followers. Followers start 0 or 1 step after the previous
  event (gaps of -1 or 0 steps in every multi-event run).
- Runs with at least one detected event: frozen 128 of 141, tracker 128 of 141.
- One of the 142 attack runs has no labelled event (`attack_mode_1_type_24_id_339.csv`).
- First noise event: median 25.1 h (3.8 to 37.2). Tracker threshold when noise followers begin: median 82 tau0
  (23 to 151); when denial-of-service followers begin: median 1.07 tau0.
- Time to clear (tt1f G; 36 noise sequences, median length 41.4 h): every rule alarms within one step of the
  start. Share of the sequence in alarm (median): frozen 100 %, tracker 37 %, tracker_slow 56 %, tracker with
  eta 0.01 tau0 32 %, daily 43 %. Last alarm at a median 23.7 h (tracker), 27.6 h (slow), 22.6 h (tau0-scaled),
  22.9 h (daily) into the sequence.
- Trace of the run fixed in the plan (`attack_mode_0_type_24_id_268.csv`, mode 0): events at steps
  37449-71577, 71578-94329, 94329-105705; tracker at their starts 1.0, 146, 146 tau0; frozen in alarm 100 % of
  each; tracker in alarm 70 %, 0 %, 0 %. Trace CSV: `target/real-telemetry/tt1f/tep_noise_run_trace.csv`
  (copy into the pack's figure_data for a figure).

## 2. Chance reference for the detection counts (tt1f F)

Each rule's alarm sequence shifted circularly within its run (200 shifts a run, seed 7; 1000 for the stored
traces). Mean and central 95 % range of the shifted counts.

Tennessee Eastman, any-alarm count (observed, then chance):

| Rule | first (141) | type 22 first (30) | type 23 first (41) | type 24 first (36) | type 22 followers (45) | type 24 followers (59) |
|---|---|---|---|---|---|---|
| frozen | 116; 60.6 [51, 69] | 18; 13.0 [8, 17] | 28; 18.1 [12, 24] | 36; 29.2 [26, 33] | 45; 20.1 [14, 26] | 59; 40.3 [34, 47] |
| tracker | 116; 56.5 [48, 66] | 18; 10.8 [6, 15] | 28; 21.0 [14, 27] | 36; 24.5 [20, 29] | 45; 16.3 [10, 23] | 21; 29.2 [21, 36] |
| daily | 106; 53.9 [45, 63] | 13; 10.8 [6, 15] | 23; 17.9 [12, 25] | 36; 24.9 [20, 29] | 44; 17.0 [12, 23] | 15; 29.9 [23, 38] |
| daily_excl | 113; 65.8 [56, 75] | 19; 13.8 [9, 19] | 24; 21.7 [14, 28] | 36; 30.0 [26, 33] | 45; 21.2 [15, 28] | 59; 41.1 [34, 48] |
| tighten_only | 122; 69.3 [60, 78] | 20; 14.2 [8, 19] | 32; 24.9 [19, 31] | 36; 29.9 [27, 33] | 45; 21.9 [16, 29] | 59; 41.7 [35, 48] |
| tracker_capped | 130; 84.8 [78, 91] | 26; 19.1 [14, 23] | 34; 33.1 [28, 37] | 36; 32.3 [30, 35] | 45; 29.9 [24, 35] | 59; 44.6 [39, 51] |

- Type 21 first events: every rule 34 of 34 against a chance of 0.1 to 0.4.
- Onset count, type 24 followers: frozen 6 against a chance of 23.2 [17, 30]; tracker 1 against 26.4 [20, 32].
  Both are below chance, because the alarm is already running (frozen) or the rule is raised (tracker).
- Reading: long events make the any-alarm count partly a matter of chance. The type 23 detections of the
  capped tracker (34) and of the excluding recalibration (24) sit inside their chance ranges; the frozen
  threshold's 28 is just above its range. Half of the 116 first-event detections of frozen and tracker are
  what their alarm rates would give anyway.

Stored traces (`threshold_transfer_tt1f_batadal_v1.json`):

- HAI 20.07 (one row a minute, approximate): frozen 36 of 38 against a chance of 17.0 [11, 23]; onset 26
  against 1.6 [0, 5]. Tracker 20 against 1.4 [0, 4]; onset 20 against 0.9 [0, 3].
- BATADAL: frozen 14 of 14 against 5.7 [2, 10]; registered tracker 6 against 5.8 [2, 9]; tracker with eta
  0.01 tau0 14 against 4.3 [1, 8]; daily 14 against 12.2 [10, 14].

## 3. BATADAL under the stronger rules (tt1f D and J)

Registered counts reproduce from the stored trace (frozen 14/14 at 0.70 times the budget, tracker 6/14 at
1.83, slow tracker 5/14, daily 14/14 at 6.34; the recomputed tracker path equals the stored one to 5e-7).

| Rule | any / onset (of 14) | false alarms over budget | threshold at onsets (median, tau0) |
|---|---|---|---|
| tracker, eta = 0.01 tau0 | 14 / 14 | 0.30 | 3.13 |
| daily, alarm episodes left out | 14 / 14 | 0.70 | 1.00 |
| tracker, rise stopped after an event | 14 / 10 | 3.05 | 1.27 |
| tracker, rise capped at 0.1 tau0 a day | 14 / 14 | 0.35 | 1.61 |
| static 1.1 / 1.25 tau0 | 14 / 14 each | 0.51 / 0.43 | |
| registered tracker under a ceiling of 1.1 / 1.25 tau0 | 14 / 13 each | 42.6 / 35.9 | 0.79 / 0.92 |
| tracker, eta = 0.01 tau0, under a ceiling of 1.1 / 1.25 tau0 | 14 / 14 each | 0.59 / 0.43 | 1.02 / 1.17 |

- The registered step on BATADAL is 6.9 tau0 per 15-minute sample (0.01 of a spread of 6,462 against tau0 =
  9.39). With a step of 0.01 tau0 the tracker loses nothing under either count. The registered loss on
  BATADAL belongs to the spread-scaled step.
- Under a ceiling the registered step makes the tracker fall 0.48 tau0 per quiet sample and run at 36 to 43
  times the budget.
- Peak score of the 14 attacks: 3.2 to 1,583 tau0, median 15. No attack peaks below 2 tau0.

## 4. Peak scores (tt1f I)

- Tennessee Eastman, 245 events: quartiles 0.86 / 1.11 / 17.4 / 166 / 827 tau0. Peak below tau0: 25 (the
  frozen threshold's 25 missed first events); below 1.1 tau0: 61; below 1.25: 70; below 2: 71. All 70
  events below 1.25 tau0 are first events (of 141).
- HAI 20.07, 38 events (minute trace): quartiles 0.45 / 5.9 / 10.1 / 20.1 / 111 tau0; 2 below tau0, 3 below
  1.5, 6 below 2.

## 5. Matched operating points on Tennessee Eastman (tt1f A)

One multiplier c for every mode, chosen so that the static threshold c tau0 raises the same number of
false-alarm episodes on the 56 sealed runs as the rule (in-sample match, descriptive).

| Rule R | c | sealed ratio (static / R) | R: first, followers any / onset | static at R's rate | first events, static minus R |
|---|---|---|---|---|---|
| tracker | 0.985 | 1.22 / 1.21 | 116, 66 / 37 | 119, 104 / 44 | +0.021 [-0.028, 0.071] |
| tracker, ceiling 1.25 tau0 | 0.979 | 1.31 / 1.30 | 121, 104 / 41 | 121, 104 / 44 | 0.000 [-0.05, 0.05] |
| daily, episodes left out | 0.978 | 1.33 / 1.33 | 113, 104 / 44 | 121, 104 / 44 | +0.057 [0.014, 0.106] |
| tighten-only | 0.965 | 1.57 / 1.57 | 122, 104 / 44 | 127, 104 / 46 | +0.035 [0.007, 0.071] |
| tracker, capped rise | 0.942 | 2.12 / 2.12 | 130, 104 / 44 | 130, 104 / 46 | 0.000 [-0.05, 0.05] |

- No adaptive rule detected more than a frozen threshold set 1.5 to 6 % lower at the same sealed alarm
  rate; two detected fewer first events.
- On the unlabelled time of the attack runs the matched static thresholds ran at 1.77 to 2.80 times the
  budget, against 0.82 to 2.35 for the rules (frozen 1.55).

## 6. SPOT under the frog on the 56 sealed placements (tt1f C, H)

| Rule | caught at 1.05 / 1.25 / 1.5 / 2 tau0 | control | threshold over tau0 at the end (quartiles) | fitted shape xi (quartiles) |
|---|---|---|---|---|
| standard SPOT (registered) | 0 / 16 / 24 / 32 | 44 / 56 / 56 / 56 | 1.19, 1.24, 1.75, 3.2e9, 1.5e21 | -1.38, -1.22, -1.07, 6.53, 12.6 |
| shape bounded to 0.5 | 0 / 0 / 0 / 21 | 44 / 56 / 56 / 56 | 1.62, 1.80, 2.26, 34.8, 85.0 | -0.5, -0.5, -0.5, 0.5, 0.5 |
| runs declustering | 44 / 56 / 56 / 56 | 43 / 56 / 56 / 56 | 0.99, 0.99, 1.02, 1.05, 1.08 | -0.19, -0.11, 0.03, 0.20, 0.29 |

- Control shapes: -0.16 to 0.35. Under the frog the fitted shape leaves that range in 55 of 56 placements of the
  first two rules; 23 of 56 standard-SPOT placements end above 10 tau0 (numerical runaway), 24 above 2 tau0.
  Bounding the shape removes the runaway and blinds the rule more evenly (35 of 56 above 2 tau0).
- Peaks in the fit: about 34,700 after the campaign against 11,200 without (standard and bounded);
  declustering keeps about 890.
- Per mode (registered file): the 8 placements of a mode always agree. Standard SPOT at 1.25 tau0: 0 of 8 in
  modes 0, 2, 4, 5 and 6, 8 of 8 in modes 1 and 3. Median inflation by mode: 1.75, 1.19, 3.9e8, 1.24, 2.4e9,
  2.8e18, 1.46. The 56 placements are seven monitor-level outcomes.
- A fixed tau0 monitor beside the attacked rule (H): during the frog against standard SPOT the score is above
  tau0 on a median 99 % of campaign steps (at least 92 %), in 56 of 56 placements, first within 2 h (median
  0.23 h). Without the frog: 0.05 % of steps. The frog is silent only to the rule it attacks.
- Silent to the attacked rule: 51 of 56 (standard), 52 (bounded), 25 (declustered).

## 7. Audit checks (amendment 2)

- K1: `calibrate_v2` returns the registered D1 threshold in all seven Tennessee Eastman modes (ratio 1.0; no
  candidate above tau0 breaks the budget).
- K2, ProvICS with the extended validity mask (3 recording gaps; 685 invalid steps instead of 577): frozen and
  tracker each detect 23 of 32 instead of 25 (onset 3 instead of 4); frozen 33.7 times the budget and 44.0 % of
  unlabelled time in alarm (registered 33.0 and 44.1 %); tracker 5.8 and 18.7 % (6.5 and 18.7 %). Tighten-only
  33.7, tracker under a 1.25 ceiling 25.9, capped tracker 38.2. Sealed rows: no gap, frozen 0.92. The registered
  conclusion (no loss) is unchanged; two detections of each rule came from steps after a gap.
- Verifier: tt1d tep59 19 of 19 after allowing ledgered exploratory accesses; rerun for provics before
  quoting its count.

## 8. Process-level campaigns on HAI normal data (tt1f E)

`threshold_transfer_tt1f_process_v1.json`: 30 placements (10 per release). The attacker writes three sensor
readings; the plant's response is not simulated. Terminal setpoint steps of 1 / 1.5 / 2 / 3 times the
smallest step the frozen threshold detects (median 0.19 scaled units).

| Campaign | Rule | caught after | control | silent to the rule | alarm episodes (median) | threshold over tau0 (median) |
|---|---|---|---|---|---|---|
| frog, reads tau_t, 6 h | frozen | 30 / 30 / 30 / 30 | 30 each | 15 of 30 | 0 | 1.00 |
| frog, reads tau_t, 6 h | standard SPOT | 9 / 21 / 30 / 30 | 30 each | 12 of 30 | 1 | 1.11 |
| frog, sees only alarms, 6 h | standard SPOT | 20 / 30 / 30 / 30 | 30 each | 0 | 13 | 1.03 |
| 20 s pulses every 30 min, 24 h | daily, episodes left out | 21 / 30 / 30 / 30 | 30 each | 0 | 50 | 1.03 |
| 20 s pulses every 30 min, 24 h | tracker, hold-off | 0 / 0 / 0 / 1 | 21 / 28 / 30 / 30 | 0 | 48 | 12.5 |

- Replay (no campaign; the three sensors show clean values during the terminal step): the frozen threshold
  detects 3 / 5 / 7 / 11 of 30, against 30 each without replay. Replay hides more than any campaign.
- Pulses sized to keep the alarm shorter than an event peak at about 1.1 times the rule's threshold (the
  score-level campaign wrote 2 times).
- Calibration check (K1): `calibrate_v2` returns the registered tau0 on HAI 21.03, 22.04 and 23.05.

## 8b. Rules from alarm practice, recalibration as a rule, a threshold watch (tt1g)

Plan `threshold_transfer_tt1g_dev_plan.md` (amendment 1 is post-hoc), result `threshold_transfer_tt1g_tep_v1.json`,
on the Tennessee Eastman score cache. Frozen: 116 first events, 104 / 44 followers, all 56 bumps in every
campaign. Bumps caught at 1.05 / 1.25 / 1.5 / 2 tau0, of 56.

| Rule | first | followers any / onset | sealed FA | frog | loud | sub-event |
|---|---|---|---|---|---|---|
| median + k MAD, last day | 115 | 56 / 39 | 0.96 | 0 / 0 / 0 / 0 | 53 / 56 / 56 / 56 | 47 / 55 / 56 / 56 |
| EWMA control limit | 115 | 45 / 35 | 0.95 | 0 / 0 / 0 / 0 | 0 / 6 / 56 / 56 | 0 / 0 / 0 / 41 |
| EWMA limit, alarms left out | 121 | 104 / 44 | 1.24 | 0 / 0 / 0 / 0 | 55 / 56 / 56 / 56 | 55 / 56 / 56 / 56 |
| static, 60 s on-delay | 108 | 104 / 51 | 1.01 | 56 each | 56 each | 56 each |
| recalibration, quiet days, one day | 116 | 104 / 44 | 1.26 | 51 / 56 / 56 / 56 | 54 / 56 / 56 / 56 | 7 / 7 / 7 / 22 |
| recalibration, oracle, one day | 108 | 104 / 46 | 1.17 | 40 / 44 / 48 / 54 | same | same |
| recalibration, quiet days, pooled (post-hoc) | 115 | 104 / 44 | 0.99 | 56 each | 56 each | 34 / 42 / 43 / 48 |
| recalibration, oracle, pooled (post-hoc) | 112 | 104 / 44 | 0.95 | 56 each | 56 each | 56 each |

- The on-delay rule (threshold 0.74 tau0, alarm after 60 s above it) loses 8 of the 34 minute-long integrity
  attacks and nothing else.
- The median rule catches 11 of the 59 noise followers and the plain EWMA limit none.
- One-day oracle recalibration: threshold above 1.5 tau0 on 21 of 56 attack-free runs; control 49 of 56 at
  1.05 tau0.
- Threshold watch at 1.5 tau0: alerts in 48 to 56 of 56 placements of every campaign that leaves a threshold
  above it (frog against SPOT: 32); false alerts on attack-free runs: 0 of 56 for ten of twelve adaptive
  rules, 15 for daily recalibration, 21 for one-day oracle recalibration. On the recorded noise sequences the
  watch on the tracker alerts in 36 of 36, a median 0.1 h after the start.

## 9. What this does to the paper's claims

- "Adaptive thresholds let attacks through" is not what the registered record shows. It shows that a plain
  tracker stops alarming during a sustained exceedance and stays raised: HAI 20.07 (any-alarm; net of chance
  the two rules are close), Tennessee Eastman noise sequences (alarm for the first day, then silence),
  BATADAL only with a mis-scaled step. The clearest loss under both counts is exploratory: the three HAI
  development releases (frozen 124 of 160 at onset, tracker 76).
- The any-alarm count needs a chance reference on long events; H1c (tracker equals frozen on first events) is
  weak evidence for the same reason.
- The score-level campaigns work as registered, at monitor level (seven modes), and the frog is visible to
  any fixed-threshold monitor running beside the adaptive rule.
- Tightening automatically bought no detection over a lower frozen threshold at the same alarm rate.
- A ceiling's guarantee is real and small where attacks barely exceed tau0 (70 of 141 first events on
  Tennessee Eastman peak below 1.25 tau0).
