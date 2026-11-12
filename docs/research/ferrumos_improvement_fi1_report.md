# FerrumOS improvement program (fi1): report

Plan: `ferrumos_improvement_fi1_plan.md`. Per-workstream detail: `fi1_reports/`. This file is updated as
rounds finish. Everything measured on recorded attacks is exploratory; no registered or published number
was recomputed or replaced. "Checked" means the main session re-ran or re-read the claim; everything
else is the reporting agent's.

Status on 2026-11-12: workstream B rounds 1 and 2 merged; workstream D round 1 in draft pull request 2;
the CI repair in draft pull request 4; workstreams A (monitor) and C (kernel) and the second round of D
still running.

## 1. CI was passing while checks failed (main session)

GitHub runs a PowerShell step and reports the exit code of its last command. In a step with several
commands, a verifier that failed in the middle did not fail the step. Draft pull request 4 sets
`$PSNativeCommandUseErrorActionPreference = $true` in every such step of both workflows. That exposed
five checks that were failing on main:

| Check | Cause | State |
|---|---|---|
| `verify_repository_discovery.py` | requires a README heading in the first 10,000 characters; the v1.3 summary moved it to 10,415 | window widened |
| `verify_world_model_paper_evaluation.py` | the recorded digest of `world_model_safety_scenarios.json` is the CRLF form; the repository stores LF | both forms accepted |
| `verify_physical_jepa_robustness.py` | the evaluator writes CRLF on Windows; compared byte for byte with an LF file | compared after normalising line endings; content identical |
| `tools/physical_sim_bridge` PyBullet test | pybullet has no wheel for the runner's Python and is not installed | skipped with a reason when absent |
| `verify_physical_world_model.py` (full sweep) | the retrained checkpoint is not bit-identical to the deployed one on GitHub's runner; every other check of the sweep passes | **open** |

The last one is not repaired. The sweep's metrics pass on the runner and only the digest equality fails,
which points to arithmetic that differs between machines, but that is not established: the local rerun
ran out of memory. Until it is, the workflow "Reproduce deterministic public evidence" is red on the
pull request, which is the true state. The required job uses the quick form of this verifier and is not
affected.

## 2. Analysis pipeline (workstream B)

### Round 1: the threshold studies (merged, main 4d626cc)

- **A convention decides one published comparison.** `real_telemetry_core.paired_event_bootstrap` scores
  a resample in which the baseline misses no event (0/0) as "no reduction". On HAI 21.03 (DR 46 of 50,
  D1 50 of 50, 98.75% level) 1.67% of resamples are of that kind, more than the 0.625% tail, so the
  miss-reduction interval is [0.0, 1.0]; without them it is [1.0, 1.0]. Checked. The convention is
  defensible (the recall-difference interval is [0.0, 0.18] and touches zero as well); the report
  should state it.
- The campaign episode counter of `tt1d_final.play` splits two alarm runs that are exactly `gap` quiet
  steps apart; every other counter merges them. Diagnostics only (median and longest alarm episode); no
  detection, gate or interval changes. Fixed in the unfrozen copies; `tt1d_final_v2` for the frozen file.
- `real_telemetry_core.rolling_mean` accumulates in float32; the error reaches 3% of the value after a
  million steps. It feeds only the D2 and D3 classifier features. `real_telemetry_core_v2`.
- Three issues in the tw1 harness written this week (a ceiling in the bisection, a shared random
  generator in the chance reference, a zero quantile in the river adapter), fixed in place. The capped
  results of tw1a are unaffected by construction.
- The two items the first audit left open: the tt1 comparison of tracker and frozen threshold holds
  under a stream-level bootstrap ([-0.50, -0.20] against the registered [-0.58, -0.26]); the cold-start
  cap of the SPOT fit does not bind on Tennessee Eastman.
- Tests in `scripts/`: 46 before, 86 after. The four registered verifications pass unchanged.

### Round 2: the technical report "Prediction Is Not Permission" v1.3 (merged, main b71f397)

No code defect changes a headline result. Several tables depend on rules or conventions the text does
not state. In order of effect:

| | Where | What | What the report needs |
|---|---|---|---|
| R1 | Table 30 (rt1 post-hoc), `real_telemetry_posthoc_rt1.py` | the threshold search keeps the lowest threshold within the false-episode budget even past the first point where the budget breaks (the pattern the first audit fixed elsewhere). With the first-break rule three cells change: at 0.5 false episodes a day D1 43 of 58 becomes 25 and D3 42 becomes 36; at 1.0, D0 22 becomes 20. The text's comparison at one a day is unchanged | one sentence naming the rule |
| P1 | Table 13, local row, `prepare_physical_jepa_safety_gymnasium_attribution_v1.py:56-62` | two candidate thresholds are exactly tied in distance to the target false-positive rate (13 and 15 of 3,471 around 14), but in floating point 13 ranks closer, so the registered tie-break (fewer false negatives) never ran. Checked. With it, common recall of the local source would be 92.40% and not 90.49%, equal to the full adapter's | a sentence; it weakens "the full adapter has higher recall than the local source" |
| R2 | Tables 28 and 29 (rt1, DR) | under the first-break rule DR is 23 of 58 at 0.74 false episodes a day and not 24 of 58 at 0.99; 14 of 15 stored thresholds are the same under both rules; no gate depends on DR | a footnote |
| X1 | Tables 4, 5, D1 (FerrumOS, H=3 and 5) | consecutive rows of the base test data are not continuous (`after[k]` is never `before[k+1]`), so multi-step targets include changes no one-step model can predict. Levels are inflated by about 37% and 14% for the GRU; rankings and signs are unchanged | one sentence |
| X2 | Table 7 | under the frozen Platt fit a probability of 0.99 needs a raw score of 11.07 (FerrumOS) or 1.63 (Physical); the largest observed are 0.19 and 0.35. The learned branch's zero true and false positives were therefore fixed before the final catalogue was opened. Arithmetic checked | one sentence |
| I1 | Table 19 | the +45.85-point warning gain is measured against the old paper model; a JEPA retrained on the same data (stored in the result file) reaches 84.57% recall at 1.33% against 85.44% at 1.42% for the selected ensemble | add the control rows |
| X3, X4 | Section 6.2; FerrumOS H=3 | calibration error uses ten equal-mass bins (equal-width bins give 0.006 and 0.101 where the text has 0.238 and 0.293); errors are averaged per episode first (with row weighting the GRU's lead over JEPA shrinks from 0.00444 to 0.000025) | one sentence each |
| P2 to P4 | Section 8.5, Tables 14 and 15 | a hazard contrast rests on 6 discordant episodes of 128 (exact sign-flip test p = 0.031, 0.094 after adjustment for three contrasts), so "both exclude zero" depends on the method; a registered output is missing from Table 14 | wording |

Verifier gaps, no number affected: `verify_real_telemetry.py` recomputes each gate from the gate's own
stored fields; the cross-domain verifiers recompute no metric; two checks are true by construction; the
attribution verifier does not re-derive thresholds (which is how P1 passed).

Found correct: incident dynamics v2 to v4 (disjoint random streams and splits, the 1% false-positive
calibration, the Bonferroni levels, every cell of Tables 21 and 23 to 27); rt1 and rt2 event pairing and
false-episode counting; no leakage in the cross-domain study, whose Tables 3 to 6 and D1 reproduce
exactly; Safety-Gymnasium Tables 11 to 15 recompute exactly.

Not reached: the rt1 SMD calibrations, Tables 9 and 10, the HAI cross-version transfer studies, the
world-model v3 selection scripts.

## 3. Userland agent runtime and authority gate (workstream D, round 1; draft pull request 2)

On main the gate could be talked around. Checked by reading main and by re-running the branch's host
tests (heliox-gate-tests 25, including all 768 cells of tool by auto-approve tier by approval state;
physical-runtime 155; neural-protocol 19).

- **The agent could approve its own pending action.** `ipc_send` needs no approval, the kernel resolves
  the `heliox` mailbox to the daemon itself, and `ipc_poll` applied `CONFIRM:<id>` from any sender. The
  branch refuses a control message to the daemon's own mailbox before prediction or confirmation.
- **One approval could cover another action.** Approvals were matched on a summary that kept 32 bytes of
  each string and showed other values as `...`. They are now bound to a fingerprint of the complete
  arguments.
- Also fixed: writing the daemon's own configuration (which sets the auto-approve tier); internal tools
  that skipped the tier check; one IPC message carrying several commands; permit expiry and watchdog
  authority not re-checked at delivery in the physical runtime; parser limits; the operator's view of a
  pending request.
- The agent's QEMU harness for these paths: 6 of 11 on main's image, 11 of 11 on the branch's (not
  repeated by the main session).

The published v1.3 report claims that prediction cannot bypass confirmation and lists as a limitation
that its tests do not prove non-bypass. No stated claim is contradicted. The finding belongs in the next
version and had to be settled before the planned paper on the operator in the loop.

Open: the kernel gives an IPC receiver no sender identity (handed to workstream C); a missing occupancy
record counts as zero humans, and speed and payload limits are not wired into the command path (policy
decisions for the author); a second agent is attacking the fixed gate.

### Round 2: a second agent attacks the fixed gate (same pull request, head 7fec04e)

Round 1's two fixes held: no alias, case or encoding of the target reaches the daemon's control mailbox
through `ipc_send`, and an approval covers exactly one set of arguments. Another route did not hold.
Checked by reading main (`tool_mapper.rs:109` put the input tools at tier 3; `src/input/mod.rs` feeds
injected keys to the kernel shell; `src/heliox/mod.rs:852-871` forwards `confirm <id>` as `CONFIRM:<id>`)
and by re-running the branch's host tests (heliox-gate-tests 34, physical-runtime 172, neural-protocol 19).

- **Typed keystrokes approved pending requests.** `keyboard_type` was tier 3, its keys reached the
  kernel shell, and the shell's `heliox confirm <id>` approved the request. With the auto-approve tier
  at 3 no operator was involved; at the default 2 it took one approval of a keystroke call whose
  displayed text hid the command. The agent reproduced it in QEMU on the round-1 image. Now the input
  tools are tier 4 and typed text may not contain Enter, control keys or non-ASCII; no approval lifts
  that.
- **The operator approved what they could not see.** Values were shown up to 48 bytes, unescaped. Now
  every byte is printed, escaped to printable ASCII; a call too long to show is refused.
- **An approval outlived the file it was about** (approve `exec_process` of a path, replace the file,
  run). A write, mkdir or delete now withdraws pending and approved requests on that path, beneath it
  and above it.
- Lower: confirmation ids restarted at 1 with every daemon start; `execute_tool` ran calls with
  malformed arguments on defaults.
- Physical runtime: a permit outlived the state it was issued against (emergency stop, proximity, a
  human entering the zone after queueing); an older observation could overwrite a newer one; actor
  telemetry could clear a latched emergency stop; ordinary commands could fill the queue so that no Stop
  fitted; an endpoint could publish telemetry for another actor. All fixed with tests that fail before.

What the gate can be claimed to guarantee after round 2, and what it cannot, is written out in
`fi1_reports/userland_round2.md`. Four gaps need the kernel (with workstream C): injected keys are not
told apart from physical ones; a click cannot be bound to its target; an approval cannot be bound to a
file version; the mailbox carries no sender identity. Decisions for the author: `service_stop` shows
only a numeric id; model-authored memory is autosaved without approval although `save_memory` is tier
3; an auto-approve tier of 4 or more approves everything by design; the two physical-runtime items
above. Because each round found a critical route, a third agent is attacking the claim.

## 4. Monitor (workstream A) and kernel (workstream C)

Running. Filled in when they report.
