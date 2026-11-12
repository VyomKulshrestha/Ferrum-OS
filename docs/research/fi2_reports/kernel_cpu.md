# fi2 kernel workstream K1: CPU protections, the prompt, the heap ledger, ext2, x87

Branch `improve/fi2-kernel-cpu`, draft pull request 7, started from `1efd7a6` (the head of pull request 6, merged
into main as `c80f7dd`); main was merged in once more at `49998ed` (documentation only). Plan:
`docs/research/ferrumos_followups_fi2_plan.md` (section K1 and "Yardstick"); method as in
`docs/research/fi1_reports/kernel_round4.md`.

Every image is a CI artifact (`bootimage-ferrumos`), booted in QEMU 11.1 under WHPX (`kernel-irqchip=off`, 4096
MiB), one harness at a time under `C:/Users/marcu/Videos/fi1-qemu.lock`, `FERRUMOS_BOOT_SECONDS=600`. Before each
push the kernel was type-checked on the host from a scratch copy and its library built with code generation (round
4's method; this assembles the new `stac`, `clac` and naked probe code), and the three host test suites were run
from the push of item 4 on (the push of item 4 itself missed a host test; see "Images").

The usual harness CPU, `-cpu Haswell`, has SMEP and no SMAP. `-cpu Broadwell-noTSX` boots under WHPX on this host
(Intel Core i7-13700HX) and exposes SMAP to the guest (QEMU warns only about `tsc-deadline` and `arat`); the kernel's
boot line reads `smep=true smap=true (cpuid smep=true smap=true)` there. The TCG fallback was not needed. All
harnesses now take the CPU model from `FERRUMOS_QEMU_CPU` (default Haswell), and `verify_kernel_k5` boots both.

| Image | CI run | Commit | sha256 | size |
|---|---|---|---|---|
| baseline (pull request 6 head) | (round 4, H) | `1efd7a6` | `c9ab1985f15c2c837e50369cee10c09fff071215f6a5a347767afd30248ca054` | 6,857,728 |
| items 1 and 2 | 43241625248 | `dbf2b79` | `d52a9ae811dca8281e6a8559b2e495f9257b157f785bc4c6752b57b643f36e45` | 6,907,904 |
| item 3 | 43243213183 | `1e93c21` | `034312cd1e88d6cc4f12828966a4a3643c91a425a034f29ca1e09864bc49c3ba` | 6,959,616 |
| item 4 | 43244564996, 43245353945 | `1bfa62f`, `e7a62c4` | none: CI failed (host test `j2_1` reads the RamFS insert as one line) | |
| item 4 | 43246778345 | `54691a2` | `49e5b3c7ce3f974883c257fa6401befaffcc9338b4cf6f528b48221d8eb33855` | 7,056,384 |
| item 5 | 43247986968 | `b6782c3` | `ae93fe1b96c5787eea3bc8786fb8ded34b3d285bb4dcd4c660b6218a1aa940a4` | 7,299,072 |
| item 6, item 5 follow-up | 43249248979, 43250897359 | `7d380a3`, `f527498` | built, not booted (superseded) | |
| merge of main | 43250999251 | `49998ed` | `4ff4bf83b657b7100ad362eb9c794a9626b25786812f85eea8d3d04c9fdef3cc` | 7,302,656 |
| final code | 43255890415 | `c55216a` | `db45b4d2ae6d3c676cfa887854c9c6d7437bbac7b48493d0197b5e32c4e5fcc4` | 7,302,656 |
| final head (final code + this report) | the run of that commit | (this commit) | expected identical to `c55216a`'s (report only; checked after the push, see the pull request) | |

All negative controls are runtime switches in the same image (`*-off` self-tests), except item 6, whose control is
the baseline image (its switch does not restore the old behaviour; see item 6). Image `49998ed` ran
`verify_kernel_k5` at 49 of 52: the three failures were controls whose test design was wrong (the CR0.NE switch, and
two crafted-disk controls whose writes ran after the filler was removed, so they never reached group 1); `c55216a`
fixed the tests only. Earlier images ran the parts of `verify_kernel_k5` they contained: items 1 and 2, 21 of 21;
item 3, 12 of 13 (the wrap case padded 100 spaces, too few for the framebuffer console's columns; fixed in the test);
items 3 and 4, 17 of 17; item 5, boots C and D at 15 of 17 (e2fsck found defect 6 of item 5, and the crafted
disk's filler was all zeros, which `mke2fs -d` stores as holes; both fixed in `f527498`).

## Harness results

### The new harness, `verify_kernel_k5.mjs` (self-tests in `src/shell/selftest_k5.rs`), on the final image

Four boots: A (`-cpu Haswell`), B (`-cpu Broadwell-noTSX`), C and D (Haswell, two ext2 disks from mke2fs; D with the
ext2 fixes switched off). Each fix check is paired with its control in the same boot.

| Check group | fix | control |
|---|---|---|
| boot reaches the prompt (A, B) | pass (2) | |
| boot A: SMEP on, SMAP off (no CPUID bit) | pass | |
| SMEP (A and B): ring-0 call into a user page faults, error 0x11 | pass (2) | switch off: call runs (2) |
| SMAP absent (A): unbracketed read succeeds | pass | |
| syscall sweep, 15 paths (A without SMAP, B with SMAP) | pass (2) | brackets off (B): ring-0 page fault at `0x800000007d` |
| boot B: SMEP and SMAP on | pass | |
| SMAP (B): unbracketed read faults (0x1), write faults, bracketed read works, AC clear | pass (4) | switch off: read and write succeed |
| AC from ring 3 (B) | pass | entry clearing off: kernel runs with AC set, read succeeds |
| console forgery, serial and screen (A) | pass (3) | marking off: 5 serial lines, 3 screen rows start with the tag |
| UART by `out` (A) | pass (exit 137) | IOPL 3: unmarked prompt on the UART, exit 0 |
| heap ledger (A): refusal, charges, release at reap | pass (3) | enforcement off: 4,257,862 bytes held, nothing refused |
| x87 #MF (A): exit 136, next process exit 2 | pass (2) | baseline image: no #MF, exit 137 (item 6) |
| disks built by mke2fs, clean disk passes e2fsck first | pass | |
| ext2 real disks (C): mount and reads, links, overwrite, growing directory, removes, e2fsck clean, cross-link, backup metadata, indirect free | pass (9) | fixes off (D): 6 control checks show the old damage |
| no kernel fault (A, B, C, D) | pass (4) | |
| total | 51/51 | |


### The twenty-one fi1 harnesses on the final image (`db45b4d2...`)

| Harness | expected | `-cpu Haswell` (SMAP off) | `-cpu Broadwell-noTSX` (SMAP on) |
|---|---|---|---|
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
| total | 315 | 315/315 | 315/315 |

Every harness passed on its first run in both columns. The second column is the SMAP sweep of item 2: every
syscall the shipped programs and the earlier self-tests make ran with SMAP on and no ring-0 fault.

### Host tests (final code)

| Suite | before (`1efd7a6`) | after |
|---|---|---|
| userland/heliox-gate-tests | 78 | 78 |
| userland/physical-runtime | 175 | 175 |
| userland/neural-protocol | 19 | 19 |

`python scripts/generate_public_evidence.py --check`, `verify_public_json_schemas.py` and
`verify_repository_discovery.py` pass. Both workflows (CI, Public Evidence Reproduction) are green on `c55216a`.


## Items

### 1. SMEP (CR4 bit 20)

Defect: CR4 bit 20 was never set, so a kernel bug that jumped to a user address ran user-controlled code in ring 0.

Fix: `cpu_protect::enable` (`src/cpu_protect.rs:62`) reads CPUID.(7,0).EBX (after checking that leaf 7 exists) and
sets SMEP where bit 7 is set; `src/lib.rs` calls it in `init` after the vector-state setup and prints `[  OK  ] CPU
protections: smep=... smap=... (cpuid smep=... smap=...)`. The kernel never executes a user page on purpose (ring 3 is
entered only through `iretq`), so nothing else changes.

Test (`test-syscall smep`): a self-test maps one page with the user bit at every level in an unused P4 slot of the
active table (index 300, address `0xffff960000000000`), with interrupts off, writes `ret` into it, and calls it
through a fault probe. The probe (`probe_call_raw`, `src/cpu_protect.rs:182`) records the recovery point and stack
pointer; the page-fault handler, for a ring-0 fault while a probe is armed, resumes there instead of stopping the
kernel (`probe_fixup`, line 225). The page and its three table frames are freed after the test.

Negative control (runtime switch `smep-off`, same image): with SMEP on, the call faults with error code `0x11`
(present, instruction fetch) at the page's address; switched off, the same call returns normally
(`kernel_call_faulted=false`). Same result under Haswell and Broadwell-noTSX.

### 2. SMAP (CR4 bit 21) and every intended user access bracketed

Defect: CR4 bit 21 was never set, so a kernel bug that followed a user pointer read or wrote user memory unnoticed.
A second defect appears once SMAP is on: ring 3 controls RFLAGS.AC (`popfq`), and neither an interrupt gate nor
`int 0x80` clears it, so a process that sets AC before a syscall would switch SMAP off for the whole syscall.

Fix:
- SMAP is set where CPUID.(7,0).EBX bit 20 is set (`cpu_protect::enable`).
- One choke point: every syscall copy to or from user memory already went through three functions in
  `src/syscall/fs.rs` (`read_user_str`, `read_user_bytes`, `copy_to_user`); a search of `src/` for raw pointer
  accesses found no other kernel access to user memory in the ring-3 syscall paths (the legacy Linux-numbered path in
  `syscall_entry_inner` serves ring-0 callers only and refuses ring 3). `read_user_str` and `read_user_bytes` now
  share `copy_from_user` (line 39), which reserves the kernel buffer first and then copies inside a
  `cpu_protect::UserAccess` window (`stac` on creation, `clac` on drop, executed only while SMAP is on, since both
  are #UD without it); `copy_to_user` (line 91) brackets its copy the same way. No allocation, lock or other call
  happens inside a window.
- `clear_ac_on_entry` (`src/cpu_protect.rs:126`) clears AC (through `pushfq`/`popfq`, valid on any CPU) at the top of
  the syscall and timer entry code and of the 19 other exception and IRQ handlers that ring 3 can reach; `iretq`
  restores the process's own flags.

Tests, under `-cpu Broadwell-noTSX` (boot B of `verify_kernel_k5`):
- `smap`: on the self-test's user page, an unbracketed ring-0 read faults (error `0x1`, present, read), an
  unbracketed write faults, the same read through `UserAccess` succeeds, and AC is clear afterwards. Control
  (`smap-off`, same image): the unbracketed read and write succeed.
- `smap-entry`: a ring-3 process sets AC and makes a syscall; at entry the kernel reads the process's own code
  page without a bracket under the probe. With the fix the kernel runs with AC clear and the read faults
  (`ac_in_kernel=false unbracketed_read_faulted=true`, 2 entries with AC counted). Control (`ac-entry-off`): the
  kernel runs with AC set and the read succeeds.
- `smap-sweep`: a ring-3 process (capability `cap:system:all`) makes 15 syscalls whose paths copy to or from user
  memory (Write, CreateDir, WriteFile, ReadFile, FileVersion, ReadDir, SystemQuery, GetRandom, ClipboardWrite,
  ClipboardRead, NotificationPost, NotificationList, LaunchContext, CreateWindow, AuditWrite); all 15 succeed under
  SMAP. Bracket control (destructive, last): with the brackets switched off (`smap-brackets-off`), the sweep's
  first copy stops the kernel with `[KERNEL] Page Fault in ring 0 (current pid 7)` at address `0x800000007d` (the
  sweep's path string), so a missed bracket shows up as a fault in a test.
- The whole fi1 suite (21 harnesses) also ran under `-cpu Broadwell-noTSX` on the final image (table above): every
  syscall the shipped programs, the authority-gate harnesses and the earlier self-tests make ran under SMAP.

Under Haswell (boot A) the kernel leaves SMAP off (`smap=false`) and the unbracketed read succeeds, as expected.

### 3. A process cannot imitate the `[SECURITY]` prompt

Defect: `sys_write_console` printed process text unmarked (round 1 and round 4 noted it), so a process could print
`[SECURITY] Process 1 is requesting destructive syscall: DeleteFile path="..."` and the operator could not tell it
from the kernel's prompt. Found while fixing it: every ring-3 context was created with RFLAGS `0x3202`, IOPL 3
(`src/scheduler/mod.rs`, `TaskContext::ring3`), so any process could also execute `out` on any port and write the
serial port directly, and use `cli`/`sti`, drive the ATA disk under the filesystem, or reprogram the PIC and PIT.

Mechanism chosen: marking process output, at the one place it enters the console (`src/syscall/console.rs`, the
Write syscall moved there from `src/syscall/mod.rs`), for both the serial port and the screen:
- every console line a process starts begins with `[pid N] `; a write continues the process's previous line
  without the prefix only if nothing else reached the console in between (a sequence number that every print
  increments, `serial::CONSOLE_SEQ`);
- the tag `[SECURITY` never appears in process text (written `[pid-SECURITY`), and a tag split over two writes is
  broken by the prefix inserted between the halves;
- bytes outside printable ASCII are written as `\xNN` (carriage return, backspace and escape could hide or
  overwrite the prefix; non-ASCII bytes could draw a look-alike tag); newline and tab pass.
- IOPL is 0 for every ring-3 context (`0x202`); no shipped program uses port I/O.

Tests (`console-forge`, `port-forge`, boot A): a ring-3 process tries seven forgeries: a plain line, the tag split
over two writes, a carriage return over a decoy, a line of five whole screen rows of spaces followed by the tag (it
wraps to the start of a row), the serial-only descriptor, a tag with a Cyrillic letter, and (separately) the UART
port directly. With the fix, none of the six serial lines that carry a forged path starts with or contains
`[SECURITY` and every one is marked `[pid 5]` (for example `[pid 5] [SECUR[pid 5] ITY] Process 1 ...`); on the
framebuffer console none of the 5 rows that carry a forged path starts with or contains the tag. The `out` attempt
ends the process at its first `out` (#GP, exit 137). Controls on the same image: with marking switched off
(`console-mark-off`), 5 serial lines and 3 screen rows start with the tag; with IOPL 3 restored for new processes
(`iopl3-on`), the process writes an unmarked prompt straight to the UART and exits 0.

### 4. Per-process kernel heap ledger

Defect: each kind of object had its own bound, but nothing capped one process's total. One process could hold three
of the largest windows (5.1 MB of the 6 MiB canvas budget), 4 MiB of RamFS, about 1 MB of IPC payloads and 0.5 MB of
socket buffers: about 10.6 MB of the 12 MiB kernel heap.

Fix (`src/memory/ledger.rs`): a cap of 4 MiB per process (`PROCESS_HEAP_CAP`, line 40) over IPC (payload and envelope
of each message the process sent that is still queued; released when received or dropped), its launch context,
AuditWrite records still in the audit ring (released when the ring drops them), RamFS file contents it wrote
(released when the file is removed or rewritten; files carry an owner), its window canvases and its socket buffers
(the last two read from the compositor and the socket table at each check, so no release site can be missed).
`ledger::fits` (line 94) is called before each allocation and refuses a request that would pass the cap; the
process's entry is dropped when it is reaped (`process::drop_by_pid`, `src/process/mod.rs:1043`). Only the WriteFile
syscalls charge RamFS writes (`ledger::with_fs_owner`), so the kernel's own writes (the audit log flush) are never
charged to whichever process is current. The kernel (pid 0) is not charged.

Test (`heap-ledger`, boot A): a ring-3 process creates two 760 x 560 windows (3,404,800 bytes), sends a 4 KiB message
to its own mailbox, writes an audit record, opens a socket (33,792 bytes), writes two 400 KiB RamFS files, receives
its message and sleeps while the self-test samples the ledger. With the fix the second file is refused (exit
bitmask 64, `failed_calls=WriteFile_b`, one refusal), the sampled total is 3,848,262 bytes and the peak 3,852,526;
after the reap the process has no entry, no window and no socket. Control (`ledger-off`, same image): nothing is
refused and the process holds 4,257,862 bytes, above the cap.

### 5. ext2 on disks made by a real `mke2fs`

The disks are built by `scripts/k5_ext2_images.sh` in a throw-away container (`docker run --rm --name fi2k-mkext2
alpine:3.20`, e2fsprogs 1.47.0): 32 MiB, 1 KiB blocks, `mke2fs -t ext2` defaults (features `ext_attr resize_inode
dir_index filetype sparse_super large_file`, 127 reserved descriptor blocks, inode size 256, four groups, backup
superblocks in groups 1 and 3). `clean.img` is filled with `mke2fs -d` (a 300 KiB file, a hard-linked pair, a
300-entry directory, a small file) and passes `e2fsck -fn` before the kernel touches it. `crafted.img` adds a 6.5 MiB
file and is then damaged with `debugfs`: `xlink` shares its block with `victim`, `evil` points at group 1's backup
superblock (block 8193), the backup superblock, descriptor and 127 reserved descriptor blocks of group 1 (8193 to
8321) are marked free, and the rest of group 0 is marked used. The kernel mounts both on private instances on the
secondary IDE channel (`test-syscall ext2-real`), and `e2fsck -fn` checks the clean disk after the boot.

Defects and fixes (`src/fs/ext2.rs`):
1. Backup superblocks and reserved descriptor blocks were not metadata (round 4 left it open). `is_metadata_block`
   (line 907) now counts, in every group that holds a superblock copy (`group_has_super`, line 52: all groups
   without `sparse_super`, else 0, 1 and powers of 3, 5 and 7), the superblock, the descriptor table and, with
   `resize_inode`, the reserved descriptor blocks. On the crafted disk with the fixes off, 129 blocks of the 40
   files written landed in 8193 to 8321 and the backup superblock's magic read `0x4646` (file bytes); with the fixes,
   none did and the magic is `0xef53`.
2. Metadata and already-free blocks were freed. `free_block` refuses a metadata block or one past the end, and a block
   whose bit is already clear (it was counted free twice). `remove` of `evil` leaves block 8193 allocated.
3. Cross-linked blocks were freed under the other file. `release_inode_blocks` (line 1289) frees a removed or
   overwritten inode's blocks except those another live inode also holds (`blocks_used_elsewhere`, line 1232, scans
   the inodes the bitmaps mark used, at most 16,384; past that, or on an error, it frees nothing and reports it). With
   the fixes off, removing `xlink` freed the shared block and the next file took it (`victim_intact_after=false`);
   with the fixes, the block stays and `victim` reads back unchanged.
4. Indirect blocks leaked on remove and on overwrite (round 4 left it open). `inode_blocks` (line 1145) walks the
   data blocks and the single, double and triple indirect pointer blocks as far as the inode's size reaches (each
   pointer block read once); remove and overwrite free both. Overwriting the 300 KiB file with 5 KiB freed 298 blocks
   (300 data, 3 pointer, 5 new) with the fixes and 7 without; removing the 6.5 MiB file freed 6,683 blocks (6,656
   data, 27 pointer) with the fixes and 6,656 without.
5. Directories were limited to 12 blocks (round 4 left it open). `add_dir_entry` continues through the single
   indirect block, allocated on first use (line 1464); a directory it extends loses the `dir_index` flag, since this
   driver keeps no hashed index. 120 names of 100 bytes made a 14-block directory, every name resolved and 20 were
   removed; with the fixes off, creation stopped at 108 names (12 blocks).
6. A removed inode got deletion time 1 (round 4's remove fix). e2fsck reads a deletion time below the inode count as
   a link in the orphan list, and reported 22 removed inodes as "part of a corrupted orphan linked list" (found by
   this test on the real disk). The deletion time is now the RTC time, at least the inode count (line 2019).
7. Mount accepted any feature bits. A disk with an incompatible feature other than `filetype`, or a read-only
   feature other than `sparse_super` and `large_file` (a journal to replay, extents, 64-bit block numbers, checksums),
   is now refused at mount; writing it with ext2 rules would corrupt it. Not switchable; not tested with such a disk.

Earlier rounds' "not testable: no real disk" items, now run on the real disk: mount-time validation of a real
superblock and descriptor table; reads through single and double indirect blocks (307,200 bytes); a 302-entry
directory listed; removal of one of two hard links (the other reads back); create, overwrite, remove, nested
directory create and remove. After all of it, `e2fsck -fn` exits 0 on the clean disk with the fixes. With the fixes
off (boot D, `ext2-fi2-off` on the same image), e2fsck reports block bitmap differences (`-(670--960)`, the leaked
indirect data), an inode bitmap difference and the orphan-list error.

### 6. CR0.NE and #MF

Defect: CR0.NE was clear (round 4: `cr0_ne=false`), so an unmasked x87 error was reported through the legacy
FERR#/IRQ 13 line, which is masked; the faulting process ran on with the error pending.

Fix: `enable_sse_extensions` sets NE (`src/lib.rs:219`). The #MF handler (`src/interrupts/mod.rs:464`) clears the
pending exception flags (`fnclex`), records exit code 136 (128 + SIGFPE, `EXIT_FLOATING_POINT`, also used for the
SIMD #XM handler) and ends the process; a ring-0 #MF still stops the kernel (it runs no x87 code).

Test (`x87-mf`, boot A): a ring-3 process unmasks the zero-divide exception, divides by zero and executes `fwait`:
one #MF, the process ends with exit 136; the next process adds 1 + 1 on the x87 and exits 2.

Negative control: the image without this item, pull request 6's head (`c9ab1985...`), running the same machine code
(self-test `user-x87`, one boot under Haswell): `cr0_ne=false ended=true exit=137`: no #MF, the process ran on until
`run_until_dead` killed it after 2 s. With the fix, the same program ends at its `fwait` with exit 136. The runtime switch (`cr0-ne-off`, clearing NE on the running kernel) does not bring
the old behaviour back under WHPX: the #MF still arrived (`cr0_ne=false mf_exceptions=1 exit=136`). The cause was not
investigated; the harness reports that result as a note and does not check it.

### 7. Page-table isolation (KPTI): not done

KPTI was not built in this workstream. A partial version would have been worse than none (the brief forbids leaving it half-built), and the work below does not fit next to items 1 to 6 and the final suite. What it needs, in this kernel:

1. Two P4 tables per process (`src/process/mod.rs`, `AddressSpace::new`, line 362). Today each process P4 mirrors every present kernel P4 entry (P4[0], 2, 3, 31, 136 and the kernel-stack region) next to its user slot P4[1]. The user copy must hold P4[1] and only an "entry" P4 slot that maps: the entry and exit stubs (`syscall_entry_stub`, `timer_interrupt_entry_stub`, and new stubs for every exception and IRQ gate), the IDT, the GDT, the TSS, the double-fault IST stack and each process's kernel stack top page (RSP0 must be mapped when the CPU pushes the interrupt frame). The kernel copy stays as today. Because the kernel image sits in P4[0] (bootloader 0.9 maps it low), the entry code, IDT, GDT and TSS must first move into their own section, page-aligned, so that one P4 slot (or one P3 subtree) can carry them without carrying the rest of P4[0].
2. CR3 switch on every entry and exit (`src/interrupts/mod.rs`). The two naked stubs (`timer_interrupt_entry_stub`, line 523, and `syscall_entry_stub`, line 1025) load the kernel CR3 before `call` and the user CR3 before `iretq`. The 23 `extern "x86-interrupt"` handlers cannot do this, since Rust code runs before the first statement: each needs a naked trampoline that switches CR3 and then calls the handler, or the handlers must be converted to naked stubs like the two above. The per-task CR3 pair lives in `scheduler::TaskContext` or a per-CPU slot reached without the kernel mapping (a fixed address in the entry slot).
3. PCID (CR4 bit 17) to keep TLB entries across the switches, with the user and kernel tables on different PCIDs, or a full TLB flush on every entry and exit. Without PCID every syscall and timer tick flushes the TLB.
4. Every place that writes a user page through the kernel's physical-memory alias stays as it is (the alias is in the kernel copy only). `scheduler::context_switch_to` and `resume_task` load the user CR3 last.
5. Tests: a ring-3 read of a kernel address must fault even where the kernel address is mapped today (the user CR3 has no mapping, not only a supervisor bit), checked by walking the user P4 from a self-test and by a ring-3 probe; and the whole fi1 suite plus `verify_kernel_k5` must pass with the switch on.

Until then, kernel memory is mapped (supervisor-only) in every address space, and on a CPU affected by Meltdown (rogue data cache load) a process can read it speculatively. Whether the guest CPU here is affected was not measured.

## Behaviour changes for the owner

- Console output of every process is marked: each line it starts begins with `[pid N] `, `[SECURITY` in its text
  becomes `[pid-SECURITY`, and bytes outside printable ASCII appear as `\xNN` (UTF-8 text from a process is no longer
  shown as characters).
- Processes run with IOPL 0: `in`, `out`, `cli` and `sti` in ring 3 now end the process (#GP, exit 137).
- An x87 or SIMD floating-point exception ends the process with exit 136 (was 137); an unmasked x87 error was
  silently left pending before.
- One process may make the kernel hold at most 4 MiB through windows, RamFS files, queued IPC messages, its launch
  context, audit records and sockets. Past that, CreateWindow returns 0, WriteFile, IpcSend, AuditWrite and Socket
  return an error, and the serial log prints `[ledger] pid N refused ...`.
- ext2 disks with feature bits the driver does not implement are not mounted. Directories on ext2 can grow past 12
  blocks (to 12 + 256 blocks at 1 KiB); a directory the kernel extends loses its hashed index flag. Removing a file
  never frees a block another file uses (a cross-linked block stays allocated; the log says so).
- SMEP is on where the CPU has it; SMAP is on where the CPU has it (not under the usual `-cpu Haswell`).
- Harnesses: `FERRUMOS_QEMU_CPU` selects the WHPX CPU model; `verify_kernel_k5` needs Docker for its ext2 boots.

## What remains

- KPTI (item 7): not done; the design is above.
- The ledger caps one process. Several processes together can still fill the heap within their own caps; the
  per-kind global bounds (canvas budget, RamFS total, IPC broker total) remain the only system-wide limits.
- The console marking covers the Write syscall. Other text a process controls is shown elsewhere (window titles,
  notifications, the assistant panel's chat); the prompt lives on the console only, so these were not changed.
- Between a process write and the kernel's record of the console sequence number there is a short window in which an
  interrupt handler's print could go unnoticed, so the next write of that process would continue the line without a
  prefix. The tag rewriting still applies to that write.
- ext2: files the kernel writes are still limited to 12 blocks (only directories grow through the indirect block);
  backup superblocks and descriptor copies are not updated when the primary changes (e2fsck accepts this); the
  shared-block scan reads every used inode on each remove, which is slow on a large disk and gives up (keeps the
  blocks) past 16,384 inodes.
- The CR0.NE runtime switch does not restore the old behaviour under WHPX (above).
- SMP: unchanged (round 4's list).

## Edits outside this workstream's areas

| File | Edit | Why |
|---|---|---|
| `src/syscall/mod.rs` | Write dispatches to `console::sys_write_console` (moved), AuditWrite calls `audit::log_user_event` | items 3, 4 |
| `src/logging/audit.rs` | `AuditEntry::charged_to`, `log_user_event`, release on eviction | item 4 (the policy workstream also changes this file) |
| `src/fs/mod.rs` | RamFS file nodes carry an owner; ledger checks | item 4 |
| `src/gui/app_window.rs`, `src/net/iface.rs`, `src/ipc/mod.rs`, `src/process/mod.rs` | ledger checks and releases | item 4 |
| `src/graphics/console.rs` | `columns()` | item 3 test |
| `src/vga/mod.rs`, `src/serial.rs` | console sequence number | item 3 |
| 15 fi1 harnesses and `scripts/lib/qemu_shell*.mjs` | CPU model from `FERRUMOS_QEMU_CPU` | item 2 sweep |

Run tools (local, not committed): the host type-check copy and `h.sh`/`suite.sh` as in round 4, with this
worktree's paths.
