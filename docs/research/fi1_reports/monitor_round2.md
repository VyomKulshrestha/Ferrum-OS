# fi1 workstream A, round 2: the monitor

Plan: `docs/research/ferrumos_improvement_fi1_plan.md`, in particular its note "monitor round 2 and the second use of
the check set". Everything here is exploratory. Round 1: `monitor_round1.md`.

## Selection rule (written and committed before any selection result of a round-2 candidate exists)

Selection set: HAI 21.03, HAI 22.04, Tennessee Eastman modes 0-3 (three datasets, equal weight). The baseline is d1,
recomputed with the round-2 benchmark (same cache, same thread settings: OMP, OpenBLAS and MKL at 2 threads, LightGBM
`n_jobs` 2, no refit needed). A candidate with more than one output state is scored as rule 4 of the plan's note
says: every non-normal state is alarm time, and an episode of any such state that starts inside an event is an
onset.

A candidate survives selection when, on the selection set:

1. mean onset recall is at least 0.02 above the baseline's;
2. mean share of unlabelled time in alarm is not above the baseline's;
3. no selection dataset loses more than 0.05 of onset recall;
4. false alarms on the sealed attack-free Tennessee Eastman runs stay below 1.5 times the budget;
5. (new) mean onset recall net of its circular-shift chance reference is not below the baseline's. Round 1 showed on
   the selection set that about half of a raw onset gain can be the higher chance level of shorter alarms.

Survivors are ranked by mean onset recall net of chance (round 1 ranked by raw onset recall); ties by the lower mean
alarm share. At most three go to the check set, once each, under new names. Rules 1-4 are round 1's rule unchanged.

Candidate families planned when this rule was written (parameters may be set on the selection set only):

- two-channel combinations of d1 and `second` (and of other round-1 scores), each channel calibrated on attack-free
  data to a share of the episode budget, with the alarm time the union and the episodes counted as described in
  "Method";
- a monitor with an "outside the fitted range" state, its indicator calibrated on attack-free data to its own share
  of the budget, the residual score used only inside the range;
- scales conditioned on the operating regime through the command inputs; channel weights fitted on attack-free data;
  handling of the post-attack period by fixed rules.

Not admitted as a candidate: any rule that silences an alarm while its score stays above threshold (for example a
maximum alarm duration). Under rule 4 that state is still alarm, and reporting it as normal would rename alarm time.
