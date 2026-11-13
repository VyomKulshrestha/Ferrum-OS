# FerrumOS follow-ups (fi2): report

Plan: `ferrumos_followups_fi2_plan.md`. Per-workstream detail: `fi2_reports/` (the kernel and gate files
are on the pull-request branch until it is merged). This file is updated as workstreams finish.
"Checked" means the main session reran or re-read the claim; everything else is the reporting agent's.
Nothing here recomputes a registered or published number.

Status on 2026-11-13, later: pull request 10 is merged (main 27cc110, and the boot image CI built there
is byte for byte the verified one); the papers' next versions are written and wait for DOIs; the
operator study is registered and its sealed run is in progress; both paper-2 rounds are finished and
the notes to the maintainers are drafted, not sent.

## 1. Kernel and gate (pull request 10, merged 2026-11-13; contains pull requests 7, 8 and 9)

Branch `improve/fi2-integration`, head dcb8b1b. Boot image built by CI for that head: sha256
`5bb2c6a75db2db9d184232cf22d6a5267dbbebfe83021ecb6f5334de715b5df5`, 7,474,176 bytes.

**Checked by the main session on that image**, one harness at a time, every harness passing on its first
run:

| CPU model | Harnesses | Checks |
|---|---|---|
| Haswell (the default; SMEP, no SMAP) | 24 | 423 of 423 |
| Broadwell-noTSX (SMEP and SMAP on; the serial logs print `smap=true`) | 23 | 372 of 372 |

The 24 are the twenty-one harnesses that pass on main (315 checks) and the three new ones:
`verify_kernel_k5` (51), `verify_kernel_k6` (31) and `verify_gate_policy` (26). `verify_kernel_k5` chooses
its own CPU models for its four boots, so it is not repeated in the second row. Host tests: gate 99,
physical runtime 179, neural protocol 19. The image downloaded from CI is byte for byte the image the
integrating agent tested.

### 1.1 Kernel protections (pull request 7; `fi2_reports/kernel_cpu.md`)

Each item has a test that fails with the fix switched off in the same image.

| Item | Result |
|---|---|
| SMEP | set where the CPU reports it; a ring-0 call into a user page faults |
| SMAP | set where the CPU reports it; every intended access to user memory goes through two bracketed helpers |
| `[SECURITY]` prompt | process console output is prefixed `[pid N]`, the tag is rewritten, other bytes escaped; seven forgery attempts fail on serial and screen |
| Kernel heap per process | a ledger with a 4 MiB cap over IPC, launch context, audit records, RamFS files, windows and sockets |
| ext2 | tested on disks made by `mke2fs`: backup superblocks and reserved descriptor blocks are metadata, cross-linked blocks are never freed, indirect blocks are freed, directories grow past 12 blocks, unknown feature bits are refused; `e2fsck -fn` reports the disk clean after the kernel's writes |
| x87 errors | CR0.NE set; the error is delivered to the faulting process |
| Page-table isolation | **not done**; the report gives the design, the branch holds no partial code |

Two defects found on the way, both present on main:

- **Every ring-3 context ran with I/O privilege level 3** (`rflags: 0x3202` in `src/scheduler/mod.rs` on
  main; checked). Any process could write to the serial port, the disk controller and the interrupt
  controller, and could switch interrupts off. Now level 0.
- **A process could set the AC flag before a system call and switch SMAP off for that call.** The flag is
  now cleared on every entry to the kernel.

### 1.2 Gate policy (pull request 8; `fi2_reports/gate_policy.md`)

Every question the fi1 gate rounds left pinned was changed, except two.

| Question | Change |
|---|---|
| Read, then send | a network call to a host outside the allowlist (provider, speech host, `network_allowlist`) needs approval; `poll_input` needs approval; at most 16 unasked tier-2 calls per 100 ticks |
| Approval by id | a confirmation counts only for the request printed last, otherwise the request is printed again; `heliox pending` in the shell; the agent's requests take at most 28 of 32 slots |
| Config fallback | a `config.json` that cannot be used gives tier 0 and one console line |
| Startup hooks | read only from `/tmp/heliox-hooks/`, which the kernel creates and ring 3 cannot write |
| Service name, autosave, tier clamp, wizard | the approval names the service; autosave runs only when `save_memory` would run unasked; an auto-approve tier of 4 is clamped to 3; the wizard escapes strings |
| Audit ring | 64 unflushed entries per source; another source's unflushed entry is never dropped |
| Panel flag | authorises only GOAL and CONFIG_UPDATED |
| Typed text | bound to the window that had focus at approval (syscall 67) |
| Config ancestors | a delete of any directory holding the configuration is refused |
| Occupancy | a missing or stale record blocks motion where humans are not allowed |
| Step, battery, payload | checked on the command path |

Left as they were: the boot-time setup panel (its first GOAL is part of first-run setup; its flag now
covers only GOAL and CONFIG_UPDATED) and a speed bound for physical commands (the command format has no
speed field). Not verified by anyone: the world-model collection scripts after the hook path changed,
and the tier-2 rate limit inside QEMU.

### 1.3 Kernel audit of the areas no fi1 round examined (pull request 9; `fi2_reports/kernel_audit.md`)

| | Defect | 
|---|---|
| High | the VirtIO graphics backing was 1 MiB and every frame copied 3 MiB into it: 2 MiB of neighbouring kernel memory overwritten per frame, and read by the host as the picture |
| High | the audit log's trim cut at a byte offset and stopped the kernel on a multi-byte character; any process can put such characters in the log |
| Medium | ring 3 could rewrite `/disk/accounts.txt` (a user session becomes root), rewrite or delete the audit log, and delete `/disk/heliox` |
| Medium | a line break in an audit message forged audit and serial lines |
| Medium | audit entries were lost for good once the log passed 12 ext2 blocks |
| Medium | PackageInstall trusted the caller's own "operator confirmed" flag for privileged capabilities |
| Low | a package could take a compiled-in program's name and capabilities; titles printed unescaped on serial; HDA, xHCI and VirtIO values from the device used unchecked |

With the fixes held back, the new harness passes 12 of 31 checks and every held-back fix fails. One
reported defect was withdrawn after its own control showed there was none (task names were already
sanitised).

Found and not fixed: bounds on two xHCI offsets, three unbounded waits on the keyboard controller and on
ACPI reboot, panics of the `acpi` crate on malformed tables, an unused `aml` dependency. QEMU's devices
report benign values, so none of these could be tested.

### 1.4 Observations that are the owner's decision

Each has file and line and one suggested option in `fi2_reports/kernel_audit.md`.

- `session root` and `login` need no authentication.
- A new window takes keyboard focus, so an application can capture the operator's next keystrokes.
- Every physical key reaches the holder of `input:read` (the daemon), which also holds `clipboard:read`.
- Commands typed in the terminal window run inside the daemon's system call.
- The package registry's checksum is unkeyed; a crafted disk can mark packages installed.

### 1.5 Behaviour changes of pull request 10

Process console output carries `[pid N]` and shows non-ASCII bytes as `\xNN`. Port I/O or `cli` from
ring 3 ends the process. A process holds at most 4 MiB of kernel heap. ext2 disks with unsupported
features are not mounted. Network sends to unlisted hosts, and `poll_input`, ask the operator. A
confirmation applies to the request shown last. Confirm and deny work from the kernel shell only. An
auto-approve tier of 4 is treated as 3. An App Store install that asks for privileged capabilities shows
the kernel's prompt. Ring 3 cannot change the accounts file or the audit log.

## 2. Papers (`fi2_reports/papers.md`)

Two of the three were published on Zenodo on 2026-11-13, after the owner confirmed: "Prediction Is Not Permission" v1.4 (DOI 10.5281/zenodo.24189826) and "When Agents Control the Kernel" v1.3 (DOI 10.5281/zenodo.24189855). Each record holds one PDF whose digest equals the file locked in this repository (checked through Zenodo's public API). The preprint of "Thresholds That Travel" is not published in its new version.

- **"Prediction Is Not Permission" v1.4**, 52 pages: thirteen additions, every word of v1.3 kept, no
  number recomputed. Its verifier passes (checked).
- **"When Agents Control the Kernel" v1.3**, 19 pages: the dependence of its trained models on the BLAS
  thread count. Verifier 57 of 57 (checked).
- **"Thresholds That Travel"**: one post-hoc paragraph on alarm time outside the fitted range, in the
  conference copy (21 pages, body ends on page 12) and in a preprint v1.2 candidate, which also carries
  the tt1g round that the published v1.1 does not have.

The papers workstream corrected two statements of the fi1 report: the OS world-model numbers belong to
"When Agents Control the Kernel" (and the count of 216 replay false alarms only to this repository's
notes), and the data manifest bound by v1.3 changed in three commits after the lock, not one.

Open: whether the preprint of "Thresholds That Travel" is updated during review; the update of the
anonymous artifact (rebuilt locally with the two cited files and no identifying string); the two
new records on the author's ORCID profile.

## 3. The operator in the loop (ol1)

Registered on 2026-11-13: protocol `operator_in_the_loop_ol1_protocol.md`, record
`operator_in_the_loop_ol1_registration.json` (main adb6b3b, pushed 00:24 +05:30), before any sealed
scenario was generated. The runner refuses to start unless the record matches the protocol's and the
code's digests. Development spend: 3.03 US dollars. The registered grids: Claude Haiku 5.5 on 2,352
episodes, Sonnet 5.5 on 280, Opus 5.5 on 140, under caps of 20, 45 and 45 dollars. The Haiku grid is
running; results will be added here by the analysis script the registration names.

## 4. Paper 2

Both rounds are finished. Their plans and drivers are on main; their results stay local until the
maintainers of the libraries and products have been told (nine draft notes, not sent).

- **Score level** (`research/tw1b`, merged at 38c4f3c): amendment 4 was committed before any run; the
  harness check reproduces the first round exactly; 294 parts ran. One part is missing, the
  budget-matched settings of one calibrator, because the harness's search grid was too coarse for it;
  that defect and two smaller ones in our own code are being fixed, and the part rerun, under an
  amendment committed first.
- **Signal level** (`research/tw1c`, merged at 05912cc): the plan was committed before any run; three
  monitoring products and two libraries ran in local containers, all removed afterwards. Limits: one
  product ran only with a shortened training window, the campaigns were open-loop, and one product was
  tested through historical analysis.
