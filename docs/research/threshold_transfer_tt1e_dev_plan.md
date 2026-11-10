# tt1e development plan: bounded loosening, attacks on the exclusion rules, an approval gate, a reconstruction score

Written 2026-11-10 and committed before any run. Status of everything below: **exploratory**. Data: the
normal files and the already-opened attack files of HAI 21.03, 22.04 and 23.05 (every attack-file read is
ledgered). Nothing here is registered evidence, and no result changes a registered outcome.

Why: the mock review of 2026-11-01 left four items open that need no new data. (1) Tighten-only has a
recall guarantee but no measured benefit, and the capped tracker's cap "bounds how fast it rises, not how
far". (2) The paper says an attacker who knows the 60 s event length could defeat the excluding rule, and
that we did not run that attack. (3) The frog is reported at one terminal magnitude (1.05 tau0), so its
reach is not measured. (4) Operator-gated loosening is recommended but no gate was attacked. A fifth item,
a reconstruction-based score, was asked for as external validity.

Setup, unless stated: exactly as `scripts/tt1c_baselines_dev.py`. D1 score, 1 Hz, smoothing 60 s,
episode gap 60 s, budget 2 false-alarm episodes a day. `natural` uses the tt1-final split of the normal
data (fit 60 / scale 20 / calibration 20 %) and the release's attack files. `normal` uses development
round r4 (fit 50 / scale 15 / calibration 10 / pseudo-deployment 25 %) and the longest pseudo-deployment
segment, with the same placements as tt1c (seed 7 + 707 for the frog, 7 + 202 for E4).

## Rules (scripts/threshold_rules_tt1e.py)

**Ceiling (bounded loosening).** A rule with a ceiling never raises its deployed threshold above
kappa x tau0. kappa in {1.1, 1.25, 1.5}, fixed here.

- `static_k`: the frozen threshold kappa x tau0. By construction every ceiling rule detects at least the
  events this threshold detects under the any-alarm count, whatever the stream held before (any rule with
  tau_t <= kappa tau0 alarms at every step whose score exceeds kappa tau0).
- `tracker_ceil_k`: the registered tracker (eta = 0.01 x spread) with its state clipped at kappa tau0
  after every update, so it does not wind up above the ceiling.
- `daily_ceil_k`: daily recalibration with the recalibrated value clipped at kappa tau0.
- `spot_gr_ceil_k`: `spot_gr` of tt1c (maximum-likelihood SPOT, refit every peak below 100 peaks, then on
  1 % growth). Deployed threshold min(z_t, kappa tau0); SPOT learns only samples at or below the deployed
  threshold.

**Approval gate.** `spot_gate24`, `spot_gate6`: `spot_gr` proposes z_t, and an approved ceiling c_t limits
it. Deployed threshold min(z_t, c_t), with c_0 = z_0. At every review (every 24 h, or every 6 h, counted
from the stream start) c is raised to z if the review window held no alarm of the deployed rule; otherwise
it stays. SPOT learns only samples at or below the deployed threshold. This stands for an operator who
signs a proposed loosening when the alarm log is quiet.

## Experiments (scripts/tt1e_defense_dev.py)

**A. Natural poisoning** (`natural <release>`). Rules: frozen, static_k, tracker, tracker_ceil_k, daily,
daily_ceil_k, spot_gr, spot_gr_ceil_k, spot_gate24, spot_gate6 (three kappa each). Per rule: events
detected (any-alarm), events detected at onset (an alarm episode starts inside the event), false-alarm
episodes a day, share of unlabelled time in alarm, paired event bootstrap against frozen (10,000
resamples) for both counts.

**B. Pulse campaign E4** (`normal <release>`), as tt1c: 12 x 120 s supra-threshold setpoint pulses a day
for up to a day, one quiet hour, then the just-detectable setpoint step. Same rules as A.

**C. Closed-loop frog with a dose response** (`normal <release>`). 24 h campaign at 0.97 x the deployed
threshold, one quiet hour, then a 600 s terminal bump of m x tau0 with m in {1.05, 1.1, 1.25, 1.5, 2, 3,
5, 10}. The rule state at the start of the terminal window is copied for each m, so one campaign serves
all magnitudes. Control: the same bumps without a campaign. Rules: frozen, spot_gr, spot_gr_ceil_k,
spot_gate24, spot_gate6, spot_gr_declust, daily_excl, tracker_capped. Reported per rule and m: fraction of
the 10 placements detected after the campaign and in the control; plus the threshold at the terminal over
tau0 (median, maximum) and campaign alarm steps.

**D. Sub-event pulses** (`normal <release>`). A score-level attacker who knows the excluding rules'
event length (60 s) and episode gap (60 s): for 24 h, every 30 minutes, it sets s_t = max(s_t, 2 tau_t)
for 45 s (48 pulses, 36 minutes above the threshold, every alarm episode shorter than an event). One quiet
hour, then the terminal bumps and control of C. Rules: frozen, daily, daily_excl, tracker, tracker_hold,
tracker_capped, tracker_ceil_k, daily_ceil_k, spot_gr. Also reported: campaign alarm episodes under each
rule. Like the frog, this attacker acts on the score and reads the threshold: an upper bound on a
physical attacker.

**E. Reconstruction score D2** (`d2 <release>`). Principal components of the standardized sensors, fitted
on the fit part, keeping the smallest number that explains 95 % of the variance. Residual e_t = z_t minus
its projection; D2 = mean of the three largest |e_t,j| / sigma_j, sigma_j the residual standard deviation
on the scale part; smoothed over 60 s; calibrated like D1 on the calibration part. Natural poisoning as in
A for frozen, tracker, daily, daily_excl, tracker_capped, spot_gr, tracker_ceil_1.25. This is the linear
case of the autoencoder detectors; no nonlinear autoencoder is run.

## What we expect, written before the runs

- Ceiling rules: recall between `static_k` and frozen on the attack files; the frog and the pulses hide a
  terminal bump only when m <= kappa, where without a ceiling `spot_gr` hid every magnitude we could
  express (its threshold left the floating-point range on HAI 21.03 and 22.04 in tt1c).
- Approval gate: blinded by the frog (it raises no alarm, so every review approves), not by E4 (the
  pulses alarm, so no review approves).
- Sub-event pulses: `daily_excl` and `tracker_hold` are blinded, since neither sees an event;
  `tracker_capped` hides bumps up to about 1.1 to 1.2 tau0; `spot_gr` and frozen are not affected.
- D2: the tracker loses recall to earlier attacks as with D1 and D0.

Any of these can fail; every rule, magnitude and release is reported in
`docs/research/threshold_transfer_tt1e_dev_v1.json`. Amendments to this plan are dated and appended below.
