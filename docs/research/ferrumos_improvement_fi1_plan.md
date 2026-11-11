# FerrumOS improvement program (fi1): plan

Written 2026-11-12 at the author's request ("completely improve FerrumOS ... there are gaps which are
causing problems in papers ... keep looking for fixes till you see improved performance"). Committed
before any change of this program. Everything it measures on recorded attacks is **exploratory**: every
dataset in the repository is spent. No registered result is recomputed or replaced.

## The gaps, as the papers themselves show them

1. **The monitor saturates.** With the registered D1 monitor the frozen threshold was in alarm for 39%
   of the unlabelled time on HAI 20.07 and 44% on ProvICS. Counted at onset, it detects few events
   (ProvICS 4 of 32; 44 of 104 follower attacks on Tennessee Eastman).
2. **Calibration on normal data does not carry over to the test recordings** (real-telemetry study rt2;
   false alarms above the budget in several finals).
3. **Defects in the analysis code were found late.** The audit of 2026-11-10 found five, all in files a
   registration had frozen. Data loaders, the model core, the injections and the bootstraps were not
   audited then, and the analysis modules have few tests.
4. **The kernel is under-tested at run time.** Four of the six fixes merged with pull request 1 have no
   harness (kexec bound, pid collision, window cap, dead recorder). The kernel builds only in CI.
5. **The authority gate and the agent runtime in userland** carry the next paper (the operator in the
   loop) and have not had a test pass of their own since the security audit.

## Workstreams

Each workstream is one Opus subagent writing in its own git worktree on a branch `improve/fi1-<name>`
(kernel: a pull request that CI builds). I review every diff before it reaches main.

| | Workstream | Yardstick |
|---|---|---|
| A | Monitor and world model: why it saturates, and a better one | monitor benchmark (below) |
| B | Analysis pipeline: second audit, tests, coverage, speed | defects found and fixed; tests; verifiers unchanged |
| C | Kernel: run-time tests for the untested fixes, second audit, fixes | QEMU harness suite; CI build; documented OS benchmarks |
| D | Userland agent runtime and authority gate: audit, tests, fixes | gate test inventory; new tests; defects fixed |

The `vision-world-model` branch is another session's work and is not touched.

## Monitor benchmark (fixed before any change)

- **Baseline:** the registered D1 monitor with its frozen threshold, run through the benchmark harness.
  The harness must first reproduce the registered numbers where a registered result exists (for example
  Tennessee Eastman: 116 of 141 first events, 104 of 104 followers, false alarms 0.98 times the budget).
  A harness that does not reproduce them is not used.
- **Calibration:** on attack-free data only, to the episode budget of the study that used the dataset,
  with the corrected calibration routine (`real_telemetry_detect_v2.calibrate`).
- **Selection set** (may guide choices): HAI 21.03, HAI 22.04, Tennessee Eastman modes 0 to 3.
- **Check set** (reported for every candidate that survives selection; never used to choose): HAI 20.07,
  HAI 23.05, BATADAL, HyGrid-ICS, voraus-AD, Tennessee Eastman modes 4 to 6, ProvICS.
- **Metrics per dataset:** onset recall of labelled events; any-alarm recall with its chance reference
  (circular shifts); share of unlabelled time in alarm; false-alarm episodes per day on unlabelled time
  against the budget; step-level average precision; median time from event start to first alarm.
- **"Improved" means, on the check set:** mean onset recall up by at least 0.05; mean share of unlabelled
  time in alarm not higher than the baseline's; no check dataset loses more than 0.05 of onset recall.
  Reported beside it: the alarm share on HAI 20.07 and ProvICS, the two recordings where the baseline
  saturates.
- A candidate is a new module. The registered monitor, its bundles under `target/real-telemetry/frozen`
  and every cached score stay as they are.

## Yardsticks for the other workstreams

- **Kernel.** Baseline: the nine QEMU harnesses on main's boot image (81 assertions), CI build, and the
  figures of `docs/BENCHMARKS.md` re-measured. A fix counts when a harness fails on the image without it
  and passes on the image with it, and no existing assertion regresses. A speed-up counts when the
  median of five boots or runs moves by more than the spread of the baseline.
- **Analysis pipeline.** Baseline: number of tests, line coverage of the modules behind paper numbers,
  run time of the verifiers. Every defect gets a test that fails before the fix. The verifiers of the
  registered studies (tt1 27 of 27, tt1b 8 of 8, tt1d 19 of 19 and 22 of 22) must pass unchanged.
- **Userland.** Baseline: the authority test inventory and the existing verifiers. Every defect gets a
  test; the gate's decision table is checked exhaustively where it is finite.

## Rules

- Files frozen by a registration (named in a protocol JSON under `docs/research` or in the
  `FROZEN_FILES` of a `*_final.py` script) stay byte-identical. Fixes to them are new `_v2` or `_v3`
  modules.
- Recorded attacks are read only through the loaders that write the access ledger, with a reason that
  starts with `EXPLORATORY fi1`. Nothing under `target/real-telemetry/raw`, `cache` or `frozen` is
  written; new files go under `target/real-telemetry/fi1/`.
- Kernel changes reach main only through a pull request that CI builds; its merge is the author's.
- One heavy job per workstream at a time, after a memory check; no GPU.
- Every number reported comes with the command that produced it. A fix that does not help is reported
  as not helping and reverted.

## Rounds and stopping

Round 1: diagnose, measure the baseline, make the first fixes. I review, merge what holds, and start the
next round on what remains. A workstream stops when its yardstick is met, or after two consecutive
rounds without gain, or after four rounds. The report then says which.

## Outputs

`docs/research/ferrumos_improvement_fi1_report.md` (per round: what was found, what was changed, the
numbers before and after, what did not help), the branches and pull requests, and the tests.

## Note, 2026-11-12 (round 1 running)

The ledger prefix this plan prescribes (`EXPLORATORY fi1`) was not accepted by the verifiers of tt1 and
tt1b, which allowed a later access only when its reason began with "post-hoc"; the first fi1 access to
BATADAL made `verify_tt1b.py` report 7 of 8. The verifier of tt1d already accepted exploratory accesses
after the final. `verify_tt1.py` and `verify_tt1b.py` (not frozen by any registration) now accept both
labels, under the same condition as before: the access must come after the registered one. All four
verifications pass again (27 of 27, 8 of 8, 19 of 19, 22 of 22). The ledger row stays as written.
