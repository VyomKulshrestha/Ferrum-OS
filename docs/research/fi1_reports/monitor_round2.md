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

## What I knew before the check run (disclosure, rule 2 of the plan's note)

I had read round 1's report, including its check table (per-dataset onset counts and alarm shares of d1,
`mad+second`, `second`, `second+loro`), its verdict, and the post-check description of HAI 20.07 and ProvICS
(sensors outside the fit range, channels far above their normal spread). No round-2 parameter was set on a check
dataset and no diagnostic ran on check data before the run: the round-2 benchmark touched check units only in the
check run itself. The `rise` channel, the budget shares and the out-of-range calibration were chosen from the
selection table above. The idea behind the second channel (followers during an earlier alarm) came from round 1's
selection results on TEP; that round 1's check run showed the same trade on TEP modes 4-6 was known to me, so the
choice was not blind to the check set's character. A round-2 pass is weaker evidence than a round-1 pass would
have been.

## Check set (second use; run once, 2026-11-12 09:28-09:35 UTC)

`python scripts/fi1_monitor_benchmark.py check2 "d1|rise3@0.8" "d1|rise3@0.9" "d1|rise3@0.67"`. Ledger rows
(`target/real-telemetry/fi1/monitor/check_ledger.jsonl`) carry `"round": 2, "use": "second use of the check set"`.
The baseline was re-scored once under the ledger label `d1 (round-2 re-score)` only to add the rule-5 numbers; the
run checks that its verdict numbers equal round 1's stored ones (they do, every dataset) and the verdict is computed
against round 1's stored baseline. Nothing was changed after the run.

Onset detected / events (onset recall net of its chance reference), then the share of unlabelled time in alarm.
voraus-AD: detected anomalous samples and the false-positive rate of normal samples (no chance reference).

| dataset | d1 (baseline) | d1\|rise3@0.8 | d1\|rise3@0.9 | d1\|rise3@0.67 | round 1 best: mad+second / second |
|---|---|---|---|---|---|
| HAI 20.07 | 26/38 (+0.645), 0.3910 | 35/38 (+0.869), 0.3910 | 35/38 (+0.869), 0.3910 | 35/38 (+0.869), 0.3906 | 26, 0.3910 / 26, 0.3908 |
| HAI 23.05 | 31/52 (+0.568), 0.0071 | 31/52 (+0.564), 0.0069 | 31/52 (+0.564), 0.0069 | 31/52 (+0.565), 0.0069 | 30, 0.0066 / 31, 0.0067 |
| BATADAL | 14/14 (+0.661), 0.0138 | 14/14 (+0.631), 0.0132 | 14/14 (+0.651), 0.0134 | 14/14 (+0.635), 0.0130 | 14, 0.0127 / 14, 0.0101 |
| HyGrid-ICS | 3/91 (-0.021), 0.0407 | 24/91 (+0.016), 0.0407 | 24/91 (+0.016), 0.0407 | 24/91 (+0.016), 0.0407 | 14, 0.0368 / 15, 0.0067 |
| voraus-AD | 243/755, 0.0811 | 223/755, 0.0644 | 241/755, 0.0811 | 197/755, 0.0525 | 324, 0.1480 / 277, 0.0979 |
| TEP modes 4-6 | 57/92 (+0.222), 0.0136 | 71/92 (+0.345), 0.0132 | 73/92 (+0.347), 0.0134 | 69/92 (+0.347), 0.0129 | 70, 0.0066 / 64, 0.0129 |
| ProvICS | 3/32 (-0.038), 0.4399 | 11/32 (+0.095), 0.4399 | 11/32 (+0.095), 0.4399 | 11/32 (+0.095), 0.4399 | 3, 0.4224 / 3, 0.3889 |
| mean onset recall | 0.478 | 0.599 (+0.120) | 0.605 (+0.127) | 0.591 (+0.112) | 0.528 / 0.514 |
| mean alarm share | 0.1410 | 0.1385 (-0.0026) | 0.1409 (-0.0001) | 0.1366 (-0.0044) | 0.1463 / 0.1305 |
| largest onset loss | | -0.026 (voraus-AD) | -0.003 (voraus-AD) | -0.061 (voraus-AD) | |
| mean net of chance (6 stream datasets) | 0.339 | 0.420 | 0.424 | 0.421 | |

### Verdict (the plan's definition, unchanged, against round 1's baseline numbers)

| candidate | mean onset recall up >= 0.05 | mean alarm share not higher | no dataset loses > 0.05 | verdict |
|---|---|---|---|---|
| d1\|rise3@0.8 | yes (+0.120) | yes (-0.0026) | yes (worst -0.026) | **improved** |
| d1\|rise3@0.9 | yes (+0.127) | yes (-0.0001) | yes (worst -0.003) | **improved** |
| d1\|rise3@0.67 | yes (+0.112) | yes (-0.0044) | no (voraus-AD -0.061) | not improved |

Two of the three splits meet the definition; the third fails only on voraus-AD, where a smaller d1 share loses
anomalous samples. The alarm-share condition for `d1|rise3@0.9` holds by 0.0001; for `@0.8` it holds through the
lower false-positive rate on voraus-AD (the stream datasets' shares are equal or slightly lower).

### What the gain is made of (read these before the verdict)

- **It is onsets during alarms that were already running, not less alarm time.** The second channel starts a new
  episode when the score rises again on top of a level it already holds. On HAI 20.07 and ProvICS the alarm share is
  unchanged (0.391, 0.440): the monitor still saturates; it now also says "something new" inside the saturated
  time. Followers carry the gain: TEP modes 4-6 followers at onset 19/41 -> 39/41, while first events fall 38/51 ->
  32/51 (`@0.8`) or 34/51 (`@0.9`); HAI 20.07 followers 25/36 -> 33/36.
- **Net of chance, the gain is real on HAI 20.07 (+0.22), TEP 4-6 (+0.12) and ProvICS (+0.13), and nil on
  HyGrid-ICS** (3 -> 24 of 91 onsets against a chance level that rises from 4.9 to 22.6 events; net -0.021 ->
  +0.016). The mean net of chance over the six stream datasets rises from 0.339 to 0.420-0.424.
- **False-alarm episodes go up where the monitor saturates.** Each channel re-arms on its own, so the operator sees
  more alarms: false-alarm episodes per unlabelled day over the budget rise on HyGrid-ICS from 9.6 to 19.2 times
  and on ProvICS from 33.7 to 73.2 times; on HAI 20.07 from 1.11 to 1.52 times; TEP 4-6 1.45 -> 1.51. Sealed
  attack-free TEP and ProvICS runs stay within the budget (0.90 and 0.92 times). The definition of improved does
  not count episodes; a paper must.

### Rule 5, the descriptive numbers

Outside the fitted range = a scaled sensor more than 5 % of its fit span beyond the world-model fit range. Same for
every monitor; the rows below are d1 -> `d1|rise3@0.8` (`@0.9` identical except where noted).

| dataset | unlabelled time outside range | alarm share inside range | events starting inside range | onset recall inside range |
|---|---|---|---|---|
| HAI 20.07 | 0.410 | 0.0367 -> 0.0367 | 27 of 38 | 0.926 -> 0.926 |
| ProvICS | 0.559 | 0.0909 -> 0.0909 | 13 of 32 | 0.154 -> 0.231 |
| HAI 23.05 | 0.049 | 0.0059 -> 0.0056 | 52 of 52 | 0.596 -> 0.596 |
| BATADAL | 0.003 | 0.0116 -> 0.0110 | 11 of 14 | 1.0 -> 1.0 |
| HyGrid-ICS | 0.998 | 1.0 -> 1.0 (only 0.2 % of the time is inside) | 3 of 91 | 0.33 -> 1.0 |
| voraus-AD | 0.038 of normal samples | 0.077 -> 0.060 (`@0.9` 0.077) | 618 of 755 | 0.220 -> 0.199 (`@0.9` 0.217) |
| TEP modes 4-6 | 0.023 | 0.0015 -> 0.0013 | 62 of 92 | 0.694 -> 0.694 (`@0.9` 0.726) |

On the two saturating recordings, the fitted range explains the saturation: HAI 20.07 spends 41 % of its unlabelled
time outside the range and its alarm share inside the range is 3.7 % (against 39 % overall); ProvICS spends 56 %
outside and 9.1 % inside (against 44 %). The monitor is near its budget where the plant is in the regime it was
fitted on and in alarm where it is not. HyGrid-ICS is outside the range almost all the time (99.8 %).

## What the two rounds establish

1. The registered D1 monitor's excess alarm time is time when the plant is outside the range the world model was
   fitted on (HAI 20.07, ProvICS, TEP after attacks). No static rescaling, channel selection, robust scale, regime
   conditioning or out-of-range state fitted on attack-free data lowered it on the saturating recordings; an
   out-of-range state alarms on the same time and, counted as alarm, raises the alarm share.
2. What can be improved is how the monitor reports new events during that time. A second alarm channel on the rise
   of the score, re-armed on its own and charged to the same episode budget on attack-free data, raises onset
   recall on the check set by 0.12-0.13 (0.08 net of chance) with the same alarm time, mostly on follower events,
   at the cost of a few first events on TEP and roughly twice the false-alarm episodes on the recordings that
   saturate.
3. This is a second use of the check set by a designer who knew round 1's check results; the gain is consistent
   across two of three budget splits and fails the per-dataset condition at the third.

## Commands

    python scripts/fi1_monitor_benchmark.py select2 "d1|second" "d1^second" "d1|second@0.67" "d1|second@0.33" "d1|mad+second" "d1|rise3" "d1|rise1" "oor:d1" "oorU:d1" "oor:d1|second" "regime4" "worst"
    python scripts/fi1_monitor_benchmark.py select2 "d1|rise3@0.8" "d1|rise3@0.67" "d1|second@0.8" "d1|rise6" "d1|rise3@0.9" "oor@0.1:d1" "oor@0.1:d1|rise3"
    python scripts/fi1_monitor_benchmark.py check2 "d1|rise3@0.8" "d1|rise3@0.9" "d1|rise3@0.67"
    python scripts/fi1_monitor_collect_r2.py                     # docs/research/fi1_monitor_round2.json
    python -m pytest -q scripts/test_fi1_monitor_v3.py scripts/test_fi1_monitor_v4.py   # 11 + 10 tests

Process notes: memory on the shared machine fell to 1.0 GB between batches; batch 2 and the check run waited for 2 GB
free before starting. No job was cut off.
