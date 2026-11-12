# fi1 kernel round 2

Branch `improve/fi1-kernel2`, draft pull request 6, stacked on pull request 5 (which contains pull requests 2
and 3). Plan: `docs/research/ferrumos_improvement_fi1_plan.md`; round 1: `kernel_round1.md`. The kernel builds
only in CI. Every image below is a CI artifact (`bootimage-ferrumos`) booted here in QEMU 11.1 with WHPX,
4096 MiB, one harness at a time under the shared lock, `FERRUMOS_BOOT_SECONDS=600`. Before each push the
kernel was type-checked on the host from a scratch copy (stable GNU toolchain, `RUSTC_BOOTSTRAP=1`, target
`x86_64-unknown-none`, empty placeholder ELFs, the registry `x86_64` 0.14/0.15 crates patched with the two
`Step` methods newer `core` requires; nothing of that is in the repository).

| Image | CI run | Commit | sha256 | size |
|---|---|---|---|---|
| baseline (pull request 5 head) | 43162924989 | `47e97e0` | `e3f39abf1968315f3efcf09df0bbf21668f5927f92819df36b6d1d6d96c6fcc7` | 10,058,240 |
| negctl | 43169792903 | `9a87a05` | `b3f8c530e43e56d5faff4f605754dba934faf681466eff1af8b6aeff90ef536f` | 10,146,816 |
| final-1 | 43169208919 (and 43169857060, byte-identical) | `d170541` / `a8eccc1` | `31ec001a31e35101518868586085046aae267de9a079b1542a411f49c9652995` | 6,362,624 |
| final | 43171416531 | `382f613` | `87a1bd5b0fbd6e9db66f57dafcb820d2d4765b7344803af41cb311c368c43579` | 6,363,648 |

negctl is this branch's self-tests, harnesses and cycle counters with every round-2 fix (and the static-image
change) held back: `9a87a05` restores the pre-fix sources of the ten touched files and adds only the stubs the
self-tests need to compile; `a8eccc1` reverts it (its tree equals `d170541`, and CI produced the same bytes).
`final` differs from final-1 only by the runt-frame correction (finding 1d below) and a finer timer meter.

## Harness results

Commands: `FERRUMOS_BOOT_SECONDS=600 node scripts/<harness>.mjs`, image copied to
`target/x86_64-unknown-none/debug/bootimage-ferrumos.bin`, one at a time under the lock. A failing run would
have been rerun once; on the final image every harness passed on its first attempt.

### New harnesses

| Harness | baseline | negctl | final |
|---|---|---|---|
| verify_kernel_selftests_k2 | not run: the self-tests do not exist there | see below | 37/37 (final-1, without the runt check: 36/36) |
| verify_net_k2 | not run (same) | 3/7: kernel panic on the first oversized frame | 12/12 (final-1: 11/11, before the rx_resets check) |

negctl, `verify_kernel_selftests_k2`. The ext2 self-tests stop that kernel, so the harness was run five times
with `FERRUMOS_SKIP_SELFTESTS` growing by the self-test that had halted the previous run:

| Run | skipped | result | where it stopped |
|---|---|---|---|
| 1 | none | 12/30 | `ext2-shift`: no prompt after the mount (shift overflow at `ext2.rs:261`) |
| 2 | ext2-shift | 12/30 | `ext2-groups`: `panicked at src\fs\ext2.rs:267:29: attempt to add with overflow` |
| 3 | + ext2-groups | 12/30 | `ext2-inode-size`: `panicked at src\fs\ext2.rs:454:58` (slice past the block) |
| 4 | + ext2-inode-size | 12/31 | `ext2-gdt`: `panicked at src\fs\ext2.rs:449:28` (block arithmetic overflow); `ext2-bpg` mounted (fail) |
| 5 | + ext2-gdt | 13/33 | ran to the end |

In every negctl run the same checks fail: user data and stack executable, heap and physical alias executable;
an unprivileged creator gets an unlimited daemon (`unprivileged_child_pages=unlimited`); 24 of 24 children
created; one mmap fault mapped 64 pages against a quota of 4; 24 sockets for one process; port 65,536 + 7781
bound (truncated to 7781); a second process bound a listening port; a 60,004-byte length delivered as 60,000
bytes, a header without ROK left in place (stall), a CRC-error header delivered; `kernel.security` stopped by a
process with no capability; the task name kept its quote; the spinning ring-3 process ran 30 s and was never
charged a tick (`max_charged_ticks=0`); the ring-0 fault was reported as `Userspace process ... caused Page
Fault ... CS=... rpl: Ring0, terminating.` and the kernel went on. Checks that pass on negctl too: NXE on,
code pages executable, no user-accessible kernel P4 entry, the kernel's own unlimited daemon, port 0 refused by
connect (smoltcp refuses it itself), the first bind, a well-formed ext2 image mounts, `cap:system:all` restarts
a service.

negctl, `verify_net_k2`: the guest answered ICMP before the corpus, then the first oversized frame stopped
the kernel: `panicked at src\net\rtl8139.rs:229:28: attempt to add with overflow` (the u16 ring index plus the
60,004-byte length taken from the header). One frame from the network halts the old kernel. The guest's serial
shows no fault from the 23 malformed frames sent before it.

### The harnesses that must keep passing (final image, sha256 `87a1bd5b…c43579`)

| Harness | expected | baseline (round 1 / joint round) | final |
|---|---|---|---|
| verify_ring3 | 7 | 7/7 | 7/7 |
| verify_mmap | 7 | 7/7 | 7/7 |
| verify_audio_nonblocking | 7 | 7/7 | 7/7 |
| verify_current_pid | 6 | 6/6 | 6/6 |
| verify_app_window | 13 | 13/13 | 13/13 |
| verify_core_apps | 24 | 24/24 | 24/24 |
| verify_scheduler_stubs | 7 | 7/7 | 7/7 |
| verify_user_pointer_isolation | 4 | 4/4 | 4/4 |
| verify_ipc_isolation | 6 | 6/6 | 6/6 |
| verify_kernel_selftests | 18 | 18/18 | 18/18 |
| verify_process_reap_cr3 | 9 | 9/9 | 9/9 |
| verify_pid_reuse | 6 | 6/6 | 6/6 |
| verify_authority_gate_joint | 24 | 24/24 | 24/24 |
| verify_net | 5 | 5/5 (run here on the baseline image) | 5/5 |

The baseline column for the first thirteen is the result recorded for pull request 5's head (CI run
43162924989) when this round was set up; they were not rerun here on that image. verify_net was run here on
it (sha256 `e3f39abf…6fcc7`).

## Defects fixed, by severity

Line numbers of the defect refer to the baseline (`47e97e0`); "fix" names the function on this branch.

### High

**1. The RTL8139 receive path: a frame from the wire overruns the receive buffer by DMA, and the driver
trusts the device's length field.** `src/net/rtl8139.rs:83-114` (setup) and `:190-222` (`receive_packet`).
(a) The driver programs an 8 KiB ring with WRAP set (RCR `0x8F|0x80`) in a 12 KiB buffer. With WRAP the
device writes a frame that runs past the ring's end linearly after it, and QEMU's ring-mode receive checks a
frame's size only against the free space of a non-empty ring (`avail != 0 && RX_ALIGN(size + 8) >= avail`):
a frame that arrives at an empty ring is written whole, whatever its size (QEMU's net layer passes up to
4096 + 65536 bytes). One 60,000-byte frame therefore writes about 57 KiB of attacker data into the physical
frames after the buffer, whoever owns them. (b) The driver then copies `length - 4` bytes from the ring, with
`length` straight from the header (up to 65,535), reading past the buffer through the physical-memory alias
and handing the result to smoltcp; with a 60,004-byte length the u16 ring index overflows and the debug kernel
stops (`attempt to add with overflow`, seen on negctl), so one frame from the network halts the old kernel. (c) A header without the ROK bit made `receive_packet` return `None`
without advancing, so reception stopped for good. (d) Fix: one contiguous block of 20 frames (ring + slack for
the largest frame QEMU writes) plus the four TX buffers; `classify_rx_header` (`:99`) bounds every length before
use: a good header with a length outside 18..=1522 is consumed and skipped, a header without ROK, with an error
bit or with a length below 4 resets the receiver (`reset_and_start`, `:200`) instead of stalling. A first
version also reset on good headers for runt frames; `verify_net_k2` found it (QEMU reports a 10-byte frame as
length 14), and `382f613` skips those instead. Harnesses: `verify_net_k2.mjs` (four oversized frames of 9000,
60000, 1600 and 60000 bytes; the driver must drop them and nothing over 1518 bytes may reach the stack) and the
`rx-header` self-test.

**2. TX and RX DMA addresses were truncated to 32 bits.** `rtl8139.rs:108` (RBSTART) and `:181` (TSAD). TX
buffers were allocated lazily at the first send from the general allocator, which returns recycled frames
first; with a 4 GiB guest some of RAM is above 4 GiB, and a frame there made the device read a different
physical page and send its contents on the wire. Fix: all DMA memory comes from one fresh contiguous block at
init, checked to end below 4 GiB. Not reachable by a harness (needs the allocator to hand out a frame above
4 GiB before the first send); argued from the code.

**3. Faults taken in ring 0 were treated as the current process's fault.** `src/interrupts/mod.rs:184-225`
(`handle_userspace_fault`). The handler checked only `CURRENT_PID != 0`, so a kernel bug during a syscall
(page fault, #GP, #UD in kernel code) killed the calling process, hid the corruption and resumed the scheduler,
possibly with locks the faulting code held. Fix: only a fault whose saved CS has RPL 3 is a user fault; a
ring-0 fault prints `[KERNEL] <fault> in ring 0 (current pid N): stopping the kernel` and halts. Demand paging
of mmap regions is unchanged. Self-test `ring0-fault` (destructive, last in `verify_kernel_selftests_k2.mjs`).

**4. No NX anywhere it mattered.** EFER.NXE was already on (the bootloader sets it), but no page the kernel
mapped had NO_EXECUTE: user data, bss and stack (`src/process/mod.rs:292` `pt_flags`, `:225` stack, `:664`
mmap pages), the 12 MiB kernel heap (`src/memory/heap.rs:69`) and the bootloader's read-write alias of all
physical memory (P4[3]), so data written anywhere in RAM could be executed through that alias. Fix: NO_EXECUTE
on non-PF_X segments, the stack and mmap pages (a page shared by a code and a data segment stays executable);
on heap pages; and on the alias's P4 entry (`memory::harden_kernel_mappings`, called once after the heap is
mapped and before any address space copies the kernel's P4). `ensure_nxe` sets NXE if it is ever clear. Nothing
executes from the alias: the kernel runs at its link address in P4[0], kexec jumps through an identity page
there, and the AP trampoline is copied but never started. Self-test `nx-flags`.

**5. Any process with `process:spawn` could create an unlimited-memory process, and mmap ignored the page
quota.** `process/mod.rs:884-914` (`create`/`register`): the quota exemption followed the program name alone,
so Exec of `/bin/heliox-daemon` by any spawner gave a child with `max_memory_pages = u64::MAX` although the
child gets only the capabilities the caller can delegate; `register` re-derived the exemption by name.
`:1200` (`fault_in_page`): demand paging of mmap regions never compared against `max_memory_pages`, so a
non-exempt process could map a large file and fault in any number of frames (the 2048-page quota applied only
to ELF segments and the stack). Fix: `quota_exempt_for` needs the creator to hold `cap:quota:exempt` or
`cap:system:all` (the kernel, pid 0, launches the boot services); `register` keeps what `create` decided;
`fault_in_limited` caps each batch at the remaining quota. Self-tests `quota-exempt`, `mmap-quota`.

### Medium

**6. The continuous-CPU quota was never enforced.** `scheduler/mod.rs:1684` (`check_and_enforce_quotas`) had
no caller, and the counter it checks was reset on every preemption (`yield_current`, `:876`), so it could not
pass one time slice anyway. Fix: the timer charges a tick only when it interrupts ring 3
(`charge_user_tick`), every syscall entry restarts the count (`note_syscall_entry`, lock-free), preemption no
longer resets it, and a non-exempt task that runs 5.5 s of ring 3 without a syscall is ended with exit code 140.
Holders of `cap:system:all` (init) keep no continuous-CPU limit, since init runs long ring-3 compute self-tests.
Self-test `cpu-quota` starts a real ring-3 process that spins on `jmp $`.

**7. Listen-port hijack and port truncation.** `net/iface.rs:182-199` (`socket_bind`), `:155`
(`socket_connect`). A second `net:listen` holder could bind a port another process listened on; smoltcp gives
an incoming SYN to the first listening socket in its set, so a lower slot received the daemon's next client.
Ports were cast with `as u16` (65,616 became 80). Fix: ports must be 1..=65535; bind is refused when a socket
of another process listens on or is connected from that port (the same process may hold several listeners).
Self-test `socket-limits`.

**8. A half-open handshake held a listener for good.** smoltcp keeps one connection per socket and has no
SYN-RECEIVED timeout (`set_timeout` is unset and covers only connect and data in flight), so one SYN from an
address that never answers left the daemon's listener (port 8785) in SYN-RECEIVED, and every later client got
a reset. Fix: `expire_half_open` (run on every `iface::poll`) returns a listener that has been half-open for
3 s to LISTEN. Harness `verify_net_k2.mjs` (a SYN it never completes, then after 5 s a SYN from another port).

**9. Resource limits.** One process could take all 64 socket descriptors (`iface.rs:41`), and nothing bounded
the number of processes created through Exec, AppLaunch or PackageLaunch (32 KiB kernel stack each on the
12 MiB heap). Fix: 16 sockets per process; at most 64 process records and 16 live children per non-root
process (`process_limit_allows`). Socket buffers (32 KiB per socket) and the mmap fault-in scratch buffer (up
to 256 KiB, in the page-fault handler) are now allocated fallibly; an infallible allocation that fails aborts
the kernel. Self-tests `socket-limits`, `process-limit`.

**10. ServiceStart/ServiceStop/restart had no effective capability check.** `services/mod.rs:262-276`. The only
check was the service's own `required_capabilities`, empty for every core service, so a process with no
capability could mark `kernel.security` stopped in the operator's service table (the state is display-only
today; nothing enforces policy from it). Fix: kernel-layer services need `cap:system:all`; a runtime service
without its own requirement needs `cap:service:register`. Effect on the daemon: its `service_start` and
`service_stop` tools now return PermissionDenied (it holds neither), so world-model collections made with this
kernel record a denial for those tools where they used to record success. Self-test `service-lifecycle`.

**11. ext2 mount trusted the superblock and group descriptors.** `fs/ext2.rs:261-291`. A crafted image stopped
the kernel: `1024 << log_block_size` overflowed (log 40), `inodes_count + inodes_per_group - 1` overflowed
(`:267`), an inode size of 200 sliced past the block buffer on the first inode read (`:454`), a group
descriptor's inode table near 2^32 overflowed the block arithmetic (`:449`), a huge group count asked the heap
for gigabytes, and `blocks_per_group == 0` divided by zero on the first block free. Fix: `validate_superblock`
(block size 1..64 KiB and a multiple of the sector size, non-zero counts, per-group counts within one bitmap
block, first data block 0 or 1, inode size a power of two between 128 and the block size, group count
consistent with blocks and inodes and at most 8192, filesystem within the device, descriptor table inside the
filesystem) and `validate_group_descriptor` (bitmaps and the whole inode table inside the filesystem). Self-tests
`ext2-valid`, `ext2-shift`, `ext2-groups`, `ext2-inode-size`, `ext2-bpg`, `ext2-gdt` on an in-memory disk.

### Low

**12. Task names reached JSON unescaped.** `syscall/query.rs:107` formats task names into SystemQuery's process
list; a task name is the last component of the Exec path, chosen by the caller, so a file named
`x","pid":1,"name":"init` forged fields in the daemon's view of the process table. Fix inside this round's
area: `scheduler::sanitize_task_name` (in `register_user`) keeps printable ASCII other than `"` and `\`,
replaces the rest with `_` and caps the length at 64, so every JSON producer is safe; query.rs is unchanged.
Self-test `task-name`.

**13. The legacy syscall path trusted a ring-3 caller.** `interrupts/mod.rs:982`: with `CURRENT_PID == 0` the
handler takes Linux-numbered calls whose SYS_WRITE copies from an unchecked pointer. Ring-3 code always runs
with its pid set, so this is defence in depth: the path now refuses a caller whose CS has RPL 3.

**14. The RTL8139 enabled interrupts it never handles.** `rtl8139.rs:111` wrote IMR = ROK|TOK for a polled
driver with no IRQ handler. Now IMR = 0.

**15. Boot image carried each embedded program two or three times.** `src/userspace/mod.rs:14-42` declared the
embedded userland ELFs as `pub const X: &[u8] = include_bytes!(..)`; a const is instantiated at each use, and the
debug image held the daemon (690 KB) three times and most apps twice. As `static` they are stored once: the
image shrank from 10,058,240 to 6,362,624 bytes. Boot timing is under Performance.

## Performance

Measured with round 1's `kernel_round1_tools/probe.mjs` (QEMU with the HDA device, as the harnesses; wall time
from QEMU start to the first serial line and to the first shell prompt), baseline and final alternating, five
boots each, then 20 s idle at the prompt and `test-syscall perf` (final only; the counters do not exist on the
baseline). Host CPU load during the runs: 44 to 100 %.

| Image | boot to prompt, s (five runs) | median | range | to first serial line, s | median | range |
|---|---|---|---|---|---|---|
| baseline | 56.6, 53.9, 51.4, 50.6, 56.9 | 53.9 | 6.3 | 34.8, 32.1, 30.5, 29.8, 35.9 | 32.1 | 6.1 |
| final | 50.0, 48.2, 46.7, 46.5, 47.0 | 47.0 | 3.5 | 28.1, 26.7, 25.8, 25.3, 26.0 | 26.0 | 2.8 |

The median boot moved by 6.9 s, a little more than the baseline's spread (6.3 s), and almost all of it (6.1 s)
is before the kernel prints its first line, where the BIOS bootloader reads the image: the image shrank by
3.7 MB (finding 15). The change passes the round's rule narrowly; with this host's load the margin is small.

Where kernel time goes at idle (final image, TSC cycles averaged over about 16,000 timer interrupts per run,
five runs):

| Counter | runs | median |
|---|---|---|
| whole timer interrupt (returns only) | 118,833; 107,330; 111,730; 137,746; 114,801 | 114,801 |
| `scheduler::tick` | 14,338; 12,021; 12,422; 20,370; 12,674 | 12,674 |
| PIC end-of-interrupt (one port write) | 55,595; 49,379; 50,635; 61,450; 52,568 | 52,568 |
| frame allocation (2000 frames, includes zeroing) | 57,916 and similar | about 50,000 |
| frame free | about 3,300 | |

At 1000 Hz that is about 115,000 cycles per millisecond, a few percent of one vCPU at idle; under WHPX with
`kernel-irqchip=off` the PIC lives in QEMU's user process, so the EOI write alone is nearly half of each tick,
and the rest is the interrupt's entry and exit. `tick` itself (about 12,700 cycles in the unoptimised debug
build) is a tenth. No change was made to the timer path: the candidate (auto-EOI mode on the 8259, which removes
the EOI write from every interrupt) changes interrupt behaviour for every device, and this round's CI budget did
not leave room to build and measure it against the five-run rule. The syscall counter stays at zero in these
runs because no ring-3 process runs at an idle shell; the compositor's idle redraw is in `src/gui` (the other
workstream's) and was not measured. No safety check was removed or weakened for speed.

## What was audited and found sound

- smoltcp 0.11 parses every packet (Ethernet, ARP, IPv4, ICMP, UDP, TCP). The kernel enables neither IPv4
  fragmentation (fragments are dropped) nor DHCP/DNS sockets; DNS is a daemon TCP client. `verify_net_k2`
  sends 23 malformed frames (runt Ethernet, ARP with hlen 255 and truncated, IHL 2 and 15, total length above
  the frame and below the header, bad header checksum, first and last fragments, version nibble 6, broadcast
  source, 3-byte ICMP, UDP length 65535 and 3, TCP data offset 15 and 2, MSS option length 0, option length past
  the header, window scale 255, SYN+FIN+RST+URG, stray ACK at sequence 2^32-1); the guest answers ICMP echo
  before and after, and nothing faults.
- TX path: smoltcp asks for at most MTU + 14 bytes; `send_packet` refuses more than 1518.
- Socket ownership checks (`lookup_fd`), close and reap paths, lock order IFACE -> SOCKETS -> FD_TABLE ->
  DEVICE -> NIC (the new half-open sweep runs inside `poll` with SOCKETS then FD_TABLE, the same order as close).
- No kernel P4 entry other than the user slot (P4[1]) has USER_ACCESSIBLE (`nx-flags` walks all 512 entries).
  P4[2], next to the user slot and shared with the kernel, cannot receive user mappings since round 1's span fix;
  `map_user_range` refuses a span past `USER_REGION_END`, and `find_free_vaddr` keeps mmap regions below the
  stack.
- The daemon's DNS response parser (`userland/heliox-daemon/src/network.rs:478-546`) bounds every name, label
  and record length.
- Window limit (4 per process, pull request 1) and IPC queue quotas (per service and broker-wide) are in place.

## Found and not fixed (other owner or out of scope)

- **Daemon HTTP client, chunked decoding** (`userland/heliox-daemon/src/network.rs:900-901`, workstream D's
  area): `chunk_end` is computed with `checked_add`, but `chunk_end + 2` is not; a chunk size of
  `usize::MAX - offset` makes `chunk_end == usize::MAX`, `chunk_end + 2` wraps to 1 in the release build, the
  bounds test passes and `&encoded[usize::MAX..1]` panics: any HTTP server the daemon talks to (plain HTTP, or a
  provider endpoint) can crash the daemon with one response. Fix: `chunk_end.checked_add(2)`.
- **Daemon HTTP client, response size** (`network.rs:738-751`): the response buffer is 32 KiB; a longer
  response is silently truncated and parsed (no Content-Length check), and a UTF-8 sequence split at the cut
  makes the whole response fail.
- **IPC mailbox ownership** (`src/ipc/mod.rs:297`, other owner): the mailbox goes to the first live task whose
  name matches. Pull request 5 stops a VFS file from taking a compiled-in name, but a second instance of an
  embedded program (Exec of `/bin/heliox-daemon` by a holder of `process:spawn`, AppLaunch of the panel twice)
  shares the name, and the mailbox passes to it when the first instance dies. Mailboxes should be bound to a pid
  at registration.
- **ext2 inode size field** (`fs/ext2.rs` `read_inode_data_inner`, other owner): a crafted inode's 64-bit size
  goes to `Vec::with_capacity` and aborts the kernel (capacity overflow or heap exhaustion); bound it by the
  blocks the inode can address and allocate fallibly.
- `scheduler::allocate_simd_buffer` writes through the pointer without a null check; on heap exhaustion that is
  a ring-0 page fault at address 0, which now stops the kernel with a message rather than corrupting it.
- RTL8139 `send_packet` reuses a TX descriptor without checking its OWN bit (QEMU completes TX synchronously, so
  this cannot be observed here).
- Service lifecycle state is still display-only; nothing enforces policy from it.

## Edits outside this round's areas

| File | Edit | Why it could not be done elsewhere |
|---|---|---|
| `src/process/mod.rs` | `pt_flags`, `map_user_stack`, `map_user_range` (NX union for shared pages), `fault_in` / `fault_in_limited` / `fault_in_page` (NX, quota, fallible scratch), `create` / `register` (exemption, limits, `parent` field) | NX and the page quota live where pages are mapped; quota and limit code is this round's area wherever it lives. Exec itself (`syscall/process.rs`) is untouched. |
| `src/userspace/mod.rs` | `pub const` -> `pub static` for the 12 embedded ELFs | image size; no behaviour change |
| `src/shell/mod.rs` | `pub mod selftest_k2;` | wiring for the new self-test file |
| `src/shell/selftest.rs` | unknown names fall through to `selftest_k2::run` | wiring (one line) |
| `scripts/lib/qemu_shell_k2.mjs` | new file, a copy of `qemu_shell.mjs` whose `bootShell` takes the QEMU network arguments | so the shared library does not change |

Run tools and raw results: `kernel_round2_tools/` (`h.sh` runs one harness under the lock, `suite.sh` the
list with one rerun on failure, `bench.sh` the boot benchmark; `summary.tsv` and `bench.tsv` are the final
image's results). The paths in them are this machine's.

No syscall numbers were added; `src/syscall`, `src/ipc`, `src/gui`, `src/input`, `src/heliox` and `userland/`
are unchanged.

## Not tested and why

- DMA truncation (finding 2): needs the allocator to hand the driver a frame above 4 GiB; argued from the code.
- Ring-0 #GP and #UD use the same classification as the page fault the self-test triggers; only the page fault
  was run.
- The continuous-CPU quota and NX were tested on processes the self-tests build from tiny ELFs; no shipped
  program spins without syscalls or executes its data, so a regression there would show in the thirteen
  harnesses above, all of which pass.
- The legacy-syscall refusal (finding 13) is not reachable without a kernel bug that runs ring-3 code with no
  current pid.
- The half-open reset and the receive path were tested with the self-test's listener; the daemon's own
  listener (port 8785) was not driven over the datagram network.
- ext2 validation was tested on in-memory images; the harness images boot without an ext2 disk, and no real
  `heliox-disk.img` exists on this machine to confirm that a well-formed disk built by `build.ps1` still mounts
  (the positive control is a hand-built image; `mke2fs` images satisfy every check by construction).
- The world-model collection pipeline was not rerun; finding 10 changes what it records for `service_start` and
  `service_stop`.

## What remains

- The four items in "Found and not fixed" for other owners (daemon chunked-decoding panic, 32 KiB response
  truncation, IPC mailbox bound to a name rather than a pid, ext2 inode size).
- Timer interrupt cost under WHPX (auto-EOI, or the local APIC timer once SMP is real), measured as above.
- `allocate_simd_buffer` null check; TX OWN-bit check.
- Kernel stacks of user processes live on the shared kernel heap with no guard page: a kernel stack overflow in
  a syscall writes into the next heap object. A guard page needs stacks mapped outside the heap.
- The bootloader's kernel stack and boot-info pages are still executable (they are in other P4 entries than the
  alias).

A third round is likely to find more defects of medium severity (resource accounting and lifecycle corners,
like findings 5 to 9) and possibly one or two of high severity in code this round read only in passing:
interrupt and context-switch paths under concurrency (lock-held faults, the timer preempting kernel tasks), the
kernel stack without a guard page, and `src/syscall`, `src/ipc` and `src/fs` outside ext2 mount, which belong to
the other workstream and were not audited here. The network receive path and the memory-protection basics are
now covered by run-time harnesses with a negative control.
