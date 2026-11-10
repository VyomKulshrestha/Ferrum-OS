# Evaluation plan: "Thresholds That Travel"

Vyom Kulshrestha, 10 November 2026. One page, written for a reader outside industrial-control security.
Studies 1 and 2 are finished. Study 3 is designed and its test data is still sealed, so this plan can
still change it.

## Claim

An anomaly detector raises an alarm when a score crosses a threshold. Many deployments let the threshold
adapt online. We claim that an adaptive threshold loses real attacks, because whatever a rule learns from
is something an earlier attack, or an attacker, can put there. A threshold should tighten itself freely
and loosen only inside a fixed band or with approval.

## Research questions

| | Question | Measure | Compared with | Data and status |
|---|---|---|---|---|
| RQ1 | Do adaptive thresholds miss recorded attacks that a fixed threshold catches? | Difference in attacks detected, 95 % paired bootstrap interval. Two counts: any alarm inside the attack, and an alarm that starts inside it. | The same detector with its threshold frozen at calibration | Done, registered: HAI 20.07 (20 of 38 against 36), BATADAL (6 of 14 against 14). Study 3: Tennessee Eastman (142 attack runs), ProvICS (32 events). |
| RQ2 | Is the cause "attacks that follow attacks"? | The same difference, split into the first attack of a run and later ones. Predicted: a loss on later attacks, none on first ones. | Frozen threshold | Study 3 (Tennessee Eastman has runs with one attack and runs with three or four). |
| RQ3 | Can an attacker blind each kind of rule on purpose? | Share of identical final attacks detected after a poisoning campaign, against a no-campaign control, for final attacks of four sizes. Three campaigns: loud pulses, a silent attacker that holds the score just under the threshold, pulses shorter than what a rule treats as an event. | Control without a campaign; frozen threshold | Exploratory on development data. Study 3: 56 independent, never-opened attack-free runs of 120 h, one placement each. |
| RQ4 | Which rules are safe, and what do they cost? | Non-inferiority to the frozen threshold (margin 0.10); false alarms against the calibrated budget on attack-free data. Rules: tighten-only, updates that leave alarms out, a capped rise, a hard ceiling at 1.1 to 1.5 times the calibrated threshold. | Frozen threshold | Exploratory so far (a ceiling at 1.1 restored 125 of 160 detections, equal to frozen). Study 3 tests it on 280 days of sealed attack-free data. |
| RQ5 | Does the result depend on the detector? | RQ1 repeated with three scores: a learned predictor's error, a model-free rate-of-change score, a reconstruction error. | | Exploratory; secondary in study 3. |

## How the result is protected from us

- Each study is registered before its test data is opened: hypotheses, rules, parameters and pass/fail
  conditions are committed, with a hash of every analysis file. The harness refuses to run if a file
  changed or the data was opened before.
- Every read of attack data goes into a ledger. A separate verifier recomputes every pass/fail result.
- Every registered outcome is reported, including failures. Two are already in the paper: study 2's
  primary condition failed, and one attack test in study 1 could not show an effect.
- Results are labelled registered, exploratory or post-hoc wherever they appear.

## Threats to validity

- All data is from testbeds or simulators; no production plant.
- The poisoning campaigns are synthetic and assume an attacker who can read the threshold: upper bounds.
- Two of the datasets are small (14 and 32 attacks).
- The stricter count can erase a difference when the fixed threshold is already in a long alarm; it did on
  HAI 20.07 (post-hoc), which is why study 3 registers both counts.
- Rules and parameters were developed on one testbed family (HAI).
- No human operator is studied, although the recommendation gives operators a role.

## Not in this paper

Commercial or open-source products at their default settings, and human or LLM operators. Both are
planned as follow-up work.

## Where I would value your view

1. Study 3's primary condition requires the loss under both counts. Is that the right bar, or too strict?
2. Is the frozen threshold enough as the baseline, given the stronger adaptive rules in RQ4?
3. What would a reviewer ask that this plan cannot answer?
