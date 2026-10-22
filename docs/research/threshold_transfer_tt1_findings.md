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
