# Thresholds That Travel: Adaptive Alarm Thresholds Let Attacks Through in ICS Anomaly Detection

Draft v0.1, 23 October 2026. Not for circulation. Target: ASIACCS 2027 (round 2, 11 December 2026) or
USENIX Security 2027 (cycle 2, 26 January 2027). Both are double-blind: the submission must drop the
author block, the repository link and the Zenodo DOIs, and point to an anonymized artifact instead.

Vyom Kulshrestha, Independent Researcher, India (ORCID 0009-0009-1434-7148)

Status marker: [VERIFY] marks a citation detail to check before submission.

---

## Abstract

Anomaly detectors for industrial control systems (ICS) raise an alarm when a score crosses a threshold.
The threshold is calibrated on clean data and must then hold a false-alarm budget for months, so
deployments often let it adapt: they recalibrate it daily, track a running quantile, or refit an
extreme-value tail as data arrive. We show that whatever an adaptive threshold learns from, an attacker
can feed it, and that real attacks feed some of these rules without any adversarial effort.

We ran a pre-registered study on three datasets that no earlier analysis in our pipeline had opened
(HAI 20.07, HyGrid-ICS and voraus-AD), with a world-model residual monitor and eleven threshold rules.
On HAI 20.07's 38 attacks the frozen threshold detected 36 at 2.23 false-alarm episodes per day; a
symmetric quantile tracker detected 20 (difference -0.42, 95% interval [-0.58, -0.26]) because earlier
attacks had raised its threshold a median 12.9 times above calibration. Daily recalibration and a ten
times slower tracker also lost recall, and the same loss appeared on HyGrid-ICS and voraus-AD, on three
earlier HAI releases, and with a second, model-free score. Twelve two-minute nuisance alarms a day
blinded every rule that learns from exceedances to a later, just-detectable setpoint attack.

Streaming extreme-value thresholds (SPOT and DSPOT) refuse to learn from alarms and escaped this natural
poisoning on the HAI data, but a closed-loop attacker who holds the score just under the current
threshold drove their thresholds upward without raising one alarm and blinded them within an hour. A
second registered study on the BATADAL water network replicated the tracker's loss (6 of 14 attacks
against 14 for the frozen threshold) and found that slow, days-long attacks also inflated SPOT and DSPOT.
Across seven datasets, a threshold that only tightens itself matched the frozen threshold's recall every
time, while every rule that can raise its own threshold lost recall on at least one. We argue that an
alarm threshold may tighten itself but should loosen only with operator approval, and we release the
registrations, ledger and code.

---

## 1. Introduction

A process-monitoring anomaly detector has two parts: a score that grows when the plant behaves unlike
its normal operation, and a threshold that turns the score into alarms. Most of the research effort goes
into the score. The threshold is usually set once, on held-out normal data, to meet a false-alarm budget,
and then expected to hold that budget on a plant that drifts: sensors age, seasons change load, and
operators retune loops. When it does not hold, the standard remedies adapt the threshold online. Daily
recalibration re-estimates a quantile on the last day of data. Online quantile tracking, the mechanism
behind adaptive conformal inference [Gibbs and Candes 2021], nudges the threshold up after every
exceedance and down otherwise. Streaming peaks-over-threshold methods (SPOT and DSPOT [Siffer et al.
2017]) refit a generalised Pareto tail as new values arrive, and the nonparametric dynamic threshold of
Telemanom [Hundman et al. 2018] recomputes its level on a trailing window.

Each of these rules learns from part of its input. Trackers and recalibration learn from the values that
exceed the threshold. SPOT and DSPOT discard values above their alarm level but learn from values between
a base level and the alarm level. A frozen threshold learns from nothing after calibration. We call the
part of the score range a rule learns from its *learning region*, and the question of this paper is what
happens when an attack, or an attacker, lands in it.

The answer depends on the region, and none of the adaptive rules we tested is safe:

- **Rules that learn from exceedances are poisoned by real attacks.** An attack is a long exceedance, so
  a tracker raises its threshold during the attack and stays high afterwards. The next attack then
  arrives under an inflated threshold. On fresh HAI 20.07 data this cost the tracker 16 of 38 attacks.
  No adversarial planning is needed; the attacks in the recording did it.
- **The same rules can be poisoned on purpose and loudly.** Twelve two-minute pulses a day, the kind of
  nuisance alarm operators learn to acknowledge, raised these thresholds enough to hide a later attack
  that a frozen threshold caught every time.
- **Rules that refuse to learn from alarms can be poisoned silently.** An attacker who reads the current
  SPOT or DSPOT threshold and holds the score just under it feeds every sample into the fitted tail. The
  tail extends, the threshold rises, the attacker follows it up, and no alarm is ever raised.

A threshold that only tightens automatically, and loosens only when an operator approves, resisted all
three. Its cost is extra false alarms when the plant drifts upward.

**Method.** The main study was registered before any test file, label or attack schedule of its three
datasets was read. A ledger records every access to recorded attack data, the analysis harness refuses
to run if any frozen source file changed after registration, and it computes the registered gates
itself. The rules and the attack designs came from development on three earlier HAI releases whose
attacks had already been used; we report how the claim changed during development, including two
hypotheses we dropped. Extensions run after the registered finals are labelled exploratory.

**Contributions.**

1. A registered comparison of eleven threshold rules on three never-opened datasets from three systems
   (a hardware-in-the-loop ICS testbed, a simulated hybrid power grid, and an industrial robot), with
   real-event recall, false-alarm rates and threshold trajectories (Section 6).
2. Evidence that exceedance-learning thresholds lose recall on real attacks because earlier attacks
   inflate them, on seven datasets and two score families, with the mechanism visible in which attacks
   are missed, and a registered replication on the BATADAL water network (Sections 6 and 7).
3. A learning-region analysis of adaptive thresholds with a matching attack for each class: supra-
   threshold pulse campaigns for exceedance learners and a closed-loop frog-boiling attack for
   extreme-value learners, including how the latter depends on the tail estimator (Section 7).
4. A design rule, supported by these results, for deployed detectors: thresholds may tighten
   themselves; loosening needs a human (Section 8).
5. The registration, access ledger, harness and verifier. [Anonymized artifact link.]

---

## 2. Background and related work

**ICS anomaly detection.** Process-level detectors learn normal behaviour from sensor and actuator
traces and flag deviations: residuals of a predictive model, reconstruction errors of an autoencoder, or
statistical bounds. Public testbed recordings with labelled attacks (SWaT [Goh et al. 2016], WADI
[Ahmed et al. 2017], BATADAL [Taormina et al. 2018], and the HAI releases [Shin et al. 2020]) are the
usual benchmarks. Evaluations typically fix one threshold per detector, chosen on clean data or, less
defensibly, on the test labels. Wu and Keogh [2021] list further benchmark pitfalls. [VERIFY]

**Threshold rules.** Static thresholds come from a quantile or a false-alarm budget on clean data.
Adaptive variants recalibrate on a trailing window, track a target exceedance rate online
[Gibbs and Candes 2021], fit an extreme-value tail and update it per observation (SPOT, and DSPOT for
drifting streams [Siffer et al. 2017]), or recompute a level on a trailing window of smoothed errors
[Hundman et al. 2018]. Alarm-management practice in process plants [ISA-18.2] treats nuisance alarms as
an operational hazard because operators learn to ignore them.

**Poisoning of anomaly detectors.** Rubinstein et al. [2009] showed that slowly shifted traffic ("boiling
frog" poisoning) can stop a PCA-based network anomaly detector from flagging a later attack. Kloft and
Laskov [2010] analysed poisoning of online centroid detectors. Chan-Tin et al. [2009] described the
frog-boiling attack on outlier rejection in network coordinate systems, where every update stays within
the rejection threshold while the system drifts. In ICS, Kravchik and Shabtai [2020] found that
autoencoder detectors retrained online on SWaT resisted their poisoning attacks, and Erba et al. [2020]
concealed attacks from reconstruction-based detectors by manipulating sensor readings. Hong [2026]
studied gradual drift against world-model monitors in simulation, without attacks or adaptive
thresholds. These works target the model or the score. We target the threshold rule and show that it can
fail even when the model resists poisoning.

**Distribution shift and calibration.** Adaptive conformal inference keeps a long-run miscoverage rate
under arbitrary shift, a guarantee about the rate of exceedances. That guarantee holds whether the
exceedances come from benign drift or from attacks, which is the property we exploit in Section 7.

---

## 3. Threat model and learning regions

**System.** A monitor computes a score s_t from plant telemetry and raises an alarm when s_t > tau_t.
The rule that sets tau_t is calibrated once on clean data to a false-alarm budget and then runs online.
Operators acknowledge alarms; persistent nuisance alarms are acknowledged without investigation.

**Learning region.** For a rule R, the learning region L(R, tau_t) is the set of score values that change
R's future thresholds. Examples:

| Rule | Update | Learning region |
|---|---|---|
| frozen, static margin | none | empty |
| symmetric tracker q_{t+1} = q_t + eta(1[s_t > q_t] - p) | up on exceedance, down otherwise | all values; upward moves only from s_t > tau_t |
| daily recalibration | (1 - p) quantile of the last day | the top p of each day, whatever its source |
| SPOT | adds s_t - t to the tail fit when t < s_t <= z_q | the band (t, tau_t] |
| DSPOT | as SPOT on s_t minus a moving mean of non-alarm values | the band, plus every non-alarm value through the mean |
| tighten-only | min(ceiling, tracker); the ceiling rises only through a permit | downward only, unless a permit fires |

A rule can loosen (raise tau_t) only through values in the part of its learning region that pushes
upward. That gives three attacker classes, from weakest to strongest:

- **A0, no attacker.** Real attacks are themselves exceedances. A rule whose upward learning region
  includes exceedances is poisoned by the attacks it is meant to detect.
- **A1, open-loop injection.** The attacker can perturb one control loop (setpoints or sensor readings)
  without seeing the monitor. Supra-threshold pulses land in the exceedance region; sub-alarm pulses land
  in the band.
- **A2, closed-loop.** The attacker can read tau_t (white-box, or by probing) and shape the score. Holding
  s_t at 0.97 tau_t places every sample at the top of the band with no alarm. We evaluate A2 at the score
  level, an upper bound on what a physical attacker can do, and through noise spoofed onto three sensor
  readings of one loop, scored by the real monitor.

The attacker's goal is a terminal attack that the frozen threshold would detect but the adapted
threshold does not.

---

## 4. Monitor, rules and data

**Monitor.** D1 is the world-model residual monitor of our earlier registered studies on HAI: an
action-conditioned ridge regression with LightGBM residual corrections (60 trees, history 3) predicts
each sensor one and five steps ahead; the score is the mean of the three largest standardised absolute
residuals at each horizon, summed and smoothed over 60 s. D0 is a model-free control: the mean of the
three largest standardised first differences. Both are calibrated on the most recent 20% of normal
training data to 2 false-alarm episodes per day (episodes merged across 60 s gaps).

**Rules.** frozen (tau_0 at the budget); margin (tau_0 + 0.25 x the spread between the calibration 99.9th
percentile and median); daily (trailing-day quantile at the calibration exceedance rate p); tracker
(eta = 0.01 x spread) and tracker_slow (eta / 10, the best false-alarm adherence among trackers in
development); tighten-only with four automatic permits and an oracle permit that simulates an operator
who refuses to loosen while an event is under way; SPOT and DSPOT with method-of-moments and
maximum-likelihood tail fits [Hosking and Wallis 1987; Siffer et al. 2017].

**Data.**

| Dataset | System | Training data | Final data | Events |
|---|---|---|---|---|
| HAI 20.07 (primary) | HIL testbed (boiler, turbine, water treatment) | 547,624 s normal, 31 sensors, 20 actions | test1 + test2, 5.15 days | 38 attacks |
| HyGrid-ICS | simulated hybrid grid SCADA, 5 Hz to 1 Hz | 9.6 h (label-blind first 40%) | 14.5 h | 91 attacks |
| voraus-AD | industrial robot, 100 Hz to 10 Hz | 948 normal runs | 1174 runs | anomalous runs |
| HAI 21.03, 22.04, 23.05 (development) | HIL testbed | normal training data | spent test files | 50, 58, 52 attacks |
| BATADAL (registered replication) | water distribution network, 15 min | 384 days normal | two test files, 260 days | 14 attacks |

**Registration.** The protocol fixed the monitor, splits, rules, injection designs, gates and seeds; the
harness recorded one ledger entry per dataset before reading a test array, refused to run if a frozen
file's SHA-256 differed from the registration, and computed the gates from its own output. A verifier
checks that each access followed the registration commit, that each dataset was opened once, and that
the stored gates match a recomputation (27 of 27 checks pass).

---

## 5. How the hypothesis changed during development

All development used normal training data and the already-opened attack files of HAI 21.03, 22.04 and
23.05. We report it because the registered claim differs from the one we set out to test.

1. *Tighten-only with automatic loosening.* Our starting design let a threshold tighten itself and
   loosen only through a statistical permit. A slow sub-threshold drift ("boiling frog" in the style of
   Rubinstein et al.) did not poison any rule: the world model absorbed the drift. Supra-threshold
   pulses did inflate the trackers, but every automatic permit we tried either opened under the pulses
   (spread permit: 3 of 30 terminal attacks caught) or failed to follow benign drift (shift permit).
2. *Static safety margin.* A margin at half the calibration exceedance rate held the budget on
   pseudo-deployment splits but cost 4 to 10 points of recall on the spent attacks (interval lower bounds
   down to -0.17), so we registered a smaller margin and made it secondary.
3. *Frozen versus adaptive.* On the spent attacks the frozen threshold held the budget on all three real
   test periods (0.66, 1.48 and 1.27 episodes per day), while the tracker lost 22, 31 and 37 points of
   recall with intervals entirely below zero. This became the registered primary.

---

## 6. Registered results

### 6.1 Primary: HAI 20.07

| Gate | Registered test | Result |
|---|---|---|
| G1 | after a pulse campaign (12 x 120 s per day at twice the terminal magnitude), daily, tracker and tracker_slow detect the terminal step in at most (frozen - 0.5) of placements; frozen at least 0.8 | frozen 10/10, each adaptive rule 0/10: pass |
| G2 | recall(tracker) - recall(frozen) on the real attacks, 95% paired event bootstrap upper bound below 0 | 0.526 vs 0.947, -0.42 [-0.58, -0.26]: pass |
| G3 | frozen false-alarm episodes per day on unlabelled test time at most 4 | 2.23: pass (above the 2.0 budget) |

G1 passes as registered, but on this stream the pulses were not needed: the adaptive rules also missed
the terminal step in the control runs, because the test stream's real attacks had already raised their
thresholds 7 to 26 times above tau_0. The pulse effect in isolation comes from development on attack-free
normal data (frozen 30/30; daily 4/30, tracker 1/30, tracker_slow 3/30).

### 6.2 Real attacks inflate adaptive thresholds

Recall against the frozen threshold (paired event bootstrap, 95%):

| Dataset (events) | frozen | daily | tracker | tracker_slow | tighten-only |
|---|---|---|---|---|---|
| HAI 20.07 (38 attacks) | 0.947 | 0.474 [-0.63, -0.32] | 0.526 [-0.58, -0.26] | 0.711 [-0.37, -0.11] | 0.947 |
| HyGrid-ICS (91 attacks) | 0.297 | 0.297 | 0.154 [-0.22, -0.08] | 0.165 [-0.21, -0.07] | 0.297 |
| voraus-AD (anomalous runs) | 0.334 | 0.148 [-0.21, -0.16] | 0.082 [-0.28, -0.22] | 0.213 [-0.14, -0.10] | 0.334 |

At HAI 20.07 attack onsets the median threshold stood at 25.6 tau_0 for daily recalibration, 12.9 for the
tracker and 6.4 for the slow tracker. HyGrid's daily rule equals frozen because its 14.5 h final never
completes a day.

### 6.3 False alarms

| Dataset | frozen | margin | daily | tracker | tracker_slow |
|---|---|---|---|---|---|
| HAI 20.07 (episodes/day) | 2.23 | 2.23 | 0.20 | 1.01 | 2.23 |
| HyGrid-ICS (episodes/day, 2.5 h unlabelled) | 19.2 | 0.0 | 19.2 | 19.2 | 19.2 |
| voraus-AD (FPR per run, target 0.05) | 0.081 | 0.033 | 0.086 | 0.012 | 0.014 |

Where an adaptive rule raised fewer false alarms than frozen, it bought them with the recall losses of
Section 6.2. The static margin matched frozen recall on HAI 20.07 and HyGrid-ICS and held voraus-AD's
target at a cost of 12 points of recall there.

---

## 7. Learning regions under attack (exploratory)

The analyses in this section were not registered. They use the spent HAI releases for development and
reopen the three tt1 datasets after their finals; every access is in the ledger.

### 7.1 Extreme-value thresholds escape natural poisoning on the HAI data

| Data | frozen | tracker | SPOT (moments) | SPOT (MLE) | DSPOT |
|---|---|---|---|---|---|
| HAI 21.03 / 22.04 / 23.05 | 1.00 / 0.76 / 0.60 | 0.78 / 0.45 / 0.23 | 1.00 / 0.79 / 0.58 | 1.00 / 0.79 / 0.60 | 1.00 / 0.79 / 0.60 |
| HAI 20.07 (post-hoc) | 0.947 | 0.526 | 0.947 | 0.921 [-0.08, 0.00] | 0.947 |

The exceptions: on HyGrid-ICS the moments SPOT lost 9 points ([-0.15, -0.03]); on voraus-AD, 190
calibration runs leave about four tail points and SPOT ran at 32% false positives against a 5% target.

### 7.2 The effect does not depend on the score

With D0 the tracker lost recall on every dataset where it was measured: [-0.38, -0.14], [-0.21, -0.05]
and [-0.19, -0.02] on the spent releases, [-0.32, -0.08] on HAI 20.07 and [-0.12, -0.02] on HyGrid-ICS.

### 7.3 Mechanism: attacks that follow attacks

The tracker's misses concentrate on attacks that start within 6 h of the previous attack's end. D1 recall
on close versus isolated attacks was 0.75 / 1.00, 0.41 / 1.00 and 0.20 / 0.67 on the spent releases and
0.48 / 0.71 on HAI 20.07 (31 close, 7 isolated). The frozen threshold also detected close attacks less
often on two releases, so part of the gap reflects harder attacks; the tracker's gap is larger on every
release.

### 7.4 Loud poisoning: pulse campaigns

Normal data of the spent releases, 30 placements; the terminal step is the smallest setpoint step the
frozen threshold detects on the clean stream.

| Campaign | frozen | daily | tracker | tracker_slow | SPOT | DSPOT |
|---|---|---|---|---|---|---|
| 12 x 120 s supra-threshold pulses per day | 30/30 | 4/30 | 1/30 | 3/30 | 29/30 | 23/30 (control 25/30) |
| 24 x 300 s sub-alarm pulses per day, open loop | 30/30 | 23/30 (control 23/30) | 19/30 (control 21/30) | 23/30 | 29/30 | 22/30 (control 24/30) |

Open-loop sub-alarm pulses did not poison SPOT: its threshold fell (0.82 to 0.98 tau_0), and many pulses
crossed SPOT's own alarm level and were refused.

### 7.5 Silent poisoning: the closed-loop frog

Score-level attacker A2, normal data of the spent releases, 10 placements each: the attacker holds the
score at 0.97 tau_t, then 1 h later a 600 s bump at 1.05 tau_0 follows.

| Rule | 24 h campaign | 6 h | 1 h | open loop, fixed level, 24 h |
|---|---|---|---|---|
| frozen, tracker, tracker_slow, tighten-only | as control | as control | as control | as control |
| SPOT (moments) | 0/30 | 0/30 | 0/30 | not moved; alarms throughout |
| DSPOT | 0/30 | 0/30 | 0/30 | not moved; alarms throughout |
| SPOT (MLE, refit every 2048 peaks) | 8/30 | 8/30 | 13/30 | 11/30 |

Each rule is compared with its own control (the same bump without a campaign). The frozen and both SPOT
controls caught 30/30 and DSPOT's 24/30; the tracker and daily controls already missed some bumps on the
drifting releases, and the campaign did not lower them further. After 1 h the moments SPOT threshold
stood at 1.1 to 4.5 tau_0; after 24 h it had grown by more than five orders of magnitude, and the MLE fit
left the floating-point range on one release. On light-tailed synthetic scores SPOT did not run away
(0.94 to 0.97 tau_0 after 24 h), so the effect depends on the heavy tail of real residual scores.

**A physically realizable version.** The score-level attacker sets the score directly. We also gave the
attacker only the readings of three sensors coupled to one setpoint channel. Every 5 minutes it reads the
rule's threshold and spoofs the largest zero-mean noise whose D1 score, computed by the real world model
on the spoofed history, stays at 0.97 of that threshold; after 6 h it stops, and 1 h later the
just-detectable setpoint step follows. This attacker is white-box: it can run the monitor.

| Rule | Terminal caught (attack / control), 12 placements | Threshold at the terminal step |
|---|---|---|
| frozen | 12 / 12 | 1.0 tau_0 |
| SPOT (MLE) | 4 / 12 | 1.04 to 1.59 tau_0 (median per release) |
| SPOT (moments) | 6 / 12 | up to 7.6 tau_0 |
| DSPOT | 9 / 9 | 0.88 to 1.12 tau_0 |

On HAI 22.04 both SPOT variants missed the terminal step on all four placements, and the campaign raised
no alarm. The spoofed noise had a scale of 0.02 to 0.04 robust units. DSPOT was not moved: its moving
mean follows the noise-driven rise, so the attacker's cap rises with it rather than with the tail.

### 7.6 Registered replication on BATADAL

We registered a second study (tt1b) to test the exploratory findings of Sections 7.1 and 7.5 on data no
analysis here had opened: the C-Town network of BATADAL [Taormina et al. 2018], re-simulated without the
original concealment [Erba et al. 2020], put on a 15-minute grid. All time-scale settings were fixed in
physical time before access: 1 h smoothing, episodes merged across 1 h, one false-alarm episode per week,
a one-day DSPOT mean. The test files hold 14 attacks in 260 days.

| Hypothesis | Registered test | Result |
|---|---|---|
| H1 | recall(tracker) - recall(frozen), interval upper bound below 0 | 6/14 vs 14/14, -0.57 [-0.79, -0.29]: pass |
| H2 | recall(MLE SPOT) - recall(frozen), lower bound at least -max(0.10, 2/N) | 14/14, difference 0: pass |
| H3 | 24 h closed-loop frog: DSPOT at least 0.5 below its control; frozen and tighten-only within 0.1 | DSPOT already 0/10 in the control: fail |

H3 failed because real attacks had already blinded DSPOT: its threshold stood 24 times above tau_0 at
attack onsets, and it detected 6 of 14 attacks. BATADAL attacks last days, and the smoothed score spends
long stretches in the band below the alarm level, which is exactly where moments SPOT and DSPOT learn.

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

With the model-free D0 score, MLE SPOT also lost recall (9/14, [-0.64, -0.14]). The margin and the
tracker step are scaled by the calibration spread (99.9th percentile minus median); BATADAL's residual
scores are heavy-tailed, so the margin sat 173 times above tau_0. Parameters scaled by a tail spread are
fragile when the tail is heavy.

---

## 8. Design guidance

A threshold rule's learning region is its attack surface. Every automatic loosening path we tested could
be pushed upward: exceedance tracking and daily recalibration by real attacks and by loud pulses; tail
refitting and moving-mean drift tracking by a closed-loop attacker; the spread and shift permits by
pulses and by benign drift. The rules that held were the ones that never loosen themselves: frozen,
static margin, and tighten-only without a permit or with an operator-gated one.

We therefore recommend:

1. **Let thresholds tighten automatically, never loosen.** A tracker capped at the calibrated threshold
   keeps the frozen threshold's recall on every dataset here and can only add sensitivity in quiet
   periods.
2. **Route loosening through an operator** who confirms the plant is in normal operation, and treat a
   request to loosen during or soon after an alarm as suspect.
3. **Recalibrate offline on verified clean data**, as a change-controlled event, when drift raises false
   alarms; our frozen thresholds held 0.66 to 2.23 episodes per day on four HAI test periods.
4. **Watch the threshold.** Log tau_t; a threshold that rises during an incident, or climbs steadily
   without alarms, is itself an indicator.

The cost is false alarms under benign upward drift: on a development split of HAI 23.05 the tighten-only
rule ran at 5.98 times the budget against 4.05 for the frozen threshold. A static margin halves that cost
on some plants (HAI 23.05 development: 0.58 times the budget) and costs recall on others (voraus-AD: 12
points).

---

## 9. Limitations

- Two registered studies with one primary dataset each; HAI 20.07 shares a testbed with the
  development releases, and BATADAL has 14 attacks.
- HyGrid-ICS is a single simulated day with 2.5 h of unlabelled final time; voraus-AD anomalies are not
  attacks.
- The pulse campaigns and the score-level frog are synthetic; the frog assumes the attacker can read the
  threshold.
- SPOT's behaviour depends on the tail estimator and on the score's tail shape; we report both.
- Event recall counts any alarm inside a labelled interval; we do not model operator response time.
- Our monitor is one world-model residual and one model-free score; reconstruction-based detectors were
  not tested.

---

## 10. Conclusion

On four never-opened datasets, adaptive thresholds that learn from exceedances missed attacks that a
frozen threshold caught, because earlier attacks had raised them. Extreme-value thresholds avoided that
failure on the HAI data but not on days-long BATADAL attacks, and an attacker who stayed under them could
drive them upward without an alarm. A threshold that only tightened itself matched the frozen threshold's
recall on all seven datasets we examined.

---

## References (to complete and check)

- Ahmed, C. M., Palleti, V. R., Mathur, A. P. WADI: a water distribution testbed for research in the
  design of secure cyber physical systems. CySWATER 2017.
- Chan-Tin, E., Feldman, D., Hopper, N., Kim, Y. The frog-boiling attack: limitations of anomaly detection
  for secure network coordinate systems. SecureComm 2009.
- Erba, A., Taormina, R., Galelli, S., Pogliani, M., Carminati, M., Zanero, S., Tippenhauer, N. O.
  Constrained concealment attacks against reconstruction-based anomaly detectors in industrial control
  systems. ACSAC 2020.
- Gibbs, I., Candes, E. Adaptive conformal inference under distribution shift. NeurIPS 2021.
- Goh, J., Adepu, S., Junejo, K. N., Mathur, A. A dataset to support research in the design of secure
  water treatment systems. CRITIS 2016.
- Hong, Z. The boiling frog threshold: criticality and blindness in world model-based anomaly detection
  under gradual drift. arXiv:2603.08455, 2026.
- Hosking, J. R. M., Wallis, J. R. Parameter and quantile estimation for the generalized Pareto
  distribution. Technometrics 29(3), 1987.
- Hundman, K., Constantinou, V., Laporte, C., Colwell, I., Soderstrom, T. Detecting spacecraft anomalies
  using LSTMs and nonparametric dynamic thresholding. KDD 2018.
- ISA. ANSI/ISA-18.2-2016, Management of alarm systems for the process industries. [VERIFY]
- Kloft, M., Laskov, P. Online anomaly detection under adversarial impact. AISTATS 2010.
- Kravchik, M., Shabtai, A. Can't boil this frog: robustness of online-trained autoencoder-based anomaly
  detectors to adversarial poisoning attacks. arXiv:2002.02741, 2020.
- Rubinstein, B. I. P., Nelson, B., Huang, L., Joseph, A. D., Lau, S., Rao, S., Taft, N., Tygar, J. D.
  ANTIDOTE: understanding and defending against poisoning of anomaly detectors. IMC 2009.
- Shin, H.-K., Lee, W., Yun, J.-H., Kim, H. HAI 1.0: HIL-based augmented ICS security dataset. CSET 2020.
- Siffer, A., Fouque, P.-A., Termier, A., Largouet, C. Anomaly detection in streams with extreme value
  theory. KDD 2017.
- Taormina, R., et al. The battle of the attack detection algorithms: disclosing cyber attacks on water
  distribution networks. J. Water Resour. Plann. Manage. 144(8), 2018.
- Brockmann, J. T., Rudolph, M., Rosenhahn, B., Wandt, B. The voraus-AD dataset for anomaly detection in
  robot applications. IEEE Transactions on Robotics, 2024.
- HyGrid-ICS: a hybrid cyber-physical security dataset for SCADA-based industrial control systems,
  v1.1.1. Zenodo, 2026. doi:10.5281/zenodo.23250890.
- Wu, R., Keogh, E. Current time series anomaly detection benchmarks are flawed and are creating the
  illusion of progress. IEEE TKDE, 2021. [VERIFY]
