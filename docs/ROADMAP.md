# FerrumOS Completion Roadmap

This document tracks the work to take FerrumOS from a v0.1.0 kernel foundation
to a usable bare-metal operating system. Each phase lands in one or more
commits on `main`. Every commit should keep the kernel booting, the boot
image building, and the command sweep green.

## Phases

### Phase 1 — Real userspace execution

The single biggest unlock. Until this lands, every userspace manifest
(`init`, `agent-bridge`, `audit-exporter`, `heliox-bridge`) is decorative
metadata. After this lands, the kernel can load and run ELF binaries in
ring 3.

- [ ] **1.1** Workspace scaffolding: `userland/` Cargo workspace + a tiny
  no_std `init` userspace binary.
- [ ] **1.2** ELF64 parser (`src/elf/`) covering the header, program
  headers, and `PT_LOAD` extraction.
- [ ] **1.3** Per-process address space (`src/process/`) with a new
  `OffsetPageTable` per process, a kernel-half and a user-half mapping
  policy, and a reusable user stack.
- [ ] **1.4** Ring-3 entry via `int 0x80` (or `syscall`), `iretq`/`sysret`
  trampoline, per-process TSS `rsp0` update, and `load_elf` that actually
  loads `/bin/init` from the embedded blob and dispatches into it.

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

- [ ] **4.1** `rtl8139` or `virtio-net` NIC driver.
- [ ] **4.2** Ethernet + ARP + IPv4 + UDP + TCP minimal stack.
- [ ] **4.3** Loopback WebSocket transport speaking JSON-RPC 2.0.
- [ ] **4.4** Userspace `heliox-bridge` actually consumes real envelopes
  from the kernel broker.

### Phase 5 — SMP, ACPI, persistent init

- [ ] **5.1** SMP: AP startup, per-CPU scheduler, lock audit.
- [ ] **5.2** ACPI: shutdown, reboot, sleep.
- [ ] **5.3** Persistent PID 1 that supervises runtime services and
  restarts them on crash.

## Out of scope for the v0.2 line

- UEFI boot (BIOS `bootloader` crate is fine for now).
- A real `malloc`/userspace heap (the embedded blob can `mmap` its own).
- A graphical UI (VGA text stays).

## Commit cadence

Each numbered sub-step is at least one commit on `main`. The commit message
prefixes match the existing repo style (`feat:`, `chore:`, `refactor:`,
`docs:`, `build:`). The boot image and the command sweep must stay green
at every commit boundary — if a sub-step temporarily breaks the sweep, the
sweep test that depends on the missing piece is moved to a `[skip-sweep]`
block in `scripts/command_sweep.mjs` until the next commit re-enables it.
