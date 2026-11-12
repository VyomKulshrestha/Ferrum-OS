# fi1 workstream A, round 1: the monitor (draft; selection rule fixed before the selection results are complete)

Plan: `docs/research/ferrumos_improvement_fi1_plan.md`. Everything here is exploratory: every dataset is spent.

## Selection rule (written 2026-11-12, after the HAI 21.03, HAI 22.04 and Tennessee Eastman mode 0 results, before modes 1-3)

A candidate survives selection when, on the selection set (HAI 21.03, HAI 22.04, Tennessee Eastman modes 0-3,
three datasets, each weighted equally):

1. mean onset recall is at least 0.02 above the baseline's;
2. mean share of unlabelled time in alarm is not above the baseline's;
3. no selection dataset loses more than 0.05 of onset recall;
4. false alarms on the sealed attack-free Tennessee Eastman runs stay below 1.5 times the budget.

At most three survivors, ranked by mean onset recall, go to the check set, once each. Candidates seen so far:
d1 (baseline), mad, tail, max, second, stable, loro, h1, h5, clip, and '+'-combinations of them.

## Selection outcome (2026-11-12, before any check-set run of a candidate)

Survivors, in rank order: `mad+second`, `second`, `second+loro`. These three, and the baseline, go to the check
set once each. Full table: `docs/research/fi1_monitor_round1.json` (selection section).
