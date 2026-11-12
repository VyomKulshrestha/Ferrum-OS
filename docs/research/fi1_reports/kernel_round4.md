# fi1 kernel round 4

Branch `improve/fi1-kernel2`, draft pull request 6, taken over from round 3 at `3a6cb3f` (image
`438ee579…fdaeb`, CI run 43199460468). Plan: `docs/research/ferrumos_improvement_fi1_plan.md`; earlier rounds:
`kernel_round1.md`, `kernel_round2.md`, `kernel_round3.md`, `joint_round2.md`. Scope, in order: vector state
across process switches, the single-processor assumption, guard pages for the static kernel stacks, ext2 write
paths, round 3's small items, and a last pass over what earlier rounds left untested.

Every image is a CI artifact (`bootimage-ferrumos`), booted in QEMU 11.1 (WHPX, `kernel-irqchip=off`,
`-cpu Haswell`, 4096 MiB; the TCG fallback with `-cpu max` was never needed), one harness at a time under
`C:/Users/marcu/Videos/fi1-qemu.lock`, `FERRUMOS_BOOT_SECONDS=600`. Before every push the kernel was
type-checked on the host from a scratch copy (round 2's method), and this round also built the kernel library
with code generation on the host (`cargo build --lib`, no link), which assembles every `asm!` block; the
kernel still links only in CI.

CPU model seen by the guest (self-test `avx-state`, every image): `GenuineIntel`, AVX and XSAVE present,
OSXSAVE set by the kernel, XCR0 = 0x7 (x87, SSE, AVX). CR0.NE is clear (self-test `user-x87`).

| Image | CI run | Commit | sha256 | size |
|---|---|---|---|---|
| baseline (round-3 head) | 43199460468 | `3a6cb3f` | `438ee579214bc8d52cc9819aa849104cc4eb38d53d7a38dd9911997ff96fdaeb` | 6,762,496 |
| A (first candidate) | 43212688808 | `5d68d94` | `d5bee20814b519c1892927252500d0e27b3b306983d65bf78e245e7419ae654a` | 6,845,952 |
| negctl | 43213619553 | `8bbfaa2` | `a8b4692123315e0eeb7246a5db46889141d3d966115d01098498dd2e0bceb6d9` | 6,846,464 |
| F (all fixes but finding 11) | 43215133510 | `48925f3` | `dc603a0b54359b79dbcec2c5c9584cfdd1788cdfe3ab569ce51285b48ac2f99d` | 6,854,144 |
| F' (F + a host-test update) | 43216624633 | `161c708` | `dc603a0b…2f99d` (identical to F) | 6,854,144 |
| H (final code: F' + finding 11) | 43217762461 | `2c31ef9` | `c9ab1985f15c2c837e50369cee10c09fff071215f6a5a347767afd30248ca054` | 6,857,728 |
| final head (H + this report) | the run of this commit | (this commit) | expected identical to H (reproducible build; checked after the push, see the pull request) | |

`b7fc831` (the window budget) was committed on top of A and never built alone. negctl (`8bbfaa2`) is
`b7fc831` with every round-4 kernel fix held back by `kernel_round4_tools/negctl.py` and all round-4
self-tests and the harness kept; `02310ff` reverts it (its tree equals `b7fc831`), and `48925f3` adds the
XSAVE area-size correction that image A's harness run called for (finding 1 below). Not held back in negctl:
the SMP boot report and assertion (a checked fact, not a defect), `write_inode`'s bounds (not reachable from a
disk; holding it back stops the kernel inside `ext2-r4`) and the Kexec mapping error (Kexec is never run).
Finding 11 came after negctl was built; its negative control is a runtime switch in the same image
(`test-syscall confirm-single-off` restores the old behaviour), as round 3 did for auto-EOI.

The CI build is reproducible: `161c708` changed only a host test, and its image is byte-identical to F's. The
report-only commit at the head therefore builds H's image again (its digest is compared with H's after the push).

## Harness results

### The new harness, `verify_kernel_k4.mjs` (self-tests in `src/shell/selftest_k4.rs`)

The baseline image has none of these self-tests. Image A could not run them: every command typed at the shell
arrived as zeros (`FerrumOS: command not found: ^@^@^@…`, as many NUL bytes as the command had characters),
7 of 37 checks passed (the boot messages and the `-smp 2` boot report). The cause is finding 1's first version,
fixed in F.

negctl ran in two boots: the full harness, which stopped at `window-budget` when the kernel panicked, and a
second boot with every other self-test skipped to reach the destructive one.

| Check | negctl (`a8b46921…`) | F (`dc603a0b…`) | H (`c9ab1985…`) |
|---|---|---|---|
| boot: one CPU online, no AP started | pass | pass | pass |
| boot: guard pages below the six static stacks | fail: `0 of 6` | pass: `6 of 6` | pass |
| `smp-state`: no AP entered the kernel; frame 0x8000 is the bootloader's | pass | pass | pass |
| `static-stack-guards`: page below each of the six stacks unmapped (6 checks) | fail (all six `guard_mapped=true`) | pass | pass |
| `static-stack-guards`: `test-syscall` runs on the shell's static stack | pass | pass | pass |
| `avx-state`: XSAVE switching, area of at least 832 bytes | fail: `area_size=512 xsave_switching=false` | pass: `area_size=832` | pass |
| `avx-state`: a new process sees zero YMM upper halves | fail: `reader_nonzero_upper_halves=16` | pass: 0 | pass |
| `avx-state`: writer A's 16 registers intact | fail: `writer_a_intact=0` | pass: 16 | pass |
| `avx-state`: writer B's 16 registers intact | pass: 16 (it ran last) | pass: 16 | pass |
| `ext2-r4` control: create, remove, create reuses the inode | pass | pass | pass |
| `ext2-r4`: metadata blocks marked free | fail: `files_read_back=false` | pass | pass |
| `ext2-r4`: reserved inodes marked free | fail: `create=err:ext2:_not_a_directory root_still_dir=false` | pass: `new_inode=11` | pass |
| `ext2-r4`: a linked inode marked free | fail: `g_shares_f_inode=true f_intact=false` | pass | pass |
| `ext2-r4`: remove one of two hard links | fail: `h2_intact_after_create=false` | pass: `links_now=1` | pass |
| `ext2-r4`: remove `/d/.` | fail: `remove=ok d_aliases_e=true` | pass: `remove=err:invalid_path` | pass |
| `ext2-r4`: round 1 finding 10 (stale entry, 256-byte name) | pass | pass | pass |
| `ext2-r4`: `write_inode` bounds (not held back) | pass | pass | pass |
| `exec-embedded-version`: compiled-in name ignores a VFS file there | fail: `embedded_check_passes=false` | pass | pass |
| `exec-embedded-version`: a changed VFS file is still refused (control) | pass | pass | pass |
| `exit-closes-windows` (round 1 finding 8) | pass | pass | pass |
| `reap-others` (round 1 finding 9) | pass | pass | pass |
| `user-x87` (CR0.NE clear: kernel unaffected) | pass | pass | pass |
| `delete-prompt`: the prompt names the escaped path | fail: `... destructive syscall: DeleteFile` | pass: `DeleteFile path="/tmp/k4-\x1b[2J\x0aAPPROVED"` | pass |
| `delete-prompt`: unanswered prompt is a denial | pass | pass | pass |
| `window-budget`: canvases within 6 MiB, the rest refused | kernel panic: `memory allocation of 1702400 bytes failed` (harness stopped here) | pass: 3 created, 7 refused, 5,107,200 bytes | pass |
| `window-budget`: windows released | not reached | pass | pass |
| no kernel fault during the self-tests | not reached (panic above) | pass | pass |
| `static-stack-overflow` (destructive): double fault | fail (second boot): no output, kernel silent | pass: `DOUBLE FAULT` panic | pass |
| `-smp 2` boot: MADT lists one AP, none started | pass | pass | pass |
| `-smp 2` boot: shell runs, `smp-state` reports 0 started | pass | pass | pass |
| `confirm-single`: with one prompt pending, a second DeleteFile is refused at once, no second prompt | not in image | not in image | pass: refused after 50 ms, 1 prompt; switch off (old behaviour, same image): 2 prompts, the second waited 3,003 ms until killed |
| `confirm-single`: the switch-off control shows two prompts | not in image | not in image | pass |
| total | 16/35 in the full run (stopped at `window-budget`), then 6/14 in the second boot | 37/37 | 39/39 |

### Every harness on F and on the final image

| Harness | expected | baseline `438ee579…` (round 3 final) | F `dc603a0b…` | H `c9ab1985…` |
|---|---|---|---|---|
| verify_kernel_k4 (new) | 39 | not run (self-tests absent) | 37/37 (before `confirm-single` existed) | 39/39 |
| verify_kernel_k3 | 48 | 48/48 | 48/48 | 48/48 |
| verify_kernel_selftests | 18 | 18/18 | 18/18 | 18/18 |
| verify_kernel_selftests_k2 | 37 | 37/37 | 37/37 | 37/37 |
| verify_net_k2 | 12 | 12/12 | 12/12 | 12/12 |
| verify_authority_gate_joint | 37 | 37/37 | 37/37 | 37/37 |
| verify_authority_gate_self_approval | 11 | 11/11 | 11/11 | 11/11 |
| verify_authority_gate_input_injection | 7 | 7/7 | 7/7 | 7/7 |
| verify_ring3 | 7 | 7/7 | 7/7 | 7/7 |
| verify_mmap | 7 | 7/7 | 7/7 | 7/7 |
| verify_core_apps | 24 | 24/24 | 24/24 | 24/24 |
| verify_app_window | 13 | 13/13 | 13/13 | 13/13 |
| verify_ipc_isolation | 6 | 6/6 | 6/6 | 6/6 |
| verify_process_reap_cr3 | 9 | 9/9 | 9/9 | 9/9 |
| verify_pid_reuse | 6 | 6/6 | 6/6 | 6/6 |
| verify_assistant_panel | 5 | 5/5 | 5/5 | 5/5 |
| verify_net | 5 | 5/5 | 5/5 | 5/5 |
| verify_user_pointer_isolation | 4 | 4/4 | 4/4 | 4/4 |
| verify_scheduler_stubs | 7 | 7/7 | 7/7 | 7/7 |
| verify_current_pid | 6 | 6/6 | 6/6 | 6/6 |
| verify_audio_nonblocking | 7 | 7/7 | 7/7 | 7/7 |

The baseline column is round 3's result for its final image, not rerun here. negctl was not run through these
twenty harnesses (it holds back only this round's fixes; its purpose is the new harness). Every harness on F
passed on its first run.

### Host tests

| Suite | before (`3a6cb3f`) | after |
|---|---|---|
| userland/heliox-gate-tests | 78 | 78 (one source-text assertion in `tests/joint2.rs` follows `exec_version_check`) |
| userland/physical-runtime | 175 | 175 |
| userland/neural-protocol | 19 | 19 |
| scripts/authority_matcher_adversarial.py | 19/19 | 19/19 |

The gate test failed (77 of 78) on the first run after finding 8: it looked for the literal
`check_version(&path, expected)` in `sys_exec_checked`; it now checks that `exec_version_check` runs before the
image is read and that it calls `check_version` for VFS paths.

## Defects fixed, by severity

Line numbers of the defect refer to `3a6cb3f`.

### High

**1. The upper halves of the YMM registers passed from one process to the next.** `src/lib.rs:214-230` enabled
AVX in XCR0, and `src/scheduler/mod.rs:1157` (`save_simd_state`) and `:1226` (`context_switch_to`) saved and
restored only the 512-byte FXSAVE area, which holds the low 128 bits of each vector register. A process that
starts or resumes after another one used AVX finds that process's YMM upper halves in its registers, and two
processes that both use AVX overwrite each other's. Round 3 judged this a covert channel because "no shipped
program uses AVX"; that is wrong: the daemon's local inference (`userland/heliox-daemon/src/cognitive/inference.rs:450-580`)
runs AVX2 code whenever SystemQuery reports `avx2: true`, which it does on this host, so a second AVX user
(any process can execute AVX instructions) reads the upper halves of the daemon's last vectors and can corrupt
its arithmetic. On negctl a reader process found 16 of 16 upper halves non-zero at its first instruction
(`reader_nonzero_upper_halves=16`), and of two writers with different patterns, the first found 0 of its 16
registers intact after a sleep and a spin (`writer_a_intact=0`).

Choice: XSAVE/XRSTOR rather than turning AVX off. Turning it off is the smaller change (no `xsetbv`, SystemQuery
reporting `avx2: false`), but a shipped program uses AVX2 and loses its fast path; XSAVE costs about 60 lines
and keeps it. Fix: `scheduler::enable_xsave` switches the scheduler to XSAVE areas when the kernel enables AVX;
each task's area is 64-byte aligned and sized to the end of the furthest component enabled in XCR0; a new
task's area and an exec'd image's area start in the initial state (zeroed: XSTATE_BV = 0, so XRSTOR loads the
initial state of every component, YMM upper halves included; FCW 0x037F, MXCSR 0x1F80); `save_simd_state`
(used by both the syscall and the timer entry path through `save_user_context`) runs `xsave64` with every
component requested, and `context_switch_to` runs `xrstor64` (`fxsave64`/`fxrstor64` remain for CPUs without
AVX). Self-test `avx-state`: two writers fill all sixteen YMM registers with different patterns, sleep (switch
through the syscall path), spin 200 million iterations (preempted by the timer), sleep again and count the
registers whose upper half still holds their pattern; a reader started after them counts non-zero upper halves.

The first version (image A) sized the area with CPUID.(0xD,0).EBX alone. Under WHPX that leaf reports 576
bytes (legacy area and header) with XCR0 = 7, while XSAVE writes 832, so every save wrote 256 bytes past the
task's area into the next heap object. On image A the shell's input line, a heap `String`, was overwritten
with zeros on each switch, and every command arrived as NUL bytes. `48925f3` sizes the area from the CPUID
subleaf of each enabled component (offset plus size; for AVX, 576 + 256) and refuses XSAVE switching below 832
bytes. negctl and F print `cpuid_d_size=576`; F prints `area_size=832`.

**2. App windows could exhaust the kernel heap.** `src/syscall/gui_window.rs:48` capped windows per process
(4, round 1), and `src/gui/window.rs:102` allocated each canvas (up to 760 x 560 x 4 = 1.7 MB) infallibly from
the 12 MiB kernel heap. Three processes holding `gui:window:*` (every GUI app has it) could hold 20 MB of
canvases: the allocation, or the next one anywhere in the kernel, panicked. On negctl, creating the largest
windows for ten owners stopped the kernel before the self-test finished (`KERNEL PANIC ... memory allocation of
1702400 bytes failed`). Fix:
all app canvases together may hold 6 MiB (`app_window::MAX_TOTAL_CANVAS_BYTES`; the shipped apps' canvases are
0.2 to 0.9 MB), checked before allocating, and the canvas is reserved fallibly; CreateWindow returns
InvalidArgument when either fails. Self-test `window-budget`. This is the largest per-process consumer of
kernel heap; the others are listed under "What remains".

### Medium

**3. ext2 allocators trusted the bitmaps.** `src/fs/ext2.rs:859-895` (`alloc_block`) handed out any block its
bitmap marked free, including the superblock, the descriptor table, the bitmaps and the inode table;
`:932-964` (`alloc_inode`) handed out reserved inodes (1 to 10; 2 is the root directory) and inodes that still
had links. A corrupted or crafted disk then had file data written over its own metadata, or one inode shared
by two names. On negctl (in-memory images): with blocks 1 to 6 marked free, two 1 KiB files were created but
did not read back (`files_read_back=false`: their blocks were the superblock and descriptor table, rewritten by
the next metadata write); with inodes 2 to 11 marked free, a create took inode 2 and overwrote the root
directory (`create=err:ext2:_not_a_directory`, `root_still_dir=false`); with a linked inode marked free, a new
file took it (`g_shares_f_inode=true f_intact=false`). Fix: `is_metadata_block` (boot block, superblock and
primary descriptor table, every group's bitmaps and inode table) is never allocated; inodes below `first_ino`
(at least 11), past `inodes_count`, or with `links_count` != 0 are never allocated; `remove` now marks a freed
inode deleted on disk (links 0, dtime set) so the allocator can reuse it. Self-test `ext2-r4`.

**4. `remove` ignored `links_count`.** `ext2.rs:1546-1607`: removing one name of a file with two hard links
freed the inode and its blocks while the other name still pointed at them; the next create reused both, so
the other name read the new file's bytes, and `versions` (keyed by inode number) moved with them. The driver
cannot create hard links, so this needs a disk made elsewhere. On negctl `h2_intact_after_create=false`. Fix:
when more than one link remains, `remove` drops one link, writes the inode back and bumps its version.

**5. Guard pages for the static kernel stacks.** The shell, desktop and dashboard stacks (64 KiB), the idle and
return stacks (32 KiB, `scheduler/mod.rs:1517-1527`) and the double-fault IST stack (20 KiB, `gdt.rs:76`) were
arrays in `.bss` with other statics directly below. On negctl a 400-level recursion on the shell stack (the task
that runs `test-syscall`) ran into the statics below 0x713000 and the kernel stopped silently, with no message,
within the harness's 10 s. Fix: each is a `memory::kstack::GuardedStack` (page-aligned, one page in front of
the stack), and `protect_static_stacks` unmaps that page at boot, before any task runs; the kernel image's
page tables are shared by every address space. The same recursion now ends in `DOUBLE FAULT`. An overflow of
the double-fault stack itself is now a triple fault (a reset; with `-no-reboot`, QEMU exits) instead of a
silent overwrite. Self-tests `static-stack-guards` and `static-stack-overflow` (destructive).

**6. The DeleteFile confirmation prompt did not name its target.** `src/syscall/mod.rs:325-338` printed
"Process is requesting destructive syscall: DeleteFile". The operator approved a deletion without seeing what
would be deleted. Fix: `confirmation_subject` reads the path from the caller (the approved call is the same
`int 0x80` re-executed with the same registers; the task is blocked meanwhile and no other task can write its
memory, so the path shown is the path deleted) and prints it with the requesting pid, through
`escape_printable` (bytes 0x20 to 0x7E except `\` and `"` as they are, every other byte as `\xNN`), so a path
cannot carry terminal escapes or a forged second line. Self-test `delete-prompt`: a ring-3 DeleteFile of
`/tmp/k4-<ESC>[2J<LF>APPROVED`; negctl prints `DeleteFile` alone, F prints
`DeleteFile path="/tmp/k4-\x1b[2J\x0aAPPROVED"`; unanswered, it times out as a denial on both.

**11. The y/n key could answer a different request than the one on screen** (`src/scheduler/mod.rs:1767`
`wake_confirmation_waiters_locked`, found while testing finding 6; round 1 had noted it, unfixed): the key
approves the first task in task order that waits for confirmation, not the one whose prompt was printed last.
With two DeleteFile requests pending, an operator answering the second prompt shown approved the first
request's deletion; with finding 6 the prompt names a path, so the mismatch would read as an approval of the
wrong file. Fix: one prompt at a time; a gated call made while another task waits is refused at once with
`[SECURITY] Process N refused without a prompt: DeleteFile path="..." (another confirmation is pending)`.
Self-test `confirm-single` (two ring-3 DeleteFiles 400 ms apart): with the rule switched off on the same image,
two prompts and the second requester blocked until killed after 3,003 ms; with it on, one prompt and the second
refused after 50 ms. (Numbered in the order found.)

### Low

**7. `remove` of `dir/.`** (`ext2.rs:1546`, `:1682`): `split_path` accepted `.` as the last component, so
removing `/d/.` for an empty directory `d` unlinked `.`, freed d's inode and blocks and left `d` in its parent
pointing at a free inode; the next directory created took it (negctl `d_aliases_e=true`). Syscalls refuse `.`
and `..` components (`syscall/fs.rs:92`), so only the kernel shell's `rm` reached it. Fix: `remove` and
`split_path` refuse `.` and `..`.

**8. ExecIfVersion checked the VFS file at a compiled-in program's path** (`src/syscall/process.rs:141`).
`/bin/init`, `/bin/task-manager` and the other embedded names run the image compiled into the kernel, never a
VFS file; the version check looked at whatever file sat at that path, so any `fs:write` holder could make every
ExecIfVersion of that name fail by writing one there. On negctl `embedded_check_passes=false`. Fix:
`exec_version_check` passes for embedded names (the image cannot change) and checks VFS paths as before (the
control, a changed VFS file, is still refused on every image).

**9. Kexec's `map_to(...).unwrap()`** (`src/syscall/kexec.rs:90`): a failed mapping (no frame for a page
table) panicked the kernel; it now returns InvalidArgument. Not tested: Kexec replaces the kernel, and the
failure needs frame exhaustion.

**10. `write_inode` had no bounds** (`ext2.rs:565-573`): inode 0 underflowed and a number past the last group
indexed past the descriptor table. Every caller passes an inode it has just read (which is bounds-checked), so
no disk reaches it; it now applies `read_inode`'s checks. Tested directly in `ext2-r4`.

## The single-processor assumption

What `src/smp` does: `smp::init` (`src/smp/mod.rs` before this round: 47 lines) copied a 230-byte real-mode
trampoline to physical 0x8000 and printed a message. No Local APIC is set up, no INIT or SIPI is ever sent, no
MADT entry is acted on, `ap_entry` is never reached and `per_cpu::PerCpu::setup_gs` is never called. Every
application processor stays in the firmware's wait-for-SIPI state. The kernel runs on one CPU.

This is now a checked fact rather than a comment:
- boot prints `[ INFO ] SMP: online_cpus=1 application_processors_started=0 madt_application_processors=N
  trampoline_region=Some(Bootloader) trampoline_copied=true`; the harness checks it on a default boot (N = 0)
  and on a boot with `-smp 2` (N = 1, the shell runs, nothing started) on negctl and F;
- `ap_entry` counts any CPU that reaches it and parks it with interrupts off; `smp::assert_single_cpu`, called
  on every timer tick, stops the kernel if the count is ever non-zero;
- the trampoline copy now happens only if the boot memory map says frame 0x8000 is not usable (it is the
  bootloader's region, so the copy never overwrote a frame the allocator could hand out; that was checked, not
  assumed);
- self-test `smp-state` reports the counters.

What must change before an application processor runs kernel code. Each item is an argument made in rounds 1
to 3, or in code comments, that holds only on one CPU:
1. Syscalls and the "check, then act" pairs. `fs::write_file_if_version`, `remove_if_version`, the
   expected-version calls and ExecIfVersion (`fs/mod.rs:555-578`, `syscall/process.rs:164`) rely on "syscalls
   run with interrupts off on the one CPU", so no filesystem change falls between check and act. On SMP another
   CPU's syscall can; the check and the act need one filesystem lock.
2. Kill and reap. `syscall/process.rs:58-63` frees a killed process's address space at once because "no CPU can
   still be executing on the target's stack in this single-core scheduler"; `process::reap_dead`, waitpid's
   fast path and quota kills assume the same. On SMP the victim may be running on another CPU: its kernel stack
   and page tables would be freed under it. Needs a per-task "running on CPU n" state and an IPI or a deferred
   free.
3. Scheduler globals: `CURRENT_PID`, `CURRENT_KERNEL_TASK_PID`, `TOTAL_TICKS` (each CPU's timer would tick it),
   `RESUME_SLOT` and the scratch context (`scheduler/mod.rs`), the single TSS with one RSP0 and one IST
   (`gdt.rs:58`, `set_kernel_stack` says "single-threaded kernel so no locking"), the one GDT, the idle and
   return stacks, and `PENDING_CONFIRM_KEY`. All must become per-CPU (the unused `PerCpu` through GS is the
   start).
4. Vector state: `save_simd_state` saves the registers of the CPU it runs on; it must run on the CPU that ran
   the task, and a task must not be resumed on another CPU before its save completes.
5. Interrupt-context locking: rounds 1 and 3 made every lock an interrupt handler takes either `try_lock` or
   taken with interrupts off on the other side (heap, input queues, keyboard queue, scheduler). With interrupts
   off a handler on CPU 1 can still wait for CPU 0's holder, which is correct for spin locks, but the
   `try_lock` paths that park work for "the next tick" (`PENDING_CONFIRM_KEY`) assume the same CPU takes the
   next tick.
6. TLB shootdown: every unmap (kernel stacks freed, guard pages, address-space teardown, mmap, the Kexec page)
   flushes only the local TLB. Another CPU could keep using a stale translation to a freed frame.
7. Device drivers: the PIC (8259) and PIT are the only interrupt sources; SMP needs the Local and I/O APIC.
   The ATA, HDA, RTL8139 and xHCI drivers are behind one mutex each, which is enough, but the network stack is
   polled from syscall context on the assumption that only one poll runs.
8. `sync::DeadlockMutex` reports core 0 for every owner (`sync/mod.rs:35`).
9. User pointers: "processes are single-threaded and there is no munmap, so a range cannot change between check
   and use" (round 3) still holds on SMP as long as a process runs on one CPU at a time.

## Earlier rounds' "not tested" items

| Round, item | Now |
|---|---|
| 1, finding 7 (input interrupts spinning on the scheduler lock) | Not testable deterministically: it needs a keyboard interrupt to land inside a short critical section. Round 3's `kbd-lock` covers the queue side. |
| 1, finding 8 (windows of an exiting process) | Tested: `exit-closes-windows` (window created for a process that then exits; 1 before, 0 after) on negctl and F. |
| 1, finding 9 (dead processes leaked by a wait) | Tested: `reap-others` (two dead processes, one deferred reap frees both) on negctl and F. |
| 1, finding 10 (ext2 entry names, deleted entries) | Tested: `ext2-r4` `stale_entry` (a deleted `s` ahead of the live `s`; a 256-byte name refused). |
| 1, full Kexec path | Not testable: it replaces the running kernel. |
| 2, DMA above 4 GiB | Not testable here: the frame allocator hands out frames in map order and reaches the RAM above 4 GiB only after about 3 GiB of allocations. |
| 2, ring-0 #GP and #UD | Not run: each stops the kernel, one per boot; they share the classification code that `kstack-overflow` and the page-fault self-test exercise. |
| 2, the daemon's listener on port 8785 over the datagram network | Not in this round's (kernel) scope. |
| 2 and 3, ext2 on a real `heliox-disk.img` | Not testable: no such disk exists on this machine and `mke2fs` is not installed; all ext2 tests use in-memory images. |
| 3, TX OWN bit (RTL8139) | Not testable: QEMU completes transmission synchronously. |
| 3, `allocate_simd_buffer` null check | Not testable without exhausting the heap at task creation. |
| 3, #MF from ring 3 | Run (`user-x87`), and it cannot be raised here: CR0.NE is clear (`cr0_ne=false`), so an unmasked x87 error is reported through the legacy FERR#/IRQ 13 path, which is masked; the process ran on until the CPU quota killed it (137) and the kernel was unaffected. |
| 3, #NM, #TS, #NP, #BR, #AC | Not raisable from ring 3 here: CR0.TS and CR0.EM are never set (#NM), there are no task gates or not-present descriptors (#TS, #NP), `bound` does not exist in 64-bit mode (#BR), and CR0.AM is clear (#AC). |
| 3, the doubled PS/2 key | Not testable deterministically (it needs the IRQ to take the byte between the poll's status read and data read). |
| 3, the daemon's HTTP client against live servers | Out of this round's scope; host tests cover the parser. |

## Audited and found sound

- The XSAVE switch on every path: `save_user_context` (syscall and timer entry, Sleep, Exit, WaitPid, the
  confirmation block) is the only place a ring-3 task's registers are saved, and `context_switch_to` is the
  only place they are restored; the timer returning to the same task touches no vector register (the kernel is
  built soft-float). Kernel tasks get an area in the initial state. A task's area is freed with the layout it
  was allocated with (`simd_layout`, fixed after boot).
- `enable_sse_extensions` runs before the scheduler exists, so every area is sized after the switch to XSAVE.
- ext2 `free_block` and `free_inode` bounds (round 3) and the overwrite path of `create_file_bytes` (old blocks
  freed after the inode points at the new ones); with finding 3, a bitmap that frees metadata can no longer
  turn into metadata being allocated.
- The bootloader's frame at 0x8000 is in the `Bootloader` region of the memory map (self-test `smp-state`),
  never handed out by the frame allocator.

## What remains

- Per-process kernel heap accounting in general (item 5 of the brief, not done as such). Bounded per object or
  per owner now: windows (4 per process, 6 MiB of canvases in total, finding 2), IPC (16 messages of 4 KiB per
  mailbox, 256 in the broker), RamFS (4 MiB, 2,048 nodes), sockets (16 per owner), RecordAudio (fallible). No
  ledger caps one process's total: IPC across many mailboxes, launch contexts and audit records add up. A
  ledger charged at allocation and released at reap would close it.
- Any process can print a forged `[SECURITY]` line through the console Write syscall (`sys_write_console`
  prints process text unmarked); round 1 noted it. Marking process output, or drawing the prompt where processes
  cannot, would close it.
- SMEP and SMAP are not enabled (CR4 bits 20 and 21 are never set).
- ext2: backup superblocks and reserved GDT blocks of `sparse_super` and `resize_inode` disks are not treated as
  metadata; a file whose block pointers cross-link another file's blocks frees them on remove; indirect pointer
  blocks still leak on remove and on overwrite; directories are limited to 12 blocks. All need a disk made
  elsewhere.
- SMP: the list above, before any AP is started.
- The XSAVE area uses standard (uncompacted) form; supervisor components (XSAVES) are not used and not needed.
- CR0.NE is clear; if the kernel ever wants #MF from user x87 code it must set it (and handle #MF, which round 3
  already does).
- Round 2's policy items and joint round 2's Q-J2a to Q-J2d are untouched (outside the kernel rounds' scope).

## Edits outside this round's areas

| File | Edit | Why |
|---|---|---|
| `src/shell/selftest_k3.rs` | helpers made `pub(super)`; unknown names fall through to `selftest_k4::run` | reuse and wiring |
| `src/scheduler/mod.rs` | `defer_reap` (self-test hook) | `reap-others` |
| `scripts/lib/qemu_shell.mjs` | `bootShell` takes `extraArgs` | the `-smp 2` boot |
| `src/acpi/mod.rs` | records the MADT's AP count | SMP report |
| `README.md`, `docs/ARCHITECTURE.md` | XSAVE, static-stack guards, the DeleteFile prompt, the single-CPU statement | statements this round made incomplete |

Run tools: `kernel_round4_tools/` (`negctl.py` builds the negative control; `h.sh` and `suite.sh` are round 3's
with this round's paths). CI runs used: 6 (43212688808 A, 43213619553 negctl, 43215133510 F, 43216624633 F', 43217762461 H, and one for this report, which changes no kernel code).

## State of the kernel after four rounds

Four rounds fixed 52 kernel defects (rounds 1 to 3: 41; this round: 11, counting finding 1's area-size
correction, a defect of this round's first image, as part of finding 1), each with a run-time test where one could reach it, and each harness run
against a negative-control image. What that leaves, plainly:

**Fixed and tested at run time.**
- Entry and exception state: DF cleared on both naked entry stubs; a gate for every exception, so no ring-3
  exception reaches the double fault; ring-0 faults stop the kernel with a message; the PIC lines without a
  handler are masked.
- Process isolation: NX on user data and on the kernel's data, heap, physical map and boot regions; user
  pointers checked for writability before every write; per-process CR3 with no stale reuse; pid reuse; mailbox
  ownership bound to a pid; vector state (x87, SSE and AVX) saved and restored per task.
- Stacks: every kernel stack, per-process and static, has an unmapped guard page; the user stack has a 64 KiB
  gap.
- Interrupt-context locking: the heap, the scheduler, the keyboard and input queues are never spun on by an
  interrupt handler that interrupted their holder.
- Resource limits: IPC slots with an operator reserve, RamFS bytes, nodes and depth, windows per process and
  canvas bytes overall, Kexec image size, RecordAudio buffers, the HTTP client's response size.
- Process lifecycle: windows, sockets, mailboxes and frames are released on exit, kill and reap, including the
  other dead processes when a wait reaps one.
- ext2: mount-time validation of every superblock and descriptor field used; bounded, validated directory
  walks; whole-file reads bounded; allocators that never hand out metadata, reserved or linked inodes;
  `links_count` honoured; empty, `.` and `..` names refused; versions that move whenever a name or content
  changes.
- The operator's confirmation: one prompt at a time, naming the pid and the escaped path, physical keys only,
  default deny on timeout.

**Known and open** (each with the round that found it):
- The kernel assumes one CPU (round 4): the nine items under "The single-processor assumption" must be done
  before any application processor runs kernel code.
- No SMEP or SMAP (round 4, not examined before): CR4 bits 20 and 21 are never set, so a kernel bug that
  follows a user pointer or jumps to user memory is not stopped by the CPU. The kernel is mapped in every
  address space without KPTI, so Meltdown-class reads of kernel memory are possible on CPUs that are affected.
- Any process can print a line that looks like a `[SECURITY]` prompt through the console Write syscall (round
  1; `sys_write_console` prints process text unmarked, checked this round); the real prompt cannot be told apart
  by its text, which matters more now that the prompt names a path.
- Per-process heap accounting as a whole (round 3, round 4): windows, IPC, RamFS and sockets (16 per owner) are
  bounded per object or per owner, but no ledger caps one process's total kernel heap.
- ext2: backup superblocks and reserved GDT blocks are not protected; cross-linked blocks are freed on remove;
  indirect blocks leak; 12-block directories (round 4).
- CR0.NE is clear (round 4): x87 errors are not delivered.
- Service lifecycle state is display-only (round 2).

**Never examined** by the four kernel rounds: the compositor and desktop input paths beyond the app-window
syscalls; the xHCI, HDA (beyond the audio syscalls), VirtIO-GPU and VBE drivers; ACPI AML; the package
manager's signature verification; `src/agent`, `src/heliox` and `src/accounts` beyond the authority gate the
joint rounds covered; the logging and audit flush to disk; timing and cache side channels; the bootloader
itself (bootloader 0.9.33, including its own stack guard).
