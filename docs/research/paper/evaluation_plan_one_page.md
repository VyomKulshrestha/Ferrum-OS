# Evaluation plan and outcome: "Thresholds That Travel"

Vyom Kulshrestha, 10 November 2026. One page, written for a reader outside industrial-control security.
All three registered studies are finished. The last column says what came out, including what failed.

## Claim

An anomaly detector raises an alarm when a score crosses a threshold. Many deployments let the threshold
adapt online. We claim that an adaptive threshold loses real attacks, because whatever a rule learns from
is something an earlier attack, or an attacker, can put there. A threshold should tighten itself freely
and loosen only inside a fixed band or with approval.

## Research questions

| | Question | Measure | Compared with | Outcome |
|---|---|---|---|---|
| RQ1 | Do adaptive thresholds miss recorded attacks that a fixed threshold catches? | Difference in attacks detected, 95 % paired bootstrap interval. Two counts: any alarm inside the attack, and an alarm that starts inside it. | The same detector with its threshold frozen at calibration | Registered. A quantile tracker caught 20 of 38 against 36 on HAI 20.07, 6 of 14 against 14 on BATADAL, and 66 of 104 against 104 on the later attacks of Tennessee Eastman runs. On ProvICS it lost nothing (25 of 32 each); the fixed threshold there was in alarm 44 % of the time. Under the stricter count the loss holds on BATADAL only. |
| RQ2 | Is the cause "attacks that follow attacks"? | The same difference, split into the first attack of a run and later ones. Predicted: a loss on later attacks, none on first ones. | Frozen threshold | Registered, Tennessee Eastman. As predicted under the first count: 116 of 141 first attacks each, 66 of 104 later attacks against 104. Under the stricter count the interval reaches zero ([-0.13, 0.00]), so study 3's primary condition failed. |
| RQ3 | Can an attacker blind each kind of rule on purpose? | Share of identical final attacks detected after a poisoning campaign, against a no-campaign control. Three campaigns: loud pulses, a silent attacker that holds the score just under the threshold, pulses shorter than what a rule treats as an event. | Control without a campaign; frozen threshold | Registered, 56 sealed attack-free Tennessee Eastman runs, all three passed. Loud pulses: tracker 0 of 56 (control 45). Short pulses: alarm-excluding recalibration 0 of 56 (control 49). Silent attacker: standard SPOT 16 of 56 attacks a quarter above the calibrated threshold (control 56). Frozen 56 of 56 each time. On ProvICS (6 placements) the silent attacker moved SPOT by 0.6 % and that test failed. |
| RQ4 | Which rules are safe, and what do they cost? | Non-inferiority to the frozen threshold (margin 0.10); false alarms against the calibrated budget on attack-free data. | Frozen threshold | Registered, Tennessee Eastman. Alarm-excluding recalibration and a capped tracker kept all 104 later attacks. False alarms over 280 sealed attack-free days, as a multiple of the budget: frozen 0.98, tracker 1.21, alarm-excluding 1.33, tighten-only 1.57, capped tracker 2.12. A ceiling at a fixed multiple of the calibrated threshold never missed an attack that the fixed threshold at that multiple caught (proved, and checked on every run). |
| RQ5 | Does the result depend on the detector? | RQ1 repeated with three scores: a learned predictor's error, a model-free rate-of-change score, a reconstruction error. | | Exploratory on HAI: the loss repeats under all three (reconstruction score 53 against 65), with one release reversed. Secondary on ProvICS: under the reconstruction score the tracker caught 16 against 25. |

## How the result is protected from us

- Each study was registered before its test data was opened: hypotheses, rules, parameters and pass/fail
  conditions were committed, with a hash of every analysis file. The harness refuses to run if a file
  changed or the data was opened before.
- Every read of attack data goes into a ledger. A separate verifier recomputes every pass/fail result and
  checks that each access came after its registration.
- Every registered outcome is reported, including failures. Three are in the paper: the primary conditions
  of study 2 and of study 3 (both datasets) failed, and one attack test in study 1 could not show an effect.
- One amendment (a missing-value fix for ProvICS) was committed before the second attempt and is reported.
- Results are labelled registered, exploratory or post-hoc wherever they appear.

## Threats to validity

- All data is from testbeds or simulators; no production plant.
- The poisoning campaigns are synthetic and assume an attacker who can read the threshold: upper bounds.
- Two of the datasets are small (14 and 32 attacks).
- The stricter count erases the difference when the fixed threshold is already in a long alarm. It did on
  HAI 20.07 (post-hoc) and on Tennessee Eastman (registered), where later attacks start inside alarms.
- Rules and parameters were developed on one testbed family (HAI).
- No human operator is studied, although the recommendation gives operators a role.

## Not in this paper

Commercial or open-source products at their default settings, and human or LLM operators. Both are
planned as follow-up work.

## Where I would value your view

1. Study 3's primary condition required the loss under both counts and failed under the stricter one. The
   paper reports a failed primary, with the first count as registered secondary evidence. Is that the
   right way to present it?
2. Is the frozen threshold enough as the baseline, given the stronger adaptive rules in RQ4?
3. What would a reviewer ask that this evaluation cannot answer?
