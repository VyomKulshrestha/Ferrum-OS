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
