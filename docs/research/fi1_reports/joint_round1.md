# fi1 joint kernel and userland round 1: sender identity, injected input, file versions

Branch `improve/fi1-gate-kernel`, draft pull request 5. It contains pull requests 2 (`improve/fi1-userland`)
and 3 (`improve/fi1-kernel`, including its later commit 6009cfc); the merge of 2 into 3 had no conflicts
(they touch different files). This round's own commits start after merge commit 39c4ced. Written 2026-11-12.

## Images

Every image is a CI artifact (`bootimage-ferrumos`), booted in QEMU 10.1 (WHPX, 4096 MiB) one harness at a
time under `C:/Users/marcu/Videos/fi1-qemu.lock`, with `FERRUMOS_BOOT_SECONDS=600`.

| Label | CI run | Commit | sha256 |
|---|---|---|---|
| pr3 | 43151884931 | 6009cfc (head of pull request 3) | 4b91314540ad94eaa22595d9401e133cb928fd891eaa07131e2d89b63a7f15a8 |
| joint1 | 43159528318 | ec85a76 (first push of this branch) | eea3f9c45e8baba158f57d4b535cfef8b24783093a1af38436176277a0f700ba |
| joint2 | 43160633518 | 4bf9e59 (this round's code; the final head differs only in this report and the negative-control pair) | e3f39abf1968315f3efcf09df0bbf21668f5927f92819df36b6d1d6d96c6fcc7 |
| negctl | 43161668784 | 7f351b2 (joint2 with the daemon's sender check, the version binding and the terminal guard held back; reverted by 9a3807c) | 84293b4aa5723c9730725d87b74d6a08bb7f87e5f37c41ca3813a3fbfa22cf62 |

The kernel source of 9a3807c is identical to 4bf9e59 (`git diff 4bf9e59 9a3807c -- src userland` is empty).

## K4, sender identity: done

**Kernel.**
- `Message.sender_flags` (`src/ipc/mod.rs:54`): `SENDER_KERNEL_SHELL` (bit 0) and `SENDER_ASSISTANT_PANEL`
  (bit 1), set only by kernel code. IpcSend attaches `process_sender_flags(caller_pid)`
  (`src/syscall/mod.rs:391`, `src/ipc/mod.rs:133`), so a process cannot choose its own flags.
- New syscall **IpcReceiveFrom = 61** (`src/syscall/mod.rs:115`, handler `sys_ipc_receive` at `:784`):
  IpcReceive's four arguments plus `args[4]` (r8) = pointer to a 16-byte record filled with the sender's pid
  (u64 LE) and flags (u64 LE). The record pointer is validated before a message is dequeued. IpcReceive (2)
  keeps its ABI; no other caller changes.
- The kernel shell marks the messages it sends for the operator: `heliox confirm` (`src/heliox/mod.rs:887`),
  `heliox voice event`, `heliox neural`, and the new `heliox deny <id>` (`src/shell/commands.rs:1506`), which
  gives the operator a DENY channel (there was none).
- **How the kernel knows a sender is the panel.** A pid gets `SENDER_ASSISTANT_PANEL` only when a kernel
  launch path that acts on operator input marks it (`mark_operator_panel`, `src/ipc/mod.rs:119`): the desktop
  launcher entry (reached only by a physical pointer, see K1), the one-time boot setup launch when no
  configuration exists (`launch_assistant_panel_if_unconfigured`), and the shell's `run
  heliox-assistant-panel` (`userspace::launch_operator_panel`, `src/userspace/mod.rs:268`). Exec and AppLaunch
  from any process never mark, so a panel the agent starts (Exec of `/bin/heliox-assistant-panel`, which the
  daemon can do with `cap:process:spawn`) has flags 0. The mark is keyed by pid, pids are never reused (pull
  request 1), and `drop_by_pid` forgets it. Exec of a VFS file whose name is a compiled-in program, an
  installed package or a mailbox alias is refused (`vfs_exec_name_allowed`, `src/syscall/process.rs:93`,
  applied at `:180`; list in `ipc::is_reserved_program_name`, `src/ipc/mod.rs:149`), which closes the
  "file named like the panel" route (it used to receive the panel's capabilities and its `assistant`
  mailbox). The third route the kernel report listed, injected clicks on the real panel, is closed under K1:
  the panel ignores injected input.

**Daemon.** `ipc_poll` (`userland/heliox-daemon/src/cognitive/orchestrator.rs:1570`) receives only through
IpcReceiveFrom and applies `authority::control_command_allowed` (`authority.rs:663`) before any command
(`orchestrator.rs:1608`): CONFIRM, DENY, GOAL, NEURAL_ARM and CONFIG_UPDATED need a sender flag of the kernel
shell or the operator panel; NEURAL_DISARM (only removes authority) is accepted from anyone; a refusal prints
`control message from pid N (sender flags F) refused: not the operator`. Fail closed: a syscall error drops
the message unapplied, and a missing sender counts as not the operator.

**Wire contract.** Additive syscall 61; who must adopt: any receiver that needs to authenticate a sender
(today only the daemon). The panel does not send CONFIRM today; if it gains an approve control it is already
an accepted channel.

**Tests.** Host: `tests/joint.rs` `k4_sender_table_is_exhaustive_over_commands_and_senders` (7 commands x 8
senders = 56 cells, including the daemon itself, an agent-started panel, pid 0 without the shell flag and
unknown flag bits), `k4_a_forged_confirm_from_another_process_is_refused_end_to_end`,
`k4_the_daemon_reads_its_mailbox_only_with_sender_identity` (source check: syscall 61, check before approve).
QEMU: `scripts/verify_authority_gate_joint.mjs`. The agent asks to run `/bin/ipc-forge-test` (an Exec of init's
ELF under that name, holding `cap:ipc:send`; `userland/init/src/main.rs:199`), the operator approves THAT
request, and the process posts `CONFIRM:<id of a pending write>` to `heliox`.

## K1, injected input: done

- `InputEvent.injected` (`src/input/mod.rs:63`), set from `INJECTING_AGENT_KEY` for InjectKey (`:189`) and true
  for InjectMouse moves and clicks. PollInput's 16-byte record is unchanged.
- The desktop keeps injected events away from every control that acts with the operator's authority
  (`src/gui/compositor.rs`): the terminal window, which is a kernel shell, ignores injected keys entirely
  (`:1229`), so the agent can neither submit a command nor leave text on the prompt for the operator's next
  Enter; the privacy lock (`:1178`); the launcher, power menu and dock (`:703`, and `:992` so a physical press
  cannot be completed by an injected release); window close buttons, which kill the process (`:770`). An
  injected press does not move physical keyboard ownership (`src/gui/cursor.rs`).
- Ordinary app windows still receive injected keys and clicks. PollWindowInput gains an optional 24-byte
  record (`src/syscall/gui_window.rs:102`): a caller passing `out_len >= 24` gets a sixth u32, bit 0 =
  injected. 20-byte callers see the old record. `libferrumgui::poll_window_input_marked`
  (`userland/libferrumgui/src/lib.rs:500`) reads it and fails closed (no flags word = injected); the
  assistant panel ignores injected events (`userland/heliox-assistant-panel/src/main.rs:274`) because it is
  an operator channel. Who must adopt: an app that acts for the operator.

Test: kernel self-test `test-syscall injected-terminal` (drives the real path: InjectKey syscall, input queue,
`cursor::process_input`, compositor), checked by the joint harness: terminal unchanged by an injected key and
changed by a physical one, an app window receives the injected key marked, an injected launcher click on the
assistant-panel entry launches nothing. The self-test restores window order, focus and the desktop's one-time
stale-key discard; the first build (joint1) did not, and the operator's queued `ring3 init` keys reached the
terminal window and started init a second time (found by the harness, fixed in 4bf9e59).

## K3, file version: done (with one window noted below)

- RamFS nodes carry `version` (`src/fs/mod.rs`, `FsNode::version` at `:96`), from a global counter
  `next_file_version` (`:53`): every create or write (even with the same content) gives the file a new
  version, and every create or remove gives its directory one. ext2 writes the low 32 bits into the inode's
  `generation` and keeps the full version in a per-boot map (`bump_version`, `version_of`,
  `src/fs/ext2.rs:308`, `:314`); an inode untouched this boot reports `ON_DISK_VERSION_BIT | generation`.
  Versions given this boot have bit 62 set and on-disk ones bit 61, so a change can never bring back the
  version seen before it, a version is never 0, and it stays below 2^63 (never read as an error status).
- `fs::file_version` (`src/fs/mod.rs:437`) and syscall **FileVersion = 62** (`src/syscall/fs.rs:302`, needs
  read access): version, 0 for nothing there, error when the kernel cannot say (`.`/`..`, a file used as a
  directory, no mount, I/O error).
- Daemon: `ConfirmationGate` takes a version source (`with_file_versions`), default `versions_unavailable`
  (fails closed); both places the daemon builds its gate install `orchestrator::kernel_file_version`
  (`orchestrator.rs:96`). `decide` (`confirmation.rs:370`) asks for the version of `version_subject`
  (`authority.rs:681`: the `path` argument exactly as the kernel receives it, or the fixed kernel image of
  `trigger_kernel_upgrade`) whenever a confirmation is involved, binds a new request to it, and withdraws a
  pending or approved request whose file has another version (`withdraw_if_version_changed`, `:143`;
  `Clearance::FileChanged`). An error refuses the call before any request exists. A denial stays final.
  Calls auto-approved by tier need no version.
- Wire contract: additive syscall 62 and `FsStat.version` (kernel-internal). Who must adopt: any approver that
  binds to a file.

Tests: host `tests/joint.rs` `k3_version_table_over_tools_changes_and_approval_state` (5 file tools x 5
changes x approved before/after the change = 50 cells; each withdrawn request is followed by a new id), plus
pending withdrawal, denial stays final, unknown version refuses with no request, default gate fails closed,
auto-approved calls need no version, and the version path. QEMU: `test-syscall file-version` and the joint
harness's K3 section (the operator approves `delete_file /tmp/fi1k3.txt`, the kernel shell then rewrites the
file, the approved delete must not run).

**Not closed:** the check and the action are two syscalls. A process that changes the file between the
daemon's FileVersion call and its Write/Delete/Exec/Kexec is not caught. Closing it needs the kernel to take
an expected version on the action itself (for example an extra argument to DeleteFile, WriteFile and Exec);
their userland wrappers leave the extra registers undefined, so that is a new set of calls.

## K2, click target: not done

Not started this round. The kernel report's design stands (HitTest with a pointer sentinel returning the
window and its owner). K1's injected mark is the other half it needs.

## Harnesses

| Harness | pr3 (6009cfc) | negctl (7f351b2) | joint2 (4bf9e59) |
|---|---|---|---|
| verify_authority_gate_joint (24 checks) | 7/20: the eight self-test checks fail (self-tests absent); the K4 probe cannot run (no `ipc-forge-test`, the section stops); **the approved delete runs after another process changed the file** | 17/24: **injected key reached the terminal** (`terminal_kept=false`); **the forged CONFIRM from ipc-forge-test approved the write** (`Write ... result=0`, no refusal printed); **the approved delete ran after the change** | 24/24 |
| verify_authority_gate_self_approval | not run | not run | 11/11 |
| verify_authority_gate_input_injection | not run | not run | 7/7 |
| verify_kernel_selftests | not run | not run | 18/18 |
| verify_process_reap_cr3 | not run | not run | 9/9 |
| verify_pid_reuse | not run | not run | 6/6 |
| verify_ring3 | not run | not run | 7/7 |
| verify_ipc_isolation | not run | not run | 6/6 |
| verify_assistant_panel | not run | not run | 5/5 |
| verify_app_window | not run | not run | 13/13 |

pr3 runs the harness version before 0576233 made its sections independent of each other, hence 20 checks.
joint1 (eea3f9c4) scored 9/10 with every self-test passing but pairing denied, because of the init restart
described under K1; with that self-test skipped it scored 21/24 with every daemon check passing. Every
harness passed on its first run on joint2; none was rerun.

## Host tests

| Suite | before (pull request 2 head) | after |
|---|---|---|
| userland/heliox-gate-tests | 44 | 54 (`joint.rs`: 10; older tests now install a stable version source, since the gate fails closed without one; one match arm added for `FileChanged`) |
| userland/physical-runtime | 175 | 175 |
| userland/neural-protocol | 19 | 19 |
| scripts/authority_matcher_adversarial.py | 19/19 | 19/19 |
| daemon `cargo check --target x86_64-pc-windows-gnu` | builds | builds |

The kernel was also type-checked on the host before each push (stable GNU toolchain with
`RUSTC_BOOTSTRAP=1`, target `x86_64-unknown-none`, empty placeholder ELFs, and the registry's `x86_64` crate
patched with the two `Step` methods newer `core` requires; scratch copy only, nothing in the repository).

## Claim as it stands

> With `auto_approve_tier` at most 3, a tool call proposed by the language model runs only if one of three
> things holds. (i) Its tier is at or below the configured auto-approve tier. (ii) An operator approved that
> tool with exactly those arguments: the approval is bound to a complete, injective serialization of every
> argument, is used once, expires, cannot override a denial, is withdrawn when the daemon changes the file
> the action is about, and, for an action on a file (write, create, delete, exec, and the kernel image of
> `trigger_kernel_upgrade`), is bound to the kernel's version of that file when the request was made, so a
> change by any process before the action is checked withdraws it, and a version the kernel cannot establish
> refuses the call. (iii) For physical commands, the deterministic interlocks hold at issue and again at
> delivery. Approvals and denials are applied only when the kernel reports that they came from the kernel
> shell or from an assistant panel the kernel launched for the operator; a message from the daemon itself or
> any other process, including a panel the agent started, is refused. When a request is created the operator
> is shown every byte of its arguments, escaped to printable ASCII, and the file it acts on. The model has no
> tool that sends to the daemon's control mailbox, writes its configuration, submits keystrokes, or blocks
> the daemon for more than 10 s. Input injection is Tier 4 and cannot press Enter or control keys; injected
> keys and clicks never reach the kernel shell, the desktop terminal, the privacy lock, the launcher, power
> menu, dock, window close buttons or the operator's panel. Text the model writes to the audit trail is one
> escaped line marked as the agent's. The bridge pairing token and the provider API key are not shown to the
> model. The world model can only add refusals.
>
> Exclusions. The gate does not guarantee: that an approved pointer click does what the operator expected,
> since the click target is not part of the approval (K2); that a file is unchanged between the daemon's
> version check and its action, a window of two syscalls (K3 remainder); that the operator can still see a
> request's text when approving it by id (Q2); that data the model reads at Tier 1 stays on the machine at
> the default tier (Q1); or that the kernel keeps every audit entry (Q6). Physical replay protection is per
> runtime instance, and confirmation ids are not single-use (R-P1, R-P3). The sender check trusts the kernel
> shell's input: whoever types on the physical keyboard or the serial console is the operator.

Removed from the exclusions: K4 (confirmations from another process) and K1 (text the agent typed onto a
shell prompt). Narrowed: K3, from "any change by another process" to the two-syscall window.

## What remains

- K2 (click target), as designed in the kernel report.
- K3's check-then-act window: an expected-version argument on DeleteFile, WriteFile, Exec and Kexec.
- The boot-time setup launch marks its panel as the operator's; it happens once per boot and only without a
  configuration, but the daemon's HUD pump decides when. A stricter rule would mark only launcher and shell
  launches.
- Q1, Q2, Q6 and the physical items as in round 3.
