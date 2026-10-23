# tt1: thresholds that travel (registered result, 2026-10-22)

Protocol: `docs/research/threshold_transfer_tt1_protocol.json`, registered in commit add86f1 before any
test file, label or attack schedule of the three fresh datasets was read. Each dataset was opened once
(`target/real-telemetry/final_access.jsonl`); `scripts/verify_tt1.py` passes 27/27 checks
(`docs/research/threshold_transfer_tt1_verification.json`).

Monitor: the rt1/rt2 D1 world-model residual (ridge + 60-tree LightGBM, history 3), calibrated once on the
most recent 20% of normal training data to 2 false-alarm episodes per day.

## Primary (HAI 20.07, 38 real attacks, 4.9 days of unlabelled operation): PASS

| Gate | Registered test | Result |
|---|---|---|
| G1 | after a pulse campaign, daily / tracker / slow tracker detect the terminal step in at most (frozen - 0.5) of placements, frozen at least 0.8, at least 6 placements | frozen 10/10; daily, tracker and slow tracker 0/10 (10 placements): PASS |
| G2 | recall(tracker) - recall(frozen) on the real attacks, 95% paired interval below 0 | 0.526 vs 0.947, -0.42 [-0.58, -0.26]: PASS |
| G3 | frozen false-alarm episodes/day on unlabelled test time at most 4.0 | 2.23/day: PASS (above the 2.0 budget, inside the rt2 band) |

**G1 caveat.** On HAI 20.07 the adaptive rules missed the terminal step in the control (no pulses) as
well: 0/10 for daily, tracker and slow tracker. The real attacks in the 3.4-day test1 stream had already
raised their thresholds 7-26x above tau0 at the terminal step. G1 passes as registered, but on this stream the pulses were
not needed. The pulse-specific effect is shown only in development, on attack-free normal streams of
HAI 21.03/22.04/23.05 (`threshold_transfer_dev_v3.json`: frozen 30/30, daily 4/30, tracker 1/30, slow
tracker 3/30, with controls mostly detected).

## Real attacks raise adaptive thresholds and hide the attacks that follow

Recall against the frozen threshold, paired event bootstrap (95%):

| Dataset (events) | frozen | daily | tracker | slow tracker | tighten-only (no permit) |
|---|---|---|---|---|---|
| HAI 20.07 (38 attacks) | 0.947 | 0.474 [-0.63, -0.32] | 0.526 [-0.58, -0.26] | 0.711 [-0.37, -0.11] | 0.947 [0, 0] |
| HyGrid-ICS (91 attacks) | 0.297 | 0.297 [0, 0] | 0.154 [-0.22, -0.08] | 0.165 [-0.21, -0.07] | 0.297 [0, 0] |
| voraus-AD (anomalous samples) | 0.334 | 0.148 [-0.21, -0.16] | 0.082 [-0.28, -0.22] | 0.213 [-0.14, -0.10] | 0.334 [0, 0] |

Median threshold at HAI 20.07 attack onsets: daily 25.6x tau0, tracker 12.9x, slow tracker 6.4x. HyGrid's
daily rule equals frozen because its 14.5 h final never completes a day. The same pattern appeared on the
recorded attacks of the spent HAI 21.03/22.04/23.05 in development (`threshold_transfer_margin_dev_v1.json`).

## False alarms: the frozen threshold transferred; adaptation bought little

| Dataset | frozen | margin (tau0 + 0.25 spread) | daily | tracker | slow tracker |
|---|---|---|---|---|---|
| HAI 20.07 (episodes/day) | 2.23 | 2.23 | 0.20 | 1.01 | 2.23 |
| HyGrid-ICS (episodes/day, 2.5 h unlabelled) | 19.2 | 0.0 | 19.2 | 19.2 | 19.2 |
| voraus-AD (per-sample FPR, target 0.05) | 0.081 | 0.033 | 0.086 | 0.012 | 0.014 |

Where an adaptive rule cut false alarms (HAI 20.07 daily and tracker, voraus tracker), it did so at the
recall cost in the previous table. The HyGrid rates rest on 2 episodes in 2.5 h of unlabelled time.

## Static margin (secondary S2)

The margin tau0 + 0.25 x spread matched frozen recall on HAI 20.07 (0.947, interval [0, 0]) and HyGrid
(interval [0, 0]) but did not lower HAI 20.07 false alarms (2.23/day). On voraus-AD it held the 5% target
(3.3%) at a recall cost of -0.12 [-0.15, -0.10], so it misses the registered "sound default" bar there.

## Tighten-only rules (secondary S4)

Without a permit the tighten-only rule matched frozen on every dataset. Its permits did not help: on
HAI 20.07 the spread permit lost 26 recall points and the shift permit 11 (intervals below zero), each
loosening 3-12 times a week. The oracle permit (simulated operator) matched frozen.

## Detection-v2 (secondary S6, its own protocol and amendment 2)

HAI 20.07 (primary for detection-v2): WorldModelV2 36/38 vs baseline 35/38 at 1.58 false-alarm
episodes/day; +0.026 [0.000, +0.079]. G1 and G2 pass, so detection-v2's registered primary passes, on a
one-attack margin. The ensemble arm (baseline OR model disagreement) found 35/38 at 3.16/day, no gain.
HyGrid-ICS (exploratory): both models 24/91, no difference.

## Post-hoc (after the finals)

HyGrid-ICS: 0.15% of the label-blind development rows were attack-labelled (251 short runs); 83% of the
final rows are. `docs/research/threshold_transfer_tt1_posthoc.json`.

## What this does and does not show

- On three fresh datasets from three systems, every rule that learns its threshold from exceedances lost
  real-event recall against a threshold frozen at calibration, and the loss came from earlier events
  raising the threshold.
- The frozen threshold held the rt2 false-alarm band on fresh HAI data (2.23/day) but not the 2/day budget,
  and overshot moderately on voraus-AD (1.6x).
- The E4 attacker is synthetic and assumes write access to one loop; on fresh HAI 20.07 the real attacks
  had already done the damage the pulses were meant to do.
- HAI 20.07 shares a testbed with the development releases. HyGrid-ICS is one simulated day; voraus-AD
  anomalies are not attacks.
- No claim of runtime authority, deployment safety or incident prevention follows.

## Extensions after registration (tt1b, exploratory)

None of this is registered. Development used the spent HAI 21.03/22.04/23.05 (attack data reused,
ledgered as exploratory); the post-hoc runs reopened the three tt1 datasets after their finals (ledgered
as post-hoc). Evidence: `threshold_transfer_tt1b_dev_v1.json`, `_tt1b_attacks_dev_v1.json`,
`_tt1b_frog_dev_v1.json`, `_tt1b_posthoc_v1.json`.

**Each adaptive threshold has a learning region, and an attacker can feed it.**

| Rule family | Learns from | Real attacks (natural) | Supra-threshold pulses | Closed-loop frog (stays just below tau_t) |
|---|---|---|---|---|
| frozen, static margin | nothing | not affected | not affected | not affected |
| tracker, slow tracker, daily | exceedances | loses recall everywhere | blinded (1-4/30) | not affected (it tightens) |
| SPOT, DSPOT (Siffer et al. 2017) | sub-alarm tail values | largely immune | resists (29/30, 23/30) | blinded |
| tighten-only, no permit | exceedances, downward only | not affected | not affected | not affected |

- **Literature thresholds and real attacks.** SPOT and DSPOT never learn from alarm values. With D1 on the
  spent HAI releases they matched frozen recall (method-of-moments SPOT 1.00/0.79/0.58, maximum-likelihood
  SPOT 1.00/0.79/0.60, frozen 1.00/0.76/0.60). Post-hoc on HAI 20.07: SPOT 0.947, DSPOT 0.947,
  maximum-likelihood SPOT 0.921 [-0.08, 0.00], frozen 0.947, tracker 0.526. Exceptions: on HyGrid-ICS
  method-of-moments SPOT lost 9 points [-0.15, -0.03] and DSPOT on D0 lost 4 [-0.09, -0.01]. On voraus-AD,
  190 calibration samples leave about 4 tail points; SPOT ran at 32% false positives against a 5% target
  and is not usable there.
- **The loss does not depend on the score.** With D0 (top-3 standardised first differences, no model) the
  tracker lost recall on every spent release ([-0.38, -0.14], [-0.21, -0.05], [-0.19, -0.02]) and on HAI 20.07
  ([-0.32, -0.08]) and HyGrid-ICS ([-0.12, -0.02]).
- **Mechanism.** The tracker's misses concentrate on attacks that start within 6 h of the previous one: D1
  recall on close versus isolated attacks 0.75/1.00, 0.41/1.00, 0.20/0.67 on the spent releases and
  0.48/0.71 on HAI 20.07 (31 close, 7 isolated).
- **Closed-loop frog boiling** (score-level, white-box: the attacker sees tau_t and holds the score at
  0.97 tau_t, so the campaign raises no alarm the clean stream would not; normal HAI data, 30 placements).
  The terminal bump at 1.05 tau0 was caught by frozen, tracker and tighten-only as often as in the control.
  Method-of-moments SPOT and DSPOT caught it 0/30 after campaigns of 24 h, 6 h and 1 h; their thresholds
  ran away (1.1-4.7x after 1 h, beyond 10^5 after 24 h). Maximum-likelihood SPOT caught 8/30 after 24 h and
  13/30 after 1 h. An open-loop attacker holding a fixed level did not move the moments variants (and
  raised alarms through the whole campaign) but still blinded maximum-likelihood SPOT on two releases.
  On light-tailed synthetic scores SPOT did not run away, so the effect depends on the heavy tail of real
  residual scores.
- **Open-loop sub-alarm pulses** (E6, 24 x 300 s a day, invisible to the frozen threshold) did not poison
  SPOT (29/30); its threshold fell.

**Design rule these results support:** a threshold may tighten itself but must not loosen itself. Every
automatic loosening path tried here (exceedance tracking, daily recalibration, tail refitting, moving-mean
drift tracking, the spread and shift permits) could be moved by real attacks or by an attacker; only the
operator-gated (oracle) permit and no loosening at all held. What this costs is false alarms under
benign upward drift (development HAI 23.05: tighten-only 5.98x budget against frozen 4.05x).

## tt1b: registered replication on BATADAL (2026-10-23)

Protocol `docs/research/threshold_transfer_tt1b_protocol.json`, registered in 3d4467d before any BATADAL
test row was read; result `threshold_transfer_tt1b_result_batadal.json` (41912ca); `verify_tt1b.py` 8/8.
BATADAL is the C-Town water network re-simulated without concealment (Erba et al. 2020), on a
15-minute grid: 384 days of normal training data, 14 attacks in 260 days of test operation. Settings in
physical time: 1 h smoothing, 1 false-alarm episode per week.

| Gate | Result |
|---|---|
| H1 real attacks poison the tracker (D1) | tracker 6/14 vs frozen 14/14, -0.57 [-0.79, -0.29]: pass |
| H2 maximum-likelihood SPOT non-inferior to frozen (tolerance two events, -0.14) | 14/14, difference 0: pass |
| H3 24 h closed-loop frog blinds DSPOT, not frozen or tighten-only | DSPOT already missed the bump in all 10 controls, so the campaign could not lower it: fail |

The primary rule fails on H3 and is retained. DSPOT's controls were blind because real attacks had raised
it 24 times above tau0 at attack onsets.

| Rule (D1) | Recall | False alarms (x budget) | Onset inflation |
|---|---|---|---|
| frozen | 14/14 | 0.70 | 1.0 |
| tighten-only | 14/14 | 2.43 | 1.0 |
| SPOT (MLE) | 14/14 | 0.81 | 1.0 |
| daily | 14/14 | 6.34 | 0.69 |
| tracker | 6/14 | 1.83 | 409 |
| tracker_slow | 5/14 | 0.70 | 74 |
| SPOT (moments) | 6/14 | 0.13 | 26 |
| DSPOT | 6/14 | 0.13 | 24 |
| margin | 3/14 | 0.05 | 173 |

- Natural poisoning reached the alarm-excluding rules here: BATADAL attacks last days, and the smoothed
  score spends long stretches in the band below the alarm, which moments SPOT and DSPOT learn from. With
  the D0 score even MLE SPOT lost (9/14, [-0.64, -0.14]).
- The margin and the tracker step are both scaled by the calibration spread (99.9th percentile minus
  median). BATADAL's residual scores are heavy-tailed, the spread was large, and the margin sat 173 times
  above tau0. A spread-scaled parameter is fragile on heavy tails.
- Across seven datasets (HAI 21.03, 22.04, 23.05, 20.07, HyGrid-ICS, voraus-AD, BATADAL), tighten-only
  matched the frozen threshold's recall every time. Every rule that can raise its own threshold lost
  recall against frozen, with the interval below zero, on at least one dataset: daily, tracker and
  tracker_slow on most; moments SPOT on HyGrid-ICS and BATADAL; DSPOT on BATADAL; MLE SPOT on BATADAL
  with the D0 score.

SWaT and WADI (requested from iTrust on 2026-10-23) will run under the same registration once their
loaders are added by amendment.
