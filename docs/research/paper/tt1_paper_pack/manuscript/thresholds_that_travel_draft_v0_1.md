# Thresholds That Travel: Adaptive Alarm Thresholds Let Attacks Through in ICS Anomaly Detection

Draft v0.1, 23 October 2026. Not for circulation. Target: ASIACCS 2027 (round 2, 11 December 2026) or
USENIX Security 2027 (cycle 2, 26 January 2027). Both are double-blind: the submission must drop the
author block, the repository link and the Zenodo DOIs, and point to an anonymized artifact instead.

Vyom Kulshrestha, Independent Researcher, India (ORCID 0009-0009-1434-7148)

Status: every number and citation was checked against the pack in a Claude Science review on
2026-10-23 (126 of 138 numbers matched; the 9 mismatches and 3 untraceable numbers are fixed in this
revision). Revised 2026-11-01: Section 3.1 (Propositions 1 to 3), the post-hoc time-in-alarm,
onset-recall and attacks-only analyses (Sections 6.2, 6.3, 7.3), the tighten-only framing, the D0
sentence and an ethics appendix. The new numbers come from `threshold_transfer_tt1_memory_check.json`
and `threshold_transfer_tt1_posthoc_alarm_time.json` and have not yet had an independent review.

---

## Abstract

Anomaly detectors for industrial control systems (ICS) raise an alarm when a score crosses a threshold.
The threshold is calibrated on clean data and must then hold a false-alarm budget for months, so
deployments often let it adapt: they recalibrate it daily, track a running quantile, or refit an
extreme-value tail as data arrive. Each rule learns from part of its input, and we ask what happens
when attacks land there.

In two pre-registered studies on data that no earlier analysis in our pipeline had opened, a symmetric
quantile tracker lost recall against a frozen threshold. It detected 20 of HAI 20.07's 38 attacks against
36 (difference -0.42, 95% interval [-0.58, -0.26]) and 6 of BATADAL's 14 against 14 (-0.57,
[-0.79, -0.29]), and every attack it caught, the frozen threshold caught too. Rerun post-hoc with an
update that saw only the attack samples, it lost as much on HAI 20.07 (20 of 38) and nearly as much on
BATADAL (7 of 14). A short analysis explains why the loss lasts: a tracker calibrated to HAI 20.07's
false-alarm rate needs 23 exceedance-free hours to undo one minute above its threshold, whatever its step
size. The BATADAL loss survives a stricter count in which an attack is detected only if an alarm begins
inside it; the HAI 20.07 loss does not (-0.16, [-0.37, 0.05]), because the frozen threshold there was in
alarm for 39% of the unlabelled time and was credited with attacks that arrived inside alarms already
running. Daily recalibration lost recall on HAI 20.07 under both counts.

On normal data of three earlier HAI releases (exploratory) we add two attacks. Twelve two-minute nuisance
alarms a day blinded every rule that learns from exceedances to a later, just-detectable setpoint step,
and a closed-loop attacker who held the score just under the current threshold drove streaming
extreme-value thresholds (SPOT, DSPOT) upward without raising an alarm. The registered test of that
attack on BATADAL could not be evaluated: fitted to a heavy-tailed calibration score, method-of-moments
SPOT and DSPOT started 49 and 46 times above calibration and were blind before any attack, so that
study's primary rule failed. A threshold that only tightens itself cannot miss an event the frozen
threshold catches; on BATADAL it cost 2.43 times the false-alarm budget, against 0.70 for the frozen
threshold. We argue that an alarm threshold may tighten itself but should loosen only with operator
approval, and we release the registrations, ledger and code.

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

The answer depends on the region, and none of the rules we tested that can raise their own threshold is
safe:

- **Rules that learn from exceedances are poisoned by real attacks.** An attack is a long exceedance, so
  a tracker raises its threshold during the attack and stays high afterwards. The next attack then
  arrives under an inflated threshold. On fresh HAI 20.07 data the tracker missed 18 of 38 attacks, 16
  of them attacks the frozen threshold caught; on BATADAL it missed 8 of 14, all caught by the frozen
  threshold. No adversarial planning is needed; the attacks in the recording did it.
- **The same rules can be poisoned on purpose and loudly.** Twelve two-minute pulses a day, the kind of
  nuisance alarm operators learn to acknowledge, raised these thresholds enough to hide a later attack
  that a frozen threshold caught every time (exploratory, attack-free development data).
- **Rules that refuse to learn from alarms can be poisoned silently.** An attacker who reads the current
  SPOT or DSPOT threshold and holds the score just under it feeds every sample into the fitted tail. The
  tail extends, the threshold rises, and the attacker follows it up. At the score level no alarm is
  raised. A physically realizable version that spoofs sensor noise blinded both SPOT variants on one
  release without an alarm, and raised alarms on another (exploratory).

A threshold that only tightens itself cannot be pushed above the frozen threshold by any of the three,
so it keeps the frozen threshold's recall by construction (Section 3.1). Its cost is extra false alarms
when the plant drifts upward. Loosening it is left to an operator, and that step carries no such
guarantee.

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
   inflate them: registered on HAI 20.07 and on the BATADAL water network (there also under a stricter
   onset count), with the cause isolated post-hoc by feeding the tracker only attack samples, and repeated
   on HyGrid-ICS, voraus-AD, three development releases and a second, model-free score (Sections 6 and
   7).
3. A learning-region analysis of adaptive thresholds: how long the tracker and daily recalibration
   remember an exceedance, as a function of the calibrated false-alarm rate alone (Section 3.1), and a
   matching attack for each class: supra-threshold pulse campaigns for exceedance learners and a
   closed-loop frog-boiling attack for extreme-value learners, including how the latter depends on the
   tail estimator (Section 7).
4. A design rule, supported by these results, for deployed detectors: thresholds may tighten
   themselves; loosening needs a human (Section 8).
5. The registration, access ledger, harness and verifier. [Anonymized artifact link.]

---

## 2. Background and related work

**ICS anomaly detection.** Process-level detectors learn normal behaviour from sensor and actuator
traces and flag deviations: residuals of a predictive model, reconstruction errors of an autoencoder, or
statistical bounds. Public testbed recordings with labelled attacks (SWaT [Goh et al. 2016], WADI
[Ahmed et al. 2017], BATADAL [Taormina et al. 2018], and the HAI releases [Shin et al. 2020 for HAI 1.0
(20.07); later releases are documented in the dataset repository]) are the usual benchmarks. Evaluations
typically fix one threshold per detector, chosen on clean data or, less defensibly, on the test labels.
Wu and Keogh [2023] list further benchmark pitfalls.

**Threshold rules.** Static thresholds come from a quantile or a false-alarm budget on clean data.
Adaptive variants recalibrate on a trailing window, track a target exceedance rate online
[Gibbs and Candes 2021], fit an extreme-value tail and update it per observation (SPOT, and DSPOT for
drifting streams [Siffer et al. 2017]), or recompute a level on a trailing window of smoothed errors
[Hundman et al. 2018]. Alarm-management practice in process plants treats nuisance and chattering alarms
as a condition to eliminate, with explicit alarm-rate targets [ANSI/ISA-18.2-2016]; operators who
acknowledge such alarms without investigating them are the failure mode our pulse campaigns exploit.

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

**Why poison rather than conceal.** An A2 attacker who can spoof sensors could also try to hide the
terminal attack directly, by spoofing the readings it disturbs. Poisoning moves that work earlier: after
the campaign the terminal step runs unmodified, so the attacker does not have to keep every reading it
changes consistent with normal operation, which constrained-concealment attacks must do [Erba et al.
2020]. We did not compare the two strategies. The A1 assumption that operators acknowledge recurring
alarms without investigating is the condition alarm-management standards try to remove [ANSI/ISA-18.2];
our pulse campaign adds twelve alarm episodes a day, and the frozen threshold alarmed on 92% of the pulses
on HAI 20.07 (registered E4).

### 3.1 How long a threshold remembers

Three facts follow from the update rules alone. They predict most of what Sections 6 and 7 measure.

**Proposition 1 (tracker memory).** Under q_{t+1} = q_t + eta(1[s_t > q_t] - p), each step with
s_t > q_t raises the threshold by eta(1 - p) and each other step lowers it by eta p. A rise built from E
exceedance steps therefore takes E(1 - p)/p quiet steps to undo, whatever the step size eta.

The calibrated exceedance rate p sets the memory. On HAI 20.07 (p = 7.2 x 10^-4 per second) the ratio is
1,385, so one minute above the threshold keeps it raised for 23 hours. On BATADAL (p = 0.0075 per
15-minute step) it is 133, so one step above the threshold keeps it raised for 33 hours. The step size
sets how high an exceedance lifts the tracker, not how long the lift lasts: on BATADAL, where eta is 6.9
tau_0 per step, one exceedance step lifts it by almost seven times tau_0. A slower tracker (tracker_slow,
eta/10) climbs less during a short attack but needs the same 1,385 quiet seconds per exceedance second to
come back down, which is why it lost recall too (Section 6.2). Recovery time bounds blind time from
above: the tracker misses a later attack only while it sits above that attack's score. Post-hoc checks on
the recorded trajectories agree with the proposition: every change of the tracker on the HAI 20.07 and
BATADAL test streams is a whole number of these up and down steps (largest deviation 7 x 10^-6 of a
step), and from the levels the tracker reached it would have needed 43 to 209 days of exceedance-free
data to return to tau_0.

**Proposition 2 (daily memory).** Daily recalibration sets the next day's threshold to the (1 - p)
quantile of the last day's N steps. An attack that holds the score above a level a for more than pN + 1
steps of one day lifts the next day's threshold to at least a. That is 64 seconds on HAI 20.07 and two
15-minute steps on BATADAL. The memory is one day, so daily recalibration is poisoned whenever attacks
fall on consecutive days, as they do in the HAI test files, and it still catches an attack whose first
day follows a quiet one. On BATADAL, whose attacks last one to five days and begin 1.7 to 24 days after
the previous one ends (post-hoc, from the recorded labels), it caught 14 of 14 with its threshold at 0.69
tau_0 at the median onset (registered tt1b).

**Proposition 3 (tighten-only).** If tau_t <= tau_0 at every step (tighten-only without a loosening
permit), every sample that alarms under the frozen threshold also alarms under tau_t. The rule therefore
detects every event the frozen threshold detects when any alarm inside the event counts, on any input and
against any attacker, adaptive ones included. What it can lose is false alarms. Under the stricter onset
count of Section 6.2 the guarantee need not hold, because a lower threshold can start an alarm episode
before an attack begins.

Proposition 3 means the tighten-only results below measure its cost, not its recall. On HAI 20.07,
HyGrid-ICS and voraus-AD its recall and false alarms equalled the frozen threshold's: the inflated tracker
under the cap kept it at tau_0 (post-hoc: on HAI 20.07 it sat below tau_0 in 0.4% of minutes). Its own
behaviour shows on BATADAL, where the tracker sat below tau_0 for 3.2% of the test time (post-hoc) and the
rule ran at 2.43 times the false-alarm budget against 0.70 for frozen (registered), and on a development
split of HAI 23.05 (5.98 against 4.05, exploratory). A loosening permit breaks the guarantee, even one
that only an operator could grant: with the registered oracle permit, a statistical permit that a
simulated operator blocks whenever the review window holds a labelled event, the rule caught the
terminal step in 1 of 10 control placements on HAI 20.07, against 10 of 10 for frozen.

---

## 4. Monitor, rules and data

**Monitor.** D1 is the world-model residual monitor of our earlier registered studies on HAI: an
action-conditioned ridge regression with LightGBM residual corrections (60 trees, history 3) predicts
each sensor one and five steps ahead; the score is the mean of the three largest standardised absolute
residuals at each horizon, summed and smoothed over 60 s. D0 is a model-free control: the mean of the
three largest standardised first differences. Both are calibrated on the most recent 20% of normal
training data: to 2 false-alarm episodes per day on the 1 Hz stream datasets (episodes merged across 60 s
gaps), to a per-sample false-alarm target of 0.05 on voraus-AD, and to one false-alarm episode per week on
BATADAL (episodes merged across 1 h).

**Rules.** frozen (tau_0 at the budget); margin (tau_0 + 0.25 x the spread between the calibration 99.9th
percentile and median); daily (trailing-day quantile at the calibration exceedance rate p); tracker
(eta = 0.01 x spread on the stream datasets, 0.05 x spread on voraus-AD) and tracker_slow (eta / 10, the
best false-alarm adherence among trackers in development); tighten-only with four automatic permits and an
oracle permit that simulates an operator who refuses to loosen while an event is under way: eleven rules
in all. On voraus-AD the spread is the calibration 99th percentile minus the median and daily
recalibration happens every 50 samples. The streaming extreme-value rules (SPOT and DSPOT, with
method-of-moments and maximum-likelihood tail fits [Hosking and Wallis 1987; Siffer et al. 2017]) were not
part of the tt1 registration: they enter in Section 7 as exploratory and post-hoc analyses and are
registered only in the BATADAL replication (tt1b).

**Data.**

| Dataset | System | Training data | Final data | Events |
|---|---|---|---|---|
| HAI 20.07 (primary) | HIL testbed (boiler, turbine, water treatment) | 547,624 s normal, 31 sensors, 20 actions | test1 + test2, 5.15 days | 38 attacks |
| HyGrid-ICS | simulated hybrid grid SCADA, 5 Hz to 1 Hz | 9.6 h (label-blind first 40%) | 14.5 h | 91 attacks |
| voraus-AD | industrial robot, 100 Hz to 10 Hz | 948 normal samples | 1174 samples | 755 anomalous samples |
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
   (spread permit: 3 of 30 terminal attacks caught in development round r3, 5 of 30 in round r4) or
   failed to follow benign drift (shift permit).
2. *Static safety margin.* A margin at half the calibration exceedance rate cut the false-alarm rate on
   pseudo-deployment splits without always reaching the budget (HAI 20.07 development: 3.79 episodes per
   day against 4.42 for frozen, budget 2), and cost 4 to 10 points of recall on the spent attacks
   (interval lower bounds down to -0.17), so we registered a smaller margin and made it secondary.
3. *Frozen versus adaptive.* On the spent attacks the frozen threshold held the budget on all three real
   test periods (0.66, 1.48 and 1.27 episodes per day), while the tracker lost 22, 31 and 37 points of
   recall with intervals entirely below zero. This became the registered primary.

---

## 6. Registered results

### 6.1 Primary: HAI 20.07

| Gate | Registered test | Result |
|---|---|---|
| G1 | after a pulse campaign (12 x 120 s per day at twice the terminal magnitude), daily, tracker and tracker_slow detect the terminal step in at most (frozen - 0.5) of placements; frozen at least 0.8 | frozen 10/10, each adaptive rule 0/10: pass, but uninformative (the adaptive controls were already 0/10) |
| G2 | recall(tracker) - recall(frozen) on the real attacks, 95% paired event bootstrap upper bound below 0 | 0.526 vs 0.947, -0.42 [-0.58, -0.26]: pass |
| G3 | frozen false-alarm episodes per day on unlabelled test time at most 4 | 2.23: pass (above the 2.0 budget; in alarm for 39% of the unlabelled time, post-hoc) |

False-alarm episodes per day are counted over the 4.94 days of unlabelled time inside the 5.15-day test
streams. G1 passes as registered, but on this stream the pulses were not needed: the adaptive rules also
missed the terminal step in the control runs, because the test stream's real attacks had already raised
their thresholds 7 to 26 times above tau_0. The pulse effect in isolation comes from development on
attack-free normal data (frozen 30/30; daily 4/30, control 21/30; tracker 1/30, control 23/30;
tracker_slow 3/30, control 25/30). Neither registered test of a deliberate campaign, G1 here or H3 on
BATADAL (Section 7.6), could show an effect, because the rules under test were already blind in the
controls; the campaign results in Section 7 are exploratory.

### 6.2 Real attacks inflate adaptive thresholds

Recall against the frozen threshold (paired event bootstrap, 95%):

| Dataset (events) | frozen | daily | tracker | tracker_slow | tighten-only |
|---|---|---|---|---|---|
| HAI 20.07 (38 attacks) | 0.947 | 0.474 [-0.63, -0.32] | 0.526 [-0.58, -0.26] | 0.711 [-0.37, -0.11] | 0.947 |
| HyGrid-ICS (91 attacks) | 0.297 | 0.297 | 0.154 [-0.22, -0.08] | 0.165 [-0.21, -0.07] | 0.297 |
| voraus-AD (755 anomalous samples) | 0.334 | 0.148 [-0.21, -0.16] | 0.082 [-0.28, -0.22] | 0.213 [-0.14, -0.10] | 0.334 |

At HAI 20.07 attack onsets the median threshold stood at 25.6 tau_0 for daily recalibration, 12.9 for the
tracker and 6.4 for the slow tracker. HyGrid's daily rule equals frozen because its 14.5 h final never
completes a day.

Every disagreement between an adaptive rule and the frozen threshold went one way. On HAI 20.07 the
frozen threshold caught 16 attacks the tracker missed and the tracker caught none that it missed (exact
McNemar p = 3.1 x 10^-5); the slow tracker split 9 to 0 (p = 0.0039) and daily recalibration 18 to 0
(p = 7.6 x 10^-6). On BATADAL the tracker split 8 to 0 (p = 0.0078). These counts are post-hoc, from the
recorded trajectories, which reproduce every registered event count.

**Time in alarm and onset recall (post-hoc).** Episode counts hide how long an alarm lasts. On HAI 20.07
the frozen threshold was in alarm for 39% of the unlabelled time. The D1 score sat above tau_0 for the
first 23.8 h of test1, of which the first 2.7 h carry no attack label and seven attacks begin inside the
rest, and for a 17-hour stretch of test2 that holds two attacks. An alarm episode that overlaps an attack
does not count as a false alarm, so the registered episode count records none of these hours. Ten of the
frozen threshold's 36 detections were attacks that began while one of these alarms was already running. Counting an attack only when an alarm episode starts inside it, the
frozen threshold detects 26 of 38, the tracker 20 (-0.16, [-0.37, 0.05]), the slow tracker 27 (+0.03,
[-0.18, 0.24]) and daily recalibration 11 (-0.40, [-0.55, -0.24]). On BATADAL the frozen threshold was in
alarm for 1.4% of the unlabelled time and the stricter count changes nothing (tracker -0.57,
[-0.79, -0.29]). On HyGrid-ICS (4.1% in alarm) the 91 attacks cover 83% of the final rows, about 100 s
apart on average, so one merged alarm episode spans several attacks and the stricter count credits few of
them: frozen 3 of 91, tracker 8 (+0.05, [0.00, 0.11]), slow tracker 5. There the stricter count reverses
the sign, but it measures how alarms merge across back-to-back attacks more than what the threshold
detects. G2 stands as registered, but the tracker's HAI 20.07 gap depends on crediting the frozen
threshold's long alarms; the BATADAL gap does not (`threshold_transfer_tt1_posthoc_alarm_time.json`). An
earlier post-hoc variant hid each file's opening run above tau_0 from the threshold update and gave
tracker -0.29 [-0.45, -0.16] and slow tracker -0.08 [-0.18, 0.00]; we superseded it because the opening
run of test1 turned out to contain seven attacks (`threshold_transfer_tt1_posthoc_transient.json`).

### 6.3 False alarms

| Dataset | frozen | margin | daily | tracker | tracker_slow |
|---|---|---|---|---|---|
| HAI 20.07 (episodes/day) | 2.23 | 2.23 | 0.20 | 1.01 | 2.23 |
| HyGrid-ICS (episodes/day, 2.5 h unlabelled) | 19.2 | 0.0 | 19.2 | 19.2 | 19.2 |
| voraus-AD (per-sample FPR, target 0.05) | 0.081 | 0.033 | 0.086 | 0.012 | 0.014 |

Where an adaptive rule raised fewer false alarms than frozen, it bought them with the recall losses of
Section 6.2. The one rule that cut false alarms at no recall cost here, the static margin on HyGrid-ICS
(0.0 against 19.2 per day at identical recall), does not adapt. The margin matched frozen recall on HAI
20.07 and held voraus-AD's target at a cost of 12 points of recall there. Counted in time rather than
episodes (post-hoc), the frozen threshold was in alarm for 39% of the unlabelled time on HAI 20.07, 4.1% on
HyGrid-ICS and 1.4% on BATADAL; the tracker for 0.2%, 0.3% and 0.4%. Tighten-only equalled the frozen
threshold on all three tt1 datasets (2.23, 19.2 and 0.081).

### 6.4 Other registered outcomes

The protocol commits us to report every rule, gate and failure. The rest of the registered record:

| HAI 20.07 rule | Recall | vs frozen | False alarms per day | Permits per week |
|---|---|---|---|---|
| tighten-only, spread permit (daily review) | 26/38 | -0.26 [-0.39, -0.13] | 1.62 | 2.7 |
| tighten-only, spread permit (6 h review) | 28/38 | -0.21 [-0.34, -0.08] | 2.63 | 4.1 |
| tighten-only, shift permit (daily review) | 32/38 | -0.11 [-0.21, -0.03] | 1.01 | 4.1 |
| tighten-only, shift permit (6 h review) | 31/38 | -0.13 [-0.24, -0.03] | 2.02 | 12.2 |
| tighten-only, oracle permit | 36/38 | 0 | 2.23 | 0 |

- **Automatic permits.** Every automatic loosening permit lost recall on HAI 20.07. On voraus-AD all four
  lost recall too (95% intervals: spread [-0.21, -0.15] with daily review and [-0.28, -0.21] with 6 h
  review; shift [-0.18, -0.13] and [-0.21, -0.15]); on HyGrid-ICS only the 6 h shift permit did (24 of
  91, [-0.08, 0.00]).
- **Oracle permit.** On the real attacks it equalled frozen, but in the G1 campaign runs it caught the
  terminal step in 7 of 10 placements after the pulses and 1 of 10 in the control.
- **First and second half of the HAI 20.07 events.** Recall was 0.947 / 0.947 for frozen, 0.474 / 0.579
  for the tracker, 0.579 / 0.842 for the slow tracker and 0.474 / 0.474 for daily recalibration.
- **E5, sub-threshold noise campaign.** Only 1 of 13 placements admitted a stealthy noise level; 12 had
  none, so E5 gives no result.
- **BATADAL frog variants** are in Section 7.6. A separate registration that shared the HAI 20.07 and
  HyGrid-ICS access (detection-v2) is reported on its own.

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
calibration samples leave about four tail points above SPOT's base level (the calibration 98th
percentile), and SPOT ran at 32% false positives against a 5% target. On the HAI data the extreme-value
thresholds started near calibration: at the start of both HAI 20.07 test files the moments SPOT stood at
1.09 tau_0, DSPOT at 1.03 to 1.05 and MLE SPOT at 1.18 (post-hoc). Section 7.6 shows what a heavier
calibration tail does to that starting point.

### 7.2 The effect does not depend on the score

With D0 the tracker lost recall on every dataset where it was measured: [-0.38, -0.14], [-0.21, -0.05]
and [-0.19, -0.02] on the spent releases (exploratory), [-0.32, -0.08] on HAI 20.07, [-0.12, -0.02] on
HyGrid-ICS and [-0.04, -0.01] on voraus-AD (post-hoc), and [-0.86, -0.36] on BATADAL (registered tt1b).

### 7.3 Mechanism: attacks that follow attacks

The tracker's misses concentrate on attacks that start within 6 h of the previous attack's end. D1 recall
on close versus isolated attacks was 0.75 / 1.00, 0.41 / 1.00 and 0.20 / 0.67 on the spent releases and
0.48 / 0.71 on HAI 20.07 (31 close, 7 isolated). The frozen threshold also detected close attacks less
often on two releases, so part of the gap reflects harder attacks; the tracker's gap is larger on every
release.

Attacks are the main thing that raises the tracker. Rerun post-hoc with its update fed only the
attack-labelled samples (the others replaced by the calibration median for the update, alarms still on
the real score), the tracker detected 20 of 38 on HAI 20.07 and 14 of 91 on HyGrid-ICS, exactly its
registered counts, and 7 of 14 on BATADAL (6 registered). Fed only the unlabelled samples, it detected 28
of 38, 27 of 91 (equal to frozen) and 11 of 14: the unlabelled exceedances add a smaller loss of their
own, -0.21 [-0.34, -0.08] on HAI 20.07 and -0.21 [-0.43, 0.00] on BATADAL.

### 7.4 Loud poisoning: pulse campaigns

Normal data of the spent releases, 30 placements; the terminal step is the smallest setpoint step the
frozen threshold detects on the clean stream.

| Campaign | frozen | daily | tracker | tracker_slow | SPOT | DSPOT |
|---|---|---|---|---|---|---|
| 12 x 120 s supra-threshold pulses per day | 30/30 (control 30/30) | 4/30 (control 21/30) | 1/30 (control 23/30) | 3/30 (control 25/30) | 29/30 (control 30/30) | 23/30 (control 25/30) |
| 24 x 300 s sub-alarm pulses per day, open loop | 30/30 | 23/30 (control 23/30) | 19/30 (control 21/30) | 23/30 | 29/30 | 22/30 (control 24/30) |

Open-loop sub-alarm pulses did not poison SPOT: its threshold fell (0.82 to 0.98 tau_0), and many pulses
crossed SPOT's own alarm level and were refused.

### 7.5 Silent poisoning: the closed-loop frog

Score-level attacker A2, normal data of the spent releases, 10 placements each: the attacker holds the
score at 0.97 tau_t, then, after a one-hour lead, a 600 s bump at 1.05 tau_0 follows (600 s is the
terminal length of every development campaign).

| Rule | 24 h campaign | 6 h | 1 h | open loop, fixed level, 24 h |
|---|---|---|---|---|
| frozen, tracker_slow, tighten-only | as control | as control | as control | as control |
| tracker | as control | as control | as control | 16/30 (control 20/30) |
| SPOT (moments) | 0/30 | 0/30 | 0/30 | not moved; alarms throughout |
| DSPOT | 0/30 | 0/30 | 0/30 | not moved; alarms throughout |
| SPOT (MLE, refit every 2048 peaks) | 8/30 | 8/30 | 13/30 | 11/30 |

Each rule is compared with its own control (the same bump without a campaign). The frozen and both SPOT
controls caught 30/30 and DSPOT's 24/30; the tracker and daily controls already missed some bumps on the
drifting releases, and the campaign did not lower them further. After 1 h the moments SPOT threshold
stood at 1.1 to 4.5 tau_0; after 24 h it had grown by more than five orders of magnitude, and the MLE fit
left the floating-point range on one release. A synthetic control with a light tail (the 60-step moving
average of |N(0, 1)|, five seeds) did not run away: the moments SPOT threshold stayed at 0.95 to 0.97 tau_0
and caught every terminal bump, and maximum-likelihood SPOT rose only to 1.02 to 1.04 tau_0, though it
missed the bump on one of the five seeds in the 24 h, 6 h and fixed-level variants. The runaway therefore
depends on the heavy tail of real residual scores.

**A physically realizable version.** The score-level attacker sets the score directly. We also gave the
attacker only the readings of three sensors coupled to one setpoint channel. Every 5 minutes it reads the
rule's threshold and spoofs the largest zero-mean noise whose D1 score, computed by the real world model
on the spoofed history, stays at 0.97 of that threshold; after 6 h it stops, and 1 h later the
just-detectable setpoint step follows. This attacker is white-box: it can run the monitor.

| Rule | Terminal steps caught, after campaign / in control (of 12 placements) | Threshold at the terminal step (median per release) |
|---|---|---|
| frozen | 12 / 12 | 1.0 tau_0 |
| SPOT (MLE) | 4 / 12 | 1.04 to 1.59 tau_0 |
| SPOT (moments) | 6 / 12 | 0.78 to 1.42 tau_0 |
| DSPOT | 9 / 9 | 0.88 to 1.12 tau_0 |

Controls caught 12 of 12 for frozen and both SPOT variants and 9 of 12 for DSPOT, so the campaign did not
change DSPOT. On HAI 22.04 both SPOT variants missed the terminal step on all four placements, and the
campaign raised no alarm. On HAI 23.05 it was not silent: the frozen threshold raised a median of 190
alarm steps during the campaign, and the SPOT variants 154 to 171. The spoofed
noise had a scale of 0.02 to 0.04 robust units against frozen and the SPOT variants, and 0.05 to 0.12
against DSPOT, whose moving mean follows the noise-driven rise, so the attacker's cap rises with the mean
rather than with the tail.

### 7.6 Registered replication on BATADAL

We registered a second study (tt1b) to test the exploratory findings of Sections 7.1 and 7.5 on data no
analysis here had opened: the C-Town network of BATADAL [Taormina et al. 2018], whose original attacks
conceal themselves in the SCADA readings, in the re-simulation without that concealment published with
the artifact of Erba et al. [2020], put on a 15-minute grid. All time-scale settings were fixed in
physical time before access: 1 h smoothing, episodes merged across 1 h, one false-alarm episode per week,
a one-day DSPOT mean. The test files hold 14 attacks in 260 days.

| Hypothesis | Registered test | Result |
|---|---|---|
| H1 | recall(tracker) - recall(frozen), interval upper bound below 0 | 6/14 vs 14/14, -0.57 [-0.79, -0.29]: pass |
| H2 | recall(MLE SPOT) - recall(frozen), lower bound at least -max(0.10, 2/N) | 14/14, difference 0: pass |
| H3 | 24 h closed-loop frog: DSPOT at least 0.5 below its control; frozen and tighten-only within 0.1 | DSPOT already 0/10 in the control: fail |
| Primary rule | H1 and H2 and H3 | fail |

We retain the primary rule as registered and report H3 as uninformative rather than refuted. H2 passes
under the registered bootstrap, whose interval is [0, 0] because no event was discordant; an exact
one-sided 97.5% bound for 0 discordant events in 14 is -0.23, beyond the -0.14 tolerance, so H2 is not
informative under an exact method. SWaT and WADI are registered under the same protocol and were
requested on 2026-10-23; they run once their loaders are added by amendment, and the replication claim is
the set of per-dataset outcomes.

H3 could not be tested because DSPOT's control was already blind, and the blindness predates the attacks.
Fitted by the method of moments to BATADAL's heavy-tailed calibration scores (spread 6,462 against
tau_0 = 9.39), SPOT's alarm level started at 49.0 tau_0 and DSPOT's at 45.8 tau_0 at the first step of each
test file, and both fell through the streams, to 24 to 44 tau_0 at the first attack (post-hoc
trajectories; the registered per-event onset inflation agrees). Rerun with no attack sample in their
update, SPOT still caught 6 of 14 and DSPOT 7 of 14 (post-hoc). MLE SPOT started at 1.22 tau_0 and caught
all 14. On BATADAL the moments-based extreme-value rules were blind from their calibration fit, not
poisoned by the attacks.

The registered frog variants (10 placements each) did test MLE SPOT. Under the 24 h closed-loop frog it
caught the terminal attack in 7 of 10 placements against 9 of 10 in its control with D1, and in 0 of 10
against 4 of 10 with D0; with 6 h and 1 h campaigns it matched its D1 control and caught 2 and 4 of 10
against 4 with D0. Frozen and tighten-only caught 10 of 10 in every variant, daily recalibration 9 of 10,
the margin none, and the tracker, SPOT and DSPOT at most 1 of 10 with or without a campaign. The frozen threshold detected
the 14 real attacks a median 3.5 steps (52 minutes) after onset and at most 65 steps (16.3 h) after.

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
be pushed upward: exceedance tracking and daily recalibration by real attacks (registered) and by loud
pulses (exploratory); tail refitting and moving-mean drift tracking by a closed-loop attacker
(exploratory); the spread and shift permits by pulses and benign drift in development, and on the
registered HAI 20.07 stream all four lost recall (Section 6.4). The rules that held were the ones that
never loosen themselves: frozen, and tighten-only without a permit. An operator-gated permit is only as
good as the operator; our stand-in, which blocked loosening only while a labelled event was in its review
window, caught 1 of 10 terminal steps in the G1 controls. A static margin never loosens either, but it is
not safe by construction: on BATADAL its spread-scaled offset sat 173 times above tau_0 and it caught 3 of
14 attacks, the largest recall loss we measured.

We therefore recommend:

1. **Let thresholds tighten automatically, never loosen.** A tracker capped at the calibrated threshold
   cannot lose an event the frozen threshold catches (Proposition 3) and can only add sensitivity in
   quiet periods.
2. **Route loosening through an operator** who confirms the plant is in normal operation, and treat a
   request to loosen during or soon after an alarm as suspect.
3. **Recalibrate offline on verified clean data**, as a change-controlled event, when drift raises false
   alarms. Our frozen thresholds held 0.66 to 1.48 episodes per day on the three development test periods
   and 2.23 on HAI 20.07 against a budget of 2, but on HAI 20.07 the threshold was in alarm for 39% of the
   unlabelled time, the kind of drift an offline recalibration should catch.
4. **Watch the threshold.** Log tau_t; a threshold that rises during an incident, or climbs steadily
   without alarms, is itself an indicator.
5. **Budget alarm time as well as episodes.** On HAI 20.07 a 24-hour alarm that overlapped seven attacks
   did not count against the episode budget at all, and an attack that begins inside a running alarm
   gives the operator nothing new to see.

The cost is false alarms under benign upward drift. On BATADAL the tighten-only rule ran at 2.43 times the
budget against 0.70 for the frozen threshold (registered); on a development split of HAI 23.05 at 5.98
against 4.05, and a ten times slower tracker under the cap brought it to 4.05 (exploratory). A static
margin can cut that cost
on some plants (HAI 23.05 development: 0.58 times the budget) but costs recall on others (voraus-AD: 12
points; BATADAL: 11 of 14 attacks), and should not be used where the calibration spread is set by a heavy
tail.

---

## 9. Limitations

- Two registered studies with one primary dataset each; HAI 20.07 shares a testbed with the
  development releases, and BATADAL has 14 attacks. Neither registered test of a deliberate campaign (G1,
  H3) could show an effect, so every campaign result is exploratory.
- Our adaptive baselines are the plain rules. None excludes alarm periods from its update, caps the
  tracker's rise or holds off after an alarm, we did not run Telemanom's dynamic threshold, and SPOT and
  DSPOT use moments or maximum-likelihood fits without declustering. Natural poisoning is shown for these
  rules, not for every adaptive threshold.
- On HAI 20.07 the monitor itself drifted: the frozen threshold was in alarm for 39% of the unlabelled
  time, which inflates its recall under the any-alarm count (Section 6.2).
- HyGrid-ICS is a single simulated day with 2.5 h of unlabelled final time; voraus-AD anomalies are not
  attacks. Post-hoc, 0.15% of HyGrid-ICS's label-blind development rows (251 short runs) carry an attack
  label, against 83% of its final rows, so its calibration is very slightly contaminated.
- The pulse campaigns and both frogs are synthetic. The score-level frog sets the score directly and reads
  tau_t; the physically realizable version also runs the monitor itself on the spoofed history to choose
  each noise scale. Both are white-box upper bounds.
- SPOT's behaviour depends on the tail estimator and on the score's tail shape; we report both.
- Parameters scaled by a calibration spread (the static margin and the tracker step) are fragile on
  heavy-tailed scores: on BATADAL the margin sat 173 times above tau_0 and missed 11 of 14 attacks.
- Event recall counts any alarm inside a labelled interval, so it credits an attack that falls inside an
  alarm already running; on HAI 20.07 that gave the frozen threshold 10 of its 36 detections (Section
  6.2). We do not model operator response time.
- Our monitor is one world-model residual and one model-free score; reconstruction-based detectors were
  not tested.
- No claim of runtime authority, deployment safety or incident prevention follows from these results.

---

## 10. Conclusion

On two registered test sets, a quantile tracker that learns from exceedances missed attacks that a frozen
threshold caught, and post-hoc it lost as much when it learned from the attack samples alone. On BATADAL
the loss survives counting only alarms that start inside an attack; on HAI 20.07 it does not, because the
frozen threshold there sat in long alarms that covered later attacks. How long a tracker or a daily
recalibration stays raised follows from its calibrated false-alarm rate alone, so making the tracker
slower does not make it forget faster. Extreme-value thresholds escaped natural poisoning on the HAI data,
where a closed-loop attacker could drive them upward without an alarm (exploratory); on BATADAL their
method-of-moments versions were blind from calibration. A threshold that only tightens itself keeps the
frozen threshold's recall by construction; on BATADAL, the one registered dataset where its tightening
changed the alarms, it ran at 2.43 times the false-alarm budget against 0.70 for the frozen threshold.

---

## Ethical considerations

All experiments ran offline on public recordings: HAI 20.07 to 23.05, HyGrid-ICS, voraus-AD and the
BATADAL re-simulation, each used under its publisher's terms. No live plant, testbed, vendor product or
operator was involved, and no human subjects took part. The pulse campaigns and both frog attacks were
injected into recorded normal data or into the score; the physically realizable frog changes recorded
sensor values in software and is scored by our own monitor.

The attacks are not new in kind. Boiling-frog poisoning of self-updating detectors has been public since
2009 [Chan-Tin et al. 2009; Rubinstein et al. 2009], and the threshold rules we attack are textbook
algorithms. What the paper adds for an attacker is the observation that an adaptive threshold widens the
window for a later attack; what it adds for a defender is a rule that closes that window at a known
false-alarm cost. We judged that publishing both helps defenders more than attackers, because the defence
is a configuration change (cap the threshold at its calibrated value) that any operator of an adaptive
threshold can apply today. The released code generates attacks only against recorded data and a score
file; it contains no tooling for reaching a control network.

---

## References

Identifiers were confirmed in the Claude Science review of 2026-10-23 (`review/review_report.md`); entries
without one had no DOI confirmed there.

- Ahmed, C. M., Palleti, V. R., Mathur, A. P. WADI: a water distribution testbed for research in the
  design of secure cyber physical systems. CySWATER 2017.
- Chan-Tin, E., Feldman, D., Hopper, N., Kim, Y. The frog-boiling attack: limitations of anomaly detection
  for secure network coordinate systems. SecureComm 2009.
- Erba, A., Taormina, R., Galelli, S., Pogliani, M., Carminati, M., Zanero, S., Tippenhauer, N. O.
  Constrained concealment attacks against reconstruction-based anomaly detectors in industrial control
  systems. ACSAC 2020, pp. 480-495. doi:10.1145/3427228.3427660.
- Gibbs, I., Candes, E. Adaptive conformal inference under distribution shift. NeurIPS 2021.
  arXiv:2106.00170.
- Goh, J., Adepu, S., Junejo, K. N., Mathur, A. A dataset to support research in the design of secure
  water treatment systems. CRITIS 2016.
- Hong, Z. The boiling frog threshold: criticality and blindness in world model-based anomaly detection
  under gradual drift. arXiv:2603.08455, 2026.
- Hosking, J. R. M., Wallis, J. R. Parameter and quantile estimation for the generalized Pareto
  distribution. Technometrics 29(3), 1987.
- Hundman, K., Constantinou, V., Laporte, C., Colwell, I., Soderstrom, T. Detecting spacecraft anomalies
  using LSTMs and nonparametric dynamic thresholding. KDD 2018, pp. 387-395. doi:10.1145/3219819.3219845.
- ISA. ANSI/ISA-18.2-2016, Management of alarm systems for the process industries. 2016.
- Kloft, M., Laskov, P. Online anomaly detection under adversarial impact. AISTATS 2010, PMLR 9:405-412.
- Kravchik, M., Shabtai, A. Can't boil this frog: robustness of online-trained autoencoder-based anomaly
  detectors to adversarial poisoning attacks. arXiv:2002.02741, 2020.
- Rubinstein, B. I. P., Nelson, B., Huang, L., Joseph, A. D., Lau, S., Rao, S., Taft, N., Tygar, J. D.
  ANTIDOTE: understanding and defending against poisoning of anomaly detectors. IMC 2009.
- Shin, H.-K., Lee, W., Yun, J.-H., Kim, H. HAI 1.0: HIL-based augmented ICS security dataset. CSET 2020.
  arXiv:2005.02315.
- Siffer, A., Fouque, P.-A., Termier, A., Largouet, C. Anomaly detection in streams with extreme value
  theory. KDD 2017, pp. 1067-1075. doi:10.1145/3097983.3098144.
- Taormina, R., et al. The battle of the attack detection algorithms: disclosing cyber attacks on water
  distribution networks. J. Water Resour. Plann. Manage. 144(8):04018048, 2018.
  doi:10.1061/(ASCE)WR.1943-5452.0000969.
- Brockmann, J. T., Rudolph, M., Rosenhahn, B., Wandt, B. The voraus-AD dataset for anomaly detection in
  robot applications. IEEE Transactions on Robotics 40:438-451, 2024. doi:10.1109/TRO.2023.3332224.
- Yolcu, F. HyGrid-ICS: a hybrid cyber-physical security dataset for SCADA-based industrial control
  systems, v1.1.1. Zenodo, 2026. doi:10.5281/zenodo.23250890 (version); concept doi:10.5281/zenodo.23250468.
- Wu, R., Keogh, E. Current time series anomaly detection benchmarks are flawed and are creating the
  illusion of progress. IEEE TKDE 35(3):2421-2429, 2023. doi:10.1109/TKDE.2021.3112126.
