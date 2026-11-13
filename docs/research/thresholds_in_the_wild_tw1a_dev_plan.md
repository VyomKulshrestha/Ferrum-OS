# tw1a: score-level targets on the Tennessee Eastman score cache (development plan)

Written 2026-11-11 and committed before any target was installed or run. Status of everything this round
produces: **exploratory**. It opens no dataset: it replays the D1 monitor scores cached by the tt1f round
(`target/real-telemetry/tt1f/mode_<m>.npz`), which come from runs that tt1d already spent.

Parent documents: `thresholds_in_the_wild_tw1_catalogue_plan.md`, `thresholds_in_the_wild_tw1_catalogue.md`
(decision: go). The reserve of 53 unopened Tennessee Eastman runs is not touched here.

## Question

When a shipped library is given a score stream and decides the alarm itself, does it behave under
recorded attacks and under the three tt1 campaigns as the catalogue reading predicts?

This round covers the targets that take a score. Targets that model a raw signal (Random Cut Forest,
OpenSearch, Netdata, Zabbix, RRDtool, Graphite, the PromQL rules, Merlion, alibi-detect) need sensor-level
campaigns and come in a later round with its own plan.

## Targets

Each target is run from the code the catalogue read. The file that holds its update statement must be
byte-identical in the installed package and in the catalogued clone; where a release differs, the
target is installed from the clone at the catalogued commit, or the difference is recorded and the row
is marked. Installed versions and file hashes go into the result file.

| Target | Role |
|---|---|
| river `anomaly.QuantileFilter` (pass-through scorer, `protect_anomaly_detector` at its default) | absorbing, count-based memory |
| river `anomaly.ThresholdFilter` at the calibrated threshold | static control |
| PySAD `QuantileFilter` post-processor | absorbing |
| PySAD `ConformalProbabilityCalibrator` with a fixed cut | absorbing, short window |
| PySAD `GaussianTailProbabilityCalibrator` with a fixed cut | absorbing |
| PySAD `AnomalyLikelihoodProbabilityCalibrator` with a fixed cut | absorbing (Numenta likelihood port) |
| PySAD `NonparametricDynamicThresholdPostprocessor` | absorbing (Telemanom port) |
| PySAD `SPOTProbabilityCalibrator` with a fixed cut | hold-out |
| StreamAD `ZScoreCalibrator`, `TDigestCalibrator` | absorbing |
| StreamAD `SpotDetector` (given the score as its series) | absorbing, no alarm branch |
| htm.core Python `AnomalyLikelihood` | absorbing |
| SPOT, the authors' `spot.py` (`with_alarm=True`) | hold-out |
| libspot v3 through its Python binding | hold-out |

A target that cannot be installed on the development machine without a compiler it lacks is recorded as
"not run" with the reason. It is not replaced by a re-implementation.

For comparison the result file repeats, from the stored tt1d and tt1g results, the outcomes of the
frozen threshold, the tracker, the standard SPOT and the alarm-excluding daily recalibration on the same
placements.

## Configurations

- **Documented (D).** Constructor defaults. A required parameter with no default takes the value of the
  project's own documentation example, recorded with file and line. This is the primary configuration.
- **Budget-matched (B).** Where a target has one sensitivity parameter (a quantile level, a probability
  cut, a multiplier), it is calibrated per mode on the four calibration runs to the budget of the study
  (2 alarm episodes a day, gap 17 steps), as tt1g did for its rules. B makes a target comparable with
  the frozen threshold; D shows what a user gets.

No alarm delay, hysteresis or de-duplication is added to a target. Episodes are counted as in tt1.

## Protocol

For each of the 7 modes and each of its sealed attack-free runs (56 placements, the registered ones of
tt1d):

1. **History.** The target is fed the mode's calibration scores before the run. Two conditions, because
   the catalogue found memories that depend on age: *full* (all four calibration runs, 479,960 steps)
   and *young* (the last 24,000 steps, one day).
2. **Campaign** on the registered 24 h window: control, frog (the score is held at 0.97 of the target's
   current effective threshold), loud pulses (33 steps at 2 tau0 every 2,000 steps), sub-event pulses
   (12 steps at 2 times the effective threshold every 500 steps). The attacker is white-box, as in tt1.
3. **Terminal step** of 167 steps at 1.05, 1.25, 1.5 and 2 tau0, where tau0 is the frozen threshold of
   the study. Two placements: after the registered lead of 1,000 steps, and directly after the campaign
   (lead 0), since a short window forgets within the lead.
4. **Outcome.** Hit when the target alarms on any terminal step; the effective threshold over tau0 at
   the end of the campaign; alarm steps and episodes during the campaign.

For the 142 recorded attack runs: any-alarm and onset counts for first and follower events, the share
of unlabelled time in alarm, the time from the start of a noise sequence to the target's last alarm,
and a chance reference by circular shifts of the alarm sequence (tt1f), since a target at documented
settings may alarm often. For the 56 sealed runs: false-alarm episodes against the budget.

**Effective threshold.** An adapter per target computes, from the target's own state, the largest score
that would not alarm. The adapter never decides an alarm: the target's own call does. On the first 2,000
steps of every run and every 100th step after, the harness checks that the target's decision equals
"score above the effective threshold" for the score at hand and for probes just above and below it; a
disagreement stops the run. Adapters and the pass-through scorer are the only code between the stream
and the target.

## Predictions (written before the run; from the catalogue)

- **Short windows** (PySAD conformal, Gaussian tail, likelihood, Telemanom port; StreamAD z-score): the
  alarm stops within about one window of a sustained exceedance. The terminal step is missed at lead 0
  when it is no larger than the campaign's level, and caught after the registered lead.
- **Count-based or global memory** (river's quantile, StreamAD's t-digest and SPOT with global memory):
  little movement with full history; clear absorption when young.
- **Hold-out** (PySAD SPOT, the authors' SPOT, libspot): unaffected by loud pulses and by sub-event
  pulses; blinded by the frog, as the standard SPOT of tt1 was.
- **Static control** (river `ThresholdFilter`): every terminal step caught in every condition.

A prediction that fails is reported as failed.

## Reading the results

The 56 placements are seven mode-level outcomes (tt1f). Results are given per mode and in total, with
no test statistics. Nothing here is a registered result.

## Where results go

Result files stay under `target/tw1/` on the development machine and are not committed: the catalogue
plan keeps attack results against named projects out of this repository until their maintainers have
been told. This plan, the harness and the adapters are committed.

## After this round

A registered version on the 53 reserve runs, with targets, configurations and outcomes fixed from what
this round shows; and the signal-level round.

## Amendment 1 (2026-11-11, before any campaign or attack run)

Written after the targets were installed and the adapters were smoke-tested on the first 20,000
calibration scores of mode 1 (consistency of the threshold reading, speed, cloning). No campaign, no
recorded attack and no sealed run had been replayed through any target.

1. **StreamAD is not run in this round.** Release 0.3.1 pins numpy 1.x, pandas 1.x and statsmodels
   0.13.5, and its t-digest dependency needs a C build; the development machine has Python 3.12 and no
   compiler. It will be run in a container with the versions it pins.
2. **The SPOT authors' `spot.py` is deferred.** It has no step call, and `run()` refuses a second call
   on the same object, so the closed-loop campaigns cannot be driven through it without changing it. A
   later pass will give it the recorded attacks and the loud pulses as whole series.
3. **htm.core's Python likelihood is not run yet.** It is not installed as a package; the adapter loads
   the catalogued file from the clone. The session's permission guard declined to execute code from the
   clone, so this target waits for the author's word. PySAD's port of the NuPIC likelihood is run.
4. **PySAD's Telemanom port is run open-loop only** (recorded attacks, sealed runs, loud pulses). It
   exposes no cheap reading of the score that would alarm next, so the frog and the sub-event pulses,
   which need that reading at every step, are not run against it.
5. **libspot is fitted on the first 1,000 scores of the history** and stepped from there. Its objects
   cannot be copied, so a branch replays the inputs.
6. **Consistency check.** The check on the score at hand runs on the first 2,000 steps of every stream
   and every 100th step after, as planned. The probes just above and below the reading need a copy of
   the target; they run on the first 200 steps and every 1,000th step, and not at all for libspot, whose
   reading is the library's own `anomaly_threshold`.
7. **The Gaussian-tail reading is approximate** (it uses the long-window mean and deviation from before
   the score). Disagreements within 5% of the reading are counted and reported; one outside stops the
   run. In the smoke test the largest was 0.6%.
8. **Configuration B is a second pass.** Its procedure is fixed now: the single parameter is found by
   bisection so that the target, after one pass over the mode's four calibration runs, raises at most 2
   alarm episodes a day over a second pass of the same runs; the most sensitive value that meets the
   budget is used.
9. **Scores that are not finite** are not given to a target and raise no alarm. The calibration data of
   the modes checked contain none.

## Amendment 2 (2026-11-11, after one test part, before the full run)

The harness was run once on one of the fourteen parts (mode 1, young history) to test it. That output is
discarded and the part is rerun with the rest. What the test changed:

1. **Two readings were wrong and the consistency check stopped them.** The Gaussian-tail calibrator
   judges a score against a deviation that the score itself has just raised, so the approximate reading
   of amendment 1 (item 7) was too low. The reading now asks the target's own meters and its own
   `_calibrate`, on shallow copies, what they would return for a candidate score, and bisects; its band
   is 1e-9 like the other bisected readings. The likelihood calibrator is two-sided (a short-window mean
   far below the long mean alarms as well, as in NuPIC); the reading is the upper edge and the check
   knows the lower one.
2. **Capped variants of the frog and of the sub-event pulses are added** (`frog_cap`, `subl_cap`): the
   injected score never exceeds 2 tau0, the level of the loud pulses. The plan defines both campaigns
   relative to the target's current reading. Against a threshold that follows the injected scores, that
   attacker's score grows without bound within the day, which no process-level attacker could produce.
   The uncapped campaigns stay as planned; every cell reports the largest injected score.

## Amendment 3 (2026-11-11, after the full run of amendment 2)

All fourteen parts ran. Eight of the nine targets completed with no disagreement between a reading and
the target's decision. The Gaussian-tail calibrator was stopped in every part by the consistency check,
during the uncapped sub-event pulses, when the injected score passed 1e12: the reading's search range
ends there. The other targets' uncapped campaigns show the same growth (injected scores of 1e9 tau0 and
far beyond), which confirms that the capped variants are the ones to read.

1. **Rerun of the Gaussian-tail calibrator only**, in every part, with the uncapped attacker stopped at
   1e6 tau0. The other targets are not rerun; their uncapped cells keep the unbounded attacker, and each
   cell reports the largest injected score.
2. **Not changed after seeing results:** targets, configurations, placements, magnitudes, the capped
   variants and the outcome definitions.
3. **Noted for a later pass, not run here:** the frog sits 3% below the reading (the tt1 value). Where a
   target's alarm threshold lies less than 3% above the level from which it learns, that frog never
   enters what the target learns from. A frog closer to the reading is a separate, later test.

Note to amendment 3 (2026-11-11): the rerun completed in nine of the fourteen parts and was stopped by
the consistency check in five. After a long run of one repeated score the calibrator's long window has
zero variance, and it then alarms on any score above that value; the reading assumed a non-alarming
score at the long-window mean. The reading now searches below the mean in that state. The five stopped
parts are rerun with it; nothing else changes.

Second note to amendment 3 (2026-11-11): one part (mode 2, full history) was stopped once more, at the
sixth score of the calibration data, which begins with one value repeated seven times. With zero
variance in its long window the calibrator compares two means of the same values that differ by one
rounding step, and alarms on the repeated value. The reading now sums the short window as the target
does and keeps that single point apart. After this, all nine targets completed in all fourteen parts
with no disagreement between a reading and a decision. The Gaussian-tail parts that had already
completed were not rerun.

## Amendment 4 (2026-11-12, round tw1b, committed before any run of its conditions)

Round tw1b runs the three follow-ups that tw1a left (programme fi2, workstream T1). It uses the same
nine targets, the same score cache, the same 56 placements and 142 recorded attack runs, the same two
histories (full and young) and the same outcome definitions. Everything is exploratory. Results stay under
`target/tw1/` as before. This amendment contains no tw1b result; it uses only tw1a's published-locally
numbers and the catalogue readings.

Code: the harness of tw1a as fixed on main after tw1a (bisection without the 1e12 ceiling, one random
generator per target and run for the chance reference, river's quantile of 0.0). New code goes in
`scripts/tw1b_*.py`; tw1a's files are imported, not changed. Before any new condition, river
`ThresholdFilter` at tau0 is rerun with the current code in all fourteen parts and must reproduce tw1a's
harness check (false alarms 0.98 times the budget, 116 of 141 first events, 104 of 104 followers, 44 at
onset, 56 of 56 in every campaign). A deviation is reported before anything else runs.

### 1. Configuration B (budget-matched)

The rule of amendment 1, item 8, is applied per mode: the single parameter is searched so that the
target, after one pass over the mode's four calibration runs, raises at most 2 alarm episodes a day (gap
17 steps) over a second pass of the same runs, counted over the whole second pass (at most
2 x 479,960 / 24,000 episodes); the most sensitive value that meets the budget is used. The rule is
incomplete in four places, completed here:

- **Search scale.** Each parameter is written as p(u) with u increasing toward less sensitive settings,
  and u is bisected (12 halvings after checking both ends). If the least sensitive end exceeds the
  budget, the budget is recorded as not reachable and that end is used. If the most sensitive end meets
  it, that end is used. The bisection assumes that fewer alarms follow from a less sensitive setting;
  every evaluation is stored, so a failure of that assumption is visible.
- **Parameters and ranges.** river `QuantileFilter` and PySAD `QuantileFilter`: q = 1 - 10^-u, u in
  [0.3, 7]. PySAD conformal (window 1000 kept): cut = 1 - 10^-u, u in [0.3, 3]; a cut above 0.999 can
  never alarm with this window, so 0.999 is the least sensitive end. PySAD Gaussian tail (window 1000
  kept) and PySAD likelihood: cut = 1 - 10^-u, u in [1, 15]. PySAD SPOT (num_init 500 kept): q = 10^-u
  with the cut at 1 - q as in configuration D, u in [1.7, 10] (the calibrator requires q below
  1 - level = 0.02). libspot (fit on 1,000 scores kept): q = 10^-u, u in [2.7, 12] (its default level is
  0.998). A setting that the library refuses counts as exceeding the budget.
- **river `ThresholdFilter`** is the static control at tau0, the study's frozen threshold. It is not
  recalibrated; its configuration B is tau0.
- **PySAD's Telemanom port** has no single sensitivity parameter: its z is chosen by the target itself,
  and p is a pruning margin. Its documented setting already raises 0.05 times the budget on the sealed
  runs. Configuration B is its documented setting, and tw1a's open-loop rows stand for it; it is not
  rerun.

Configuration B is then run through the tw1a protocol for both histories, with the campaigns control,
loud pulses, capped sub-event pulses and the capped frog at the four distances of section 2, with the
recorded attack runs and the sealed false-alarm count. The uncapped campaigns are not run (amendment 3:
their injected scores grow without bound).

### 2. The frog closer to the reading

Beside the frog 3% below the reading (0.97 of the target's own current reading, tw1a), the frog is run
at 2%, 1% and 0.5% below it (0.98, 0.99, 0.995), each capped at 2 tau0 as in amendment 2. It is run on
the eight targets with a reading (all but the Telemanom port), in configuration D for both histories
(with control and the 3% frog rerun beside them under the current code), and in configuration B as
above. The recorded attack runs are not repeated in configuration D: they do not depend on a campaign.

### 3. The SPOT authors' script on whole series

The script (`spot.py` of the SPOT authors, Software Heritage snapshot 360fcff0, revision a7a499c4) is
copied unchanged into an empty directory under `target/` and loaded by a separate driver run with
`python -I`. Class `SPOT` with the README's settings for the univariate examples: q = 1e-4 (also the
constructor default), `initialize()` at its default level 0.98, `run(with_alarm=True)`. One object is
built per series, as the authors do: `fit(init_data, data)`, `initialize()`, `run()`. `init_data` is the
history (full: the mode's 479,960 calibration scores; young: the last 24,000). Non-finite scores are
dropped from a series before it is given to the script.

- **Recorded attack runs**: `data` is the whole attack run. Outcomes as in tw1a (any-alarm and onset,
  first and follower events, chance reference, unlabelled time in alarm).
- **Campaigns**: `data` is the campaign stream of the placement: the registered 24 h window, the lead of
  1,000 steps and the terminal step, `s[c_start : terminal_start + 167]`. The pre-campaign part of the
  sealed run is not given (each step above the initial threshold costs a Grimshaw fit; a whole sealed
  run per magnitude does not fit the machine). Campaigns: control and loud pulses (open loop, as tw1a's
  amendment 1 promised). False alarms are counted on the control stream (about one day per placement).
- **Terminal step**: the score that the script compares at step i is `data[i] > extreme_quantile`, and
  `run()` returns the threshold after every step. A magnitude whose terminal score exceeds the threshold
  the script reports for the step before the terminal step is counted as caught on its first step, by
  the script's own comparison. Every other magnitude is run as its own whole series (the stream up to
  the terminal step with the terminal scores raised), at lead 0 (terminal directly after the window)
  and after the lead. The reading at campaign end is the script's threshold at that step.
- **Frog, limited.** The frog needs the threshold of the step before, which a whole-series run gives
  only afterwards. The attacker plans the frog with a copy of the script's own update (its `_grimshaw`
  and `_quantile` methods on an object of the script's class, stepped by the driver); the script is
  then run unchanged on the planned series, and its returned thresholds must equal the planned ones at
  every step, or the cell is reported as stopped. Every frog step is a peak and costs one Grimshaw fit
  on a growing peak set, so this is run on one placement per mode (the first registered sealed run),
  young history, the 3% capped frog, with the terminal steps after the lead.

### 4. Predictions (written before any run of these conditions)

From the catalogue readings (absorbing, count-based or hold-out) and tw1a's numbers:

- **Harness check.** river `ThresholdFilter` at tau0 reproduces tw1a exactly.
- **Frog at 2%, 1%, 0.5% (configuration D).**
  - river and PySAD `QuantileFilter` are not blinded at any distance: a score held just below a running
    quantile pulls that quantile down, not up. The reading at campaign end stays within 5% of control
    and every terminal step caught in control is caught.
  - PySAD conformal: not blinded (the window fills with the frog's value and the reading follows it
    down), as at 3% (53 56 56 56).
  - PySAD Gaussian tail: blind at lead 0 at every distance, recovered after the lead, as at 3%.
  - PySAD likelihood: still blind after the lead at every distance, as at 3%.
  - PySAD SPOT (q 1e-3): its alarm threshold lies about 2.5% above its peak threshold, so the frog at
    2%, 1% and 0.5% enters the peaks. Prediction: blinded like libspot at all three distances (reading
    at campaign end above 2 tau0 and no terminal step up to 2 tau0 caught after the lead) in at least 5
    of 7 modes, for both histories.
  - libspot: blinded at every distance, as at 3% (at most 8 of 56 caught at 2 tau0).
  - river `ThresholdFilter`: 56 of 56 everywhere.
- **Configuration B.**
  - The budget is reachable for both running quantiles, the Gaussian tail, the likelihood, PySAD SPOT
    and libspot in every mode; for the conformal calibrator it is not reachable (cut 0.999 still above
    budget) in at least 4 of 7 modes.
  - On the sealed runs, every B setting raises between 0.3 and 3 times the budget (the calibration runs
    and the sealed runs are of the same modes).
  - Running quantiles at B (q near 1 - 1e-3 or higher) count only a thin tail, so the loud and capped
    sub-event pulses, which put 1.65% and 2.4% of the window's scores at 2 tau0, lift the reading: above
    1.25 tau0 at campaign end with young history, by at least 10% over control with full history. The
    frogs do not blind them.
  - Conformal at B: blind at lead 0 after the capped sub-event pulses, recovered after the lead; loud
    pulses and frogs leave it as in control.
  - Gaussian tail at B: blind at lead 0 after the capped frogs, recovered after the lead.
  - Likelihood at B: blind after the lead following the capped frogs, as in D.
  - PySAD SPOT and libspot at B: blinded by the frog at every distance at which it enters the peaks;
    unaffected by pulses.
  - Followers in the recorded attacks: hold-out targets (PySAD SPOT, libspot) lose none of the 104
    that the frozen threshold finds; running quantiles lose at least 10.
- **The SPOT authors' script.** It behaves as libspot does in configuration D: loud pulses leave the
  outcome of control unchanged in every placement where its threshold is below 2 tau0; it finds at
  least 100 of the 104 followers; on the control streams it stays below the budget with full history.
  The planned frog raises its threshold above 2 tau0 within the day in at least 5 of the 7 placements,
  and no terminal step up to 2 tau0 is caught after the lead there; the script's thresholds equal the
  planned ones at every step.

A prediction that fails is reported as failed. Nothing here changes after the runs start; a change
needed by a stopped run goes in a dated note below with its reason.

Note to amendment 4 (2026-11-12, after the harness check, before any run of the new conditions): the
harness check passed (river `ThresholdFilter` at tau0 with the current code: false alarms 0.98 times
the budget, 116 of 141 first events, 104 of 104 followers with 44 at onset, 56 of 56 in every campaign,
both histories). One detail of section 3 is fixed now, for cost: in the planned frog, the terminal
outcome at each magnitude is the planner's (the script's own update, stepped from the state after the
lead), and the script itself is run on the whole series once more for the largest magnitude, 2 tau0;
the two must agree. A whole-series run of a frog stream takes about half an hour, because every frog
step adds a peak and refits.
