# fi2 integration: kernel protections, gate policy and kernel audit in one branch

Branch `improve/fi2-integration`, draft pull request 10 against `main`. It starts from the head of pull request 7
(`654d29a`, kernel protections, `kernel_cpu.md`) and merges `origin/improve/fi2-kernel-audit` at `1f2133b` (pull
request 9, `kernel_audit.md`), which contains pull request 8 (gate policy, `gate_policy.md`). Merge commit `a4ff3a5`.

Method as in the three workstreams: host type-check and code-generation build of the kernel library before the push,
the host test suites and the CI host-side checks run locally, the image built by CI, and every harness run one at a
time under `C:/Users/marcu/Videos/fi1-qemu.lock` (lock first, then `memfree.py 4 4.5` while holding it, released after
each harness), `FERRUMOS_BOOT_SECONDS=600`.

## Textual conflicts

| File | Sides | Resolution |
|---|---|---|
| `src/logging/audit.rs` | K1: `AuditEntry::charged_to`, `log_user_event`, charge released when the ring drops an entry. P: `AuditEntry::source`, `log_event_from`, `insert_entry` with the per-source quota of 64 unflushed entries (`SOURCE_QUOTA`), `remove_entry`. K2: `escape_controls`, `trim_log` at character boundaries, the flush retry, `FLUSH_PATH_OVERRIDE`. | The P and K2 file is the base. `AuditEntry` has both `source` and `charged_to` (`audit.rs:43`). `log_event` and `log_event_from` (`:112`) go through `log_event_inner` (`:119`), which escapes the message first, then, for a charged record only, checks the ledger and refuses before taking the ring lock (the check reads the compositor and the socket table), and stores the entry with its source and charge. `log_user_event` (`:63`) is `log_event_inner(pid, UserAudit, message, true)`. The charge is released wherever an entry leaves the ring: `remove_entry` (`:183`, used by both quota rules) and the drain of the switched-off rule (`:196`). K1's old release in a drain after `push` no longer exists because P replaced that code; the charge now follows P's eviction paths. |
| `src/syscall/mod.rs` | K1: AuditWrite calls `audit::log_user_event(caller_pid, &message)` and refuses when the heap budget is exceeded. P: AuditWrite calls `log_event_from(caller_pid, UserAudit, ...)`. | `log_user_event(caller_pid, &message)` (`syscall/mod.rs:583`); it logs with the caller as source, so P's attribution holds. FocusTarget (67), the PackageInstall prompt and K1's move of Write to `syscall/console.rs` merged without conflict. |
| `src/shell/mod.rs` | K1: `pub mod selftest_k5;`. P and K2: `selftest_p1`, `selftest_k6`. | All three modules (`shell/mod.rs:9-11`). |
| `userland/heliox-gate-tests/tests/policy_fi2.rs:452` (no textual conflict; failed after the merge) | P's host test `q6_...` checked the source text `log_event_from(\n caller_pid,` in AuditWrite. | The test now checks that AuditWrite calls `log_user_event(caller_pid, &message)`, that `log_user_event` calls `log_event_inner(pid, AuditEvent::UserAudit, message, true)` and that `log_event_inner` stores `source` and `charged_to`. The behaviour the test pins (the caller is the source) is unchanged; the runtime check of Q6 is the self-test `audit-quota` with its switch-off control in `verify_gate_policy`. |

`README.md`, `docs/ARCHITECTURE.md`, `capabilities.json`, `llms-full.txt`, `src/fs/mod.rs`, `src/syscall/fs.rs` and
the harnesses merged without conflict; `generate_public_evidence.py --check` passes on the merge.

## Semantic checks

**1. SMAP: every user-memory access of the other branches.** A search of the merged `src/` for raw pointer accesses
(`from_raw_parts`, `copy_nonoverlapping`, `read_volatile`, `read_unaligned`, casts to `*const u8` / `*mut u8`) finds
no new access to user memory outside `syscall/fs.rs` `copy_from_user` and `copy_to_user`. The new paths use them:
FocusTarget writes its record and title through `write_target_record` (`syscall/hud.rs:147`, `copy_to_user` after
`valid_user_write_range`); the window-bound InjectKey (`syscall/input.rs`) takes only register arguments; the
PackageInstall prompt reads the package name with `read_user_str` (`syscall/mod.rs`, `confirmation_subject`);
SystemQuery type 5 (`syscall/query.rs:44`, `query_services`) returns through the existing `copy_to_user`;
`refuse_kernel_record` and `refuse_shell_only` (`syscall/fs.rs:160`, `:171`) work on the path string already copied by
`read_user_str`; the audit paths log kernel strings. `selftest_p1.rs` and `selftest_k6.rs` read user memory only
from ring 3 programs, never from ring 0; `selftest_k6.rs:118` reads physical memory past the virtio backing through
the kernel's physical map (supervisor pages). The proof is the run of every harness under `-cpu Broadwell-noTSX`
(SMAP on) below: no ring-0 page fault.

**2. IOPL 0 and AC clearing.** Neither other branch adds an interrupt or exception gate, an entry stub or a ring-3
context constructor: `src/interrupts`, `src/scheduler` and `src/gdt.rs` are unchanged by them (23 `x86-interrupt`
handlers, the same 22 AC-clearing call sites as on pull request 7). No self-test of theirs uses port I/O from ring 3.

**3. The heap ledger.** New per-process kernel allocations of the other branches:
- audit entries: an AuditWrite record is charged to its writer (above); P's quota bounds each source to 64 unflushed
  entries and the ring to 256, each message at most 1,024 bytes before escaping (`syscall/mod.rs` AuditWrite) or a
  kernel-written string. Kernel records are not charged; the ring bounds them.
- package state: the package registry is global and written only by PackageInstall/Remove of signed packages from
  the catalog; it is bounded by the catalog, not per process. Not charged.
- focus bindings: a bound InjectKey queues two input events in the existing bounded input queues; FocusTarget
  allocates nothing that outlives the call. Not charged.
- `/tmp/heliox-hooks`: created by the kernel (owner 0, not charged); ring 3 cannot create files there.

**4. Console marking.** The kernel's own prompts are printed by the kernel and stay unmarked: the DeleteFile and the
new PackageInstall prompt (`[SECURITY] Process N is requesting destructive syscall: PackageInstall name="..."
capabilities=...`) are `println!` in `dispatch_for_process`. K2's `escape_printable` of titles applies to kernel lines
that quote a title; process console output is marked by K1. `verify_kernel_k6` matches `[SECURITY]` and `[N]
SecurityViolation` at line starts produced by the kernel, and `verify_gate_policy` matches daemon text as substrings;
both pass below with the marking on.

**5. RamFS.** `/tmp/heliox-hooks` and its triggers are written by the kernel shell (no syscall, not charged; the
ledger charges RamFS writes only inside the WriteFile syscalls, `syscall/fs.rs:311` and `:315`). The kernel-record and
shell-only refusals run before `with_fs_owner`, so a refused write charges nothing.

**6. ext2.** K2's `audit-flush` test mounts an ext2 RamDisk built in memory (revision 1, no feature bits), which the
mount-time feature check accepts. The flush rewrites the file through `create_file_bytes`; the overwrite now frees
the old blocks through `release_inode_blocks` (a scan of the used inodes, a few dozen on that disk). The 12-block file
limit that K2's flush retry works around is unchanged (K1 made only directories grow past 12 blocks), so the retry
still runs (`trimmed_flushes`, below).

**7. Self-test dispatch.** `test-syscall <name>` tries `selftest::run`, which falls through k2, k3, k4 and k5 (k4
ends in `selftest_k5::run`, k5 returns false for an unknown name), then `selftest_p1::run`, then
`selftest_k6::run` (`shell/commands.rs`). No name is defined twice.

## Images

| Image | CI run | Commit | sha256 | size |
|---|---|---|---|---|
| pull request 7 head | 43274432214 | `654d29a` | `db45b4d2ae6d3c676cfa887854c9c6d7437bbac7b48493d0197b5e32c4e5fcc4` | 7,302,656 |
| pull request 9 head (contains 8) | (pull request 9) | `1f2133b` | `0a30642b0911032eb25e4204923965d6324a5db4c195b06a2326417622747470` | 7,031,296 |
| integration | 43288923458 | `a4ff3a5` | `5bb2c6a75db2db9d184232cf22d6a5267dbbebfe83021ecb6f5334de715b5df5` | 7,474,176 |
| integration head (+ this report) | the run of that commit | (this commit) | expected identical to `a4ff3a5`'s (report only; checked after the push, see the pull request) | |

## Harness results on the integration image

Image `5bb2c6a7...` (`a4ff3a5`). First column: the default CPU (`-cpu Haswell`, SMEP on, SMAP off). Second column: every
harness again with `FERRUMOS_QEMU_CPU=Broadwell-noTSX` (SMEP and SMAP on; the boot line of every serial log of that pass
reads `smap=true`).

| Harness | expected | Haswell | Broadwell-noTSX |
|---|---|---|---|
| verify_kernel_k5 (new in 7) | 51 | 51/51 | 51/51 |
| verify_kernel_k6 (new in 9) | 31 | 31/31 | 31/31 |
| verify_gate_policy (new in 8) | 26 | 26/26 | 26/26 |
| verify_kernel_k4 | 39 | 39/39 | 39/39 |
| verify_kernel_k3 | 48 | 48/48 | 48/48 |
| verify_kernel_selftests | 18 | 18/18 | 18/18 |
| verify_kernel_selftests_k2 | 37 | 37/37 | 37/37 |
| verify_net_k2 | 12 | 12/12 | 12/12 |
| verify_authority_gate_joint | 37 | 37/37 | 37/37 |
| verify_authority_gate_self_approval | 11 | 11/11 | 11/11 |
| verify_authority_gate_input_injection | 7 | 7/7 | 7/7 |
| verify_ring3 | 7 | 7/7 | 7/7 |
| verify_mmap | 7 | 7/7 | 7/7 |
| verify_core_apps | 24 | 24/24 | 24/24 |
| verify_app_window | 13 | 13/13 | 13/13 |
| verify_ipc_isolation | 6 | 6/6 | 6/6 |
| verify_process_reap_cr3 | 9 | 9/9 | 9/9 |
| verify_pid_reuse | 6 | 6/6 | 6/6 |
| verify_assistant_panel | 5 | 5/5 | 5/5 |
| verify_net | 5 | 5/5 | 5/5 |
| verify_user_pointer_isolation | 4 | 4/4 | 4/4 |
| verify_scheduler_stubs | 7 | 7/7 | 7/7 |
| verify_current_pid | 6 | 6/6 | 6/6 |
| verify_audio_nonblocking | 7 | 7/7 | 7/7 |
| the twenty-one fi1 harnesses | 315 | 315/315 | 315/315 |
| total | 423 | 423/423 | 423/423 |

Every harness passed on its first run in both passes, one at a time under the shared lock (other sessions' runs
interleaved). How the variable acts per harness: `verify_kernel_k5` chooses its CPU per boot (A, C and D `-cpu
Haswell`, B `-cpu Broadwell-noTSX`) and ignores it, so its second run repeats the first; `verify_kernel_k6` boots
through `bootShell` and takes it in all four boots, the one with `-device virtio-gpu-pci` included (the device
argument is added to the CPU model, not instead of it); `verify_gate_policy` and the fi1 harnesses that spawn QEMU
themselves read it in their `-cpu` argument; `verify_net` was started only after host port 8080 was free (it was).


## Host tests and CI checks

| Suite | pull request 7 | pull request 9 | integration |
|---|---|---|---|
| userland/heliox-gate-tests | 78 | 99 | 99 (one source-text assertion of `q6_...` follows the merged AuditWrite, above) |
| userland/physical-runtime | 175 | 179 | 179 |
| userland/neural-protocol | 19 | 19 | 19 |

`generate_public_evidence.py --check`, `verify_public_json_schemas.py`, `verify_public_evidence_contract.py`,
`verify_qemu_command_evidence.py`, `verify_repository_discovery.py` and the CI's first ruff line pass locally; both
workflows are green on `a4ff3a5`.

## Behaviour changes of the whole

The union of the three lists, with no change from merging:
- Kernel protections (`kernel_cpu.md`): SMEP and SMAP where the CPU has them; process console output marked
  `[pid N] `, `[SECURITY` written `[pid-SECURITY`, non-printable bytes as `\xNN`; ring 3 at IOPL 0; floating-point
  exceptions end the process with exit 136; 4 MiB of kernel heap per process; ext2 disks with unknown features not
  mounted, directories past 12 blocks, shared blocks never freed.
- Gate policy (`gate_policy.md`): network calls to hosts off the allowlist ask; `poll_input` asks; tier-2 calls rate
  limited; a CONFIRM approves only the request printed last, `heliox pending` and `heliox deny`; a configuration that
  cannot be used gives tier 0; startup test hooks only under `/tmp/heliox-hooks`, written from the kernel shell;
  service notices name the service; autosave only at tier 3; tier 4 read as 3 unless unlocked; the audit ring's
  per-source quota; the panel flag limited to GOAL and CONFIG_UPDATED; typed keys bound to the window focused at
  approval; ancestors of the daemon's configuration cannot be deleted; occupancy and step interlocks.
- Kernel audit (`kernel_audit.md`): the virtio-gpu backing holds a whole frame; audit log trimmed at character
  boundaries and flushed in a shorter tail when the file is refused; `/disk/heliox/audit.log` and `/disk/accounts.txt`
  cannot be changed by ring 3; control characters in audit messages escaped; a privileged PackageInstall asks the
  operator at the kernel prompt; packages cannot take a compiled-in program's name; titles escaped in kernel serial
  lines; device-supplied counts and offsets bounded.
- Added by the integration: an AuditWrite record that would take the writer past its 4 MiB budget is refused (the
  Q6 quota still applies to the records it accepts).

## What remains

Each workstream's "What remains" stands: KPTI (design in `kernel_cpu.md`), the system-wide heap bound across
processes, the device and design items of `kernel_audit.md`, the residuals of `gate_policy.md`. Nothing of the three
sides was dropped in the merge.
