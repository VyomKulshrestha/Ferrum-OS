# FerrumOS

A truly agentic operating system built in Rust — where the AI agent has full
hardware control: it can see the screen, hear audio, type commands, browse the
web, manage files, remember context, and autonomously operate.

FerrumOS keeps the kernel deterministic and independent from probabilistic AI
systems. The AI brain runs natively as a freestanding userspace process
(`heliox-daemon`) with direct syscall access to all hardware drivers.

## Current Status

Version 0.2.0 — **All 13 implementation phases complete.** Boot image: 5829 KB.

### Kernel

- Bootloader integration through `bootloader`
- VGA text output and UART serial logging
- GDT, IDT, CPU exception handlers, PIC timer and keyboard IRQs
- Page-table setup, boot-info frame allocation, and a 1 MiB kernel heap
- Preemptive task scheduler with per-task context switching and priority queues
- Interactive shell with 35+ commands including `dashboard`
- SMP initialization, ACPI shutdown/reboot
- Real userspace execution: ELF loader, Ring-3 entry, per-process address spaces

### Filesystem

- Volatile in-memory RAM filesystem with VFS mount table
- ATA PIO block storage driver
- Read-write Ext2 filesystem with block/inode allocation
- VFS layer with longest-prefix mount matching and sync

### Security & Services

- Capability registry and caller-held capability authorization
- 5-tier permission model with operator confirmation gates
- Audit logging hooks for security and lifecycle events
- Modular service manager with typed service manifests
- IPC broker with capability-checked message delivery

### Networking

- RTL8139 PCI NIC driver with real TCP/IP via smoltcp
- Socket syscalls: `socket`, `bind`, `listen`, `accept`, `connect`, `send`, `recv`
- HTTP/1.1 client (GET + POST) with 32KB response buffer
- WebSocket client (RFC 6455) for streaming LLM responses

### Hardware Drivers

- VGA framebuffer (Bochs VBE) with 1024×768 graphical console
- Intel HDA audio controller with play/record/volume DMA
- XHCI USB 3.0 host controller with device enumeration
- USB HID keyboard and mouse (boot protocol)
- PS/2 keyboard via 8042 controller
- PIT 8254 timer, UART 16550 serial

### Agent Daemon (`heliox-daemon`)

- Bare-metal ReAct orchestrator (observe → think → act → verify → reflect)
- Hierarchical planner with dependency-ordered task decomposition
- TF-IDF vector store with cosine similarity for persistent memory
- `no_std` JSON parser and LLM response decoder
- 35 tools mapped to 30 kernel syscalls
- Config-driven LLM endpoint from `/disk/heliox/config.json`
- Multi-agent domain router (Code/Web/System/Files specialization)
- Web agent with HTML-to-text extraction and link discovery
- Reasoning telemetry emitted to kernel audit log

## Architecture

```text
+----------------------------------------------------------+
| Agent Layer (heliox-daemon)                              |
| ReAct orchestrator, multi-agent routing, web browsing     |
+----------------------------------------------------------+
| Cognitive Layer (heliox-daemon)                          |
| Vector store, TF-IDF, planner, reflector, domain routing  |
+----------------------------------------------------------+
| Runtime Layer                                            |
| Services, permissions, IPC, config, 35 tool ↔ syscall map |
+----------------------------------------------------------+
| Kernel Layer                                             |
| Boot, memory, interrupts, scheduling, ELF loader, Ring-3  |
+----------------------------------------------------------+
| Storage / VFS Layer                                      |
| ATA PIO block driver, Ext2 filesystem, VFS mount table    |
+----------------------------------------------------------+
| Network / Hardware Layer                                 |
| RTL8139 NIC, Intel HDA, XHCI USB, USB HID, smoltcp      |
+----------------------------------------------------------+
```

## Build

Prerequisites:

- Rust nightly through rustup
- `x86_64-unknown-none` target
- `bootimage`
- QEMU for local boot testing

```powershell
rustup toolchain install nightly
rustup target add x86_64-unknown-none --toolchain nightly
cargo install bootimage

.\build.ps1 check
.\build.ps1 build
```

The boot image is created at:

```text
target\x86_64-unknown-none\debug\bootimage-ferrumos.bin
```

## QEMU Launch

```bash
qemu-system-x86_64 \
  -drive format=raw,file=target/x86_64-unknown-none/debug/bootimage-ferrumos.bin \
  -serial stdio \
  -vga std \
  -netdev user,id=net0,hostfwd=tcp::8785-:8785 \
  -device rtl8139,netdev=net0 \
  -device intel-hda -device hda-duplex \
  -device qemu-xhci -device usb-kbd -device usb-mouse
```

Or use the build script:

```powershell
.\build.ps1 run
```

## Shell Commands

| Command | Description |
| --- | --- |
| `help` | Show available commands |
| `clear` | Clear the screen |
| `echo <text>` | Print text |
| `ps` | List running tasks |
| `mem` | Show heap usage |
| `ls [path]` | List directory contents |
| `cat <file>` | Display file contents |
| `stat <path>` | Show filesystem metadata |
| `mounts` | Show mounted filesystems |
| `mkdir <dir>` | Create directory |
| `touch <file>` | Create empty file |
| `write <file> <text>` | Write text to file |
| `rm <path>` | Remove file or directory |
| `devices` | List registered hardware devices |
| `net` | Show network interfaces and counters |
| `net send <text>` | Deliver a capability-checked loopback packet |
| `caps` | List security capabilities |
| `services` | List registered services |
| `services start/stop <id>` | Start or stop a service |
| `ipc` | Show IPC broker statistics |
| `syscalls` | Show syscall ABI table (0–29) |
| `programs` | List userspace program manifests |
| `users` | List launched userspace processes |
| `run <program>` | Launch a manifest-backed userspace process |
| `dashboard` | Full-screen system status TUI |
| `agent status` | Show agent runtime boundary state |
| `agent start` | Start the sandboxed agent boundary |
| `heliox status` | Show Heliox daemon state |
| `heliox tiers` | List the 5-tier permission model |
| `log` | Show audit log |
| `uptime` | Show system uptime in ticks |
| `uname` | Show system information |
| `shutdown` | Shut down via ACPI |
| `reboot` | Reboot via ACPI |
| `disk` | List ATA drives or read sectors |

## Syscall Table

| # | Name | Description |
|---|------|-------------|
| 0 | Yield | Cooperative yield |
| 1 | IpcSend | Send an IPC message |
| 2 | IpcReceive | Receive an IPC message |
| 3 | ServiceStart | Start a registered service |
| 4 | ServiceStop | Stop a registered service |
| 5 | CapabilityCheck | Check if a capability is held |
| 6 | AuditWrite | Write to the audit log |
| 7 | Socket | Create a TCP socket |
| 8 | Bind | Bind a socket to an address |
| 9 | Listen | Listen on a socket |
| 10 | Accept | Accept a connection |
| 11 | Recv | Receive data from a socket |
| 12 | Send | Send data through a socket |
| 13 | Wait | Wait (stub) |
| 14 | Connect | Connect to a remote host |
| 15 | ReadFile | Read a file from the VFS |
| 16 | WriteFile | Write/create a file in the VFS |
| 17 | ReadDir | List directory contents |
| 18 | Exec | Execute an ELF binary as a new process |
| 19 | ReadFramebufferInfo | Get framebuffer dimensions |
| 20 | ReadTextBuffer | Capture screen text contents |
| 21 | CreateDir | Create a directory |
| 22 | DeleteFile | Delete a file or directory |
| 23 | PlayAudio | Play PCM audio via HDA DMA |
| 24 | RecordAudio | Record audio from HDA input |
| 25 | SetVolume | Set audio output volume |
| 26 | InjectKey | Inject a keyboard event |
| 27 | InjectMouse | Inject a mouse event |
| 28 | PollInput | Poll the input event queue |
| 29 | SystemQuery | Query live system data as JSON |

## Agent Tools (35 total)

| Tier | Tools |
|------|-------|
| **0 — Observe** | `system_info`, `list_processes`, `query_memory`, `get_config`, `poll_input`, `add_subtask` |
| **1 — Safe** | `ipc_send`, `audit_write`, `yield_cpu`, `report_status`, `capability_check`, `read_file`, `read_dir`, `sleep`, `read_screen`, `set_volume` |
| **2 — Network** | `net_connect`, `net_send`, `net_recv`, `http_get`, `load_memory`, `set_goal`, `record_audio`, `browse_url` |
| **3 — Modify** | `write_file`, `create_directory`, `save_memory`, `service_start`, `service_stop`, `play_audio`, `keyboard_type`, `mouse_click`, `mouse_move` |
| **4 — Destructive** | `exec_process`, `delete_file` |

## Development Status

All 13 implementation parts are complete:

| Phase | Parts | Status |
|-------|-------|--------|
| **A — Kernel Foundation** | 1–5 (Boot, Scheduler, FS, Security, Services) | ✅ Complete |
| **B — Networking & Agent** | 6–9.5 (NIC, Process, Daemon, VGA, Bugfixes) | ✅ Complete |
| **C — Hardware Drivers** | 10–11 (HDA Audio, XHCI USB + Input) | ✅ Complete |
| **D — Application Layer** | 12–13 (SystemQuery, Dashboard, WebSocket, Web Agent, Multi-Agent) | ✅ Complete |

## Design Rules

- Keep the kernel deterministic — no AI inference in kernel space.
- Every agent action goes through a real syscall — no stubs.
- Capability-checked boundaries between kernel and agent.
- Use Rust safety by default; keep unsafe blocks small and documented.
- Hardware first — if you want an agentic OS, you need drivers.
