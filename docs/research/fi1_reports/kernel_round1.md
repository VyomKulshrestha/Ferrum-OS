# fi1 workstream C (kernel), round 1

Branch `improve/fi1-kernel`, draft pull request "fi1 kernel: run-time tests and audit fixes". Plan:
`docs/research/ferrumos_improvement_fi1_plan.md`. The kernel builds only in CI; every image below is a CI
artifact (`bootimage-ferrumos`) booted here in QEMU 10.1 with WHPX, 4096 MiB, one harness at a time under
the shared lock.

| Image | CI run | Source |
|---|---|---|
| main | 43111829305 | `dba7016` (main at the start of fi1) |
| pre-PR1 | 42951620869 | `b8b4fe4` (main just before pull request 1 was merged) |
| negctl | 43118516970 | `04daaf2`: this branch's harnesses and self-tests with the fixes they check held back |
| final | 43135433840 | `d654407`: this branch with every fix (later commits change only this report) |

## Host conditions and harness budgets

The host was shared with other agents: CPU load 10 to 100 % and 0.1 to 1.9 GB of free physical memory for a
4 GiB guest. With the HDA device attached, main's image needed 148 to 214 s to reach the prompt (most of it
in two HDA polling loops, see Performance), so the harnesses that wait 35 to 90 s for the first prompt
failed before their first assertion. The nine baseline harnesses therefore gained an opt-in
`FERRUMOS_BOOT_SECONDS` for the first prompt only (default unchanged). The table uses
`FERRUMOS_BOOT_SECONDS=600` for both images; post-boot waits are unchanged. Commands:
`FERRUMOS_BOOT_SECONDS=600 node scripts/<harness>.mjs`, one at a time, image copied to
`target/x86_64-unknown-none/debug/bootimage-ferrumos.bin`. A failing run was rerun once.

## Results

### The nine baseline harnesses

| Harness | expected | main | final |
|---|---|---|---|
| verify_ring3 | 7 | 7/7 (234 s) | 7/7 (64 s) |
| verify_mmap | 7 | 1/2, 1/2, 1/2, then 7/7 (202 s) | 7/7 (68 s) |
| verify_audio_nonblocking | 7 | 7/7 (211 s) | 7/7 (32 s) |
| verify_current_pid | 6 | 6/6 (39 s) | 6/6 (28 s) |
| verify_app_window | 13 | 1/2, 1/2, then 13/13 (65 s) | 13/13 (37 s) |
| verify_core_apps | 24 | 1/2, then 24/24 (116 s) | 24/24 (62 s) |
| verify_scheduler_stubs | 7 | 7/7 (35 s) | 7/7 (18 s) |
| verify_user_pointer_isolation | 4 | 4/4 (45 s) | 4/4 (22 s) |
| verify_ipc_isolation | 6 | 6/6 (41 s) | 6/6 (25 s) |
| total | 81 | 81 after reruns | 81, all on the first attempt |

Times are harness wall times. main's mmap failures are timeouts waiting for heliox-daemon after `ring3 init`
(init's Exec of the daemon maps its 16,954-frame image through the quadratic frame allocator, 24 to 36 s on
main in the spawn benchmark below, and the harness allows 30 s from the command); its app-window and core-apps failures are timeouts after
boot under peak load. None is a wrong result. In the default-budget runs at the start (ring3, mmap and
audio, two attempts each; the first of them overlapped with this workstream's own probe boots) main never
reached its first prompt within 90 s. The final image boots in 49.6 to 55.5 s with HDA attached, inside
the 90 s budget of those three harnesses.

### New harnesses

| Harness (checks) | main | negctl (fixes held back) | final |
|---|---|---|---|
| verify_kernel_selftests | 3/16: self-test command absent; a guest session ran `syscall 101 5 4` and got `Ok value=1` | 3/7: kernel panic at `elf-bounds` ("virtual address must be sign extended"); with `FERRUMOS_SKIP_SELFTESTS=elf-bounds,heap-bounds` 6/12: kexec `oversize_rejected=false`, window-cap `created=6`, dead-recorder `released=false`, exec-path all three bypasses allowed, guest `syscall` allowed | 18/18 |
| verify_process_reap_cr3 (9) | 3/4: the shell hangs at the second `run calculator` after `kill 4` (twice) | 9/9 (negctl keeps the CR3 fix) | 9/9 |
| verify_pid_reuse (6) | 2/3: hangs at the second launch (CR3 defect) | 4/6: calculator pids 100 and 101 reuse the kernel stub's and the init model's ids; `syscall 101 5 4` = `Ok value=1`, so the calculator held init's cap:system:all (twice) | 6/6 (pid 99 is followed by 103) |

The main and negctl runs of `verify_kernel_selftests` used the 16-check version (before K1 added two checks);
negctl's heap-bounds self-test also stopped the kernel when it was not skipped (64 MiB infallible
allocation). The two K1 checks have no negative-control run: K1 was written after the negctl build.
The first two final-image runs of the 18-check version scored 17/18: the harness looked for the typed
command line in output that starts after it (a harness bug; the serial log shows `echo probe` followed by
`probe` with no injected key). After the fix to the check it scored 18/18.


## Defects fixed, by severity

Each entry: where, why it is wrong, the fix, and the harness that fails without the fix and passes with it.

### High

**1. Kernel tasks ran on a dead process's page tables; reaping freed the live CR3.**
`src/scheduler/mod.rs:1516` (`resume_task`), backstop in `src/process/mod.rs` `drop_by_pid` and
`scheduler::leave_address_space`. Kernel tasks (shell, desktop) are registered with `cr3 = 0`, and
`resume_task` loaded CR3 only when it was non-zero, so after any app ran the shell kept the app's L4 loaded.
`kill <pid>` (and the window close button, and ProcessKill) reaps the app and returns its page-table frames
while the CPU still uses them; the frame allocator is LIFO and `AddressSpace::drop` frees the L4 last, so the
next `AddressSpace::new` receives that L4, zeroes it, and the kernel stops. On main's image the shell hangs at
the second `run calculator` after one `kill`. Fix: kernel tasks run on `BOOT_CR3`; `drop_by_pid` switches to
`BOOT_CR3` first if the CPU is on the dying L4. Harness `verify_process_reap_cr3.mjs` (three launch/kill
rounds).

**2. The shell's `syscall <pid> <num> [arg0]` ran a syscall with any pid's authority from any session.**
`src/shell/commands.rs:1038`. `cmd_syscall` called `dispatch_for_process` with no check, so after
`session guest` (or `login` as a user account) `syscall 101 58 <pid>` acts as init with `cap:system:all`.
Fix: the command needs `cap:system:all`. Harness `verify_kernel_selftests.mjs` (guest denied, root allowed).

**3. A malformed ELF halted the kernel.** `src/process/mod.rs:248` (`Process::load_elf`). `VirtAddr::new`
panics on a non-canonical address and ran before the user-region check, so Exec of a file whose PT_LOAD has
`p_vaddr = 0x0000_8000_0000_0000` aborted the kernel (needs `process:spawn` and a file the caller can
write). Fix: check the range first. Harness: `test-syscall elf-bounds` in `verify_kernel_selftests.mjs`.

**4. Caller-sized kernel buffers aborted the kernel when the heap could not hold them.**
`src/fs/mod.rs:272` (`try_zeroed_vec`), used by `read_file_bytes` (`:300`), ReadFile
(`src/syscall/fs.rs:150`), GetRandom (`src/syscall/mod.rs:678`), socket Recv (`src/syscall/socket.rs:111`),
`read_user_bytes` (`src/syscall/fs.rs:42`) and RamFS writes (`src/fs/mod.rs:169`). All used infallible
allocation on a 12 MiB heap; Exec of the 64 MiB `/disk/mmap_verify` (ext2 builds) allocates 64 MiB and
aborts. Fix: fallible allocation, returning InvalidArgument. Harness: `test-syscall heap-bounds`.

### Medium

**5. Exec skipped the package signature gate for `/disk//pkgs-available/<name>/bin`.**
`src/syscall/process.rs:79` (`exec_path_allowed`), applied at `:160`. The gate matches only the exact
spelling; the filesystems drop empty components, so a doubled slash loaded an uninstalled or altered package
binary without its signature and digest check (with no capabilities, since none are derived for it). Fix:
VFS Exec paths must be plain absolute paths outside the package repository. Harness: `test-syscall exec-path`.

**6. The ELF loader mapped one page past an unaligned segment.** `src/process/mod.rs:413`
(`AddressSpace::map_user_range`, span from `user_span` at `:65`). The span was measured from `vaddr` instead
of its page base, so a segment that starts mid-page mapped an extra page; for a segment ending at the top of
the user region that page is at `0x100_0000_0000`, in P4[2], whose tables are shared with the kernel, and the
entry stayed there after exit. Fix: page-base span, and refuse a span past `USER_REGION_END`. Harness:
`test-syscall elf-bounds` (one page for 0xFFF bytes at an offset of 1). The negative control could not show
this check failing: the same self-test first loads the non-canonical segment, which panics a kernel without
defect 3's fix. From the code, the old span maps two pages for that segment.

**7. Keyboard and mouse interrupts could spin forever on the scheduler lock.** `src/scheduler/mod.rs:1022`
(`total_ticks`), `:1630` (`wake_confirmation_waiters`). The PS/2 handlers timestamp events through
`total_ticks()` and look for confirmation waiters, both of which took `SCHEDULER.lock()`; the desktop loop and
`ps` hold that lock with interrupts enabled, and on one CPU the handler never gets it. Fix: the tick count is
an atomic mirror written by `tick()`; the waiter wake uses `try_lock` and otherwise parks the key (with its
press tick, so it cannot answer a prompt that appeared after it) for the next tick. Not reachable by a
deterministic harness (it needs an interrupt to land inside a short critical section); argued from the code.

**8. Windows outlived their process.** `src/process/mod.rs:934`. `close_for_pid` ran only on ProcessKill,
the close button and shell `kill`; an app that exited or faulted left up to four canvases (about 1.7 MB each)
on the kernel heap. Fix: `drop_by_pid` closes them. Not covered by a harness: the shell's `kill` closes windows itself, and the
exit path needs a ring-3 program that exits with a window open (userland, workstream D).

**9. Dead processes leaked when a wait reaped someone else.** `src/scheduler/mod.rs:1065`
(`reap_dead_except`). WaitPid and the deferred reap freed one process and then removed every dead task from
the scheduler, and `reap_dead` finds processes only through those entries; the other dead processes' frames,
kernel stacks and sockets were never freed. Fix: free every dead process except the running one before
removing the entries. Not covered by a harness here (needs a ring-3 parent that waits while another child
is dead).

**10. ext2 directory entries.** `src/fs/ext2.rs:896` (name length), `:1038` (bounds), `:1045` (deleted
entries). A name over 255 bytes was truncated into `name_len` or indexed past the block; `remove_dir_entry`
matched deleted entries by their stale name, so deleting a re-created file could free the live file's inode
and blocks. Fix: reject names outside 1 to 255 bytes, bound the entry walk, skip `inode == 0`. Not covered:
the harness images boot without an ext2 disk.

### Low

**11. kexec read up to 8 MiB into the heap before checking the 4 KiB bound.** `src/syscall/kexec.rs:56`.
Fix: read at most one page. The bound itself (`validate_image`, `:26`) is pull request 1's fix 6.

## Run-time tests for pull request 1's untested fixes

| PR 1 fix | Harness | negctl (fix held back) | final |
|---|---|---|---|
| 1 pid reuse of the init model id | `verify_pid_reuse.mjs` | fails: pids 100 and 101 reused, pid 101 holds cap:system:all | passes |
| 4 window cap | `verify_kernel_selftests.mjs` (window-cap) | fails: 6 of 6 windows created | passes: 4 created, 2 refused |
| 5 dead recorder | `verify_kernel_selftests.mjs` (dead-recorder) | fails: session kept | passes: released |
| 6 kexec bound | `verify_kernel_selftests.mjs` (kexec-bound) | fails: 4097-byte image accepted | passes: rejected, 4096 accepted |

The pre-PR1 image (run 42951620869) exists, but it cannot run these harnesses: the self-test command did
not exist then, and the pid harness stops at its second launch on any image without the CR3 fix (defect 1).
The negative-control build is the image without the fixes: commit `04daaf2` reverts exactly these four fixes
(and holds back this round's) on top of the same harness code.

## Performance

Measured with `kernel_round1_tools/bootbench.sh` (set `FI1_IMAGES`, `FI1_WORKTREE`, `FI1_LOCK`, `FI1_MEMFREE`) (QEMU with the HDA device, as in verify_ring3/mmap/audio; wall time
from QEMU start to the first `FerrumOS:~$` on serial), main and final alternating, five boots each:

| Image | boot to prompt, s (five runs) | median | range |
|---|---|---|---|
| main | 161.5, 164.3, 168.7, 148.2, 169.4 | 164.3 | 21.2 |
| final | 49.6, 52.2, 55.5, 52.9, 55.1 | 52.9 | 5.8 |

The median moved by 111 s, more than five times the baseline's spread. Serial timestamps (probe timeline,
`probe.mjs` writes one per boot) attribute it:

1. **HDA reset polls, 109 s of main's boot in the timed run** (`src/devices/hda.rs:503` and `:545`). After setting the
   reset bit of CORBRP, init polled up to 5,000,000 times for it to read back as 1; QEMU's intel-hda never
   reads it back, and every poll is an MMIO exit under WHPX. It then polled RIRBWP bit 15 the same way, but
   that bit is write-only and always reads 0 (HDA spec 4.4.2), so that loop could only time out. On main the
   step from `HDA: GCAP` to `HDA: root node` took 109.1 s; on the final image it takes under 0.1 s. Fix: a
   10,000-poll bound for the CORBRP latch, no wait on RIRBWP. Real controllers latch the bit in
   microseconds, so the bound does not change their behaviour.
2. **Quadratic frame allocator** (`src/memory/mod.rs:275`, `:325`). Every fresh frame re-walked the memory map
   from the start (`usable_frames().nth(next)`), and every freed frame was checked against the whole free
   list (`Vec::contains`). Mapping heliox-daemon's 16,954 frames at boot took 8.2 s on main (from
   `Ring-3 init loaded` to `Ring-3 heliox-daemon loaded`) and 0.6 s on the final image. Fix: a region cursor
   and a `BTreeSet` of free-frame addresses beside the LIFO list; allocation order and the reuse invariant
   that `test-syscall frame-recycle` checks are unchanged.

What remains in a final-image boot of about 53 s: about 31 s before the kernel prints anything (most likely the BIOS
bootloader reading the 9.8 MB debug image), and about 16 s in one HDA verb: setting the ADC's stream format
(NID 4, verb 0x20011) blocks the vCPU for 3.7e10 TSC cycles with zero polls, so the time is spent inside
QEMU when the guest writes CORBWP (QEMU opens the host capture device for the new format). The kernel does
not cause either; a smaller boot image (release profile or stripped debug info, outside `src/`) and starting
QEMU with `-audiodev none` in the harnesses would address them.

Exec of heliox-daemon from ring 3 (`kernel_round1_tools/spawnbench.sh`: boot, `write /tmp/mmap_test 1`,
`ring3 init`; wall time from init's `Spawning heliox-daemon...` to the daemon's first serial line), main and
final alternating, five runs each:

| Image | spawn to first daemon line, s | median | range |
|---|---|---|---|
| main | 33.8, 36.4, 28.4, 34.0, 23.9 | 33.8 | 12.5 |
| final | 0.7, 0.8, 0.5, 0.9, 0.8 | 0.8 | 0.4 |

This is the frame allocator alone (no HDA access happens there). It is also why main fails verify_mmap at
times: that harness gives the daemon 30 s from `ring3 init` to finish its mmap check.

Not reproduced: the preview-latency figures of `docs/BENCHMARKS.md` need `target/heliox-disk.img` with the
model files (built by `build.ps1` with WSL `debugfs`), which is not present in any checkout on this machine.
No safety check was removed or weakened for speed.

## Audited and found sound

- Capability checks in `src/syscall/mod.rs` for every syscall, and every user pointer going through
  `read_user_str` / `read_user_bytes` / `valid_user_range` / `copy_to_user`, with lengths capped before
  allocation (IPC 4096, PollInput 256 events, clipboard, notifications, LaunchContext 1024, PackageList,
  PresentWindow with an exact w*h*4 check, HUD).
- `contains_user_range` excludes mmap regions, so kernel copies never fault on unpopulated pages.
- ELF parser (`src/elf/mod.rs`): header and program-header bounds with `checked_add`, `p_memsz >= p_filesz`,
  ordered non-overlapping PT_LOAD segments.
- Pid reuse after pull request 1: ids are monotonic and skip held ids, so windows, sockets, launch contexts,
  audio sessions and confirmation flags cannot be inherited.
- WaitPid enforces the parent relation; `drop_by_pid` is idempotent; ProcessKill refuses self, pid 0,
  `cap:system:all` and `cap:quota:exempt` holders.
- Network: the kernel parses no packets itself (smoltcp 0.11 does, with no reassembly buffers); every socket
  operation checks `owner_pid`; sockets are closed on reap; lock order IFACE -> SOCKETS -> DEVICE -> NIC.
- Package manager: ed25519 `verify_strict` on manifests, SHA-256 binding of the binary, capability allowlist.
- Lock order NEXT_PID -> SCHEDULER/USERSPACE and ACTIVE_CAPTURE -> SCHEDULER has no inversion; `tick()` uses
  `try_lock`; serial printing uses `try_lock` in interrupt context.

## Who can post CONFIRM to the heliox mailbox (request from workstream D)

Workstream D stopped the agent daemon from approving its own pending actions in userland. The kernel side:
`IpcReceive` (`src/syscall/mod.rs` IpcReceive arm, `src/ipc/mod.rs` `receive_for_service`) copies only the
payload, although every `ipc::Message` already records `source_pid` (set from the caller in the IpcSend
arm). The daemon cannot tell who sent `CONFIRM:<id>`.

**Senders today.** IpcSend needs `ipc:send:*` (`ipc::authorize_message`). Holders: `init`
(`cap:system:all`), `heliox-daemon` itself, `heliox-assistant-panel`, the model processes `agent-bridge` and
`audit-exporter` (model registry only, no ring-3 code), and the `ipc-owner-test` probe init can exec. The
agent can reach this set in three ways:
1. It is in it: the daemon can post to its own mailbox (D's userland refusal covers this path only).
2. It holds `cap:process:spawn`. Exec of `/bin/heliox-assistant-panel` gives the child the panel's manifest
   capabilities filtered by the daemon's, which include `ipc:send`; Exec of any VFS file whose last path
   component is `heliox-assistant-panel` does the same (the task name, and so the capability lookup and the
   mailbox name, come from the file name).
3. It holds `cap:input:inject`. InjectKey/InjectMouse reach the real panel's window through PollWindowInput
   with nothing marking them as injected (the kernel marks injected keys only for its own confirmation gate,
   `INJECTING_AGENT_KEY`), so the agent can click the panel's own approve button.

**Smallest kernel change that lets the receiver authenticate the sender.** A new syscall, `IpcReceiveFrom`
(next free number, 61): the same four arguments as IpcReceive plus `args[4]` = pointer to a 16-byte record
the kernel fills with `source_pid` and a flags word. Flag bit 0 is set when the sender is a process the kernel
launched from its embedded image of `heliox-assistant-panel` (known at spawn time in `spawn_elf_with_context` /
`sys_exec`'s embedded branch; recorded per pid). IpcReceive keeps its ABI (its wrappers leave r8 undefined,
so `args[4]` cannot be added to it), so no existing caller changes behaviour and every current harness is
unaffected. On its own it changes nothing at run time: the daemon must switch to IpcReceiveFrom and accept
CONFIRM/DENY only with flag bit 0 set. Two kernel companions close paths 2 and 3: Exec must refuse a VFS image
whose name equals a compiled-in program name, and window input events produced by InjectKey/InjectMouse must
carry an "injected" bit in PollWindowInput's record (a format change the panel has to adopt) that it checks before acting on an
approve click. Because the receiving side is userland (workstream D) and a kernel-only change has no effect
until it is used, this round records the design and does not change the code; it would also have needed one
more CI image and a full rerun of the harness table.

## Kernel items K1 to K4 from workstream D (gate red-team, round 2)

**K1, injected keys reached the kernel shell. Implemented.** `src/input/mod.rs` `inject_key_event`.
InjectKey (`src/syscall/input.rs:24`) sets `INJECTING_AGENT_KEY` around the event, so injected and physical
keys are already told apart at the one place both pass. The kernel confirmation gate used the flag; the shell
bridge did not, so when the desktop did not own the keyboard the agent's `keyboard_type` could type
`heliox confirm <id>` into the root shell, which forwards `CONFIRM:<id>` to the daemon
(`src/heliox/mod.rs`, the `confirm` arm). Fix: injected keys are not fed to the shell (counted in
`INJECTED_KEYS_KEPT_FROM_SHELL`); they still go to the GUI event queues, so injected typing into an app window
works as before. Wire contract unchanged; no userland change. What it changes: an agent can no longer drive
the kernel shell at all (no shipped program or harness relies on that; `verify_kernel_grade_autonomy_safety`
already treats the injected `y` reaching the shell as stray input it erases). Harness:
`test-syscall injected-key` in `verify_kernel_selftests.mjs`. Not closed: the desktop's terminal window is
also a kernel shell (`src/gui/compositor.rs:1200`, the terminal's Enter handling runs `shell::commands::execute`),
and it reads keys from `EVENT_QUEUE`, whose `InputEvent` has no injected mark; when the desktop owns the
keyboard and the terminal is focused, injected keys still become commands. The next step is an `injected`
field on `InputEvent` set from `INJECTING_AGENT_KEY`, with the terminal ignoring injected keys (kernel-only,
but `PollInput` serialises these events for the daemon, so its record must keep its layout). Injected keys and clicks reaching a
GUI window carry no mark, so the agent can still operate the assistant panel's own approve control (see K2
and K4).

**K2, binding an approval click to its target. Designed.** HitTest (syscall 40, `src/syscall/hud.rs:129`,
needs `hud:overlay`) already returns the window id and control label under a given point. Smallest change:
let HitTest accept `x = y = u32::MAX` to mean "the pointer now", and return the pointer position and the
window's owner pid alongside the label. Additive to the wire contract (the sentinel is not a valid
coordinate). The panel, or the kernel when it delivers the click, can then require that an approve click
lands on the approve control of the panel window, from a physical device. The physical part needs window
input events to carry an `injected` bit set by InjectMouse/InjectKey; that is a change to PollWindowInput's
record that every GUI app's input decoder (libferrumgui, userland) has to accept.

**K3, binding an approval to a file version. Designed.** Neither filesystem has a usable version: the ext2
inode has `generation` and `mtime` fields that the driver always writes as 0 (`src/fs/ext2.rs`, inode
constructors), and RamFS nodes have no metadata. Smallest change: a per-file change counter, incremented on
every write, create and remove: RamFS `FsNode::File` gains a `version: u64`; ext2 increments the inode's
`generation` on each data write (it is already on disk, so no format change). `FsStat` gains `version`, and a
new stat-style syscall (or a larger record from an existing one) returns it. An approval then records
`(path, version)` and the executor refuses when the version moved. Kernel side is additive; the daemon and
panel must record and compare it.

**K4, sender identity on IPC.** See the section above; designed, not implemented, because it does nothing
until the daemon receives through it.

## Found and not fixed (second round)

- Listen-port hijack: `src/net/iface.rs` `socket_bind` lets a second `net:listen` holder bind a port another
  socket listens on; a freed lower slot can then take the daemon's next client. Ports above 65535 are
  truncated with `as u16`.
- One process can take all 64 sockets (no per-owner limit).
- RTL8139 (`src/net/rtl8139.rs`): the device-reported length is not bounded before the copy; a bad header
  stalls reception; DMA addresses are truncated to 32 bits while TX frames can come from above 4 GiB with
  4 GiB guests; IMR enables interrupts that have no handler.
- Confirmation gate: the prompt names neither pid nor path, `y` approves the first blocked waiter rather than
  the one prompted, and the Write syscall lets any process print a fake `[SECURITY]` prompt.
- ServiceStart/ServiceStop have no capability check (service state is display-only today).
- IPC mailbox ownership is by task name; an Exec'd file named like a service takes its mailbox.
- SystemQuery formats task names into JSON unescaped.
- The quota exemption is looked up by program name (`process::create`/`register`), and mmap demand paging
  ignores `max_memory_pages`.
- `check_and_enforce_quotas` is never called; no limit on process count through AppLaunch, Exec or
  PackageLaunch; no NX bit on any user page; a fault in ring 0 during a syscall is treated as a user fault.
- ext2 superblock fields are not validated at mount (block-size shift, inode size, zero blocks per group).

## Not tested and why

- Step 1 also asked for the other boot-image-only `verify_*` harnesses on main. Not run: with main's boots of
  150 to 300 s on this host each run took 4 to 25 minutes, and the lock was shared; the time went to the nine
  baselines, the new harnesses on three images, and the benchmarks.
- Defects 7 (interrupt/lock) and 9 (reap leak) need timing or a ring-3 program shape no shipped program has.
- Defect 10 needs an ext2 disk; the harness images boot without one.
- Defect 8 on the exit path needs a ring-3 program that exits with a window open.
- The full kexec path (copy and jump) is not run: it replaces the kernel. The self-test runs the size check
  that guards the copy.
