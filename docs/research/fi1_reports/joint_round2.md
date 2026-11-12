# fi1 joint round 2: attacking sender identity, the injected mark and file versions; K3's window and K2

Branch `improve/fi1-gate-kernel`, draft pull request 5, taken over at 47e97e0. Written 2026-11-12. The
adversary is the language model: it picks every tool call and argument, sees every result, and may spread
an attack over many turns and restarts.

## Summary

- No critical break found in the three round-1 mechanisms (no operator command applied from a non-operator,
  no tier-3/4 effect without an approval through sender identity or the injected mark).
- Four defects in the file-version mechanism and the filesystem under it, one of them a tier-4 effect
  through a tier-3 tool (J2-1). All fixed, with a kernel self-test, a harness check and host source checks.
- Item 2 done: version-guarded WriteFile, DeleteFile and Exec (syscalls 63 to 65), a re-check after the
  single read of the kernel image for Kexec, adopted by the daemon for every approved file action.
- Item 3 (K2) done: PointerTarget (syscall 66) and InjectMouse type 2; an approved `mouse_click` is bound to
  the window, owner and window-relative position under the pointer, shown to the operator, and refused or
  dropped by the kernel if that changed.

## Breaks, by severity

### J2-1 (high): a Tier-3 write deleted a directory tree, including the daemon's configuration

- **Where**: `src/fs/mod.rs` RamFS `create_file_bytes` (47e97e0 `:190`) did `children.insert(name, file)`
  without checking what was there. Over a directory it replaced the node and dropped its whole subtree.
  ext2 already refused ("not a regular file").
- **Sequence** (`auto_approve_tier=3`, or at tier 2 with one approval of what reads as a file write):
  `write_file {path:"/disk/heliox", content:"x"}`. On a boot without an ext2 disk at `/disk` (the harness
  images, and any machine without one), `/disk/heliox` is a RamFS directory holding `config.json`. The
  daemon refuses writes to `config.json` itself and the world model refuses `delete_file` of it, but neither
  checks its parent. The write replaces the directory; the configuration, memory and everything else in it
  are gone, and the daemon falls back to defaults at the next reload or restart (Q3 of round 3:
  `auto_approve_tier` 2 if the operator had chosen 0 or 1). The same works for `/etc`, `/tmp/<anything>`.
- **Why it is a break**: deleting a tree is the effect of `delete_file` (Tier 4, always asks below tier 4);
  it ran through a Tier-3 tool with no approval at tier 3.
- **Fix**: RamFS refuses a write whose target is a directory (`"is a directory"`), as ext2 does.
- **Tests**: self-test `file-guard` (`write_over_dir_refused`, `child_kept`); end to end in
  `verify_authority_gate_joint` (the operator approves `write_file /tmp/fi1j21`, a directory holding a file;
  the write fails and the file is still there); host `joint2.rs::j2_1_a_ramfs_write_never_replaces_a_directory`.

### J2-2 (medium): the version of `/disk/mmap_verify` never changed

- **Where**: `fs::file_version` (47e97e0 `src/fs/mod.rs:437`) called `fs::stat`, which answers
  `/disk/mmap_verify`, `/mmap_verify` and `mmap_verify` with a synthetic 64 MiB file and the fixed version
  `ON_DISK_VERSION_BIT`. WriteFile, DeleteFile and Exec act on the real file at that path (Exec reads it
  through `read_file_bytes`, which uses the VFS directly).
- **Sequence**: the agent writes a harmless ELF to `/disk/mmap_verify` and asks for `exec_process` of it;
  the operator checks it and approves. Any other process then rewrites the file (the threat K3 exists for).
  The version the daemon reads is unchanged, so the approval stands and the new binary runs.
- **Fix**: `file_version` asks the filesystem (`vfs::resolve` + `Filesystem::stat`), never the synthetic
  answer. The mmap test's `stat` is unchanged.
- **Tests**: self-test `file-guard` (`mmap_rewrite_changes`, `mmap_absent_after_remove`); host
  `j2_2_the_version_comes_from_the_filesystem_not_the_mmap_test_shortcut`.

### J2-3 (medium): a directory's version did not cover what a delete of it removes

- **Where**: RamFS gave a new version only to the parent of a changed node. `remove` of a RamFS directory
  removes its whole subtree, and `delete_file` of a directory is version-bound to the directory.
- **Sequence**: the operator approves `delete_file /tmp/work` (seen empty or harmless). Another process
  then writes `/tmp/work/sub/report.txt`. `/tmp/work`'s version is unchanged, the approval stands and the
  delete removes data that was not there when the operator approved.
- **Fix**: every RamFS create, write and remove gives a new version to every directory from the root down
  to the parent (`bump_directory_versions`). This over-revokes approvals bound to a directory (fail closed);
  files are unaffected. ext2 refuses to remove a non-empty directory, so it needs nothing.
- **Tests**: self-test `file-guard` (`deep_change_bumps_dir`); host `j2_3_a_directory_version_covers_its_subtree`.
- Also fixed here: a path ending in `//` (`/tmp/x//`) named a child called `""` that no lookup reaches,
  so the version the kernel reported (that of `/tmp/x`) and the node a write created were different nodes.
  `split_path` now refuses an empty name (`empty_name_refused`).

### J2-4 (low): test-program aliases bypassed the reserved-name rule

- **Where**: `sys_exec` (47e97e0 `src/syscall/process.rs:125`) ran init's ELF for any path *containing*
  `quota-test`, `huge-test`, `socket-owner-test`, `ipc-owner-test` or `ipc-forge-test`, naming the process
  after the last component. Round 1's `vfs_exec_name_allowed` applies only to the VFS branch.
- **Sequence**: an approved `exec_process {path:"/tmp/ipc-forge-test/heliox-daemon"}` (or
  `.../heliox-assistant-panel`, `.../init`) ran init's code as a process named `heliox-daemon`, with that
  program's manifest capabilities (intersected with the caller's) and a claim on its mailbox. If the real
  daemon restarted later, the impostor came first in the task list and received the `heliox` mailbox:
  the operator's CONFIRM, DENY and NEURAL_DISARM. It needs a Tier-4 approval and its messages carry no
  sender flag, so it is not an escalation; it is an availability break of the operator's disarm channel and
  a hole in round 1's rule.
- **Fix**: only `/bin/<name>` or the bare name is a test alias (`is_init_test_alias`); every shipped caller
  uses `/bin/<name>`.
- **Tests**: self-test `file-guard` (`alias_exact`, `alias_nested_refused`, `alias_reserved_refused`); host
  `j2_4_only_exact_test_program_paths_run_inits_elf_under_a_test_name`.

## Attacks tried (one line each)

**Operator-panel flag (K4)**
- What a flagged panel forwards: `GOAL:<text the operator typed>` and `CONFIG_UPDATED:` only; no CONFIRM,
  DENY or NEURAL_ARM is ever built (`heliox-assistant-panel/src/main.rs:85,293`). Holds.
- Agent text inside a panel message: the panel drops injected keys before any send (`:274`), accepts only
  printable ASCII, and its IPC inbox (`CHAT:` lines anyone may send) only changes the display. Holds.
- Agent-triggered flagged launch: launcher entry needs a physical release (injected releases cancel); the
  shell's `run` needs physical keys; the boot setup launch runs once per boot from whoever first calls
  HudUpdate (the agent's `hud_update` can only move it earlier), launches the embedded panel ELF, and that
  panel is driven only by physical keys. Holds.
- Files the panel reads: only whether `config.json` exists. The agent cannot write it (refused) or delete it
  (world model), but could replace its directory before J2-1's fix.
- Crash and relaunch, kill and race: no automatic relaunch; the daemon has no kill tool; task-manager kills
  need approved injected clicks. A panel the agent Exec's has flags 0 (refused) even if it owns the
  `assistant` mailbox. Holds.
- Pid reuse: pids are never reused; `forget_pid` on reap; flags are taken at send time. Holds.

**Kernel-shell flag**
- Shell inputs: `shell::commands::execute` is called only from the serial/PS/2 shell loop and the desktop
  terminal's Enter; no script, autostart, history replay or alias facility exists. Injected keys reach
  neither. Holds.
- Terminal content: the command is the text after the last prompt; command output written during a command
  (including other processes' console writes while `TERMINAL_REDIRECT` is on) lands before the prompt the
  terminal appends afterwards, and Backspace/Escape stop at the prompt. Holds.
- `heliox voice event <text>` and `heliox send voice_event` turn arbitrary text into a flagged GOAL, but only
  from typed keys. `heliox::submit_request` (which flags CONFIRM) is reachable only from shell commands. Holds.
- Serial console: input reaches the shell only as typed keys; whoever types there is the operator (as
  stated in the claim).

**The flags themselves**
- Old receive call: the daemon's only mailbox read is IpcReceiveFrom; `SYS_IPC_RECEIVE` in `tool_mapper.rs`
  is an unused constant; no tool receives. Only the task named `heliox-daemon` owns `heliox` (but see J2-4).
- The 16-byte record: validated (non-null, mapped user range) before a message is dequeued. Holds.
- Payload longer than the daemon's 1024-byte buffer: truncated, still one command; a truncated GOAL stays a
  GOAL. Holds.
- Flooding the `heliox` mailbox (16 per service) so an operator's DENY or disarm is dropped: the agent's
  `ipc_send` to its own mailbox is refused; another process needs an approved exec. Noted, not changed.
- Integer handling: flags are kernel-set bits 0 and 1; the daemon tests `flags & OPERATOR_SENDERS`. Holds.

**Injected mark (K1)**
- Every producer: PS/2 and USB HID keys and mice are unmarked; InjectKey marks through
  `INJECTING_AGENT_KEY` (syscalls run with interrupts off on one CPU, so a physical key cannot be read as
  injected or the reverse except a physical key arriving inside InjectKey, which is then treated as
  injected: fail closed); InjectMouse moves and clicks are marked; `inject_gesture_event` has no caller.
- Hops: compositor to app window keeps the mark (24-byte PollWindowInput record); PollInput's 16-byte record
  does not carry it, but its only reader is the daemon's `poll_input` tool. No clipboard paste into the
  terminal, no drag and drop, no window-to-window forwarding syscall.
- Derived events: only the daemon holds `cap:input:inject`, and any InjectKey is marked whoever calls it.
  Apps that act on injected input with their own authority (text-editor writes, task-manager kills, app-store
  installs) are reached only through approved Tier-4 injection: the K2 exclusion, now narrowed for clicks.
- Redirecting the operator's own next action: an approved `mouse_move` can place the pointer under the
  operator's next physical click, and an approved click can focus the terminal so the operator's next typing
  becomes a shell command. Both need a Tier-4 approval; listed under the claim's exclusions.
- `KEY_ALT_TAB` (0xF1) from InjectKey would switch windows; `keyboard_type` admits only 0x20 to 0x7E.

**File version (K3)**
- Spellings: the daemon asks the version of the exact `path` it passes to the action, and both resolve the
  same way; relative paths are refused by `authorize_path`; `.`/`..` refused. Holds, except `//` (J2-3 note).
- Rename: no rename syscall. Delete and recreate: a new boot version. Within a boot a version never repeats;
  across a reboot approvals are lost; an untouched ext2 inode reports `ON_DISK | generation`, disjoint from
  boot versions. Holds.
- Directories: shallow (J2-3). Write over a directory: J2-1. Mount aliasing: no mount syscall. Synthetic
  test path: J2-2. mmap: read-only, no write-back. Second descriptor: no positional write syscall; every
  mutation goes through `create_file_bytes`, `create_dir` or `remove`. Overflow: 61-bit counter.
- ext2 error paths: `remove` can fail after unlinking the entry and before the parent's version moves (I/O
  error only). Noted, not changed (ext2 is shared with the other agent's superblock work).
- Check-then-act: closed by item 2.

## Item 2: the check-then-act window of K3

Wire contract (additive; WriteFile, DeleteFile and Exec are unchanged for every other caller):

| Syscall | Arguments | Result |
|---|---|---|
| 63 WriteFileIfVersion | WriteFile's four, `args[4]` = expected version (0: nothing may exist there) | 0, or `VersionMismatch` (-7) with nothing written |
| 64 DeleteFileIfVersion | DeleteFile's two, `args[2]` = expected version | 0, or -7; gated by the kernel's 'y' prompt exactly like DeleteFile |
| 65 ExecIfVersion | Exec's two, `args[2]` = expected version (0 for programs compiled in) | pid, or -7 before any image is read; needs `process:spawn` |

The kernel checks and acts in one syscall (`fs::write_file_if_version`, `fs::remove_if_version`,
`sys_exec_checked`). Syscalls enter through an interrupt gate on the kernel's one CPU and kernel tasks are
preempted only at their safepoints, so no filesystem change can fall between the check and the action; the
fs helpers also wrap both in `without_interrupts`. Kexec takes bytes, not a path: the daemon reads the image
in one ReadFile call and then requires FileVersion to still equal the approved version before calling Kexec;
since versions never repeat within a boot, an equal version means no write happened in between.

Adoption: `confirmation::clear_for_execution_bound` returns what an approval was bound to (`Bound`);
`tool_mapper::execute` passes the version to `write_file`, `delete_file`, `exec_process` and
`trigger_kernel_upgrade`, which use the guarded calls whenever the call runs on an approval. Calls
auto-approved by tier use the old calls (no approval, nothing to bind). `create_directory` is version-bound
but needs no guard: CreateDir fails if anything exists. Who else must adopt: any approver that binds to a file.

Tests: host `joint2.rs` (`j2_k3_*`, 5 tests: the bound version for 4 tools x present/absent, nothing bound
without an approval, the version word, the daemon's and the kernel's wiring); self-test `file-guard` lines 1
and 2 (stale write, delete and exec refused with nothing changed; current version acts).

## Item 3: K2, the click target

Wire contract (additive):
- **PointerTarget = 66** (needs `hud:overlay`, like HitTest): `args[0]` = 24-byte record (window id u64, 0 for
  the desktop; owner pid u64, 0 for kernel-drawn windows; window-relative x and y u32), `args[1..3]` optional
  title buffer; returns the title length.
- **InjectMouse type 2**: `args[1]` button, `args[2]` window, `args[3]` owner, `args[4]` = x << 32 | y.
  Refused with -7 if the pointer is not over exactly that target now; otherwise the press and release carry
  the target (`InputEvent.click_target`) and `cursor::process_input` drops them if the pointer is over
  anything else when the desktop processes them (`GUARDED_CLICKS_DROPPED`). Types 0 and 1 are unchanged.
- Daemon: the gate takes a click-target source (`with_click_targets`, default fails closed; the daemon
  installs `orchestrator::kernel_click_target`). An approval of `mouse_click` is bound to the target when the
  request is made, the operator is shown `[clicks window N "<title, escaped>" of pid P at (x, y) in the
  window]`, a change withdraws it (`Clearance::TargetChanged`), and the approved click goes out as type 2.
- Not covered: what the owning app draws at that position (an app can change its own interface), and
  `keyboard_type`, whose target (the focused window) is not bound.

Tests: host `joint2.rs` (`k2_*`, 6 tests: the display, 5 kinds of change x approved before/after the change
= 10 cells, no target refuses, default fails closed, denial stays final, a hostile title cannot forge the
display, wiring); self-test `click-target` (delivered on target, refused when elsewhere, dropped if the
pointer moves before delivery); end to end in the joint harness (the notice names the target; the approved
click runs).

## Policy questions (behaviour unchanged, pinned)

**Q-J2a. The operator panel's flag is accepted for every operator command**
(`documents_j2_q_the_panel_flag_is_accepted_for_every_operator_command`). The panel only ever sends GOAL and
CONFIG_UPDATED, yet its flag also authorizes CONFIRM, DENY and NEURAL_ARM.
- (a) Accept only GOAL and CONFIG_UPDATED from `SENDER_ASSISTANT_PANEL`. Cost: an approve control added to the
  panel later needs this widened deliberately.
- (b) Keep it. Cost: unused authority on a GUI process that shares the desktop with injected input.

**Q-J2b. The boot-time setup launch marks a panel the operator did not ask for.** Its timing is set by the
first HudUpdate. It holds today because the panel takes only physical keys. Option: mark only launcher and
shell launches (cost: the first-run wizard's GOAL and CONFIG_UPDATED would be refused until the operator
reopens the panel).

**Q-J2c. Keyboard focus is not part of an approval.** `keyboard_type` goes to whatever window has focus when it
runs. Option: bind it like a click (a FocusTarget query and an InjectKey variant). Cost: one more syscall
pair.

**Q-J2d. `delete_file` of an ancestor of `config.json`** (`/disk/heliox`) is not refused the way `delete_file`
of the file is. It needs a Tier-4 approval. Option: refuse deletes of any ancestor of the daemon's
configuration.

## Images and harnesses

Every image is a CI artifact (`bootimage-ferrumos`), booted in QEMU (WHPX, 4096 MiB), one harness at a time
under `C:/Users/marcu/Videos/fi1-qemu.lock`, `FERRUMOS_BOOT_SECONDS=600`.

| Label | CI run | Commit | sha256 |
|---|---|---|---|
| before (round-1 head) | 43160633518 | 4bf9e59 (code of 47e97e0) | e3f39abf1968315f3efcf09df0bbf21668f5927f92819df36b6d1d6d96c6fcc7 |
| after | 43168389480 | fad4fbd (code of the final head; later commits change only this report) | ec5f18fa4f9e96041c6e093b913a0a6d50f5bfcacd38d7e02946140362738f7f |

The `after` image is left at `target/x86_64-unknown-none/debug/bootimage-ferrumos.bin`.

| Harness | before (e3f39abf) | after (ec5f18fa) |
|---|---|---|
| verify_authority_gate_joint (37 checks, 13 new) | 27/37: the 7 new self-test checks fail (self-tests absent); **J2-1 end to end: the approved write of `/tmp/fi1j21` returned 0 and the directory and its file were gone**; the click notice names no target | 37/37 |
| verify_authority_gate_self_approval | 11/11 (round 1) | 11/11 |
| verify_authority_gate_input_injection | 7/7 (round 1) | 7/7 |
| verify_kernel_selftests | 18/18 (round 1) | 18/18 |
| verify_process_reap_cr3 | 9/9 (round 1) | 9/9 |
| verify_pid_reuse | 6/6 (round 1) | 6/6 |
| verify_ring3 | 7/7 (round 1) | 7/7 |
| verify_ipc_isolation | 6/6 (round 1) | 6/6 |
| verify_assistant_panel | 5/5 (round 1) | 5/5 |
| verify_app_window | 13/13 (round 1) | 13/13 |

Every harness passed on its first run on the `after` image; none was rerun. The `before` column of the
joint harness is this round's harness run against the round-1 image; the other `before` numbers are round
1's runs of the same image.

Host tests:

| Suite | before (47e97e0) | after |
|---|---|---|
| userland/heliox-gate-tests | 54 | 70 (`joint2.rs`: 16 new; older tests install a stable click-target source, since the gate now fails closed without one, and `gate_table.rs` gains a match arm for `TargetChanged`) |
| userland/physical-runtime | 175 | 175 |
| userland/neural-protocol | 19 | 19 |
| scripts/authority_matcher_adversarial.py | 19/19 | 19/19 |
| daemon `cargo check --target x86_64-pc-windows-gnu` | builds | builds |

The new host tests do not compile on 47e97e0 (`clear_for_execution_bound`, `Bound`, `ClickTarget` and the
kernel's guarded syscalls do not exist there). The kernel was type-checked on the host before the push
(scratch copy, as in round 1). CI runs used: 1 of 6 for code (43168389480), plus the push of this report.

## Claim as it stands

> With `auto_approve_tier` at most 3, a tool call proposed by the language model runs only if one of three
> things holds. (i) Its tier is at or below the configured auto-approve tier. (ii) An operator approved that
> tool with exactly those arguments: the approval is bound to a complete, injective serialization of every
> argument, is used once, expires, cannot override a denial, and is withdrawn when the daemon changes the
> file the action is about. For an action on a file (write, create, delete, exec, and the kernel image of
> `trigger_kernel_upgrade`) it is bound to the kernel's version of that file when the request was made, and
> the kernel performs the approved write, delete or exec only if the file still has that version, checked in
> the same step as the action (for the kernel image, re-checked after the image is read); a directory's
> version covers everything beneath it, and a version the kernel cannot establish refuses the call. For a
> pointer click it is bound to the window, its owner and the position under the pointer, which the operator
> is shown, and the kernel delivers the click only onto that target. (iii) For physical commands, the
> deterministic interlocks hold at issue and again at delivery. Approvals and denials are applied only when
> the kernel reports that they came from the kernel shell or from an assistant panel the kernel launched for
> the operator. When a request is created the operator is shown every byte of its arguments, escaped to
> printable ASCII, and the file or click target it acts on. The model has no tool that sends to the daemon's
> control mailbox, writes its configuration, submits keystrokes, or blocks the daemon for more than 10 s. A
> write never replaces a directory. Input injection is Tier 4 and cannot press Enter or control keys;
> injected keys and clicks never reach the kernel shell, the desktop terminal, the privacy lock, the
> launcher, power menu, dock, window close buttons or the operator's panel. Text the model writes to the
> audit trail is one escaped line marked as the agent's. The bridge pairing token and the provider API key
> are not shown to the model. The world model can only add refusals.
>
> Exclusions. The gate does not guarantee: what the owning application does with an approved click at the
> approved position, or which window receives approved typed text (Q-J2c); that a physical click or keystroke
> after an approved pointer move or focus change goes where the operator meant; that the operator can still
> see a request's text when approving it by id (Q2); that data the model reads at Tier 1 stays on the machine
> at the default tier (Q1); or that the kernel keeps every audit entry (Q6). Physical replay protection is
> per runtime instance, and confirmation ids are not single-use (R-P1, R-P3). The sender check trusts the
> kernel shell's input: whoever types on the physical keyboard or the serial console is the operator.

## What remains

- Q-J2a to Q-J2d above; Q1, Q2, Q6 and the physical items as in round 3.
- The `heliox` mailbox's 16-message quota can be filled by a process the operator approved, dropping a later
  DENY or NEURAL_DISARM (kernel IPC, outside this round's fixes).
- ext2 `remove` error path (unlinked entry, parent version unchanged) - in ext2, shared with the other agent.
