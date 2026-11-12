# fi1 kernel round 3

Branch `improve/fi1-kernel2`, draft pull request 6, taken over from round 2 at `8d21d68` (image
`2b4bc33b…a045c`). Plan: `docs/research/ferrumos_improvement_fi1_plan.md`; earlier rounds: `kernel_round1.md`,
`kernel_round2.md`, `joint_round2.md`. Scope, in order: concurrency in the interrupt and context-switch paths,
stacks, a second reader's audit of `src/syscall`, `src/ipc` and `src/fs`, the daemon's HTTP client, round 2's
small items, timer cost.

Every image is a CI artifact (`bootimage-ferrumos`), booted in QEMU (WHPX, `kernel-irqchip=off`, 4096 MiB),
one harness at a time under `C:/Users/marcu/Videos/fi1-qemu.lock`, `FERRUMOS_BOOT_SECONDS=600`. Before every
push the kernel was type-checked on the host from a scratch copy (round 2's method). The `syscall`, `ipc` and
`fs` audit was a separate read-only pass whose findings were checked against the code before any was fixed.

| Image | CI run | Commit | sha256 | size |
|---|---|---|---|---|
| baseline (round-2 head) | (round 2) | `8d21d68` | `2b4bc33be01f3166a613c24fc87769ea079a3534888c1f594f93c6dd561a045c` | |
| A (first candidate) | 43189963256 | `7ed1bb1` | `6b81729c166eff25b97b61ab1a1233c8f6495f7ccba3d852cbcf8d3893755cc0` | 6,730,752 |
| negctl | 43190864541 | `679a159` | `4e43738f4480a20212e5b183f08ffc6496bdcf1e7b3bede5d75690893a3580a4` | 6,620,160 |
| B | 43190989931 | `479d444` | `f121ac0677b930927d6b60899322cf67528cadb9c72113b09140f9f555b01548` | 6,740,992 |
| F (all fixes, normal EOI) | 43192738780 | `26dff86` | `c3ea01496b37467ef5f261c2d4c55ebd4222a165793b1bbe6335a3578bcf6c14` | 6,762,496 |
| final (F + auto-EOI at boot, this report) | 43199460468 | `992752f` | `438ee579214bc8d52cc9819aa849104cc4eb38d53d7a38dd9911997ff96fdaeb` | 6,762,496 |

negctl (`679a159`) is the final self-tests, harness and counters with every round-3 kernel fix held back
(scratch script: the fixed files restored from `8d21d68`, plus a one-line `receive_for_owner` stub that
forwards to the old broker); `479d444` reverts it (its tree equals `5b73643`). Not held back in negctl: the
`allocate_simd_buffer` null check, the guards on `push_keyboard` and `poll_ps2_keyboard` (only `read_keyboard`
and the input queues were reverted), and the auto-EOI switch, which is off by default there. `26dff86` adds to B
the mailbox-claim correction found by the harnesses (finding 7 below) and the matching change to init's IPC
test; `992752f` adds only the auto-EOI default (see Performance) and this report.

## Harness results

### The new harness, `verify_kernel_k3.mjs` (self-tests in `src/shell/selftest_k3.rs`)

The baseline image has none of these self-tests, so it was not run there. On negctl a self-test that stops
or hangs the kernel ends the run, so the harness was rerun with `FERRUMOS_SKIP_SELFTESTS` growing by the
self-test that had stopped the previous run (as in round 2):

| negctl run | skipped | where it stopped |
|---|---|---|
| 1 | none | `df-entry`: `[KERNEL] Page Fault in ring 0 (current pid 5)`, instruction fetch at `0x15` (the backwards `rep movs` overwrote a return address) |
| 2 | + df-entry | `irq-alloc`: no output after the task spawn, no prompt within 60 s (the timer spinning on the heap lock) |
| 3 | + irq-alloc | `kbd-lock`: hung after "polling for 6 s" while the harness typed (keyboard interrupt spinning on the queue lock) |
| 4 | + kbd-lock | `ext2-r3`, first crafted case: `panicked at .../raw_vec/mod.rs:28:5: capacity overflow` |
| 5 | + user-stack, ipc-mailbox, ramfs-limits, ext2-r3 | `user-exceptions`, first case: `panicked at src\interrupts\mod.rs:290:5: DOUBLE FAULT` (ring-3 `div` by zero) |
| 6 | + user-exceptions | `user-write-ro`: `[KERNEL] Page Fault in ring 0 (current pid 5): stopping the kernel`, address `0x8000000000` (the caller's read-only text) |
| 7 | + user-write-ro | ran to the end; `kstack-overflow` ended in `DOUBLE FAULT` (see the last row below) |

Checks per self-test (negctl values from the run in which the self-test ran):

| Check | negctl | final |
|---|---|---|
| boot stack and boot-info P4 entry (P4[2]) non-executable | fail: `boot_stack_nx=not_marked` | pass |
| kernel image stays executable | pass | pass |
| process kernel stack mapped, no-execute | pass | pass |
| page below a process kernel stack unmapped | fail: `below_stack_mapped=true` (heap) | pass |
| freed kernel stack unmapped, slot returned | fail | pass |
| DF clear in kernel code on syscall and timer entry from a ring-3 task with DF set; memcpy correct | kernel stopped (run 1) | pass: 0 and 0 entries with DF, 5,001 probes, 0 bad |
| timer wakes tasks while kernel code allocates with interrupts on | kernel hung (run 2) | pass: 2,028,617 allocations, 1,990 wakes |
| typing while the shell polls its queues | kernel hung (run 3) | pass: 40 keys, 23.5 M polls |
| no mmap region / ELF segment may end at the user stack | fail / fail | pass / pass |
| user stack overflow kills the process (137), kernel runs on | pass | pass |
| mailbox: first owner; second instance never takes it; nothing queued for the first reaches the second; a later process owns it | 3 of 5 (`owner_after_first_died=second`, `second_got_firsts_message=true`) | 5 of 5 |
| unflagged senders get 12 of 16 slots; operator message accepted when full; all delivered | fail (16 accepted, operator message refused) | pass (12, accepted, 13 delivered) |
| RamFS byte budget; depth 32; deep tree removed; newline name refused | fail (6 MiB written, depth 41, newline name created); removal passes | pass |
| ext2: control image; 2^64-1 byte file; 4 GiB directory; rec_len 0xFFFF on create and on remove; looping indirect blocks; `/f/`; no aliasing of a freed inode; free counts above totals; superblock free count 0; remove with a failing block free | kernel stopped at the first crafted case (run 4) | 11 of 11 |
| ring-3 divide error, trap flag, `icebp`, non-canonical stack (#SS), unmasked SSE exception (#XM) end the process; kernel runs on | kernel stopped at the first (run 5) | 6 of 6 |
| GetRandom into the caller's read-only text is refused | kernel stopped (run 6) | pass: exit `0xFFFFFFFD` (InvalidArgument) |
| kernel stack overflow stops the kernel with a double fault | pass, but not for the right reason (below) | pass: `DOUBLE FAULT` |

The destructive `kstack-overflow` check does not discriminate. On negctl the process stack sat 136 KiB above
the start of the heap; the recursion (about 190 KiB in the debug build) wrote through every heap object below
it and faulted only when it left the heap, which also ends in a double fault. On the final image it faults
at the first byte below the 32 KiB stack. The non-destructive `kstack-guard` check (`below_stack_mapped`) is
the one that tells the two apart, and it fails on negctl. The harness keeps the destructive check as a
regression test of the fault path (the guard must lead to a double fault on the IST stack, not a hang or a
triple fault).

On image A the same harness showed the round's other fixes passing; its failures were two harness defects
(a field read before its last value; exit code 139 expected where the kernel records 137), corrected before
the final runs, and the exception self-test, which A did not contain.

### Every harness on F and on the final image

| Harness | expected | baseline (round 2 / joint round 2) | F (`c3ea0149…`) | final (`438ee579…`) |
|---|---|---|---|---|
| verify_kernel_k3 (new) | 48 | not run (self-tests absent) | 48/48 | 48/48 |
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
| verify_net | 5 | 5/5 | 5/5 | first run 0/1, rerun 5/5 (then 5/5, 5/5) |
| verify_user_pointer_isolation | 4 | 4/4 | 4/4 | 4/4 |
| verify_scheduler_stubs | 7 | 7/7 | 7/7 | 7/7 |
| verify_current_pid | 6 | 6/6 | 6/6 | 6/6 |
| verify_audio_nonblocking | 7 | 7/7 | 7/7 | 7/7 |

On F every harness passed on its first run. On the final image every harness passed on its first run except
`verify_net`, whose first run failed: the guest's serial log stops after `HDA: output path configured` and the
harness's fixed 90 s boot limit (it does not read `FERRUMOS_BOOT_SECONDS`) ran out, at a moment the host had
2.0 GB of free memory. In passing boots of every image this round, F included, the next HDA verb takes about
36.9 G TSC cycles (`HDA: slow verb nid=4 verb=0x20011`), a pre-existing wait in the HDA driver that leaves
little of the 90 s on a loaded host. The rerun passed 5/5, and two further runs passed 5/5. The baseline
column is the result recorded for `8d21d68` when this round was set up; those were not rerun here.

Two harnesses failed on image A and led to the last kernel change: `verify_ipc_isolation` 2/3 and
`verify_authority_gate_joint` 29/33 (both twice), both from the first version of finding 7 (see there). init's IPC test
(`userland/init/src/main.rs`, test mode 8) asserted that one sender gets all 16 slots of a mailbox; it now
asserts 12, the unflagged share.

### Host tests

| Suite | before (`8d21d68`) | after |
|---|---|---|
| userland/heliox-gate-tests | 70 | 78 (`tests/http.rs`: 8 new) |
| userland/physical-runtime | 175 | 175 |
| userland/neural-protocol | 19 | 19 |
| scripts/authority_matcher_adversarial.py | 19/19 | 19/19 |
| heliox-daemon `cargo check --target x86_64-pc-windows-gnu` | builds | builds |

Negative control for the HTTP tests: the `8d21d68` decoder and parser compiled into a scratch test (not
committed) on the new tests' inputs. A chunk size of `usize::MAX - 18` panics in the debug build
(`chunk_end + 2` overflows) and in the release build (the wrapped bound passes and the slice index panics);
a body shorter than its Content-Length is returned as complete (`Ok("hello")` for `Content-Length: 9`); a
40 KiB response cut at 32 KiB is returned as a 32,749-byte body.

## Defects fixed, by severity

Line numbers of the defect refer to `8d21d68`.

### High

**1. Ring 3 controls the direction flag the kernel runs with.** `src/interrupts/mod.rs:352-388` and
`:777-813`, the naked timer and syscall entry stubs. The SysV ABI requires DF = 0 at every call; an interrupt
gate does not clear it, and neither stub executed `cld`. A ring-3 process that runs `std` and then makes any
syscall (or is interrupted by the timer) runs the kernel's Rust code with DF = 1, so every `memcpy`/`memset`
the compiler emits as `rep movs`/`rep stos` copies downwards from its destination over whatever lies below,
typically the kernel stack. On negctl a process looping `std; mov eax, 31 (GetPid); int 0x80` made the kernel
jump to `0x15` in ring 0. The handlers declared `extern "x86-interrupt"` get a `cld` from LLVM; only the two
naked stubs lacked it. Fix: `cld` in both stubs before the call (user DF is restored by `iretq`). Self-test
`df-entry` counts entries with DF set and checks a 256-byte `memcpy` during each syscall.

**2. A ring-3 divide by zero (and five other exceptions) stopped the kernel.** `interrupts/mod.rs:57-107`.
The IDT had gates only for #BP, #DF, #PF, #GP, #UD and #OF. Delivering any other exception through a
not-present gate raises #NP, whose gate was missing too, so the CPU escalated to a double fault, which
panics. Any process could halt the system with `div` by zero, a set trap flag, `icebp`, a push through a
non-canonical stack pointer (#SS) or an unmasked SSE exception (#XM, CR4.OSXMMEXCPT is set). Fix: gates for
#DE, #DB, NMI, #BR, #NM, #TS, #NP, #SS, #MF, #AC, #XM (a ring-3 fault ends the process, a ring-0 one stops
the kernel) and #MC; a spurious-IRQ7 handler that EOIs only when IRQ 7 is in service; and the PIC lines with no
handler masked at init (`lib.rs:177`), since an interrupt on one of them would arrive at a missing gate the
same way. Self-test `user-exceptions` (five ring-3 programs).

**3. Allocation in the timer interrupt against a heap lock taken with interrupts enabled.**
`src/memory/heap.rs:38` (`LockedHeap`, a spin lock that does not disable interrupts) and
`src/scheduler/mod.rs:706` (`tick` collects the pids to wake in a fresh `Vec` on every tick that wakes a
task; `run_queues.push_back` may grow too). Kernel tasks (shell, desktop, dashboard) allocate with interrupts
enabled. A timer interrupt that arrives while such a task is inside `alloc`/`dealloc`, on a tick that wakes a
sleeper, spins on the heap lock with interrupts off on the only CPU: the kernel hangs. With a background app
sleeping 30 ms at a time and the desktop drawing, this is a matter of time. Fix: the global allocator takes
the heap lock inside `without_interrupts` (`IrqSafeHeap`), and `tick` wakes sleepers in place without a
`Vec`. Self-test `irq-alloc` (2 s of allocation with interrupts on while a parked task is woken every tick):
negctl hangs, final survives 2 million allocations and 1,990 wakes.

**4. Keyboard and input queues locked with interrupts enabled.** `interrupts/mod.rs:534` (`read_keyboard`,
polled in a tight loop by the shell and the dashboard), `:578` (`poll_ps2_keyboard`, called from the desktop
loop), `src/input/mod.rs:214-215, 281-282, 299-300, 336, 357, 366, 385-386, 398, 414, 419` (event queues).
The keyboard and mouse interrupts take the same spin locks. A key pressed while the shell held
`KEYBOARD_QUEUE`, or while the desktop's PS/2 poll or a USB HID report held `EVENT_QUEUE`, spun in the
interrupt handler for good. `poll_ps2_keyboard` also read port 0x60 after checking the status register with
interrupts on, so the IRQ handler could take the byte in between and the poll would read it again (a doubled
key). Fix: every non-interrupt path to these queues runs with interrupts disabled; the PS/2 poll runs whole
with interrupts disabled. Self-test `kbd-lock` with 40 keys typed by the harness: negctl hangs.

**5. The kernel wrote to user memory it had only checked was mapped.** `src/syscall/fs.rs:58-79`
(`valid_user_range`, `copy_to_user`) and `src/process/mod.rs:321-349`, `:522`. ELF text and read-only data
are recorded user mappings, so a syscall given a pointer into the caller's own code passed validation, and
the kernel's write was a ring-0 protection fault, which (since round 2) stops the kernel. Reachable with no
capability (LaunchContext with a context, IpcReceive) and with common ones (ReadFile with `fs:read`,
GetRandom, PollInput, Recv). `IpcReceiveFrom` also dequeued the message before the write faulted. Fix:
`process::user_range_is_writable` walks the process's page tables for PRESENT|USER|WRITABLE;
`copy_to_user` and every output check before a side effect (22 call sites in 14 files) use it. Self-test `user-write-ro`.

**6. Kernel stacks without a guard.** `process/mod.rs:958-966`: each process's 32 KiB kernel stack (where its
syscalls, page faults and timer interrupts run) was a box on the kernel heap; an overflow wrote silently into
the heap object below. Fix: `src/memory/kstack.rs`, a stack region in the heap's P4 slot (P4[136], whose P3
table every address space shares), 64 KiB slots with the top 32 KiB mapped no-execute and the lower 32 KiB
never mapped. An overflow faults on the guard and, since the CPU cannot push the fault frame there, raises a
double fault on its IST stack. Freeing unmaps and returns the frames. Self-tests `kstack-guard` and
`kstack-overflow` (destructive: 160 levels of 512-byte frames on a process stack; final: `DOUBLE FAULT`).

**7. IPC mailboxes followed the name, not the process.** `src/ipc/mod.rs:297-324`. Ownership was
recomputed on every call as the first live task with the name (then the first process record), so a second
instance of a program (Exec of `/bin/heliox-daemon` by a holder of `process:spawn`, a second AppLaunch of the
panel) became the owner when the first died and received every message queued for the first, including the
operator's CONFIRM, DENY or NEURAL_DISARM. Fix: a mailbox is bound to the pid that gets a scheduler task under
the name while the mailbox is free (`claim_mailbox`, called from `scheduler::register_user`); a process that
registered while a live owner existed never owns it; a dead owner's mailbox stays closed until a new process
registers; each message carries the pid it was queued for (`target_pid`) and only that pid receives it
(`receive_for_owner`); reaping a pid drops its claim and its queued messages. Messages queued before any
process ran under the name (for a boot image registered but never dispatched) pass to the first owner. The
first version claimed at `process::register`; the never-dispatched boot image of the daemon (pid 3) then held
the claim and the daemon that init starts (pid 4) never received, which `verify_ipc_isolation` and
`verify_authority_gate_joint` caught on image B. Self-test `ipc-mailbox`.

**8. ext2 on a crafted disk: kernel aborts, a heap overwrite and a hang.** `src/fs/ext2.rs`:
- `:707` an inode's 64-bit size went to `Vec::with_capacity` (a regular file with `dir_acl` = 0xFFFFFFFF:
  capacity overflow panic on negctl; a directory claiming 4 GiB: a failed 4 GiB allocation aborts), on any
  path lookup through that directory. Fix: whole-inode reads are refused above 16 MiB and reserved fallibly.
- `:1063-1077` `add_dir_entry` split the last entry of a block using its on-disk `rec_len` and `name_len`
  unchecked: with `name_len` 255 and `rec_len` 0xFFFF at offset 1016 the new entry was written 256 bytes past
  the 1 KiB block buffer (a heap overwrite), then a slice panicked. `:1173` merging on remove added two
  `rec_len` in u16 (0xFFFF overflowed). Fix: `dir_entry_fits` (record holds header and name, 4-byte aligned,
  inside the block) on every entry the driver parses, edits or merges; the split also checks room.
- `:1021-1030`, `:1135-1201` the directory block walks ran until a zero pointer, ignoring the size: indirect
  blocks pointing at themselves gave about 16.8 million iterations (and a block list that exhausts the heap).
  `:653` the triple-indirect limit overflowed u32 for blocks of 8 KiB and more. Fix: walks are bounded by the
  directory's size; block-map arithmetic is u64; block size is capped at 4 KiB (`:269`; a 64 KiB block also
  stored `rec_len` 0 for a new directory block).
- `:898`, `:967`, `:935-936`, `:998-999`, `:1606-1610` free-count arithmetic underflowed or overflowed on
  counts the disk supplies (also reachable from SystemQuery's usage). Fix: saturating arithmetic, free counts
  above the totals rejected at mount, and a block bitmap that marks blocks past the end free is refused
  instead of handing out a block outside the filesystem.
- `:1645-1658` `split_path` accepted an empty last component: removing `/disk/f/` (a regular file `f` whose
  data holds an entry with `name_len` 0) parsed f's data as directory entries, freed f's inode and blocks, and
  left `/disk/f` pointing at the freed inode; the next file created took it (`f_now_aliases_new_file` in the
  self-test). Fix: empty names refused; `add_dir_entry` and `remove_dir_entry` require a directory.
Self-test `ext2-r3` (11 crafted or control images on an in-memory disk).

### Medium

**9. Operator messages could be crowded out.** `ipc/mod.rs:256-261`: 16 messages per service and 256 in
the broker, first come; any holder of `ipc:send:*` could fill the daemon's mailbox so that `heliox deny` or
`heliox neural disarm` from the kernel shell failed with QueueFull. Fix: unflagged messages may take 12 of
16 slots per mailbox and 240 of 256 in the broker; messages the kernel marks as the operator's
(`SENDER_KERNEL_SHELL`, `SENDER_ASSISTANT_PANEL`) may use all. Self-test `ipc-mailbox`; init's ring-3 IPC test
now expects 12.

**10. RamFS could exhaust the kernel heap and the kernel stack.** `src/fs/mod.rs:190-215`, `:603-616`. Any
holder of `fs:write` (the daemon and two apps) could write 4 MiB files until an infallible allocation
elsewhere in the kernel failed (an abort), and a 4,096-byte path makes a tree about 2,000 levels deep, which
`accumulate_usage` (SystemQuery) and the recursive drop on remove walked one stack frame per level. Fix: 4 MiB
of file data and 2,048 nodes in RamFS, 32 path components, iterative teardown and usage walk; names with
control characters refused (a newline forged ReadDir lines). Self-test `ramfs-limits`.

**11. ext2 `remove` could fail after unlinking and before the parent's version moved.** `ext2.rs:1543-1563`:
the entry was removed, then blocks and the inode were freed with `?`, and only then the parent's version
bumped; an I/O error or a block outside the groups returned with the name gone and the version a
version-bound approval relies on unchanged. Fix: the parent's version moves right after the unlink; freeing
is best effort (a failure leaks blocks and is logged); `links_count` and `used_dirs_count` saturate.
`create_file_bytes` now checks the 12-block limit before allocating (it allocated and wrote every block
first, `:1355`), writes the inode before freeing the old blocks (`:1394-1405`: a failed write left the file
pointing at freed blocks with its version unchanged) and frees only direct blocks as data (it freed
indirect pointer blocks as data). Self-test `ext2-r3` (`remove_error`).

**12. User stack without a guard gap.** `process/mod.rs:561` and `load_elf`: an mmap region could end exactly
at the stack's base, and an ELF segment could sit right below it, so a stack overflow wrote into them. Fix:
64 KiB below the stack are reserved for neither. A stack overflow ends the process (killed, 137). Self-test
`user-stack`.

**13. Daemon HTTP client.** `userland/heliox-daemon/src/network.rs:900-901`: `chunk_end + 2` overflowed, so one
chunked response from any server the daemon talks to (a provider endpoint, or plain HTTP) crashed the daemon
(panic = abort). `:653`, `:740`, `:850`, `:1133`: responses were read into 32 KiB and silently cut, and the
cut response parsed as complete; a body shorter than its Content-Length was accepted. Fix: framing moved to a
syscall-free module `http_parse.rs`: checked chunk arithmetic with a terminal chunk required, a 1 MiB
response limit that is an explicit error, Content-Length enforced (truncation an error, conflicting values
refused), an HTTP/1.x status line with a three-digit code, UTF-8 checked on the body only; reading stops
once a declared length has arrived. TLS: an error after data counts as end of stream, and the framing checks
then refuse a truncated body. While reading the rest of the file: `ws_recv_frame` (`:1402`) allocated a
64-bit length from the frame header (one frame from a client of the bridge port aborted the daemon; now at
most 1 MiB), and answered pings by recursing (`:1438`; now a loop with at most 64 pings per receive).
Redirects are not followed (a 3xx is returned to the caller). Host tests `tests/http.rs`.

### Low

**14. `RecordAudio` allocated up to 4 MiB infallibly** (`src/syscall/audio.rs:227`), and started DMA first.
Fix: fallible allocation before the device is started.

**15. `allocate_simd_buffer` wrote through a null pointer on heap exhaustion** (`scheduler/mod.rs:435`).
Fix: return 0; the switch path already skips FXSAVE/FXRSTOR for 0. Not testable without exhausting the heap.

**16. RTL8139 reused a TX descriptor without checking OWN** (`src/net/rtl8139.rs:227-238`). Fix: wait up to
100,000 reads of TSD for OWN (bit 13), else refuse the send and count it (`TX_BUSY_DROPS`). QEMU completes TX
synchronously, so this cannot be provoked here; `verify_net` and `verify_net_k2` pass.

**17. Stale safepoint marker** (`interrupts/mod.rs:482-493`). When the timer switched away from a kernel task
parked at its safepoint, `CURRENT_KERNEL_TASK_PID` stayed set until that task ran again. Today a later timer
tick that interrupts ring-0 code (only `sys_write_console` enables interrupts inside a syscall) ignores it
because the task is not Running, so this is not exploitable now; the marker is cleared on the switch.

**18. The bootloader's stack and boot-information pages were executable.** Both live in P4[2], read-write.
Fix: `memory::harden_boot_regions` sets NO_EXECUTE on the P4 entry holding the boot stack and on the one
holding the boot information, unless it also holds the kernel image, the heap or the user slot; called right
after the heap is mapped, before any address space copies the kernel's P4. Self-test `boot-nx`.

## Performance

Timer interrupt cost with and without the master 8259's auto-EOI mode, measured on one image (`c3ea0149…`,
which boots with the normal EOI) so that nothing else differs: per boot, 20 s idle at the prompt, counters
reset, 20 s idle with the normal EOI write, `test-syscall perf`; then `pic-aeoi-on`, reset, 20 s idle, `perf`.
Five boots (`kernel_round3_tools/bench_aeoi.sh` with round 1's `probe.mjs`). TSC cycles per timer interrupt,
averaged over about 14,300 interrupts per window; host CPU load sampled after each boot.

| Boot | host load % | normal EOI | auto-EOI |
|---|---|---|---|
| 1 | 16 | 61,610 | 42,130 |
| 2 | 9 | 56,889 | 37,539 |
| 3 | 4 | 66,056 | 34,852 |
| 4 | 34 | 60,581 | 32,559 |
| 5 | 91 | 75,352 | 96,464 |
| median | | 61,610 | 37,539 |
| range | | 18,463 | 63,905 |

The median moved by 24,071 cycles (39 %), more than the baseline's spread (18,463), so by the round's rule
the change is kept: the image built from the head boots with auto-EOI on (`lib.rs`, `set_pic_auto_eoi(true)`;
`test-syscall pic-aeoi-off` switches back). In four of five boots auto-EOI was lower by 19,000 to 31,000
cycles, about what round 2 measured for the EOI write itself; in boot 5 the host was at 91 % load and the
auto-EOI window was the slower one, which is what widens its range. The other handlers still send their EOI;
on the master it is a no-op in this mode (no in-service bit is ever set), and the slave (mouse, ATA) stays in
normal mode. The spurious-IRQ7 handler reads the in-service register, so it never sends an EOI in this mode.

Confirmation on the final image (`438ee579…`, which boots in auto-EOI mode), three boots, the same
protocol with the order reversed (20 s with the default, then `pic-aeoi-off`, reset, 20 s): auto-EOI 45,607,
42,421 and 44,171 cycles; normal EOI 64,143, 61,117 and 72,845 (host load 71, 14 and 27 %). One further
single-window boot of the final image measured 98,469 cycles in auto-EOI mode with every other counter also
two to three times its usual value (`tick` 21,080 cycles, frame allocation 54,081), consistent with a loaded
host rather than with the mode. `timer_eoi_avg_cycles` is 0 on the final image: the timer no longer writes an
EOI.

These figures are lower than round 2's 114,801 because round 2 averaged from boot (boot work included) and
this round resets the counters after 20 s at the prompt. Boot to prompt in the benchmark boots was 39.4, 39.9,
39.5, 39.4 and 39.0 s; the host was quieter than during round 2's measurement, so no boot-time comparison is
claimed.

What the fixes cost: the heap lock now runs `cli`/`sti` around every allocation and free (tens of cycles
against heap operations of thousands; not isolated by a measurement), and `tick` no longer allocates. No
safety check was removed or weakened for speed.

## Audited and found sound

- **Syscall entry and exit.** `int 0x80` uses an interrupt gate (IF cleared) with DPL 3; the CPU switches to
  TSS.RSP0, which `resume_task` sets for every task; the stub saves all 15 GPRs and the iretq frame, and the
  saved RFLAGS (with the user's IF, DF, TF) is restored by `iretq`. No preemption happens inside a syscall:
  the timer preempts only ring 3 and kernel tasks at their safepoints; the one handler that enables
  interrupts (`sys_write_console`, `syscall/mod.rs:911`) holds no lock while it prints, and a timer tick there
  cannot preempt it (finding 17).
- **FPU and SIMD state.** The kernel is built for `x86_64-unknown-none` (soft-float, no SSE), so kernel code
  never touches x87/SSE registers; `save_user_context` does FXSAVE on every switch away from a ring-3 task and
  `context_switch_to` FXRSTOR on every switch in. Segment bases: FSGSBASE is not enabled and there is no
  `swapgs`, so ring 3 cannot change FS/GS bases (they are 0 for every selector it can load).
- **Exit, kill and reap against a running, sleeping or blocked task.** On one CPU with syscalls running with
  interrupts off, a task is never killed while it executes kernel code; a task killed while Blocked (sleep,
  waitpid, confirmation) is removed from the run queues and `tick` wakes only Blocked tasks; the dying task's
  kernel stack is never freed while in use (exit and quota kills switch away through `resume_after_death`;
  waitpid's fast path defers the child to `DEFERRED_REAPS`; every reaper runs on another task's stack or the
  return stack). With guarded stacks a violation of this would now fault instead of silently reusing freed
  heap memory; all nineteen harnesses, which kill, exit and reap processes, pass.
- **Locks taken in interrupt context.** Timer: `SCHEDULER.try_lock` in `tick`, PICS, the heap (finding 3).
  Keyboard and mouse: the input queues (finding 4), `SCHEDULER.try_lock` for confirmation keys, serial output
  with `try_lock` when interrupts are off. ATA: PICS only. The network receive path is polled (IMR = 0) from
  syscall and kernel-task context, never from an interrupt. Every other path that takes PICS does so with
  interrupts disabled.
- User pointers: zero length, `ptr + len` overflow and the user-region bounds are checked before any
  dereference; processes are single-threaded and there is no munmap, so a range cannot change between check
  and use.
- `read_user_str` / `read_user_bytes` cap lengths before validating and copy fallibly; per-handler caps hold
  (IpcSend 4096, WriteFile/ReadFile 4 MiB, Recv/Send 1 MiB, PollInput 256 events, Kexec 4 KiB).
- PointerTarget (66) and IpcReceiveFrom (61) validate their 24- and 16-byte records before any side effect
  (now as writable memory); FileVersion (62) and the expected-version calls (63 to 65) check and act inside one
  `without_interrupts` section.
- Socket descriptors are owner-checked on every call and closed on reap; the audio capture slot is released
  for dead owners.
- ext2 directory listing: `rec_len` 0 stops the parse; names are bounded by the data; `read_file_offset`
  slicing is bounded; `free_inode` checks its range; `read_inode` is safe given round 2's superblock checks.
- RamFS: `split_path` refuses empty names, a write never replaces a directory, versions cover the subtree.
- The daemon's DNS parser (round 2) and the TLS buffers: `embedded-tls` reads records of at most 16,640
  bytes (16 KiB of payload plus overhead) into a 16,640-byte buffer, which is its documented size.

## Not tested and why

- The TX OWN check (finding 16): QEMU completes transmission synchronously; argued from the code.
- The `allocate_simd_buffer` null check (finding 15): needs heap exhaustion at task creation.
- #NM, #TS, #NP, #BR, #MF and #AC from ring 3 were not raised by a test (the gates share the handler of the
  five that were); #AC needs CR0.AM, which the kernel leaves clear; NMI and #MC cannot be raised from ring 3.
- The doubled PS/2 key (finding 4) was not provoked; the hang was.
- ext2 fixes were tested on in-memory images; no real `heliox-disk.img` exists on this machine. The control
  image (create, read, remove) passes.
- The daemon's HTTP client was tested on the host with the parsing module; no live provider or chunked server
  was driven from QEMU. The WebSocket changes were exercised by `verify_authority_gate_*` (the bridge), not by
  a hostile frame.
- The kstack guard on the static stacks (shell, desktop, dashboard, idle, return, double-fault IST): not done,
  see below.

## Found and not fixed

- **AVX state is not saved.** `enable_sse_extensions` turns on AVX in XCR0, but switches save and restore
  only the FXSAVE area: the upper halves of the YMM registers pass from one process to the next. No shipped
  program uses AVX (the daemon is built with `+sse,+sse2`), so today this is a covert channel between two
  processes that both use AVX, not a leak of anyone's data. Fix: XSAVE/XRSTOR with a 64-byte-aligned area of
  the size CPUID leaf 0xD reports, or leave AVX off in XCR0.
- **Static stacks without a guard:** the shell, desktop and dashboard kernel tasks, the idle and return
  stacks and the double-fault IST stack are arrays in `.bss`. They run kernel code only. A guard needs a
  page-aligned unmapped page below each.
- The kernel's DeleteFile confirmation prompt does not name the path (`syscall/mod.rs:325-338`); the daemon
  binds its own approvals to path and version, other callers do not.
- ExecIfVersion checks the VFS file for names that execute the embedded ELF (`syscall/process.rs:141`); any
  `fs:write` holder can make it fail for those names.
- ext2 allocators do not refuse bitmap bits that map to metadata blocks or reserved inodes (disk corruption,
  not kernel memory); `remove` ignores `links_count` (hard links) and leaks indirect blocks; overwrite of a file
  with indirect blocks leaks its tail.
- Kexec (`cap:system:kexec` only): `map_to(...).unwrap()` and an unreserved destination frame.
- Package binaries run through Exec are all named `bin` and so share one mailbox name; with finding 7 only the
  first to get a scheduler task owns it.
- `sys_read_dir` builds the whole listing before truncating to the caller's buffer.

## Edits outside this round's areas

| File | Edit | Why |
|---|---|---|
| `userland/init/src/main.rs` | IPC test mode 8 expects 12 accepted messages | it asserted the old 16-slot behaviour that finding 9 changes |
| `userland/heliox-gate-tests/src/lib.rs`, `tests/http.rs` | compiles `http_parse.rs` from the daemon's source; 8 tests | the host test crate for syscall-free daemon modules |
| `README.md`, `docs/ARCHITECTURE.md` | IPC ownership and quota, kernel and user stack guards, RamFS limits | statements made false by findings 6, 7, 9, 10, 12 |
| `src/shell/selftest_k2.rs`, `src/shell/mod.rs` | unknown names fall through to `selftest_k3::run` | wiring |

Run tools: `kernel_round3_tools/` (`h.sh` one harness under the lock, `suite.sh` a list with one rerun on
failure, `bench_aeoi.sh` the timer benchmark, `negctl.py` the script that built the negative control,
`ed.py` its helper). Paths in them are this machine's.

CI runs used: 6 (43189963256, 43190864541, 43190989931, 43192738780, 43199460468 for the auto-EOI default, and one for the final edit of this report, which changes no code).

## What remains

- The items under "Found and not fixed": AVX state, guards for the static kernel stacks, the DeleteFile prompt,
  ExecIfVersion for embedded names, ext2 allocator trust in bitmaps and `links_count`, Kexec's unwrap.
- Round 2's policy items and joint round 2's Q-J2a to Q-J2d are untouched.

A fourth round would most likely find defects of medium severity: ext2 write paths beyond the cases built
here (indirect blocks, hard links, a disk whose bitmaps lie), more resource accounting (heap use per process
outside RamFS: windows, sockets, IPC payloads are bounded per object but not per process in total), and
corners of the daemon's network code that host tests cannot reach. High-severity defects of the kinds this
round found (a user-controlled CPU state or exception the kernel did not expect, a lock shared with an
interrupt handler) are less likely now that every exception has a gate, both entry stubs clear DF, and every
lock the interrupt handlers take was checked; the remaining candidates are the AVX state above and whatever a
future SMP bring-up adds (every "one CPU, interrupts off" argument in this report assumes one CPU).
