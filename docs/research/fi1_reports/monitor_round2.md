# fi1 workstream A, round 2: the monitor

Plan: `docs/research/ferrumos_improvement_fi1_plan.md`, in particular its note "monitor round 2 and the second use of
the check set". Everything here is exploratory. Round 1: `monitor_round1.md`.

## Selection rule (written and committed before any selection result of a round-2 candidate exists)

Selection set: HAI 21.03, HAI 22.04, Tennessee Eastman modes 0-3 (three datasets, equal weight). The baseline is d1,
recomputed with the round-2 benchmark (same cache, same thread settings: OMP, OpenBLAS and MKL at 2 threads, LightGBM
`n_jobs` 2, no refit needed). A candidate with more than one output state is scored as rule 4 of the plan's note
says: every non-normal state is alarm time, and an episode of any such state that starts inside an event is an
onset.

A candidate survives selection when, on the selection set:

1. mean onset recall is at least 0.02 above the baseline's;
2. mean share of unlabelled time in alarm is not above the baseline's;
3. no selection dataset loses more than 0.05 of onset recall;
4. false alarms on the sealed attack-free Tennessee Eastman runs stay below 1.5 times the budget;
5. (new) mean onset recall net of its circular-shift chance reference is not below the baseline's. Round 1 showed on
   the selection set that about half of a raw onset gain can be the higher chance level of shorter alarms.

Survivors are ranked by mean onset recall net of chance (round 1 ranked by raw onset recall); ties by the lower mean
alarm share. At most three go to the check set, once each, under new names. Rules 1-4 are round 1's rule unchanged.

Candidate families planned when this rule was written (parameters may be set on the selection set only):

- two-channel combinations of d1 and `second` (and of other round-1 scores), each channel calibrated on attack-free
  data to a share of the episode budget, with the alarm time the union and the episodes counted as described in
  "Method";
- a monitor with an "outside the fitted range" state, its indicator calibrated on attack-free data to its own share
  of the budget, the residual score used only inside the range;
- scales conditioned on the operating regime through the command inputs; channel weights fitted on attack-free data;
  handling of the post-attack period by fixed rules.

Not admitted as a candidate: any rule that silences an alarm while its score stays above threshold (for example a
maximum alarm duration). Under rule 4 that state is still alarm, and reporting it as normal would rename alarm time.

## Method

- **Cache and settings.** Round 1's residual cache of all fifteen units, unchanged. It already holds the scaled
  sensors Z, the actions U and the fit ranges of sensors and actions; nothing was re-extracted. OMP, OpenBLAS and MKL
  at 2 threads; no model is refitted in round 2, so LightGBM does not run. No GPU.
- **Benchmark additions (`scripts/fi1_monitor_benchmark.py`, commit aea4022, before any round-2 candidate result and
  before the check run).** Multi-state monitors are scored under rule 4: alarm time is the union of the states;
  episodes are taken per state (merged across the gap within the state); an episode of any state that starts inside
  an event is an onset; every state's episodes outside events count as false alarms against the one budget, so a
  two-channel monitor is charged for both channels' episodes. Rule-5 numbers for every monitor: share of unlabelled
  time outside the fitted range (a scaled sensor more than 5 % of its fit span beyond the range of the world-model
  fit data, round 1's descriptive definition); alarm share on unlabelled time inside the range; onset recall of the
  events that start inside the range; onset recall of first and follower events separately. voraus-AD: a sample is
  outside when any of its steps is. The baseline d1 through the round-2 benchmark reproduces round 1's selection
  numbers exactly (49/50, 44/58, 103/153; shares 0.00755, 0.00274, 0.01863), and the multi-state path run on d1
  alone gives the same counts, shares and average precision as the single-score path.
- **Candidates (`scripts/fi1_monitor_v4.py`).** All static, fitted on the attack-free residual-scale and
  calibration splits.
  - `A|B@q`: two alarm channels. A is calibrated alone to share q of the episode budget, B to 1 - q
    (`real_telemetry_detect_v2.calibrate` with the budget times the share; voraus-AD: the per-sample quantile at
    1 - alpha times the share). The sum of both channels' episodes on the calibration split is within the budget.
  - `A^B@q`: one channel, max(sA / tA, sB / tB), recalibrated to the full budget (union episodes counted once).
  - `rise<L>`: the smoothed D1 score minus its own value L smoothing windows earlier. A fixed linear filter: it
    responds to a new rise on top of a level the score already holds (a follower attack during the disturbance
    left by an earlier one) and learns nothing from the stream.
  - `oor[U]@q:X`: two output states. Out-of-range indicator = largest excess of a scaled sensor (with U: or of an
    action) beyond the fit range, in fit spans, smoothed with the registered window, calibrated on the calibration
    split to share q of the budget and floored at 0.05. The calibration recordings are held out of the world-model
    fit, so this is the held-out-recording calibration the plan's note suggests. The inner monitor X is calibrated
    on calibration time outside that state to 1 - q and is not evaluated while the state is on.
  - `regime<K>`: per-channel scales per k-means cluster of the command inputs (residual-scale split).
  - `worst`: per-channel scale = the largest per-recording residual spread over the attack-free recordings.
- **Re-arming.** A two-channel monitor re-arms each channel on its own: a channel's episode ends after `gap` quiet
  steps of that channel, and its next crossing is a new episode of that channel even while the other channel is
  still in alarm. That is how a follower attack can be an onset during an earlier alarm, and it is why both
  channels' episodes are charged to the budget. The union variant (`^`) shows what happens without it.

## Selection

`python scripts/fi1_monitor_benchmark.py select2 <names>`, two batches; table
`target/real-telemetry/fi1/monitor/results/selection_table_r2.json`. Net of chance: mean over the three selection
datasets of onset recall minus its circular-shift chance level. Tennessee Eastman (TEP) first and follower events at
onset (baseline 78 of 90 and 25 of 63). Sealed: false alarms on the sealed attack-free TEP runs over the budget.

| monitor | mean onset (gain) | net of chance (gain) | mean share | sealed | TEP first | TEP followers | onset change HAI 21.03 / 22.04 / TEP | outcome |
|---|---|---|---|---|---|---|---|---|
| d1 | 0.804 | 0.653 | 0.0096 | 1.03 | 78 | 25 | | baseline |
| d1\|rise3@0.8 | 0.871 (+0.068) | 0.697 (+0.044) | 0.0093 | 0.99 | 73 | 61 | 0 / 0 / +0.203 | survives, rank 1 |
| d1\|rise3@0.9 | 0.878 (+0.074) | 0.696 (+0.043) | 0.0096 | 1.02 | 76 | 61 | 0 / 0 / +0.222 | survives, rank 2 |
| d1\|rise3@0.67 | 0.858 (+0.054) | 0.694 (+0.041) | 0.0092 | 0.99 | 67 | 61 | 0 / 0 / +0.163 | survives, rank 3 |
| d1\|second@0.8 | 0.854 (+0.050) | 0.690 (+0.037) | 0.0093 | 1.05 | 74 | 52 | 0 / 0 / +0.150 | survives, rank 4 |
| d1\|second@0.67 | 0.845 (+0.041) | 0.689 (+0.036) | 0.0093 | 1.05 | 70 | 52 | 0 / 0 / +0.124 | survives, rank 5 |
| d1\|rise3 (q 0.5) | 0.844 (+0.040) | 0.685 (+0.032) | 0.0091 | 1.00 | 63 | 61 | 0 / -0.017 / +0.137 | survives, rank 6 |
| d1\|rise1 | 0.843 (+0.039) | 0.681 (+0.028) | 0.0090 | 1.03 | 62 | 59 | 0 / 0 / +0.118 | survives, rank 7 |
| d1\|second@0.33 | 0.834 (+0.030) | 0.675 (+0.022) | 0.0091 | 1.04 | 70 | 52 | 0 / -0.034 / +0.124 | survives, rank 8 |
| d1\|rise6 | 0.844 (+0.040) | 0.666 (+0.014) | 0.0092 | 0.98 | 63 | 61 | 0 / -0.017 / +0.137 | survives, rank 9 |
| d1\|mad+second | 0.830 (+0.026) | 0.672 (+0.019) | 0.0091 | 1.00 | 66 | 62 | 0 / -0.086 / +0.163 | out: HAI 22.04 |
| d1\|second (q 0.5) | 0.822 (+0.018) | 0.668 (+0.015) | 0.0092 | 1.01 | 67 | 52 | 0 / -0.052 / +0.105 | out: gain, HAI 22.04 |
| worst | 0.813 (+0.009) | 0.662 (+0.009) | 0.0099 | 1.04 | 77 | 25 | 0 / +0.034 / -0.007 | out: gain, share |
| oor@0.1:d1 | 0.841 (+0.037) | 0.655 (+0.003) | 0.0154 | 1.02 | 76 | 44 | 0 / 0 / +0.111 | out: share |
| d1^second | 0.801 (-0.003) | 0.650 (-0.003) | 0.0096 | 0.96 | 75 | 27 | -0.020 / +0.017 / -0.007 | out |
| regime4 | 0.810 (+0.006) | 0.648 (-0.004) | 0.0108 | 0.99 | 78 | 26 | -0.040 / +0.052 / +0.007 | out |
| oor@0.1:d1\|rise3 | 0.805 (+0.001) | 0.640 (-0.013) | 0.0150 | 1.01 | 62 | 44 | 0 / -0.017 / +0.020 | out |
| oor:d1 (q 0.25) | 0.808 (+0.004) | 0.631 (-0.022) | 0.0160 | 0.86 | 68 | 43 | -0.040 / 0 / +0.052 | out |
| oor:d1\|second | 0.781 (-0.023) | 0.611 (-0.042) | 0.0158 | 1.00 | 66 | 43 | -0.040 / -0.069 / +0.039 | out |
| oorU:d1 | 0.764 (-0.039) | 0.608 (-0.045) | 0.0211 | 0.86 | 69 | 22 | -0.040 / 0 / -0.078 | out |

What the selection set says:

1. **The two-channel idea works on the selection set, and the second channel that serves followers best is
   `rise3`, not `second`.** With d1 at 80-90 % of the budget, TEP followers at onset go from 25 to 61 of 63 while
   first events fall only from 78 to 73-76 of 90; HAI is unchanged. Net of chance, TEP onset recall rises from
   0.277 to 0.413-0.414, so the gain is not the higher chance level of shorter alarms. Equal shares (q 0.5) cost
   first events (62-67 of 90): halving d1's budget raises its threshold.
2. **One alarm channel built from the two scores (`d1^second`) gives nothing.** The follower gain needs the second
   channel to re-arm while the first is still in alarm, which only separate episodes allow.
3. **The out-of-range state does not help under rule 4.** Calibrated on held-out attack-free recordings, its
   threshold sits at the floor on HAI 21.03 and TEP (0.05 of a span: those recordings stay in range) and at 0.57
   spans on HAI 22.04 (a calibration recording leaves the fit range by more than half a span). On TEP, 3.1 % of
   unlabelled time is outside the range (after attacks); the residual score already alarms on about half of it and
   the state alarms on all of it, so the alarm share goes up (0.0186 to 0.030-0.045). The indicator is not better
   calibrated than the extrapolating residual. Descriptively, the baseline's TEP alarm share inside the range is
   0.0022 against 0.0186 overall: almost all of its excess alarm time on TEP is time outside the fitted range.
4. Regime-conditioned scales and worst-recording scales do not move onset recall.

Survivors sent to the check set under the rule (ranked by net of chance): `d1|rise3@0.8`, `d1|rise3@0.9`,
`d1|rise3@0.67`. They are one design with three budget splits, so the check run is close to one test, not three
independent ones. A pass by one split and not by the others should be read as fragile.
