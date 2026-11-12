# fi1 workstream B, round 1: the analysis pipeline behind the papers

Date 2026-11-12. Branch `improve/fi1-pipeline` (based on main at 7632050). This round audits the Python code that produces
the numbers in the tt1, tt1b, tt1d, rt1/rt2 and tw1 papers. It does not change any frozen file, and it does not
recompute any registered result. Every frozen file still matches its registration: tt1 has 11 files, tt1b 12 and
tt1d 15, all checked on disk by `FrozenDigestTests`.

All tests run from `scripts/`:
`python -m pytest -q test_fi1_pipeline.py test_real_telemetry_detect_v2.py test_threshold_online_v2.py test_threshold_rules_tt1c_v2.py test_tt1d_data_v2.py`
The command uses a venv with pytest and coverage (`target/fi1-venv`). The new tests use synthetic data, with
two exceptions: `FrozenDigestTests` hashes the frozen files, and `MissReductionTests` uses the stored rt2 counts.

## Findings, ordered by effect on reported numbers

| # | file:line | What is wrong | Minimal reproduction | Numbers it can touch | Fix | Test |
|---|---|---|---|---|---|---|
| F0 | `real_telemetry_core.py:253-254` (`paired_event_bootstrap`), frozen | The relative miss reduction 1 − miss_b/miss_a is undefined (0/0) in a resample where the baseline misses no event. The function scores such a resample as 0.0. When those resamples exceed the lower tail, the convention alone sets the interval's lower end to 0.0. | rt2 HAI 21.03, D1 vs DR: DR finds 46/50 and D1 50/50, at the 98.75 % level. 1.67 % of resamples have no DR miss, which is more than the 0.625 % tail. The interval is [0.0, 1.0]; the stored rt2 result has exactly this. If undefined resamples are dropped, it is [1.0, 1.0]. | The rt2 primary gate (`real_telemetry_rt2.py:293`, "lower bound above zero") on HAI 21.03 D1 vs DR. The gate fails there, and this convention is what decides it. The paper (PINP v1.3, Table 32 and its text) reports the failure correctly as computed. It does not say that the 0/0 rule decides it. The recall-difference interval [0.0, 0.18] reaches zero in those same resamples, legitimately. Other comparisons are unaffected because the baseline misses events in every resample: rt1 tables, rt2 HAI 23.05, D1 vs D0. | No change to the registered result. `real_telemetry_core_v2.paired_event_bootstrap(..., undefined="zero"\|"drop")` reproduces the frozen output exactly with "zero" and reports `undefined_share`. Recommendation: state the 0/0 convention in the paper next to Table 32. | `MissReductionTests` |
| F1 | `tt1d_final.py:229` (`play`), frozen. The same pattern was copied into `tt1e_defense_dev.py:200` and `tt1g_baselines_dev.py:173`, which are not frozen. | A new campaign alarm episode starts when `i - last > gap`. Every other counter in the study (`threshold_rules._episodes`, `DailyExcl`, tracker_hold after the first audit, tt1g `Recal`) merges runs separated by up to `gap` quiet steps, that is `> gap + 1`. | Two 5-step alarm runs inside a campaign, separated by exactly `gap` quiet steps. `_episodes` counts 1. `play` counts 2 and reports a longest episode of 5 instead of 15. | Only the campaign diagnostics: `median_alarm_episodes` and `longest_alarm_episode` (tt1d), and `alarm_episodes` (tt1e and tt1g exploratory). The count changes only where two runs sit exactly `gap` apart. Terminal detections, inflation, alarm steps and all gates come out identical; the test asserts this. | `tt1d_final_v2.play_v2` / `placement_v2`. tt1e and tt1g are fixed in place (one line each). | `CampaignEpisodeTests` |
| F2 | `real_telemetry_core.py:144-149` (`rolling_mean`), frozen | The cumulative sum runs in the input dtype. On float32 the rounding error grows with stream length. | A 10-step mean of \|N(0,1)\| float32 scores. Error against float64: 0.0027 at 1e5 steps, 0.012 at 5e5, 0.025 at 1e6 (3 % of the mean). | The rt1/rt2 D2 and D3 classifier features (`real_telemetry_detect.Scorer.raw:75` passes float32 S1). D1 is unaffected because `smooth` casts to float64, and the tt1d PCA score runs in float64. The bias is largest late in long test streams, while the classifiers were trained on short windows where the error is near zero. Bound: at most 0.3 % of a typical feature value per 1e5 steps. I did not measure the effect on D2/D3 detections, because that needs the test files. | `real_telemetry_core_v2.rolling_mean` (float64 accumulation, input dtype returned, same head). | `RollingMeanPrecisionTests` |
| F3 | `tw1_adapters.py:23-29` (`bisect_tau`), not frozen | The bisection ceiling is an absolute 1e12. A target whose threshold has risen above it reads as +inf ("no score alarms"), and the attacker silently falls back to tau0. | PySAD SPOT with a true threshold of 1.57e12 reads inf. An uncapped frog over 2,900 steps reaches 1.1e11 tau0, and its end-of-campaign reading becomes None (second reader's repro). | Only the uncapped `frog`/`subl` cells of PySAD SPOT in tw1a. There the attacker is weakened, so the terminal catches can be overstated, and `median_reading_at_campaign_end` is biased low. Capped cells and the Gaussian rerun cannot reach 1e12. | Fixed in place: the bracket widens geometrically up to 1e300 before bisecting. Outputs below 1e12 are unchanged. | `Tw1Tests.test_bisect_beyond_old_ceiling` |
| F4 | `tw1a_score_level_dev.py:187,256`, not frozen | One RNG per mode is shared by all targets and runs, and it is consumed only when a run has alarms. A target's chance reference therefore depends on which targets ran before it. An `only` rerun (amendment 3) gets different shifts from a full run. | Same alarms: 0.185 in a full run, 0.170 in a rerun. | `chance_detected` in tw1a. This is Monte Carlo noise (SE about sd/√200 per run), not bias, but it cannot be reproduced. Stored tw1a outputs were made with the old scheme, so a rerun of the new code will differ from them by that noise. | Fixed in place: `chance_rng(mode, target, run)` seeds each (mode, target, run) separately. `chance` now uses a cumulative sum and gives the same value for the same shifts (4.8 times faster on a 120k-step run). | `Tw1Tests.test_chance_*` |
| F5 | `tw1_adapters.py:99-101` (`RiverQuantile.tau`), not frozen | river alarms on `score >= (quantile or inf)`, so a quantile of exactly 0.0 never alarms. The adapter returned 0.0. | Stub quantile 0.0: adapter tau 0.0, river never alarms. | None reported: a mismatch would have raised `Disagreement` and stopped the run. Latent. | Fixed in place (`math.inf if not v`). | `Tw1Tests.test_river_quantile_zero_never_alarms` |

F3–F5 come from a second reader I asked to review the tw1 files. I checked each repro before fixing it.

### Verifiers: do they check what they claim?

- **`verify_tt1.py` and `verify_tt1b.py`** say "frozen files unchanged". They only compare the digests stored in
  each result file with the protocol, so neither one hashes the files on disk. A frozen file edited after the
  final would still pass. `verify_tt1d.py` does hash the disk (`check_frozen`). I did not change the two
  verifiers; check counts stay 27 and 8. Instead, `FrozenDigestTests` checks the disk against all three
  protocols, and I propose it for CI (below).
- **Ledger prefix.** The fi1 plan's `EXPLORATORY fi1` ledger reason made `verify_tt1b` report 7 of 8 after
  workstream A opened BATADAL. I reported it during the round, and main fixed it in 7632050. My final runs
  include that commit.
- Everything else in the three verifiers does what its name says: one access per dataset, access after the
  registration commit, gates recomputed from stored per-run records, event and placement counts, sealed-run
  identity and ProvICS row coverage.

### The two items the first audit left open

1. **The tt1 G2 bootstrap resamples events, not streams. Decided: the G2 verdict does not change.** A cluster
   bootstrap needs only per-stream sums, and the post-hoc file stores them while reproducing the registered
   counts: test1 has 28 events, frozen 26 and tracker 12; test2 has 10 events, frozen 10 and tracker 8. At the
   stream level the interval is [−0.50, −0.20], against the registered event-level [−0.58, −0.26]. Every one of
   the three distinct resamples has tracker below frozen, so G2 (upper end < 0) holds. Two streams are a thin
   basis for any interval, but the sign holds in every stream. Command: `python scripts/fi1_tt1_g2_cluster_check.py`.
   Output: `target/real-telemetry/fi1/pipeline/tt1_g2_cluster.json`.
2. **The `gpd_mle` cold-start cap. Decided: it does not touch the tt1d Tennessee Eastman numbers.** SpotGR's
   first fit is always cold. On the attack-free calibration pool of every TEP mode (9,600 peaks each, from the
   tt1f cache), the cold fit equals scipy's MLE to within 1e-8 relative NLL. The fitted θ is at most 0.07 % of
   the cap, with ξ between −0.13 and 0.38. Command: `python scripts/fi1_gpd_cold_check.py`. Output:
   `target/real-telemetry/fi1/pipeline/gpd_cold_check.json`. ProvICS has no score cache. There the cap binds
   only for ξ̂ of roughly 5 or more, since θ_max·ȳ = 1000 corresponds to ξ ≈ log 1000 + E log(y/ȳ). Its stored
   tau0 and p are ordinary, so I did not check it further.

### A suspected finding that was wrong

At first I suspected that `tt1d_data.provics_attack:253` turns a ground-truth row lying before the recording into
an observed `[0, 1)` event. It does not: the tuple assignment uses the unclamped `a`, so such a row keeps
`b <= 0` and counts as unobserved. `ProvicsIntervalTests` pins this behaviour and the source line.

## Checked and found correct

- **`real_telemetry_core`:** the Scaler fits on fit-split data only; feature causality; `valid_index`; residual
  alignment; `events`; `event_report`; the Forecaster's row sampling.
- **`inject`:** the freeze and replay sources lie before the window whenever callers pass start ≥ T/4, which
  the injectors do.
- **`real_telemetry_injections.Injector`:** for every HAI family, labels are one contiguous run, and Z and V are
  unchanged outside it (`InjectorTests`). One quirk, not a defect: `regime_flip` takes the new level from the
  50 lowest distinct values of an action (`np.unique(...)[:50]`). For an action with more than 50 levels, a
  flip therefore always moves toward the bottom of its range. This affects development injections only.
- **`real_telemetry_data`, `tt1_data`, `tt1b_data`, `tt1d_data`:** column roles and constant-column drops come
  from training data only. The HAI 20.07 margin cut and run edges are correct. ProvICS dev and sealed rows
  neither overlap nor leave a gap, and `_p_grid` is checked against hand-computed bins and a validity mask
  (`GridTests`).
  - HyGrid's 1 Hz aggregation does not reindex missing seconds. On the development 40 % that removes 13 of
    34,753 seconds (three 4–5 s gaps), so in practice it has no effect.
  - voraus-AD decimates by global row index, so each sample's phase shifts by up to 90 ms. This is harmless and
    consistent between train and test.
  - BATADAL bins take the last row's values but the bin-wide label maximum. This is a minor alignment choice.
- **`tt1_final`:** `split` gives a chronological partition (tested). Thresholds, the `paired` direction, and G1
  to G3 (G2 direction tested).
- **`tt1b_final`:** H1 to H3 (H2 tolerance tested). Frog placements avoid labels.
- **`tt1d_final`:** `cluster_bootstrap` (singleton groups match the event bootstrap; whole runs are resampled;
  95 % coverage on synthetic data), `stream_rows`, `summarise`, `summarise_campaigns`, gates. The ceiling rules
  never miss what κ·tau0 catches (the H3/P3 claim, tested on random inflating streams).
- **Threshold rules, batch against online:** tracker, tighten-only, daily (v2), SPOT, DSPOT and SPOT-MLE are
  identical. The tt1c path matches a manual loop for tracker_hold, tracker_capped, daily_excl and spot_gr. No
  rule's threshold at step t depends on the score at t. GPD method of moments, z_q and gpd_mle agree with
  scipy. tt1e ceilings and gate, tt1g OnDelay, EWMA and Recal are tested.
- **Shared code paths:** episode counters in `threshold_rules`, `real_telemetry_detect` and tw1a match a
  brute-force merge on 1,500 random arrays. The circular-shift chance references in `tt1f_batadal_trace.chance` and tw1a match a brute-force `np.roll`
  count. `tt1f_tep_dev.chance_clear_peaks` uses the same wrap formula and was read, not run.
- **`real_telemetry_detect_v2.calibrate`:** meets its budget on its own input in 30 random cases.
- **Paper tooling:** `tt1_named_version.py` requires an exact single match per replacement and refuses
  anonymous residue. `tt1_artifact_deps.py` only follows static imports. tt1d loads tt1c and tt1e through
  `importlib`, so they are in the closure only because other entries import them statically. The duplicate
  `tt1b_dev.py` entry is harmless.
- **tw1 (second reader):** campaign windows, labels, clones, the consistency check, episode counting, the chance
  computation (shifts in [1, n−1]), merge arithmetic, `tw1a_export_setup.py` and `tw1_catalogue_build.py`.
  One design note for the write-up: the chance reference keeps short shifts that still overlap the event,
  which makes the reference conservative.

## Counts before and after

| | Before | After |
|---|---|---|
| Tests in `scripts/` (excluding the physical-sim test, which errors at collection for an unrelated import) | 46 | 86 |
| Tests on the modules in scope | 17 | 57 |

Line coverage of the in-scope modules, with the tests in scope (`coverage run --include=...`). Statement counts
include import-time lines.

| Module | Statements | Before | After |
|---|---:|---:|---:|
| real_telemetry_core | 173 | 30 % | 38 % |
| real_telemetry_injections | 186 | 9 % | 77 % |
| threshold_rules | 81 | 23 % | 67 % |
| threshold_rules_ext | 104 | 13 % | 95 % |
| threshold_online | 98 | 40 % | 79 % |
| threshold_rules_tt1c | 257 | 27 % | 68 % |
| threshold_rules_tt1d | 42 | 0 % | 67 % |
| threshold_rules_tt1e | 76 | 0 % | 49 %+ |
| threshold_rules_tt1g | 80 | 0 % | 29 %+ |
| tt1_final | 279 | 0 % | 27 % |
| tt1b_final | 206 | 0 % | 26 % |
| tt1d_final | 425 | 0 % | 28 % |
| tt1d_data | 167 | 32 % | 35 % |
| tw1_adapters | 263 | 0 % | 38 % |
| tw1a_score_level_dev | 231 | 0 % | 22 % |
| real_telemetry_detect | 234 | 39 % | 39 % |
| real_telemetry_data, real_telemetry_dev, tt1_data, tt1b_data | — | ≤ 32 % | ≤ 32 % |

The tt1e and tt1g figures were measured before `LaterRuleTests` was added, which raised both further. The
loaders and model-fitting functions stay low because they read data files or fit LightGBM, and neither belongs
in a unit test.

## Verifiers (final runs on this branch, with 7632050)

tt1 27 of 27, tt1b 8 of 8, tt1d 19 of 19 (tep59) and 22 of 22 (provics). All pass.

Wall times on a loaded machine (other agents were running QEMU tests):

| Verifier | Baseline median of 3 | Final, one run |
|---|---|---|
| tt1 | 15.0 s | 48.9 s, a single cold run under load |
| tt1b | 16.6 s | 14.9 s |
| tt1d tep59 | 31.0 s | 19.5 s |
| tt1d provics | 35.6 s | 12.0 s |

The variation is load, not code: I changed no file that the verifiers import.

**Profile of `verify_tt1d.py provics`** (cProfile, 15.1 s total):

- 9.6 s goes to importing `tt1d_final`. Of that, 8.5 s is lightgbm and sklearn, pulled in at the top of the
  frozen `real_telemetry_core`.
- 1.9 s is `assemble`: 186 cluster bootstraps of 10,000 resamples.
- 1.3 s is three `git log` calls.

The only safe speed-up would have to avoid those imports. The imports sit in frozen files, so it would mean a
lazy-import shim in the verifiers. That gains at most about 3 s, because sklearn is needed anyway, and the
verifiers' ledger logic is under the coordinator's control. I did not apply it.

For the tw1a harness, `chance` is now 4.8 times faster with identical values. Its run time is dominated by
per-step calls into the third-party targets. I did not profile it end to end, since that needs the tw1
environment and a full part run.

## Proposed CI lines (not applied; ci.yml unchanged)

```yaml
      - name: Analysis pipeline tests (fi1)
        run: |
          python -m pip install --disable-pip-version-check pytest scipy scikit-learn lightgbm pandas
          cd scripts && python -m pytest -q test_fi1_pipeline.py test_real_telemetry_detect_v2.py test_threshold_online_v2.py test_threshold_rules_tt1c_v2.py test_tt1d_data_v2.py
      # add to the ruff check / ruff format --check lists:
      #   scripts/test_fi1_pipeline.py scripts/tt1d_final_v2.py scripts/real_telemetry_core_v2.py
      #   scripts/fi1_tt1_g2_cluster_check.py scripts/fi1_gpd_cold_check.py scripts/tw1_adapters.py scripts/tw1a_score_level_dev.py
```

Two classes need repository files that CI has. `FrozenDigestTests` hashes files tracked in git.
`CampaignEpisodeTests.test_exploratory_copies_fixed` imports tt1e and tt1g; their imports need no data. Pinning
pytest and the scientific stack to the versions already pinned in ci.yml is advisable.

`tt1e_defense_dev.py` and `tt1g_baselines_dev.py` got a one-line fix each but were not reformatted, because
ruff format would rewrite about 290 lines of their existing style. Every new file and both tw1 files pass
`ruff format --check` and `ruff check`.

## Not done in this round

- The effect of F2 on rt1/rt2 D2/D3 detections. It needs the HAI test files: rescore once with
  `real_telemetry_core_v2.rolling_mean`.
- The effect of F1 on the stored tt1d campaign diagnostics. The TEP sealed scores are cached under
  `target/real-telemetry/tt1f`, but reading them is a sealed-data access with no ledger row, so I left it.
- An end-to-end profile of the tw1a harness.
- A finer-than-stream (block) bootstrap for tt1 G2. It needs per-event detections on HAI 20.07, which no stored
  file has. That means one ledgered post-hoc rescoring (about 30 minutes of CPU).
- The data loaders' fit and scale paths, and the LightGBM forecaster. They are read and judged correct above,
  but they have no unit tests.
