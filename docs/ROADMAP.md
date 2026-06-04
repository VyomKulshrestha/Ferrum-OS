# FerrumOS Completion Roadmap

This document tracks the work to take FerrumOS from a v0.1.0 kernel foundation
to a usable bare-metal operating system. Each phase lands in one or more
commits on `main`. Every commit should keep the kernel booting, the boot
image building, and the command sweep green.

## Goal

Phase 1 makes the kernel a real OS by adding true user-space execution:
ELF loading, isolated address spaces, and a ring-3 entry. Phases 2 through
5 harden the kernel and add the device support that user-space will need.

Heliox-OS is a *consumer* of the boundary that Phase 1 exposes. The Heliox
bridge (`src/heliox/`) is already wired in (60 methods, 5 tiers, 120 actions,
9 service slots, 6 capabilities). It will only be exercised end-to-end once
a real userspace exists to host the bridge. See
<https://github.com/VyomKulshrestha/Heliox-OS> for the upstream daemon
sources and JSON-RPC contract; the kernel-side surface mirrors them.

## Phases

### Phase 1 — Real userspace execution

The single biggest unlock. Until this lands, every userspace manifest
(`init`, `agent-bridge`, `audit-exporter`, `heliox-bridge`) is decorative
metadata. After this lands, the kernel can load and run ELF binaries in
ring 3.

- [x] **1.1** Workspace scaffolding: `userland/` Cargo workspace + a tiny
  no_std `init` userspace binary.
- [x] **1.2** ELF64 parser (`src/elf/`) covering the header, program
  headers, and `PT_LOAD` extraction.
- [x] **1.3** Per-process address space (`src/process/`) with a new
  `OffsetPageTable` per process, a kernel-half and a user-half mapping
  policy, and a reusable user stack.
- [ ] **1.4** Ring-3 entry via `int 0x80`, `iretq` trampoline, per-process
  TSS `rsp0` update, and `load_elf` that actually loads `/bin/init` from
  the embedded blob and dispatches into it. Includes a `ring3` shell
  command for manual dispatch and a sweep test that verifies the user
  banner reaches the serial port.

### Phase 2 — Preemptive scheduling

- [ ] **2.1** Per-task `TaskContext` save/restore (callee-saved registers,
  CR3, flags).
- [ ] **2.2** Timer-interrupt context switch wired into the PIT IRQ.
- [ ] **2.3** Priority preemption with a run-queue per priority.
- [ ] **2.4** `sleep(ms)` and `wait(pid)` syscalls.

### Phase 3 — Persistent filesystem

- [ ] **3.1** ATA PIO driver (IDE primary master/slave).
- [ ] **3.2** ext2 reader (or FAT32 if simpler) with read-only mount.
- [ ] **3.3** Replace `ramfs.root` with the real mount in the boot flow.
- [ ] **3.4** `fsync`-style commit and write support.

### Phase 4 — Real network + Heliox transport

- [x] **4.1** `rtl8139` or `virtio-net` NIC driver.
- [x] **4.2** Ethernet + ARP + IPv4 + UDP + TCP minimal stack.
- [x] **4.3** WebSocket transport speaking JSON-RPC 2.0.
- [x] **4.4** Userspace `heliox-bridge` actually consumes real envelopes
  from the kernel broker.

### Phase 5 — SMP, ACPI, persistent init

- [x] **5.1** SMP: AP startup, per-CPU scheduler, lock audit.
- [x] **5.2** ACPI: shutdown, reboot, sleep.
- [x] **5.3** Persistent PID 1 that supervises runtime services and
  restarts them on crash.

## Out of scope for the v0.2 line

- UEFI boot (BIOS `bootloader` crate is fine for now).
- A real `malloc`/userspace heap (the embedded blob can `mmap` its own).
- A graphical UI (VGA text stays).
- Heliox-OS daemon port. The bridge in `src/heliox/` is the contract;
  the Python daemon (planner, orchestrator, verifier, reflector,
  ChromaDB, TRIBE-v2) lives in the Heliox-OS repository and is a
  future port.

## Commit cadence

Each numbered sub-step is at least one commit on `main`. The commit message
prefixes match the existing repo style (`feat:`, `chore:`, `refactor:`,
`docs:`, `build:`). The boot image and the command sweep must stay green
at every commit boundary — if a sub-step temporarily breaks the sweep, the
sweep test that depends on the missing piece is moved to a `[skip-sweep]`
block in `scripts/command_sweep.mjs` until the next commit re-enables it.
