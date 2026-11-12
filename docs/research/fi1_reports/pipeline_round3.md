# fi1 workstream B, round 3: do the conclusions survive the thread count?

Date 2026-11-12. Branch `improve/fi1-pipeline3`, based on main at 2c8ce61. Everything here is exploratory. No
committed or registered result was recomputed in place or replaced, and no frozen file was edited. Reruns
were written under `target/fi1-pipeline3/` in this worktree. Machine: 24 logical CPUs, OpenBLAS 0.3.29
(Haswell kernel, NumPy 2.2.6), torch 2.6.0 on CPU. Numbers in this file are in
`docs/research/fi1_pipeline_round3.json`.

## Summary

| Study | Thread counts run | Do the conclusions survive? | Largest relative change | What flips | Closest gate in the committed run | Single thread repeats bit for bit |
|---|---|---|---|---|---|---|
| Physical-JEPA v3 sweep and promotion | 24, 4, 1 (full sweep) | **No.** Only at 24 | different model selected | selection (3 becomes 0); promotion fails at 4 (OOD false negatives 1 against 0) and at 1 (OOD one-step error 0.003870 against 0.003777); three candidate validation checks; four verifier assertions | OOD false negatives not increased: 0 against 0, no slack | yes (training trace) |
| Physical-JEPA robustness evaluator | 24, 4, 3, 2, 1 | yes; 5 of 5 gates at every count | 5.9% | no gate; one claim-level step of the scaling curve | data scaling final h3 below smallest-data h3: 2.8% (2.0% at 2 and 3 threads) | yes |
| OS world-model study | 24 (truncated), 4 (full), 1 (truncated) | **No** for the verifier's numbers and one comparison | factor 4 (safe-replay false positives 216 to 50) | four verifier assertions; "rules + JEPA at least rules + mean delta" | rules + JEPA against rules + mean delta: one false positive (0.814 against 0.812) | not measured (one run per count) |
| Incident dynamics v3, v4 (physical) | torch 4 and 1 (registered 8), inference and analysis only | yes | 5.5e-8 | none; the verify stage's 1e-7 inference check would fail for the v2 paper JEPA control | not affected | not measured |
| Cross-domain study | torch 4 and 1 (registered 16), archived inference only | yes | 1.0e-6 | none; the archived-inference verifier's four exact-equality checks fail | not affected | not measured |
| Safety-Gymnasium | not rerun (environment cannot be imported here) | not rerun | | | | |

The thread count enters through OpenBLAS's float32 matrix products in training (section 2). Inference with
fixed weights is unaffected in the NumPy evaluators and changes in the eighth decimal in the torch ones.
Training with selection on top of it (early stopping, validation gates, a single training run per
candidate) turns that into a different model, and in two studies into different conclusions.

## 1. The thread count, study by study

A "gate" is a registered pass/fail rule; a "claim" is a comparison a report states in words; a "verifier"
row is a check of an existing verifier that reads a number a rerun produces. Margins are relative to the
threshold (positive passes).

### 1.1 Physical-JEPA v3 sweep (`verify_physical_world_model.py`, full sweep): the selection and the promotion flip

The registered sweep (four candidates, 8,000 to 9,000 epochs each, NumPy float32 training) was rerun with
the registered command at 24, 4 and 1 BLAS threads (`fi1_thread_sweep_run.py`; 18, 16 and 21 minutes).

| | committed | 24 threads | 4 threads | 1 thread |
|---|---|---|---|---|
| deployed checkpoint reproduced | | yes, byte for byte | no | no |
| candidates accepted on validation | 0, 2, 3 | 0, 2, 3 | 0, 1, 2 | 0, 1, 3 |
| selection scores (lower wins) | .875 .927 .829 **.764** | identical | **.807** .861 .869 .942 | **.802** .867 .941 .874 |
| selected | 3 (128 by 256, seed 91) | 3 | 0 (96 by 192, seed 42) | 0 |
| epochs completed (early stopping) | 8000 7425 8500 8175 | identical | 8000 7425 6700 7200 | 8000 8000 8575 9000 |
| promotion (11 gates) | passes | passes | **fails**: OOD false negatives 1 against 0 | **fails**: OOD one-step error 0.003870 against the limit 0.003777 |
| selector exit code | 0 | 0 | 1 | 1 |

Validation checks that flip:

| Check | committed | 4 threads | 1 thread |
|---|---|---|---|
| candidate 1: incident validation geometric ratio <= 0.95 | 0.972, fails | 0.902, passes | 0.895, passes |
| candidate 3: original validation worst ratio <= 1.02 | 0.774, passes | 1.101, fails | 0.857, passes |
| candidate 2: original validation worst ratio <= 1.02 | 0.869, passes | 0.997, passes | 1.084, fails |

Checks of `verify_physical_world_model.py` that read numbers the sweep produces, and fail at 1 and 4
threads: the selected index is 3 (both); OOD rules-plus-JEPA false negatives 0 (4 threads: 1); ordinary,
incident and stress test false negatives 8, 1, 1 (4 threads: 6, 1, 1; 1 thread: 1, 2, 0); the deployed
digest (both). The checks that hold at every count: 682 malformed OOD observations rejected, and H=3 error
below the deployed baseline's on the ordinary, incident and stress tests. The matched-autoencoder
comparison could not be produced at 1 or 4 threads: `evaluate_physical_jepa_v3_baselines.py` refuses a
selection whose promotion failed.

Closest gates of the committed run: the promotion gate "OOD false negatives not increased" has no slack
(0 against 0): one more miss fails it, and at 4 threads one more miss is what happened. The next closest
are "OOD one-step error <= 0.95 x deployed" (10.5% margin; fails at 1 thread) and "incident test geometric
ratio <= 0.90" (10.5%). The rejected candidate 1 sits 2.3% outside its incident gate and 0.43% inside its
worst-horizon gate. The selection score of the selected candidate leads the runner-up by 8.5%.

The evaluation of fixed weights does not depend on the thread count here: the deployed baseline's test
metrics (`current_test`, 0 of its numeric leaves changed at 4 threads) are identical. The dependence is in
training.

Largest relative change: not meaningful as a percentage, because different candidates are selected; every
candidate's validation metrics differ (215 numeric leaves of `candidates` at 4 threads).

### 1.2 Physical-JEPA robustness evaluator (`verify_physical_jepa_robustness.py`): conclusions hold

Rerun with the verifier's artifact (`incident-v1-baseline.bin`) at 1 (twice), 2, 3, 4 (twice) and 24
(twice) threads, about 30 to 55 seconds each.

| Threads | numeric leaves changed (of 148) | largest relative change | registered gates | data-scaling gate: final h3 / smallest-data h3 |
|---|---|---|---|---|
| committed | | | 5 of 5 | 0.026644 / 0.027420, margin 2.8% |
| 24 | 0 (identical to the committed file, both runs) | 0 | 5 of 5 | as committed |
| 4 | 30 | 5.9% (matched autoencoder test FP 16 against 17) | 5 of 5 | 0.026443 / 0.027209, 2.8% |
| 3 | 26 | 4.4% (data scaling, 1,750 episodes, h5) | 5 of 5 | 0.027859 / 0.028434, 2.0% |
| 2 | 30 | 5.9% | 5 of 5 | 0.027779 / 0.028346, 2.0% |
| 1 | 30 | 5.9% | 5 of 5 | 0.026298 / 0.027501, 4.4% |

The gate that can fail is "data scaling: final h3 below the smallest-data h3"; it is the only registered
gate that reads a trained model (the counterfactual accuracy, 1.0 against 0.95, and the rare-hazard false
negatives, 0 against 21 for the rules alone, use the fixed artifact and do not change). Its margin is 2.0%
to 4.4% across the counts measured here. This is the gate that most plausibly failed on GitHub's 4-core
runner with 24 threads forced (not run here: the runner's processor may select another OpenBLAS kernel,
which changes results as the thread count does). A claim-level change: the committed curve is not
monotone (h3 rises from 0.026518 at 1,000 episodes to 0.026644 at 1,750), while at 1 and 4 threads it
falls at that step; a report that describes the curve as decreasing at every step would be wrong in the
committed numbers and right in others. Two runs at the same count are bit-identical (1, 4 and 24).

### 1.3 Incident dynamics v3 and v4 (Tables 21 to 27): inference rerun, training not rerun

The registered runner pins `torch.set_num_threads(8)` and LightGBM `num_threads=8` in its code, so the
thread count is fixed wherever it runs. Retraining the study (hours of queued jobs) was not feasible. What
was measured: the runner's `verify` stage mirrored for the physical domain with torch at another count
(`fi1_thread_incident.py`; the runner's own `set_num_threads` neutralised): regenerated catalogs,
inference of every pipeline from the retained checkpoints against the stored evidence, and the analysis
recomputed from the recomputed evidence against the stored result.

| Run (physical domain) | catalogs | pipelines bit-identical | largest absolute difference (pipeline) | within the verifier's atol 1e-7 | analysis leaves changed | gates, counts or intervals changed |
|---|---|---|---|---|---|---|
| v3, torch 4 threads (registered: 8) | identical | 12 of 15 | 3.6e-7, scores of `v2-paper-action_conditioned_jepa` | no (that pipeline, all three populations) | 30, all of that pipeline (mean errors, Brier, ECE, bin means); largest relative change 4.7e-8 | none |
| v4, torch 4 threads | identical | 14 of 17 | 3.6e-7, same pipeline | no (same) | 30, same pipeline; 5.5e-8 | none |
| v3, torch 1 thread | identical | 12 of 15 | 3.6e-7, same pipeline | no (same) | 30, same pipeline; 5.5e-9 | none |

The FerrumOS domain was not run (its historical rows need the published dataset through the frozen
loaders; time). A rerun at 8 threads, the registered count, is what the runner's own verify stage does;
round 2 did not rerun it and neither did this round.

The pipelines the study is about are bit-identical: the selected v3 physical pipeline (an ensemble of
three LightGBM models, `p24-gbr-h8-iw4-scaled`, which predicts each row independently) and the v2 ridge
pipelines. Only the torch control
(the v2 paper JEPA) changes. Registered conclusions, gates and every count are unchanged; the 1e-7
inference check of the runner's own verify stage would fail for that control at a thread count other than
8, which the runner prevents by pinning 8.

### 1.4 Cross-domain study (Tables 3 to 7, D1)

Training was not rerun (18 torch checkpoints; the study's training used deterministic torch algorithms).
`verify_cross_domain_archived_inference_v1_2.py` recomputes the historical tables from the archived
checkpoints and compares them with the stored records by canonical JSON equality, with torch pinned to
16 threads in its code. `fi1_thread_crossdomain.py` runs it unchanged with torch and BLAS at another count
(its own pin neutralised) and records how large each difference is.

| Record | numeric leaves | changed at 4 threads | largest relative change | verdicts, flags or orderings changed |
|---|---|---|---|---|
| FerrumOS, original domain record (Tables 3, 4, D1) | 572 | 23 | 1.6e-7 | none |
| FerrumOS, common-episode record (Table 5) | 266 | 133 | 4.2e-7 | none |
| Physical, original domain record | 711 | 93 | 1.0e-6 (a risk-coverage uncertainty bound) | none |
| Physical, common-episode record | 266 | 135 | 3.1e-8 | none |
| Attribution diagnostics | 1,288 | 0 | 0 | none |

At 1 thread the picture is the same: at most 7.7e-7 relative (physical risk-coverage bound), 3.8e-7
(FerrumOS common-episode interval), no verdict changes. At 16 threads, the verifier's own count, all
eight checks pass and every record is exact (reference run, under the machine lock).

So the verifier's four exact-equality checks fail at any thread count other than the pinned one, while
no printed digit of Tables 3 to 7 can change (the largest change is a millionth of the value).

### 1.5 OS world-model study (`verify_world_model_paper_evaluation.py`)

The commands of `reproduce_world_model_paper.py --full` (JEPA encoder, transition seeds 17, 42 and 91,
autoencoder baseline, paper evaluation), run by `fi1_thread_os_world_model.py` with the published
dataset (digest ae7498c7..., read from the main checkout). The full pipeline was run at 4 threads (64
minutes on a loaded machine); at 24 and 1 threads only the JEPA encoder and the selected transition seed
17 were run (truncated, to keep lock time short and because one transition seed took 10 minutes at 4
threads).

At 24 threads (truncated run) the JEPA encoder (9fb5f08b...) and the selected transition model for seed
17 (bd80ccb2...) reproduce the committed digests byte for byte, so the committed evidence is reproducible
on this machine at 24 threads and the changes below are an effect of the thread count. PLACEHOLDER_OSWM_T1

At 4 threads (full pipeline), against the committed evaluation:

| | committed | 4 threads |
|---|---|---|
| model digests (encoder, seeds 17/42/91, autoencoder encoder and transition) | recorded | all six differ |
| rules + JEPA confusion (verifier asserts 198/52/41/209) | 198 / 52 / 41 / 209, BA 0.814 | 185 / 65 / 31 / 219, BA 0.808 |
| rules + validation-calibrated JEPA (asserted 209/41/41/209) | 209 / 41 / 41 / 209 | 204 / 46 / 40 / 210 |
| rules + mean delta, rules + autoencoder, rules only | 198/52/42/208, 189/61/41/209, 147/103/21/229 | identical |
| untouched QEMU safe replay, rules + JEPA false positives (asserted 216 of 1,969) | 216 | 50 |
| same, validation-calibrated | 265 | 159 |
| seed aggregate, max combined FNR (asserted >= 0.376) | 0.376 | 0.356 |
| H=2 above H=3 balanced accuracy (asserted) | 0.848 > 0.814 | 0.852 > 0.808 |
| seed 17 / 42 / 91 rollout H=3 normalized error | 0.0387 / 0.0411 / 0.0399 | 0.0847 / 0.0840 / 0.0808 |
| seed 17 / 42 / 91 combined balanced accuracy | 0.814 / 0.762 / 0.782 | 0.808 / 0.764 / 0.772 |
| horizon ablation BA, H=1..5 | .844 .848 .814 .822 .834 | .848 .852 .808 .808 .798 |
| rules versus combined, accuracy difference [95% CI] | 0.062 [0.03, 0.094] | 0.056 [0.03, 0.084] |

Four of the verifier's data-derived assertions fail at 4 threads (two confusion tables, the safe-replay
false positives, the seed-aggregate FNR). Of the paper's comparisons: rules + JEPA above rules only holds
(0.808 against 0.752); rules + JEPA above rules + autoencoder holds (0.808 against 0.796; committed margin
2.3%); rules + JEPA at least rules + mean delta flips (committed 0.814 against 0.812, a margin of one
false positive; at 4 threads 0.808 against 0.812). The paper already says the study "does not establish
that JEPA outperforms the per-action mean model"; the committed ordering is not stable either. The
safe-replay false-alarm count (216 of 1,969) is the least stable number: it changes by a factor of four.

### 1.6 Safety-Gymnasium tables (11 to 15): not rerun

`run_physical_jepa_safety_gymnasium.py` needs `safety_gymnasium` and MuJoCo; the import fails in this
interpreter (`ValueError: mutable default <class 'numpy.ndarray'> for field color`, a dataclass
incompatibility of the installed package), and nothing may be installed. The attribution adapters are
fitted with full-batch Adam in NumPy float64 on 17,768 rows; their thresholds were re-derived exactly
from the stored adapters (section 5, check (c)), which tests the stored decision but not its sensitivity
to the thread count of the fit.

## 2. Where the nondeterminism enters

Measured with `fi1_thread_where.py` (one process; thread counts 1, 4 and 24 switched with threadpoolctl):

- **Every float32 matrix product of the physical-JEPA trainer** (`train_physical_jepa.train`: the forward
  products, the weight gradients `X.T @ G` and the back-propagated products, at the registered shapes,
  batch 1024, latent 128, hidden 256) differs bit for bit between 1 thread and 4 or 24 threads, by up to 7.6e-5
  in absolute value. NumPy's `sum(axis=0)` (pairwise, no BLAS) does not depend on the thread count. The
  dependence is OpenBLAS's SGEMM: the partition of the product across threads changes the order of the
  floating-point additions.
- **It grows in training.** Training the registered 128-by-256 shape (seed 91, 1,200 simulator episodes)
  at 4 threads departs from 1 thread at the first checkpoint (epoch 25, relative weight difference 4e-8)
  and the difference reaches 3.6e-6 by epoch 325; at 24 threads it departs from 1 thread faster (5.7e-8 at epoch 25, 2.8e-4 by epoch 125, 6.9e-4 by epoch 325). Over 8,000 to 9,000 Adam steps it changes which
  validation checkpoint early stopping keeps (epochs completed differ, table 1.1) and then which
  candidate passes its validation checks. The selection rules turn a small numerical difference into a
  different model.
- **Inference with fixed weights does not change** with the thread count in the physical evaluators
  (`current_test` identical at 4 threads; the robustness gates that read the fixed artifact identical at
  every count). Those paths predict one row at a time (matrix-vector products), which OpenBLAS computes
  the same way at any thread count.
- **Single-threaded runs repeat bit for bit**: the robustness evaluator at 1 thread twice (identical
  files), the 400-epoch training trace at 1 thread twice (identical at every checkpoint). So do repeated
  runs at 4 and at 24 threads.
- **The OS world-model trainers** (`train_world_model_jepa.py`, `train_world_model.py`, full-batch
  float32 NumPy) behave like the physical trainer: at 24 threads the committed digests reproduce, at 4
  threads every model differs, and the rollout H=3 error of the transition models roughly doubles
  (0.0387 to 0.0847 for seed 17), with the downstream safety numbers of section 1.5.
- **PyTorch inference** (incident dynamics, cross-domain) changes with the intra-op thread count in the
  eighth decimal (at most 3.6e-7 absolute, 1e-6 relative), enough to fail exact-equality and 1e-7
  checks and nothing else. LightGBM prediction and NumPy ridge prediction are bit-identical across counts.
- **The thread count alone does not pin the result across machines.** The deployed physical checkpoint
  reproduces at 24 threads on this Haswell-kernel machine. GitHub's 4-core runner at 4 threads gives the
  same robustness numbers as this machine at 4 threads (main session's measurement), but at 24 threads
  forced it gives numbers that match neither (also the main session's); why was not established (a
  different OpenBLAS kernel for that processor is one candidate). A result file should name the BLAS vendor, version, kernel architecture and thread count;
  `environment_record()` does.

## 3. What each report needs

- **Physical-JEPA v3 evidence (the promotion record, the deployed checkpoint and every report that calls
  them deterministic).** "The v3 sweep reproduces the deployed checkpoint, its selection and its
  promotion only with 24 OpenBLAS threads (Haswell kernel). Rerun with 4 or 1 threads on the same
  machine, it selects another candidate (96 by 192, seed 42), and promotion fails: at 4 threads on the
  registered OOD false-negative gate (1 against 0), at 1 thread on the OOD one-step error gate (0.003870
  against 0.003777). The promotion decision is therefore a property of one training run, not of the
  configuration; the OOD false-negative gate passed with no slack." This is a flipped selection and a
  flipped promotion gate, and belongs wherever the v3 promotion is cited as evidence for the model.
- **Physical-JEPA robustness report.** "Values of the trained baselines (data scaling, matched
  autoencoder) change by up to 5.9% with the BLAS thread count; all five registered gates pass at 1, 2,
  3, 4 and 24 threads; the closest, final h3 below the smallest-data h3, keeps a margin of 2.0% to 4.4%.
  The scaling curve is not monotone in the committed run."
- **Incident dynamics v3/v4.** "Inference was recomputed at 1 and 4 torch threads instead of the registered 8: the selected LightGBM pipeline and the ridge pipelines are bit-identical, the torch control (v2 paper JEPA) differs by at most 3.6e-7, and no gate, count or interval changes. The study's models were not retrained at another thread count." No conclusion changes.
- **Cross-domain study.** "The archived-inference check compares records exactly and passes only at the 16 torch threads it pins; at 1 or 4 threads values differ by at most 1e-6 relative and no table entry changes." No conclusion changes; the verifier could compare with a stated tolerance instead of exact equality.
- **OS world-model study.** "The committed models and evaluation reproduce byte for byte with 24 OpenBLAS threads on the development machine. With 4 threads the retrained models differ, the rollout H=3 error of the transition models roughly doubles (0.039 to 0.085), rules + JEPA gives 185/65/31/219 instead of 198/52/41/209 (balanced accuracy 0.808 instead of 0.814), the false alarms on the untouched QEMU replay fall from 216 to 50 of 1,969, and rules + JEPA falls below rules + per-action mean (0.808 against 0.812). The ordering of JEPA and the per-action mean, and the replay false-alarm count, are not stable under a change of BLAS thread count." This is a flipped comparison; the false-alarm count of the replay should not be quoted as a property of the method.
- **Every future study**: train with one thread (`repro_env.pin_threads(1)` or the `_v2` entry points),
  record `environment_record()` in the protocol and the result, and treat a selection or a gate that
  flips under a change of thread count as unstable, for example by registering a rule over several
  training seeds instead of one run.

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

A second reader worked read-only on this part (scratch scripts in the session scratchpad, `b3reader/`).
I checked the stored numbers behind H1 and M1 myself and read the code of T1. The rest is the reader's.
Every printed number of PINP Tables 9 and 10 matches its stored JSON.

| # | Where | What | Published number it touches | Sentence needed |
|---|---|---|---|---|
| H1 | Table 9, `evaluate_physical_jepa_recorded_hil_replay.py:134-151, 362` | Event recall is read at a post-hoc threshold (99th percentile of clean non-attack errors of the same test files) held fixed across fault conditions; the faults raise the alarm rate. Checked in `physical_jepa_recorded_hil_replay_result_v1.json`: row FPR 1.00% clean, 1.29% latency, 1.20% jitter, 1.33% noise, 1.01% dropout, 1.95% combined; false alerts 17.5 to 32.8 per hour; recall 38.5% to 50.0%. A chance reference from mean event length (52 events, mean 218.9 s) puts at least one random alarm in an average event about 65% of the time at the clean rate (reader's estimate; per-event lengths not read) | Table 9, event recall column | "Event recall uses a post-hoc threshold at the 99th percentile of clean non-attack test errors, held fixed across conditions; under faults the normal-row alarm rate rises from 1.00% to 1.95%, so the higher recall reflects more alarms, not better detection." |
| H2 | Table 9, recovery, lines 385-413 with `select_physical_jepa_v5.py:83-102` | The predictor is memoryless, so the first row after a fault window equals the clean prediction; "recovery 0 s in 472/472" holds by construction. PINP already says it is not a physical recovery claim | Table 9, recovery | "Because the model is memoryless, the first post-window row equals the clean prediction, so this measure is zero by construction." |
| M1 | Table 10, `run_physical_jepa_multi_embodiment_3d.py:283-333` | Checked in the stored 288 cases: initial clearance at most 0.271 m, median 0.061; the rule blocks the 265 cases below 0.2; the learned branch blocks all 288. A shielded run is simulated only when the union does not block, so no shielded trajectory was run and "0 shielded contacts, Wilson [0, 1.32%]" counts no trials | Table 10 and PINP line 349 ("No shielded contact was observed in this run") | "Generated clearances never exceed 0.271 m (median 0.061) against block thresholds of 0.2 (rule) and 0.18 (predicted, learned); the learned branch alone blocks all 288 cases, so 0% completion follows from the case design, and no shielded trajectory was simulated." |
| T1 | HAI cross-version v2, `train_physical_hai_v2.py:219-249` (`shared_percentile`) | The registered rule is "the first percentile whose alert-event rate is at most two per hour". The code binary-searches a predicate that is not monotone (3-of-5 rule plus cooldown), then steps down only while the previous index is eligible, so it can skip an earlier eligible percentile (reader's reproduction with the real function: returns 0.961 where the rule gives 0.95). It can only return an equal or higher percentile, so the final 48/50 at 0.555 false alerts per hour is not inflated. Whether any stored percentile differs needs the scores (a ridge refit on the HAI files); not done | v2 selection and the registered 21.03 threshold (percentile 0.967), only if the rate is non-monotone there | "The shared percentile was found by binary search, which assumes the alert-event rate is monotone in the threshold; the registered rule is the first eligible percentile." |
| T2 | v1, `train_physical_hai_temporal.py:845-855` | The code's sort drops the registered primary key (masked state error); all candidates share one masked model, so it is a constant tie and the outcome is unchanged | none | none |
| W1 | world-model v3.x selection | The four safety checks of the selection pass for all 30 candidates because learned-only misses all 256 dangerous validation episodes and the rules alone have 0 FN and 0 FP; the choice was decided by rollout error on engineered fixtures | interpretation of the v3.x selection | "The safety checks of the v3 selection were met by every candidate because the rule path alone separated the validation catalog; the selection rests on rollout error." |
| S1 | rt1 SMD, `real_telemetry_detect.py:113-124` (frozen) | The lowest-within-budget rule (round 2, R2) with a 10-minute merge gap lets a threshold keep a machine in long alarm while its episode count stays within budget. Stored: DR thresholds exactly 0.0 on machine-2-3 and machine-3-10; on test normal minutes DR alarms 34.5% of the time, D1 17.7%. PINP attributes the SMD alarm rates to the forecaster; the calibration rule is a second plausible cause. Size per machine not measured (needs the 335 MB bundle) | rt1 SMD (already reported inconclusive) | "SMD thresholds are the lowest within an episode budget whose episodes merge across gaps of up to 10 minutes; several DR thresholds are 0, so normal-minute alarm fractions are not bounded by the budget." |

Thin margins (stored JSON, reader's arithmetic):

- HAI v2 selection: selected balanced accuracy 0.755142 against the eligible runner-up 0.754271 (gap
  0.00087). Three 38/52 candidates fail the source-selection false-alarm gate at 2.0001 and 2.0004 per
  hour, because hours are counted after trimming context rows (78.9967 h instead of 79.0); at 79.0 h, 158
  events equal 2.0 exactly. None would have won.
- HAI v1 final (registered, failed): the transition gate passes at 0.946213 against 0.95 (0.4%).
- World-model v3 selection: the selected candidate's incident ratio 0.0027237 against the runner-up's
  0.0030814, a 13.1% gap; every rejected candidate is at least ten times worse. A 1-6% numerical change
  cannot change the selection. Its own acceptance margins are 2.3% (base H5 ratio 0.9969 against 1.02)
  and 3.4% (base geometric 0.96685 against 1.0). All 30 base and incident ratios and the accepted set of
  18 recompute from the stored per-horizon errors.

## 7. Commands

From the worktree root, with `CUDA_VISIBLE_DEVICES=-1`. Runs above 4 threads held the machine lock.

```
# physical-JEPA v3 sweep at n threads (writes target/fi1-pipeline3/sweep/t<n>_run1/)
python scripts/fi1_thread_sweep_run.py --threads 4 --run run1
python scripts/fi1_thread_sweep_run.py --threads 1 --run run1
python scripts/fi1_thread_sweep_run.py --threads 24 --run run1 --skip-baselines
python scripts/fi1_thread_compare.py sweep

# robustness evaluator (the verifier's artifact)
OPENBLAS_NUM_THREADS=<n> OMP_NUM_THREADS=<n> python scripts/evaluate_physical_jepa_robustness.py \
    --artifact docs/research/artifacts/physical-jepa-stress-v3/incident-v1-baseline.bin \
    --output target/fi1-pipeline3/robustness/t<n>_run1.json
python scripts/fi1_thread_compare.py robustness

# where the dependence enters
python scripts/fi1_thread_where.py --threads 1 4 --epochs 400
python scripts/fi1_thread_where.py --threads 1 4 24 --epochs 400

# incident dynamics (verify stage mirrored at another torch count)
python scripts/fi1_thread_incident.py --version 3 --domain physical --threads 4
python scripts/fi1_thread_incident.py --version 4 --domain physical --threads 4
python scripts/fi1_thread_incident.py --version 3 --domain physical --threads 1

# cross-domain archived inference
python scripts/fi1_thread_crossdomain.py --threads 4
python scripts/fi1_thread_crossdomain.py --threads 1

# OS world model (dataset read from the main checkout's target/world-model-v3-work)
python scripts/fi1_thread_os_world_model.py run --threads 4 --run run1
python scripts/fi1_thread_os_world_model.py run --threads 1 --run run1
python scripts/fi1_thread_os_world_model.py run --threads 24 --run run1
python scripts/fi1_thread_compare.py os-world-model

# machine-readable summary
python scripts/fi1_pipeline_round3_summary.py

# tests (venv with pytest on the base interpreter)
cd scripts && python -m pytest -q test_repro_env.py test_fi1_pipeline3.py test_fi1_pipeline.py test_fi1_pipeline2.py
```

Proposed CI lines (workflows unchanged):

```yaml
      - name: Analysis pipeline tests (fi1 round 3)
        run: |
          python -m pip install --disable-pip-version-check pytest threadpoolctl
          cd scripts && python -m pytest -q test_repro_env.py test_fi1_pipeline3.py
      # add to the ruff check / ruff format --check lists:
      #   scripts/repro_env.py scripts/test_repro_env.py scripts/test_fi1_pipeline3.py
      #   scripts/*_v2.py entry points of this round (evaluate_physical_jepa_robustness_v2.py,
      #   select_physical_incident_jepa_v2.py, train_world_model_v2.py, train_world_model_jepa_v2.py)
      #   scripts/fi1_thread_*.py scripts/fi1_pipeline_round3_summary.py
```

`test_repro_env.py` skips its threadpoolctl tests where threadpoolctl is absent; the torch test skips
without torch. `test_fi1_pipeline3.py` needs only NumPy and repository files.

## 8. Not reached

- A second full sweep at 1 thread (the repeatability at 1 thread rests on the robustness evaluator twice
  and a 400-epoch training trace twice, both bit-identical) and a sweep at 2 or 3 threads.
- The physical-JEPA matched-autoencoder comparison of `verify_physical_world_model.py` at 1 and 4 threads:
  the baseline evaluator refuses a selection whose promotion failed.
- The OS world-model pipeline in full at 1 and 24 threads (truncated to the encoder and seed 17), two
  runs at one count, and the five-seed evaluation (`world_model_full_seed_evaluation.json`).
- Incident dynamics: retraining at another thread count (hours of queued jobs); the FerrumOS domain's
  inference; a rerun at the registered 8 threads.
- Cross-domain: retraining.
- Safety-Gymnasium: any rerun (`safety_gymnasium` does not import in this interpreter).
- The threshold studies' monitor (tt1 family): workstream A measured 0.4% threshold shifts at 2 threads;
  not repeated here.
- The rt1 SMD calibration per machine (335 MB bundle), whether T1 changes any stored HAI v2 percentile,
  per-event lengths for the Table 9 chance reference.
- Proposed but not done: a tolerance-based variant of the archived-inference verifier, and a sweep rule
  that selects over several training seeds; both change registered procedures and are the author's call.
