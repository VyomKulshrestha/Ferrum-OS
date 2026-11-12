# fi2 kernel audit (workstream K2)

Branch `improve/fi2-kernel-audit`, draft pull request 9, built on draft pull request 8 (gate policy, head
`109031c`), which it contains. Plan: `ferrumos_followups_fi2_plan.md` (section K2 and "Yardstick"); method and
the list of areas no round examined: `docs/research/fi1_reports/kernel_round4.md` ("Never examined").

Method as in fi1. Every image is a CI artifact (`bootimage-ferrumos`), booted in QEMU (WHPX, `-cpu Haswell`,
4096 MiB), one harness at a time under `C:/Users/marcu/Videos/fi1-qemu.lock`, `FERRUMOS_BOOT_SECONDS=600`.
Before every push the kernel library was built on the host with code generation (stable GNU toolchain,
`RUSTC_BOOTSTRAP=1`, target `x86_64-unknown-none`, a scratch copy with placeholder userland ELFs); the kernel
links only in CI. Negative controls: one image with every tested fix held back by
`kernel_audit_tools/negctl.py` (built by CI, then reverted), plus a same-image check where the old
computation can be shown directly (device values).

## What each area contains and how much was read

| Area | Files | Lines | Read |
|---|---|---|---|
| Compositor and desktop input | `src/gui/` (compositor 1,359, desktop 578, window 351, gui/mod 330, cursor 275, app_window 262), `src/input/mod.rs` 477, `src/graphics/` (mod 226, console 344, font 427), `src/clipboard/mod.rs` 69, `src/notification/mod.rs` 108, `src/syscall/{gui_window,input,hud,clipboard,notification,graphics,query}.rs` | about 5,100 | all of compositor, window, app_window, cursor, input, clipboard, notification and the listed syscalls; gui/mod 1-200; desktop 1-80 and 245-300 (layout and drawing below were not read line by line); graphics/mod in full; console and font not read (fixed glyph tables, no external input) |
| Drivers | `src/devices/` (xhci 1,929, hda 1,560, camera_synth 484, virtio_gpu 480, usb_hid 371, vga_fb 343, ps2_mouse 182, mod 155, pci 91), `src/audio/mod.rs` 232, `src/hardware.rs` 70, `src/syscall/{audio,camera}.rs` | about 6,200 | all, by a read-only sub-audit whose findings were checked against the code here; virtio_gpu, hda 735-800, xhci 800-830 and 935-965, vga_fb 180-343 also read here |
| ACPI and AML | `src/acpi/mod.rs` 119; crates `acpi` 4.1.1 and `aml` 0.16.4 | 119 plus crate paths | all of `acpi/mod.rs`; in the `acpi` crate: `from_rsdt`, SDT validation, the MADT iterator and `parse_interrupt_model`, `PlatformInfo`. `aml` is linked by `Cargo.toml:75` and referenced nowhere: no AML is interpreted |
| Packages | `src/pkg/mod.rs` 771, `src/syscall/pkg.rs` 121, the `pkg` shell command, `src/userspace/mod.rs` program table | about 1,100 | all |
| Agent, Heliox, accounts, security, services | `src/agent/mod.rs` 155, `src/heliox/mod.rs` 970, `src/accounts/mod.rs` 129, `src/security/` (mod 349, rand 68, time 140), `src/services/mod.rs` 434, the shell's session, login and useradd commands | about 2,250 | accounts, agent, services and security/mod in full; heliox 1-300 and 750-970 (the method table and the request path; the persona and runtime-slot tables between were skimmed); rand and time not read |
| Logging and the audit flush | `src/logging/{mod,audit}.rs` 252, every `flush_to_disk` caller | 252 | all |
| Bootloader | `Cargo.toml` (`bootloader =0.9.33`, `map_physical_memory`), crate source `build.rs`, `src/main.rs`, `src/page_table.rs` | crate paths | stack, guard page, physical map, NXE |

## Images

| Image | CI run | Commit | sha256 | size |
|---|---|---|---|---|
| baseline (pull request 8 head) | (pull request 8) | `109031c` | `8f9b45ca9ac792e1c6201f34f4b7d85f972ef01eb25f553bd529d5f1fea6348d` | not recorded here |
| A (first candidate) | 43260234763 | `d351d90` | `ec66e8c72b49e0e2dfafa3479bad7358fb5f18b40f8616a38d163a42b5ddec6f` | 7,027,200 |
| negctl 1 | 43260297587 | `d238b90` | `8c95fb11fd4396216fa0bb1aa1cbbe94cdd640184d76fc23211a86b342500048` | 7,019,008 |
| A' (negctl 1 reverted) | 43260429786 | `57b3179` | `ec66e8c7…ddec6f` (identical to A) | 7,027,200 |
| B (A + device-bounds self-test) | 43261494825 | `3476d00` | `5dbfc84726575770d0fb880ee613a22993e0412e20adedce38b7348f0390c3e9` | 7,032,832 |
| negctl 2 | 43264629794 | `46fb23f` | `93807d18a7bc4ab10d25d5e8a971e06341fe12226b7dbf2a51b80ce12b12b836` | 7,023,104 |
| C (final code: negctl 2 reverted, tree equals `d8010a5`) | 43264641280 | `cea5f61` | `0a30642b0911032eb25e4204923965d6324a5db4c195b06a2326417622747470` | 7,031,296 |
| final head (C + this report) | the run of this commit | (this commit) | expected identical to C (reproducible build; only this file changes) | |

`8a0c230` (SystemQuery task-name escaping, later dropped, see "Audited and found sound") was built (run
43260744592) and never run through a harness. `d8010a5` was pushed together with negctl 2 and its revert and got
no CI run of its own; `cea5f61` has the same tree, and its image is the final code's. negctl 1 is `d351d90` with
the fixes held back; negctl 2 is `d8010a5` with the same fixes held back (its `audit-flush` self-test has the
longer marker that makes the control lose it). negctl 1 predates the `device-bounds` self-test; negctl 2 does not hold back its helpers: their
control is the old computation printed beside each result.

## Harness results

### The new harness, `verify_kernel_k6.mjs` (self-tests in `src/shell/selftest_k6.rs`)

Four boots: one with `-device virtio-gpu-pci` for `virtio-backing` alone (on the control the present
overwrites kernel frames: in a first harness version that ran everything in one boot, every later ring-3 start on
negctl 1 failed with `failed to allocate kernel stack`), one for the rest, and one each for `audit-trim-utf8` and
`hda-subnodes`, which stop the kernel without their fix.

| Check | negctl 2 (`93807d18…b836`) | C (`0a30642b…7470`) |
|---|---|---|
| boot with virtio-gpu-pci; device found | pass | pass |
| virtio: backing holds a 1024x768 frame | fail: `backing_bytes=1048576` | pass: `backing_bytes=3145728` |
| virtio: a present writes nothing past the backing | fail: `past_end_pattern_words=1024` | pass: 0 |
| no kernel fault in the virtio boot | pass | pass |
| boot | pass | pass |
| ring 3 with fs:write cannot write `/disk/accounts.txt` | fail: `ok` | pass: `permission_denied` |
| the same through `//disk//accounts.txt` | fail: `ok` | pass |
| ring 3 cannot write `/disk/heliox/audit.log` | fail: `ok` | pass |
| ring 3 cannot delete `/disk/heliox` | fail: `ok`, `heliox_dir_exists=false` | pass, directory kept |
| control: a write to `/tmp` succeeds | pass | pass |
| denied write's path with a line break is one entry | fail: the entry holds a line break | pass: `\x0a` |
| AuditWrite text with a line break is one entry | fail | pass |
| no forged line starts a serial line | fail: `[1] SecurityViolation: forged-path` | pass |
| audit flush past the 12-block file writes the newest entry | fail: `last_flush=ext2: file size exceeds direct block limit (12 blocks) marker_on_disk=false` | pass: `marker_on_disk=true trimmed_flushes=2 final_file_bytes=6395` |
| precondition: the file reached the 12 KiB limit | pass (12,077) | pass (12,087) |
| control: PackageInstall without the claim: no prompt, fails at once | pass (56 ms) | pass |
| self-confirmed PackageInstall gets the operator prompt | fail: no prompt | pass: `PackageInstall name="k6-none" capabilities=<unverified>` |
| the unanswered prompt is a denial | fail: `invalid_argument` after 54 ms | pass: `permission_denied` after 5,009 ms |
| a package entry cannot replace a compiled-in program's capabilities | fail: `capabilities_after=cap:fs:write` | pass |
| verification refuses a compiled-in name, not a free one | fail: `name_taken=false` | pass |
| a notification title cannot start a forged serial line | fail: `[SECURITY] forged-title line` | pass |
| xHCI: 1,023 scratchpads refused (old array: 8,184 bytes in a 4,096-byte page), 4 accepted | pass (helper not held back) | pass |
| virtio: queue 32,768 cut to 256, 64 kept | pass (helper not held back) | pass |
| virtio: capability pointer 0xF8 not followed (old `ptr + 16` overflows u8), 0x40 followed | pass (helper not held back) | pass |
| virtio: BAR 61 refused (old `0x10 + bar * 4` overflows u8), BAR 5 at 0x24 | pass (helper not held back) | pass |
| no kernel fault during the self-tests | pass | pass |
| audit trim inside a two-byte character leaves the kernel running | fail: `panicked at src\logging\audit.rs:293:42` | pass |
| the trimmed log keeps the newest bytes within the cap | fail | pass (131,071 bytes) |
| HDA SUBNODE_COUNT past node 255 leaves the kernel running | fail: `panicked at src\devices\hda.rs:350:12` | pass |
| the node range is cut at 255 | fail | pass (`start=240 end=255 nodes=15`) |
| total | 12/31 | 31/31 |

negctl 1 (`8c95fb11…0048`) ran the earlier harness: 9/33, the same failures, except that `audit-flush`
passed (its short marker still fit into the last free bytes of the 12th block, so the self-test could not
tell the control apart; negctl 2 has the longer marker) and `query-names` (dropped, see "Audited and found
sound") showed no forged entry with escaping off. B (`5dbfc847…c3e9`) ran it: 31/33, the two failures being
the `serial-titles` status format (the post returns the new notification's id, fixed in the harness) and the
`query-names` control.

### Every harness on the final image C

| Harness | expected | C `0a30642b…7470` |
|---|---|---|
| verify_kernel_k6 (new) | 31 | 31/31 |
| verify_gate_policy | 26 | 26/26 |
| verify_kernel_k4 | 39 | 39/39 |
| verify_kernel_k3 | 48 | 48/48 |
| verify_kernel_selftests | 18 | 18/18 |
| verify_kernel_selftests_k2 | 37 | 37/37 |
| verify_net_k2 | 12 | 12/12 |
| verify_authority_gate_joint | 37 | 37/37 |
| verify_authority_gate_self_approval | 11 | 11/11 |
| verify_authority_gate_input_injection | 7 | 7/7 |
| verify_ring3 | 7 | 7/7 |
| verify_mmap | 7 | 7/7 |
| verify_core_apps | 24 | 24/24 |
| verify_app_window | 13 | 13/13 |
| verify_ipc_isolation | 6 | 6/6 |
| verify_process_reap_cr3 | 9 | 9/9 |
| verify_pid_reuse | 6 | 6/6 |
| verify_assistant_panel | 5 | 5/5 |
| verify_net | 5 | 5/5 |
| verify_user_pointer_isolation | 4 | 4/4 |
| verify_scheduler_stubs | 7 | 7/7 |
| verify_current_pid | 6 | 6/6 |
| verify_audio_nonblocking | 7 | 7/7 |
| the twenty-one fi1 harnesses together | 315 | 315/315 |

Every harness passed on its first run on C, one at a time under the shared lock (other sessions' suites
interleaved). `verify_gate_policy` and the fi1 harnesses were not run on the negative controls (they hold back
only this workstream's fixes; their purpose is the new harness).


### Host tests

| Suite | before (`109031c`) | after |
|---|---|---|
| userland/heliox-gate-tests | 99 | 99 |
| userland/physical-runtime | 179 | 179 |
| userland/neural-protocol | 19 | 19 |
| `generate_public_evidence.py --check` and the four public-evidence verifiers | pass | pass |

Both workflows (CI, Public Evidence Reproduction) passed on every pushed commit.


## Defects, by severity

Line numbers of the defect refer to `109031c`.

### High

**1. The virtio-gpu backing was a third of a frame.** `src/devices/virtio_gpu.rs:264` allocated 256 pages (1 MiB)
for the scanout backing ("1024x768x4 fits in ~192 pages": it is 768 pages), `:429` copied every frame
(1024 x 768 x 4 = 3 MiB) into it and `:388` told the device the backing was 3 MiB. With a virtio-gpu-pci device
attached, every desktop frame overwrote the 2 MiB of physical memory after the backing (the next DMA
allocations: the HDA command and buffer rings are allocated right after it at boot), and the host scanned out
that memory as part of the picture. Any process with `hud:overlay` forces a frame through HudUpdate
(`syscall/hud.rs:94-123`). On negctl a present of a one-colour frame left that colour in all 1,024 words
checked just past the backing (`backing_bytes=1048576 past_end_pattern_words=1024`); before the present, 0.
Fix: the backing is `BACKING_BYTES` (one 1024x768 frame, 768 pages), its size is recorded, and `present`
refuses a frame larger than the backing or a pixel buffer shorter than the frame. Self-test `virtio-backing`,
in its own boot with `-device virtio-gpu-pci`: C prints `backing_bytes=3145728 past_end_pattern_words=0`.

**2. Trimming the flushed audit log could stop the kernel.** `src/logging/audit.rs:231-236` cut the log at a
byte offset (`content[overflow..]`, `content[content.len() - MAX_SIZE..]`). A cut inside a multi-byte character
panics. Any process, holding no capability, puts such characters into the log: the path of a denied WriteFile is
logged (`filesystem write denied: <path>`, `syscall/fs.rs:139`), up to 4,096 bytes per call. Where `/disk` is
RamFS (every harness boot) the file reaches the 128 KiB cap, and every trim from then on is a cut at an
attacker-chosen offset. On negctl, `trim_log` on a log of two-byte characters cut at byte 2 stopped the
kernel (`panicked at src\logging\audit.rs:293:42`). Fix: `trim_log` cuts after a line break, or at the next
character boundary. Self-test `audit-trim-utf8` (own boot): C keeps 131,071 bytes (the cut moves to the next character
boundary) ending in the newest byte.

### Medium

**3. Ring 3 could rewrite the audit log and the account table.** `syscall/fs.rs:228` (write, create) and `:341`
(delete) let any `fs:write` holder (the text editor, the assistant panel, the daemon, a package granted
`cap:fs:write`) rewrite or delete `/disk/heliox/audit.log`, and delete `/disk/heliox` (RamFS removes a directory
with its contents). The same holder could rewrite `/disk/accounts.txt`; the shell resolves a logged-in user's
capabilities from that file on every command (`shell/commands.rs:27-36`), so a process could turn the
operator's `user` session into `root` (`cap:system:all`) without the operator. On negctl a ring-3 process with
`fs:write` wrote both files and deleted `/disk/heliox` (`write_accounts=ok write_audit_log=ok delete_audit_dir=ok
heliox_dir_exists=false`). Fix: `KERNEL_RECORD_PATHS` (the two files); WriteFile, WriteFileIfVersion and
CreateDir of either are refused, and DeleteFile of either or of a directory above one (`/disk`,
`/disk/heliox`), with any number of slashes. The kernel's own writers (the audit flush, `useradd`, the shell's
`write`) do not go through the syscalls and are unaffected. Self-test `kernel-records`; the control write
elsewhere succeeds on both images.

**4. A line break in an audit message forged entries.** `logging/audit.rs:100` stored the message as given, and
`:106` printed it to serial; audit.log lines are `[tick] Event: message`. Messages carry text a process chose:
the path of any denied write (no capability needed), AuditWrite text (`audit:write`, the daemon; the daemon's
own escaping, joint round 3 item R3-2, covers only text the model produced). On negctl a denied write of
`/k6\n[1] SecurityViolation: forged-path` put a two-line entry in the ring and a serial line starting
`[1] SecurityViolation: forged-path`; AuditWrite did the same. Fix: `escape_controls` writes control
characters (C0, DEL, C1) and backslash as `\xNN` (`\u{NNNN}` above 0xFF) before the entry is stored or
printed. Self-test `audit-escape`.

**5. Once audit.log passed what the filesystem writes, every later entry was lost.** `logging/audit.rs:206`
marked the new entries flushed before writing, and `:238` returned the write's error. The ext2 driver writes
files of at most 12 direct blocks (12 KiB at 1 KiB blocks, 48 KiB at 4 KiB) under the 128 KiB cap, so on a real
disk the flush that crossed that size failed, and so did every later one: each took its entries out of the
unflushed set and lost them. On negctl, with an ext2 image of 1 KiB blocks, the file grew to 12,077 bytes, the flush of the final marker failed (`ext2: file size exceeds direct block
limit (12 blocks)`) and the marker never reached the file; the file had stopped growing at that size while 81 entries of about 230
bytes each (18.6 KB) were logged. Fix: when the file is
refused, the flush writes the newest half, then the newest quarter, down to 1 KiB, and counts
`FLUSH_TRIMMED` or, failing even that, `FLUSH_FAILURES`. Self-test `audit-flush` (an ext2 RamDisk mounted at
`/k6audit`, `FLUSH_PATH_OVERRIDE` pointing the flush there for the test).

**6. A process confirmed its own privileged package install.** `syscall/pkg.rs:56` passed `args[2] == 1` to
`pkg::install` as "the operator confirmed the privileged capabilities" (`cap:fs:read`, `cap:fs:write`,
`cap:audio:play`). The flag is the App Store's second click on the same button (`userland/app-store/src/main.rs:289-302`),
which an injected click (InjectMouse into an ordinary app window is allowed) can make; any `pkg:request`
holder can also pass it directly. On negctl a ring-3 PackageInstall with the flag set returned at once (54 ms)
with no prompt. Fix: in `dispatch_for_process`, a PackageInstall with `args[2] == 1` from a `pkg:request` holder
is a gated call like DeleteFile: the kernel prints
`[SECURITY] Process N is requesting destructive syscall: PackageInstall name="..." capabilities=...`
(escaped; the capabilities come from the signed manifest, `<unverified>` when it does not verify) and the
operator answers with a physical y or n; no answer in 5 s is a denial; `cap:confirmation:bypass` does not skip
it (as for Kexec). Self-test `pkg-confirm` (prompt, then denial after the timeout) with `pkg-confirm-unclaimed`
(flag 0: no prompt, immediate failure for a missing package) as the same-image control.

### Low

**7. A package named like a compiled-in program replaced that program's capabilities.**
`userspace/mod.rs:319` (`register_dynamic_program`, called by the shell's `pkg run`) overwrote the
capability list of any program with that name. A signed package named `calculator` with `cap:fs:write`, once
run, made the desktop launcher start the compiled-in calculator with `cap:fs:write`. On negctl the entry was
replaced (`capabilities_after=cap:fs:write`). Fix: `register_dynamic_program` refuses (returns false) when the
existing entry has another entry path; `pkg::verify` refuses a package whose name belongs to a compiled-in
program (`name_taken_by_program`), so it can be neither installed nor launched; `pkg run` stops if
registration is refused. Self-test `pkg-name`.

**8. Titles chosen by a process were printed raw in kernel serial lines.** `notification/mod.rs:72`
(`[notification] posted ... title=`), `gui/compositor.rs:827`, `:1107`, `:1253` and
`syscall/hud.rs:206` printed notification and window titles as given; a line break started a forged kernel
line. On negctl a notification titled `k6\n[SECURITY] forged-title line` produced a serial line
`[SECURITY] forged-title line`. Fix: these lines print the title through `escape_printable`. Printable ASCII
titles print as before. Self-test `serial-titles`. (Any process can still write raw text to serial through
the console Write syscall, fd 2; marking that output is the other kernel workstream's console item.)

**9. Device-supplied values** (each is reached only by a device that reports these values; QEMU's report
benign ones, so each is tested by feeding the crafted value to the function that now parses or bounds it,
with the old computation shown on the same value):
- `devices/hda.rs:752`: `start_nid..(start_nid + num_nodes)` in u8 from the codec's SUBNODE_COUNT response
  overflowed past node 255 and stopped the kernel at boot. Fix: `subnode_range` cuts at 255. Self-test
  `hda-subnodes` (own boot): negctl `panicked at src\devices\hda.rs:350:12`; C `end=255 nodes=15`.
- `devices/xhci.rs:811` and `:954`: HCSPARAMS2 allows 1,023 scratchpad buffers; the array listing them is one
  page (512 entries), so entries past 512 were written into the next physical frame (8,184 bytes for 1,023).
  Fix: `scratchpad_count` refuses more than 512 and xHCI init fails cleanly. Self-test `device-bounds`.
- `devices/virtio_gpu.rs:243`: the controlq size the device offers (up to 32,768) indexed an avail ring of one
  page. Fix: `controlq_size` asks for at most 256 and writes it back to the device. `device-bounds`.
- `devices/virtio_gpu.rs:158-163` and `:176`: capability offsets `ptr + 16` and the BAR offset
  `0x10 + bar * 4` were u8 arithmetic on device data and overflowed (stopping the kernel) for a capability
  at 0xF0 or later or a BAR index of 61 or more. Fix: `cap_pointer_usable` (pointer at most 0xEC) and
  `bar_config_offset` (BAR 0 to 5). `device-bounds`.

## Found, not fixed

Device and firmware data (Medium; the device or firmware must misbehave; QEMU's do not, so none could be
tested):
- `devices/xhci.rs:840-845`: DBOFF and RTSOFF are added to the BAR base without the BAR's size, so a controller
  can direct the driver's register writes anywhere in the physical map. Option: probe the BAR size and refuse
  offsets past it. (A bus-master device can already write anywhere by DMA; there is no IOMMU.)
- `devices/ps2_mouse.rs:81` (init flush, interrupts off), `:126` (interrupt handler) and `acpi/mod.rs:110`
  (reboot): loops on 8042 status bits with no bound; on hardware without an 8042 (port reads 0xFF) boot or
  reboot hangs. Option: bound each loop (a few thousand reads) and give up.
- The `acpi` 4.1.1 crate, on firmware tables: a table with `length` below 36 and a valid checksum underflows
  in `from_rsdt`; a MADT entry of length 0 loops forever; SAPIC entries reach `unimplemented!()`; a MADT
  without a boot processor panics on `unwrap`. `acpi/mod.rs:21-36` maps any physical address the tables name
  without a range check. Option: validate the MADT in the kernel before handing it to the crate, or move to a
  newer crate release that returns errors.
- `Cargo.toml:75` links `aml` 0.16.4, which nothing uses. Option: remove the dependency.

Design (observations for the owner, who decides; each with a suggested option):
- New window takes keyboard focus: `gui/app_window.rs:139` focuses every new app window (except the one
  boot-time panel launch). A process holding `gui:window:*` (every GUI app) can open a window while the
  operator types in the terminal window and receive the following keys. Option: give focus to a new window
  only within a short time after a physical click or key, otherwise raise it unfocused.
- Every physical keystroke reaches the `input:read` holder: `input/mod.rs:216` copies each key into
  `DAEMON_EVENT_QUEUE`, including keys typed into other apps' windows and the terminal (the confirmation y/n
  is consumed before it). The holder is the daemon, which also holds `clipboard:read`. Option: deliver keys to
  the daemon only while its own surface (or no window) has focus.
- Terminal-window commands run inside the daemon's syscall in ambient-desktop mode: `syscall/hud.rs:108` runs
  `cursor::process_input`, and Enter in the terminal window runs `shell::commands::execute` there
  (`gui/compositor.rs:1313`) with the daemon as the current process. Not examined further (operator keys
  only). Option: queue terminal commands to the shell task instead of running them in the caller.
- No authentication: `session root` (`shell/commands.rs:1831`) and `login` (`:1879`) switch to root from any
  session without a credential; documented in `docs/ARCHITECTURE.md` ("no password/credential field yet").
  The kernel-record fix above stops processes from editing profiles; a person at the console still can.
  Option: require the current session to hold `cap:system:all` for `session root` and for logging into a
  root-profile account, once harnesses use a separate path to reset the session.
- The package registry checksum is plain SHA-256 (`pkg/mod.rs:355`): whoever can write the disk can mark
  signed packages installed (without the privileged confirmation). Signature and allowlist still bound what
  such a package can be. Option: a keyed checksum, or re-asking for privileged packages at first launch.

Low (correctness, from the driver sub-audit; reachable only with unusual devices or not reachable today):
`devices/xhci.rs:1600` (`transfer_len - residual` underflows on a device residual larger than the request; the
function has no caller), xHCI event dequeue advanced twice after hot-plug (`poll_events`, no caller), frames
leaked per `interrupt_xfer` and on `port_reset` errors, completions not matched to their command TRB;
`devices/virtio_gpu.rs:398` (`send_sync` reports the previous response as success after a timeout);
`devices/hda.rs:672` (`send_verb` polls up to 5 million MMIO reads while holding the HDA lock, reachable through
SetVolume and PlayAudio with a dead codec); `vga_fb.rs:291` (`x + w` in u32 in `draw_rect`; every caller passes
screen-bounded values).

## Audited and found sound

- App windows: a process presents into and polls only windows it owns (`app_window.rs:299-348`); canvas sizes
  are clamped and budgeted (round 4); window ids are never reused (`NEXT_APP_WINDOW_ID`); every path that
  removes a window recomputes `focused_idx` (create, close, close_for_pid, minimize, taskbar, alt-tab).
- Injected input is kept from operator controls (terminal window, lock, launcher, power menu, dock, close
  buttons) on press and release; bound clicks and keys are dropped if the target changed (`cursor.rs:120-136`).
- Drawing: `set_pixel` and `blend_pixel` clip to the framebuffer; HUD coordinates are u16 and the landmark loop
  stops at 8; the suggestion is length-checked and UTF-8 checked.
- Clipboard (64 KiB, fallible copy) and notifications (32 entries, bounded fields, `|` and line breaks removed
  before display) need their capabilities; reads copy at most the caller's buffer after a writability check.
- SystemQuery's process list: task names are sanitized at registration (`scheduler/mod.rs:624`,
  `sanitize_task_name` turns `"`, `\` and non-printable bytes into `_`), so a name cannot add JSON entries. A fix
  for this was written (`8a0c230`) and dropped when its same-image control showed no forged entry.
- Package signatures: Ed25519 `verify_strict` with the compiled-in key over the whole manifest, which binds
  name, version, allowlisted capabilities and the binary's SHA-256; the binary is hashed on every verification;
  install, launch and `capabilities_for` require the registry's version and digest to match;
  `/disk/pkgs*` is closed to ring 3 without `cap:pkg:manage`.
- Services: lifecycle calls check the service's layer and required tokens (fi1); state is display-only.
- Agent and Heliox modules: reached only from the kernel shell; they grant no capability.
- Capability matching (`security/mod.rs:230-298`): segment-boundary matching (fixed in fi1, `4fac783`).
- Audio, camera and screen syscalls: capability-checked, lengths capped, user ranges checked for writability
  (sub-audit).
- DMA lifetime: no driver frees a DMA buffer, so no device writes into freed memory; drivers hand devices
  physical addresses and use the physical map for CPU access.
- Bootloader 0.9.33: the kernel stack is 512 pages with an unmapped guard page below it
  (`page_table.rs:52-54`), NXE is set before the kernel runs, and the physical map sits at a free level-4
  entry; the kernel moves off the boot stack to its own guarded stacks (round 4), and the memory map's
  bootloader region at 0x8000 is never allocated (round 4, `smp-state`).

## What remains

- The found-not-fixed items above.
- Timing and cache side channels (named in round 4) were not examined.
- `graphics/console.rs` and `graphics/font.rs`, `security/rand.rs` and `security/time.rs` were not read.

## Behaviour changes for the owner

- Installing a package that requests `cap:fs:read`, `cap:fs:write` or `cap:audio:play` from the App Store now
  shows the kernel's `[SECURITY]` prompt after the App Store's own confirmation; the operator presses y on
  the physical keyboard or serial console within 5 s. `pkg install <name> --confirm` at the shell is unchanged.
- Ring-3 processes cannot create, write or delete `/disk/accounts.txt` or `/disk/heliox/audit.log`, or delete
  `/disk` or `/disk/heliox`. No shipped program does; `useradd` and the audit flush are kernel-side.
- Audit messages and the serial `[AUDIT]` lines show control characters and backslashes as `\xNN`.
- Notification and window titles in serial lines are escaped the same way (`escape_printable`); printable
  ASCII titles look as before.
- A package may not use the name of a compiled-in program.
- A virtio-gpu device offering a queue larger than 256 entries is asked for 256; an xHCI controller asking for
  more than 512 scratchpad buffers is not initialised.

## Edits outside this workstream's areas

| File | Edit | Why |
|---|---|---|
| `src/syscall/mod.rs` | PackageInstall in the gated set of `dispatch_for_process`; its prompt text in `confirmation_subject` | finding 6 |
| `src/syscall/fs.rs` | `refuse_kernel_record` in the write, create and delete paths | finding 3 |
| `src/shell/commands.rs` | `pkg run` stops when registration is refused; `test-syscall` falls through to `selftest_k6` | finding 7, wiring |
| `src/shell/mod.rs` | `pub mod selftest_k6` | wiring |
| `README.md`, `docs/ARCHITECTURE.md` | the PackageInstall prompt, kernel records, audit escaping and flush | statements these fixes changed |

Run tools: `kernel_audit_tools/negctl.py` (builds the negative control). CI runs used: 7 for kernel images (43260234763 A, 43260297587 negctl 1, 43260429786 A', 43260744592 `8a0c230`,
43261494825 B, 43264629794 negctl 2, 43264641280 C), and one for this report's commit, which changes no
kernel code.
