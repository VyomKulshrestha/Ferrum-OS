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
| `verify_physical_jepa_robustness.py` (regeneration) and `verify_physical_world_model.py` (full sweep) | the results depend on the number of BLAS threads (below) | regeneration skipped, with a printed reason, on machines with fewer than 24 logical CPUs |

### The physical-JEPA evidence depends on the number of BLAS threads

The trainer and the robustness evaluator use NumPy's multi-threaded linear algebra, and the order of
floating-point summation changes with the number of threads. Measured on the development machine
(24 logical CPUs; OpenBLAS 0.3.29, Haswell kernel, at most 24 threads), regenerating
`physical_jepa_robustness.json`:

| BLAS threads | Result |
|---|---|
| 24 (the default here) | identical to the committed report |
| 4 | 30 values differ, by up to 5.9%; identical, digit for digit, to what GitHub's 4-core runner produces |
| 1 | 30 values differ; a third set |

Examples at 4 threads against the committed report: the matched autoencoder's false positives 16 against
17; `validation_h1` at the second data-scaling point 0.01325 against 0.01384. With 24 threads forced on
the 4-core runner the evaluator's numbers shift again and one of its own gates fails, so the evidence
does not reproduce there under either setting. On the runner at 4 threads the full sweep's comparisons
still pass (for example JEPA against the matched autoencoder); only the exact values and the checkpoint
digest differ.

The full training sweep was then rerun on the development machine with the pinned 24 threads
(`verify_physical_world_model.py` without `--quick`): it reproduces the deployed checkpoint, the
selection, every promotion decision and the training corpus byte for byte (20 of 20 checks). The same
dependence shows in the threshold studies' monitor: refitting it with BLAS and LightGBM capped at two
threads moves calibrated thresholds by up to 0.4% (workstream A), with identical detection counts where
compared.

Consequences. The evidence described as deterministic reproduces only on a machine that runs 24 BLAS
threads natively; the workflow "Reproduce deterministic public evidence" never reproduced it on GitHub
(hidden by the exit-code gap). Both verifiers now pin the reference thread count for their subprocess,
so on the development machine the check no longer depends on the caller's environment, and they skip
regeneration with a printed reason on smaller machines. No published number was changed. The reports
should state the dependence; future studies should train with one BLAS thread, which is slower and
reproducible, and record the thread count in the protocol.

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

### Round 3: a third agent attacks the round-2 claim (same pull request, head 09d1bc4)

No critical break: with the auto-approve tier at 3 or below it found no way to run a tier-3 or tier-4
action with no operator approval. Host tests re-run by the main session: heliox-gate-tests 44,
physical-runtime 175, neural-protocol 19. This is the stopping point the plan sets for the workstream.
Four breaks were found and fixed:

- **High: an approved kernel upgrade survived a rewrite of the image it boots.**
  `trigger_kernel_upgrade` takes no arguments and runs whatever is in `/disk/boot/kernel.bin`, so the
  rule that withdraws an approval when its file changes did not know about it. The tool is now tied to
  that file and the operator's display names it.
- **Medium: the model could read two secrets kept for the operator** (the bridge pairing token from the
  screen, the provider API key from the daemon's config file) and send them out with a tier-2 network
  call. Both are now redacted wherever the model reads them.
- **Medium: the agent could forge audit entries** by writing newlines into `audit_write`. Agent text is
  now one escaped, marked line. The kernel's 256-entry audit ring can still be flooded (kernel change).
- **Low:** `sleep` with a huge argument froze the daemon; it is now refused above 10 seconds.

Questions the round leaves for the author, each pinned by a test of current behaviour:

1. **Read, then send.** At the default auto-approve tier 2, reading (files, the screen, `poll_input`,
   which sees every key the operator types) and sending over the network both run without asking, so
   anything the agent can read can leave the machine. Options: network calls at tier 3; a destination
   allow-list; approval for a network call that follows a read; `poll_input` at tier 3; or keep it and
   state it.
2. **The operator approves by id from a console the agent can scroll.** A request is printed once; a
   long second request can scroll a short dangerous one off screen, and the shell has no command to list
   or deny pending requests.
3. A configuration file that exists but does not parse falls back to auto-approve tier 2, which raises
   authority if the operator had chosen 0 or 1.
4. Test hooks under `/tmp` ship in the production daemon (one makes an ungated request at start-up).
5. The round-2 decisions above remain open.

The claim the gate supports after three rounds, with its exclusions, is in
`fi1_reports/userland_round3.md`.

## 4. Kernel (workstream C, round 1; draft pull request 3, head 0302dbd, CI green)

Twelve defects fixed. The agent built a negative-control image (its new harnesses and self-tests with
the fixes held back) to show that each harness fails without its fix. Detail, the harness table and the
raw timings: `fi1_reports/kernel_round1.md` on the pull-request branch.

| | Defect | Where |
|---|---|---|
| High | kernel tasks kept a dead process's page-table root, so reaping freed live page tables and the next launch hung the kernel | `src/scheduler/mod.rs` |
| High | the shell's `syscall <pid>` command ran with any process's authority from a guest or user session (now needs `cap:system:all`; diff read by the main session) | `src/shell/commands.rs` |
| High | a non-canonical load address in an ELF file panicked the kernel from Exec | `src/process/mod.rs` |
| High | caller-sized kernel buffers aborted the kernel when the heap ran out (file reads, random bytes, socket receive, RamFS writes) | `src/fs/mod.rs` and others |
| Medium | Exec of a package path with a doubled separator skipped the package signature gate | `src/syscall/process.rs` |
| Medium | the ELF loader mapped one page past unaligned segments | `src/process/mod.rs` |
| Medium | keyboard and mouse interrupts spun on the scheduler lock; windows outlived an exited process; dead processes leaked when a wait reaped another; ext2 name and entry bounds | several |
| Medium | agent-injected keys reached the root kernel shell (the kernel half of the gate's keystroke route) | `src/input/mod.rs` |
| Low | kexec copied up to 8 MiB into the heap before its size check | `src/syscall/kexec.rs` |

Harnesses (agent's runs): the nine baseline harnesses 81 of 81 on the final image; the new kernel
self-tests 18 of 18 on the final image against 6 of 12 on the negative control; process reaping 9 of 9
against a hang on main at the second launch after a kill; pid reuse 6 of 6 against 4 of 6.

Checked by the main session, one run each on images downloaded from CI (identified by digest), machine
under load:

| Harness | main's image | pull request's image |
|---|---|---|
| `verify_kernel_selftests` | 4 of 18, 227 s | 18 of 18, 75 s |
| `verify_process_reap_cr3` | 3 of 4, the kernel hangs at the second launch after a kill, 238 s | 9 of 9, 64 s |
| `verify_pid_reuse` | not run | 6 of 6 |
| `verify_ring3` | 7 of 7, 210 s | 7 of 7 in three of four runs, about 72 s |

The one failing `verify_ring3` run was a race in the harness, which read the serial text the moment the
banner appeared; the faster kernel exposed it. The harness now waits for the line (pull request 3,
6009cfc) and passes.

Speed (agent's runs, five alternating boots each, machine under load):

| | main, median | final image, median |
|---|---|---|
| boot to the shell prompt | 164.3 s | 52.9 s |
| ring-3 Exec of the daemon | 33.8 s | 0.8 s |

Two causes: the audio driver waited on two reset bits that QEMU never sets (one of them is write-only by
specification), 109 seconds of a boot, now bounded (diff read by the main session); and the frame
allocator re-walked the memory map on every allocation. The remaining 53 seconds are mostly the
bootloader reading the image and one audio command inside QEMU, neither kernel code.

Designed, not implemented (they need userland to adopt them): a pointer-target query for binding a click
approval, a per-file change counter for binding an approval to a file version, and a receive call that
returns the sender. Still open in the kernel: the desktop's terminal window still executes injected
keys; network items (listen-port hijack, socket limit, packet length bound); quotas never enforced; no
NX bit; ring-0 faults treated as user faults.

### Kernel round 2 (draft pull request 6, stacked on pull request 5; head 8d21d68 after the merge below, CI green)

Fifteen defects fixed in the areas round 1 left. Detail and the negative-control table:
`fi1_reports/kernel_round2.md` on the pull-request branch.

| | Defect |
|---|---|
| High | the network card's receive path let one 60,000-byte frame overwrite about 57 KiB of other physical memory, then read up to 64 KiB out of bounds through the frame's length field |
| High | DMA addresses were truncated to 32 bits (a transmit buffer above 4 GiB would send another page of memory onto the wire; not testable here) |
| High | a fault in ring 0 was blamed on the current process: the process was killed and the kernel ran on. Any ring-0 fault now stops the kernel |
| High | nothing was non-executable: user data, stacks, mmap pages, the kernel heap and the physical-memory alias now are |
| High | the page quota could be escaped (the exemption followed the program's name; mmap fault-in ignored the quota) |
| Medium | the continuous-CPU quota was never enforced (a ring-3 task that runs 5.5 s without a system call is now ended; the daemon holds the exemption capability, checked by the main session); a second process could bind a port another listened on; a half-open handshake held a listener forever; no limits on sockets or processes; any process could stop a kernel service; a crafted ext2 superblock panicked the kernel |
| Low | task names in JSON output; the legacy system-call path from ring 3; unused interrupts unmasked; the embedded programs copied into the boot image two or three times (image 10.06 MB to 6.36 MB) |

Boot to the prompt (agent's runs, five each): 53.9 s to 47.0 s, almost all from the smaller image.

Two changes of behaviour that the author should know before merging:

- **Starting or stopping a kernel service now needs `cap:system:all`.** The daemon's `service_start` and
  `service_stop` tools get a denial, so world-model data collected on this kernel records a denial
  where earlier collections recorded success.
- **The continuous-CPU limit is enforced** for ordinary programs (not for the daemon or init).

**Merge and verification by the main session.** Pull request 5 gained commits after pull request 6
branched from it. The two were merged on pull request 6's branch (one conflict, in the self-test
dispatch table; both sides kept), CI built the result, and nineteen harnesses were run on that image
(sha256 2b4bc33b...), one at a time, each passing on its first run: 228 of 228 checks.

| Harness | merged image | Harness | merged image |
|---|---|---|---|
| `verify_kernel_selftests` | 18 of 18 | `verify_ipc_isolation` | 6 of 6 |
| `verify_kernel_selftests_k2` | 37 of 37 | `verify_process_reap_cr3` | 9 of 9 |
| `verify_net_k2` | 12 of 12 | `verify_pid_reuse` | 6 of 6 |
| `verify_authority_gate_joint` | 37 of 37 | `verify_assistant_panel` | 5 of 5 |
| `verify_authority_gate_self_approval` | 11 of 11 | `verify_net` | 5 of 5 |
| `verify_authority_gate_input_injection` | 7 of 7 | `verify_user_pointer_isolation` | 4 of 4 |
| `verify_ring3` | 7 of 7 | `verify_scheduler_stubs` | 7 of 7 |
| `verify_mmap` | 7 of 7 | `verify_current_pid` | 6 of 6 |
| `verify_core_apps` | 24 of 24 | `verify_audio_nonblocking` | 7 of 7 |
| `verify_app_window` | 13 of 13 | | |

Host tests on the merged branch: heliox-gate-tests 70, physical-runtime 175, neural-protocol 19.

Left for a third round: concurrency in the interrupt and context-switch paths; kernel stacks without a
guard page; the bootloader's stack still executable; an audit of `src/syscall`, `src/ipc` and `src/fs`
by a reader who did not write the gate changes; mailboxes owned by task name; a crafted ext2 inode size
that aborts the kernel; and, in the daemon's HTTP client, a chunk length that can overflow (one crafted
response crashes the daemon) and responses silently cut at 32 KiB.

## 5. Kernel and userland together (joint round 1; draft pull request 5, head 47e97e0, CI green)

Pull request 5 contains pull requests 2 and 3 and is to be reviewed after them. It removes two of the
exclusions the gate's claim carried and narrows a third.

- **Sender identity (done).** A new receive call (syscall 61) returns the sender's pid and two flags
  that only the kernel sets: "the kernel shell" and "the assistant panel the kernel launched for the
  operator". The daemon reads its control mailbox only through it and applies a confirmation, denial,
  goal, neural arming or configuration reload only from those two senders; a sender the kernel cannot
  establish is refused (logic read by the main session in `authority.rs` and `orchestrator.rs`). A panel
  started by any process, the daemon included, carries no flag, and Exec of a file named like a built-in
  program is refused. The shell gains `heliox deny <id>`.
- **Injected input (done).** Input events carry an "injected" mark. Injected keys and clicks no longer
  reach the desktop terminal, the privacy lock, the launcher, the power menu, the dock, window close
  buttons or the operator's panel; ordinary application windows still receive them.
- **File version (done, with one window left).** Every file has a change counter (syscall 62). An
  approval of a write, create, delete, exec or kernel upgrade is bound to the file's version at request
  time, so a change by any process withdraws it. Still open: a change between the daemon's version check
  and its action, which are two system calls.
- **Click target (not done).**

Checked by the main session on images downloaded from CI. The image of the pull request's head has the
same digest as the one the agent tested (e3f39abf...), so the build is reproducible from the same source.

| Harness | negative control (enforcement held back) | pull request 5's head |
|---|---|---|
| `verify_authority_gate_joint` | 17 of 24: a forged CONFIRM approved the write; an approved delete ran after another process changed the file; injected keys reached the terminal | 24 of 24 |
| `verify_authority_gate_self_approval` | | 11 of 11 |
| `verify_authority_gate_input_injection` | | 7 of 7 |
| `verify_kernel_selftests` | | 18 of 18 |
| `verify_ring3` | | 7 of 7 |
| `verify_ipc_isolation` | | 6 of 6 |

Host tests re-run by the main session: heliox-gate-tests 54, physical-runtime 175, neural-protocol 19,
capability matcher 19 of 19.

Exclusions that remain in the claim: the click target; the check-then-act window of the file version;
read-then-send at the default tier; approvals by id from a console the agent can scroll; whoever types
at the physical keyboard or serial console is the operator; the two physical-runtime replay items.

### Joint round 2: a fresh agent attacks pull request 5's mechanisms (same pull request, head 3170366, CI green)

No critical break: no way was found to have an operator command applied from a non-operator, or to get
a tier-3 or tier-4 effect with no approval, through the sender flags or the injected mark. Four defects
were found in and under the file-version mechanism and fixed:

- **High: a write deleted a directory tree.** In the in-memory filesystem a write to a path that names
  a directory replaced the directory node and dropped everything under it. `write_file` of
  `/disk/heliox` (tier 3) removed the daemon's configuration and every file beside it, after which the
  daemon fell back to the default auto-approve tier. A write now refuses a directory, as ext2 already
  did (fix read by the main session in `src/fs/mod.rs`).
- **Medium:** one test path reported a fixed file version, so an approved exec there survived a rewrite
  of the binary.
- **Medium:** a directory's version did not change when something deeper inside it changed, although
  deleting the directory removes all of it. Every change now gives a new version to every directory
  above it.
- **Low:** Exec treated any path containing a test program's name as that program, which bypassed the
  reserved-name rule.

Built in the same round:

- **The check-then-act window is closed.** New calls (syscalls 63 to 65) write, delete and execute only
  if the file still has the expected version, checked in the kernel in the same step as the action. The
  daemon passes the version an approval was bound to.
- **Click target.** A new call (syscall 66) reports the window, its owner and the position under the
  pointer. An approved click is bound to that target, the operator is shown it, and the click is refused
  if the target changed. Not covered: what the application draws at that position, and keyboard focus.

Checked by the main session: host tests heliox-gate-tests 70, physical-runtime 175, neural-protocol 19;
on the head's image from CI (sha256 ec5f18fa..., the image the agent left in place):
`verify_authority_gate_joint` 37 of 37, `verify_authority_gate_self_approval` 11 of 11,
`verify_authority_gate_input_injection` 7 of 7, `verify_kernel_selftests` 18 of 18, `verify_ring3` 7 of
7, `verify_app_window` 13 of 13, each on its first run.

What the claim still excludes: what an application does with an approved click, and which window
receives approved typed text; physical input after an approved pointer move or focus change;
read-then-send at the default tier; approvals by id from a scrollable console; the two physical-runtime
replay items; and the assumption that whoever types at the keyboard or serial console is the operator.
New questions for the author: the panel's flag is accepted for confirmations although the panel never
sends them; the boot-time setup launch marks a panel the operator did not ask for; deleting a directory
above the daemon's configuration is not refused (it needs a tier-4 approval).

With two consecutive rounds (userland round 3 and this one) finding no critical break, the gate
workstream stops here under the plan's rule.

## 6. Monitor (workstream A, round 1; merged to main)

**Verdict: not improved.** No candidate meets the definition the plan fixed in advance. The harness, the
diagnosis and the negative result are on main; detail in `fi1_reports/monitor_round1.md`, numbers in
`fi1_monitor_round1.json`. The verdict table below was recomputed by the main session from the stored
per-dataset numbers.

**The harness reproduces the registered record.** Fed the registered Tennessee Eastman scores it gives
every registered figure exactly (116 of 141 first events, 104 of 104 followers with 44 at onset, false
alarms 0.984 times the budget on the sealed runs). Refitted monitors reproduce the registered counts on
HAI 20.07 (36 of 38, onset 26, 39.1% of unlabelled time in alarm), HAI 21.03, 22.04 and 23.05, HyGrid-ICS,
BATADAL, ProvICS and Tennessee Eastman. voraus-AD gives 243 of 755 where the registered run has 252: the
refit ran with two BLAS threads, the threshold came out 0.2% higher, and nine samples lie between the two.

**Why the monitor stays in alarm.**

1. Calibration does carry over between attack-free recordings of one dataset (thresholds within 8 to
   13%), so too little normal data is not the cause on the selection set.
2. Five channels account for most of the excess: they appear in 82 to 99% of unlabelled alarm steps.
3. After attacks those channels run far above their normal residual spread (up to 3.4 times on HAI, 14
   to 17 times on Tennessee Eastman) while the plant is still disturbed.
4. Part of it is the operating regime: on HAI 21.03, 24% of unlabelled alarm steps have a sensor outside
   the range the model was fitted on, against 0.6% of quiet steps.
5. Described after the check run, without changing anything: on **HAI 20.07, 94% of the alarm time has a
   sensor outside the fit range**, and thresholds calibrated on each of its own training recordings span
   a factor of 2.2; on **ProvICS every one of the 13 channels runs above twice its normal spread across
   the whole attack recording** (median 14 times). The two saturating recordings are outside the regime
   the monitor was fitted on. That is a property of the data and of any model fitted on it; channel
   aggregation does not address it.

**Candidates.** Selection (rule committed before the results) kept three: scoring by the mean of the
second to fourth largest channel residuals (`second`), the same with median and MAD scaling
(`mad+second`), and with the threshold of the worst calibration recording (`second+loro`). On the
selection set they raised mean onset recall from 0.80 to about 0.85.

**Check set, run once** (onset detections of events; share of unlabelled time in alarm):

| Dataset | baseline | `mad+second` | `second` | `second+loro` |
|---|---|---|---|---|
| HAI 20.07 | 26 of 38; 0.391 | 26; 0.391 | 26; 0.391 | 26; 0.391 |
| HAI 23.05 | 31 of 52; 0.0071 | 30; 0.0066 | 31; 0.0067 | 31; 0.0067 |
| BATADAL | 14 of 14; 0.0138 | 14; 0.0127 | 14; 0.0101 | 14; 0.0100 |
| HyGrid-ICS | 3 of 91; 0.0407 | 14; 0.0368 | 15; 0.0067 | 15; 0.0067 |
| voraus-AD | 243 of 755; 0.081 | 324; 0.148 | 277; 0.098 | 277; 0.098 |
| Tennessee Eastman, modes 4 to 6 | 57 of 92; 0.0136 | 70; 0.0066 | 64; 0.0129 | 59; 0.0125 |
| ProvICS | 3 of 32; 0.440 | 3; 0.422 | 3; 0.389 | 3; 0.389 |
| **mean onset recall** | 0.478 | 0.528 (+0.050) | 0.514 (+0.036) | 0.507 (+0.028) |
| **mean alarm share** | 0.1410 | 0.1463 | 0.1306 | 0.1305 |

`mad+second` reaches the required gain but its alarm share is higher (voraus-AD); the other two lower the
alarm share but gain too little. No dataset loses more than 0.05 under any candidate. The alarm share on
HAI 20.07 does not move, and on ProvICS it falls from 0.44 to 0.39 at best.

What the gain is made of: on Tennessee Eastman the candidates trade first events for followers (first
events at onset 38 of 51 for the baseline against 32, 33 and 29; followers 19 of 41 against 38, 31 and
30). The HyGrid-ICS gain is at its chance level (onset recall net of chance about +0.02).

**Round 2.** The plan gives the workstream a second round. Two ideas come out of round 1 and neither
was tested in it: a combination that keeps the baseline for first events and adds `second` for
followers, each at half the alarm budget; and a monitor that says when the plant has left the range it
was fitted on. See the plan's note of 2026-11-12 for how the check set is used a second time.
