# fi1 workstream B, round 3: do the conclusions survive the thread count?

Date 2026-11-12. Branch `improve/fi1-pipeline3`, based on main at 2c8ce61. Everything here is exploratory. No
committed or registered result was recomputed in place or replaced, and no frozen file was edited. Reruns
were written under `target/fi1-pipeline3/` in this worktree. Machine: 24 logical CPUs, OpenBLAS 0.3.29
(Haswell kernel, NumPy 2.2.6), torch 2.6.0 on CPU. Numbers in this file are in
`docs/research/fi1_pipeline_round3.json`.

## Summary

PLACEHOLDER_SUMMARY

## 1. The thread count, study by study

A "gate" is a registered pass/fail rule; a "claim" is a comparison a report states in words; a "verifier"
row is a check of an existing verifier that reads a number a rerun produces. Margins are relative to the
threshold (positive passes).

PLACEHOLDER_STUDIES

## 2. Where the nondeterminism enters

PLACEHOLDER_WHERE

## 3. What each report needs

PLACEHOLDER_SENTENCES

## 4. Reproducible by construction: `scripts/repro_env.py`

- `pin_threads(n)` sets the BLAS and OpenMP pools of the running process through threadpoolctl, the six
  thread variables for child processes and libraries loaded later (`OPENBLAS_NUM_THREADS`,
  `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `BLIS_NUM_THREADS`, `VECLIB_MAXIMUM_THREADS`,
  `NUMEXPR_NUM_THREADS`), PyTorch's intra- and inter-op threads when torch is loaded, and returns the
  LightGBM keyword (`num_threads`), which LightGBM takes per call. `lightgbm_params(params)` replaces any
  thread alias with the pinned count and refuses to run before a pin. `unpin()` restores everything.
- `environment_record()` returns Python, NumPy, SciPy, scikit-learn, LightGBM, PyTorch and threadpoolctl
  versions; every BLAS/OpenMP pool as threadpoolctl reports it (vendor, version, kernel architecture,
  threads); the pinned count; the thread variables; torch's threads; logical CPUs; platform.
- `stamp_json(path)` adds the record to a result file under `reproducibility_environment` (a result that
  is not a JSON object gets a `<stem>.environment.json` sidecar). `pin_from_environment()` pins to
  `REPRO_THREADS` (default 1) for scripts with their own argument parsing. `run_script_pinned` runs a
  script's `__main__` unchanged in a pinned process and stamps its outputs.

Adopted (none of these is named by any protocol, freeze JSON or `FROZEN_FILES`; checked by grep):
`tw1a_score_level_dev.py` (part files and summary), `tw1a_export_setup.py`, `fi1_gpd_cold_check.py`,
`fi1_rt_calibration_check.py`, `fi1_tt1_g2_cluster_check.py`. Each pins one thread by default
(`REPRO_THREADS=n` to change) and stamps what it writes. `tw1_adapters.py` writes no result and
`tw1_catalogue_build.py` computes nothing numerical; both are unchanged. All new scripts of this round
pin and record as well.

Pinned entry points beside frozen or byte-verified producers (originals unchanged):

| Entry point | Wraps | Why not edited |
|---|---|---|
| `evaluate_physical_jepa_robustness_v2.py` | the robustness evaluator | frozen by digest in the paper dynamics calibration protocols v1 and v2 |
| `select_physical_incident_jepa_v2.py` | the v3 sweep | reproduced byte for byte by `verify_physical_world_model.py` |
| `train_world_model_v2.py` | the OS transition trainer | frozen in the incident-dynamics selections v1/v2 and `world_model_training_config.json` |
| `train_world_model_jepa_v2.py` | the OS JEPA encoder trainer | frozen in `world_model_training_config.json` |

Each takes `--threads N` (default 1) plus the original's arguments and stamps the original's JSON output.

Tests: `scripts/test_repro_env.py`, 13 tests (pinning in process and in a child, unpin, LightGBM
keywords, torch, the record's fields, single-thread repeatability of a training-sized product, the
entry points' argument forwarding, `run_script_pinned` with a child script, and the digest of the frozen
evaluator).

## 5. Verifier checks added (`scripts/test_fi1_pipeline3.py`)

Each check is a function that returns a list of problems; the test asserts the list is empty on the
committed files, and a perturbation test changes one stored value in a copy and asserts that the matching
problem appears. 16 tests.

| Check | Ties | Perturbations that make it fail (each tested) |
|---|---|---|
| (a) `rt1_gate_problems` | each rt1 primary gate to `D2_vs_D1` (miss reduction, interval), the miss reduction to the per-event outcomes, the false-alarm rate to D2's and to `false_episodes / normal_days`, the budget to the protocol's (HAI 2, SMD 1), the verdict to the comparison, the success rule to both verdicts | gate miss reduction 0.5; SMD comparison miss reduction 0.3; gate interval [0.1, 0.9]; gate false alarms 1.0; SMD budget 2.0; D2 false episodes 99; HAI gate `passes` true; success rule true; one missed HAI event marked detected |
| (a) `rt2_gate_problems` | the registered pair of primary comparisons, each miss reduction to the per-event outcomes, D1's false-alarm rate, the limit of 4 per day, the verdict, the success rule | D1_vs_DR miss reduction 0.5; D1 false episodes 50; budget 3.0; `passes` true; success rule true; D1_vs_D0 removed; both intervals lifted to [0.5, 1.0] |
| (b) `learned_contribution_problems` | per domain, from the 512 stored case records: Platt probabilities, `learned_block` = probability >= threshold, case counts, the three confusion tables with their Wilson intervals, the additional blocks, the Wilson interval of the additional rate, the Brier score, the equal-mass ECE | a probability; a `learned_block`; a dangerous count; a rules-only FN; a Wilson bound; a combined TP; additional dangerous and safe counts; a Brier score; ECE 0.006 (the equal-width value) |
| (c) `attribution_threshold_problems` | re-scores the 3,494 validation rows (seeds 4096-4127) with each stored adapter, reproduces the counts at each registered threshold, re-derives each threshold with exact fractions, and allows exactly one documented exception: `local-sensing-without-jepa` (registered 0.751, FP 13, FN 4; exact rule 0.726, FP 15, FN 3; round 2, P1). Run on attribution protocols v1 and v2 | hazard-only threshold 0.79; JEPA-only 0.70; local-only 0.726 ("documented exception no longer occurs"); target FPR 13/3471; local-only stored FN 5; the exception removed |
| (d) `catalog_problems`, replacing `final_catalog_digests_recorded` | the final catalogs on disk against the recorded digests, their case counts, and the case records' ids and labels against the catalog's, in order | a recorded digest; a case count; reversed records; a flipped label; a missing catalog path |
| (d) `rule_preservation_problems`, replacing `rule_blocks_never_erased` | the stored rules-only counts against the records' rule blocks; the combined gate blocks at least what the rules block; combined = rules + learned additions | one record's rule block set without the summary; then the summary too; additional safe or dangerous counts changed |

The two replaced checks are true for every input: `final_catalog_digests_recorded` compares a digest with
the digest of the file it just wrote, and `rule_blocks_never_erased` counts `rule & ~(rule | learned)`.
The verifiers are unchanged; these checks run as tests.

## 6. What round 2 did not reach

PLACEHOLDER_ITEM4

## 7. Commands

PLACEHOLDER_COMMANDS

## 8. Not reached

PLACEHOLDER_NOT_REACHED
