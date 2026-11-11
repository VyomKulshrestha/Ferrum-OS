# tt1g development plan: baselines from alarm practice, a recalibration rule and a threshold watch

Status: **exploratory**. Written on 2026-11-11 and committed before any run. Both mock reviews of the
revision ask whether the paper's findings hold for threshold rules an ICS engineer would actually use,
and whether its recommendations (recalibrate under change control, watch the threshold) do anything when
run as rules. This round answers on the Tennessee Eastman data, from the D1 score cache that the tt1f
round built with a ledgered access (`target/real-telemetry/tt1f/`); no dataset is opened again. Nothing
here is registered and no registered outcome changes.

Script: `scripts/tt1g_baselines_dev.py`; rules: `scripts/threshold_rules_tt1g.py`.
Result: `docs/research/threshold_transfer_tt1g_tep_v1.json`.

## Rules

Each is calibrated per mode on the four calibration runs to the registered budget of 2 false-alarm
episodes a day (episodes merged across 17 steps), by the smallest multiplier that keeps the budget and
every larger one (the corrected search of the code audit). State at the start of a stream comes from the
calibration scores.

- **median_mad**: tau_t = m + k s, with m the median and s the median absolute deviation of the last day
  of scores, recomputed every hour; k calibrated. Its learning region is the bulk of the scores, not the
  tail: an attack moves it only if it fills a large part of the window.
- **ewma**: tau_t = mu_t + L sigma_t, with mu and sigma the exponentially weighted mean and standard
  deviation of the score (half-life one day), updated at every step; L calibrated. The classical control
  limit; mean and variance learn from every value, alarms included.
- **ewma_excl**: the same, but steps on which the rule alarms do not update mu and sigma.
- **on_delay**: a fixed threshold c tau0 that alarms only after the score has been above it for 60 s
  (17 steps); c calibrated. No learning; the alarm-management on-delay.
- **recal_quiet**: the frozen threshold, recalibrated at the end of each day on that day's scores (budget
  quantile by the same search) if the day held no alarm episode of 60 s or longer; otherwise unchanged.
  A stand-in for recalibration that trusts the alarm log.
- **recal_oracle**: the same, but a day is accepted only if it holds no labelled attack step and no
  injected campaign step. A stand-in for recalibration on verified clean data, the paper's
  recommendation; it uses information no deployed rule has.

For comparison, from the cache with the registered code: frozen, tracker, daily, daily_excl,
tracker_capped, spot_gr.

## Measurements

1. **Recorded attacks** (141 attack runs): first events and followers detected under both counts;
   false-alarm episodes over the budget on the unlabelled time of the attack runs; paired difference
   against frozen (runs resampled, 10,000 resamples).
2. **Attack-free cost** (56 sealed runs, 280 days): false-alarm episodes over the budget and the
   threshold over tau0 at the end of the run.
3. **Campaigns** (the 56 registered placements, same seeds, score level): loud pulses, sub-event pulses
   and the frog at 0.97 of the rule's threshold; terminal bumps of 1.05 / 1.25 / 1.5 / 2 tau0 caught after
   the campaign and in the control. For on_delay the frog holds 0.97 of its fixed threshold.
4. **Threshold watch.** For every adaptive rule above and for tracker, daily, daily_excl, tracker_capped
   and spot_gr: an alert fires when the rule's threshold exceeds 1.5 tau0. Reported: placements in which
   the alert fires during each campaign and the hours until it does; sealed runs in which it fires with no
   campaign (false alerts); attack runs in which it fires, and whether it fires before the rule's last
   alarm in noise sequences.

## What would change the paper

- If median_mad or on_delay keeps the frozen threshold's detections under recorded attacks and under all
  three campaigns at a comparable alarm rate, the paper's claim narrows to tail- and exceedance-learning
  rules, and it will say that bulk-robust rules are a way out.
- If recal_oracle holds the budget and loses nothing while recal_quiet is poisoned by a campaign, the
  recommendation "recalibrate on verified clean data" has its first measurement, with the caveat that
  verification is the hard part.
- If the threshold watch fires in every campaign placement and rarely without one, recommendation 1 of
  the guidance has a measured detector; if it fires often on attack-free runs, the paper says so.

## Not in this round

CUSUM (it changes the statistic, not the threshold rule), Telemanom at the budget (run in tt1c above
the budget), a published detector, and the same analysis on HAI (needs the monitors refitted) or on
BATADAL (the stored trace has no calibration scores).

## Amendment 1 (2026-11-11, post-hoc: written after the first results were seen)

The first run is in `threshold_transfer_tt1g_tep_v1.json` and stays as it is. In it both recalibration
rules use one day of scores, and that window is too short: on attack-free runs the threshold of
recal_oracle exceeded 1.5 tau0 in 21 of 56 runs and the rule caught 49 of 56 bumps of 1.05 tau0 with no
campaign at all. A one-day window was a poor stand-in for the paper's recommendation, which is to
recalibrate on verified clean data, not on little data. Two rules are added and reported as post-hoc:

- **recal_pooled_quiet** and **recal_pooled_oracle**: as recal_quiet and recal_oracle, but an accepted
  day is added to the pool of calibration data (the four calibration runs and every accepted day so far)
  and the threshold is recalibrated on the whole pool by the same budget search.

Measurements 1 to 4 are repeated for these two rules only (`natural2`, `campaigns2`), and merged into the
same result file under their own names.
