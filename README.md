# FerrumOS

An operating system built in Rust — where the AI agent has full
hardware control: it can see the screen, hear audio, type commands, browse the
web, manage files, remember context, and autonomously operate.

FerrumOS keeps the kernel deterministic and independent from probabilistic AI
systems. The AI brain runs natively as a freestanding userspace process
(`heliox-daemon`) with direct syscall access to all hardware drivers.

## Features

### Kernel & Core
- Bootloader integration through `bootloader`
- GDT, IDT, CPU exception handlers, PIC timer and hardware IRQs
- Page-table setup, boot-info frame allocation, and a 12 MiB kernel heap (increased to support VBE double-buffering)
- Preemptive task scheduler with per-task context switching and priority queues
- Interactive shell with 35+ commands including `dashboard`
- SMP initialization, ACPI shutdown/reboot
- Real userspace execution: ELF loader, Ring-3 entry, per-process address spaces, on-demand page-fault lazy allocation, and file-backed memory mapping (`mmap`)

### Graphical Desktop Environment (GUI)
- Custom Compositor and Window Manager
- Interactive Desktop Taskbar and Dock
- Movable, focusable GUI windows with close buttons and interactive titles
- **Generic app-window framework**: any userland process can call `CreateWindow`/`PresentWindow`/`PollWindowInput` to own a real window backed by its own RGBA8 canvas and a per-window input queue — not limited to the kernel's hardcoded System Monitor/Terminal/Agent HUD window types
- PS/2 Mouse integration with 9-bit signed delta parsing and auto-recovery
- CPU-efficient main loop with interrupt-driven `hlt` architecture and off-screen double-buffering
- Hardware cursor rendering with dynamic drop-shadows

### Filesystem
- Volatile in-memory RAM filesystem with VFS mount table
- ATA PIO block storage driver
- Read-write Ext2 filesystem with block/inode allocation
- VFS layer with longest-prefix mount matching and sync

### Security & Services
- Capability registry and caller-held capability authorization
- 5-tier permission model with operator confirmation gates (gated Tier 3/4 syscalls require physical key confirmation, using RIP-2 instruction rewinding for restartable blocking calls)
- Persistent Audit Logging: Out-of-interrupt deadlock-free writing to `/disk/heliox/audit.log` (128KB log size cap with automated FIFO truncation)
- Resource Quotas: Syscall rate limiting, continuous CPU execution limits, and memory mapping bounds check (default 8 MiB)
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
- PS/2 keyboard and mouse via 8042 controller (IRQ1 & IRQ12)
- PIT 8254 timer, UART 16550 serial

### Agent Daemon (`heliox-daemon`)
- Bare-metal ReAct orchestrator (observe → think → act → verify → reflect)
- Multi-Provider Support: Natively connects to local Ollama or cloud models (OpenAI, Gemini, Claude) via host proxy
- Ambient Background Logic: Actively records voice from mic and performs anomaly screen vision checks
- Interactive Agent HUD: Desktop GUI widget for Live Telemetry streaming and direct goal input
- Hierarchical planner with dependency-ordered task decomposition
- TF-IDF vector store with cosine similarity for persistent memory
- `no_std` JSON parser and LLM response decoder supporting OpenAI Chat Completions format
- 39 tools mapped to 39 kernel syscalls
- Config-driven setup via `/disk/heliox/config.json`
- Reasoning telemetry emitted over IPC to the GUI service

## Architecture

```text
+----------------------------------------------------------+
| Agent Layer (heliox-daemon)                              |
| ReAct orchestrator, multi-provider network client (LLM),  |
| ambient mic/vision recording, multi-agent domain routing  |
+----------------------------------------------------------+
| Cognitive Layer (heliox-daemon)                          |
| Vector store, TF-IDF, planner, reflector, JSON decoder    |
+----------------------------------------------------------+
| Runtime Layer                                            |
| Services, permissions, IPC, config, 37 tool ↔ syscall map |
+----------------------------------------------------------+
| GUI & Compositor Layer                                   |
| Window manager, JARVIS Agent HUD, taskbar, telemetry IPC  |
+----------------------------------------------------------+
| Kernel Layer                                             |
| Boot, memory, interrupts, scheduling, ELF loader, Ring-3  |
+----------------------------------------------------------+
| Storage / VFS Layer                                      |
| ATA PIO block driver, Ext2 filesystem, VFS mount table    |
+----------------------------------------------------------+
| Network / Hardware Layer                                 |
| RTL8139 NIC, Intel HDA (audio), XHCI USB, smoltcp (TCP)   |
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
| `desktop` | Launch Graphical Desktop Environment (GUI) |
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
| 30 | Exit | Terminate the calling process |
| 31 | GetPid | Get process ID of the caller |
| 32 | Sleep | Cooperatively sleep/suspend process |
| 33 | WaitPid | Poll child process exit status |
| 34 | Write | Write bytes to console or serial |
| 35 | Close | Close a socket |
| 36 | ReadCameraFrame | Read a YUYV frame from the camera driver |
| 37 | CameraInfo | Get camera details (width, height, status) |
| 38 | Kexec | Gated warm reboot/relocation to new kernel image |
| 39 | HudUpdate | Update HUD suggestion overlay |
| 40 | HitTest | Perform a visual element hit-test |
| 41 | Mmap | Memory map a file |
| 42 | GetRandom | RDRAND-backed CSPRNG bytes |
| 43 | GetTime | Read RTC time (for TLS cert validity checks) |
| 44 | CreateWindow | Create an app-owned GUI window with a caller-sized canvas |
| 45 | PresentWindow | Submit an RGBA8 pixel buffer to an owned window |
| 46 | PollWindowInput | Poll one pending input event scoped to an owned window |

## Agent Tools (39 total)

| Tier | Tools |
|------|-------|
| **0 — Observe** | `system_info`, `list_processes`, `query_memory`, `get_config`, `add_subtask`, `camera_capture`, `gesture_status` |
| **1 — Safe** | `ipc_send`, `audit_write`, `yield_cpu`, `report_status`, `capability_check`, `read_file`, `read_dir`, `sleep`, `read_screen`, `set_volume`, `poll_input`, `local_inference` |
| **2 — Network** | `net_connect`, `net_send`, `net_recv`, `http_get`, `load_memory`, `set_goal`, `record_audio`, `browse_url` |
| **3 — Modify** | `write_file`, `create_directory`, `save_memory`, `service_start`, `service_stop`, `play_audio`, `keyboard_type`, `mouse_click`, `mouse_move` |
| **4 — Destructive** | `exec_process`, `delete_file`, `trigger_kernel_upgrade` |

## Heliox Daemon Setup

The Heliox agent daemon requires configuration to connect to your preferred LLM provider. There are two ways to set this up:

> [!NOTE]
> **RAM Filesystem Fallback**: The kernel pre-creates `/disk/heliox/` as a directory within the RAM filesystem (`RamFS`) at boot. If a physical Ext2 formatted ATA disk is not mounted at `/disk`, all configuration writing and loading will transparently fall back to the RAM filesystem, allowing you to use the setup wizard or shell without any partition setup.

### Option A: Interactive Setup (Agent HUD)
1. Boot the OS and launch the graphical desktop:
   ```
   FerrumOS:~$ desktop
   ```
2. Click inside the **Agent HUD** window to focus it (it will show a neon-cyan border).
3. Follow the 3-step setup wizard by typing your values and pressing **Enter**:
   * **Step 1: Select Provider**: Choose `ollama`, `openai`, `gemini`, or `claude`.
   * **Step 2: API Host / Port**: Enter the address (e.g., `10.0.2.2:11434` for local Ollama, or `generativelanguage.googleapis.com:443` for Gemini).
   * **Step 3: API Key**: Type your API key (or leave it blank for local Ollama).
4. Once completed, the GUI compositor writes `/disk/heliox/config.json` and signals the daemon via IPC (`CONFIG_UPDATED`) to reload configuration and wake from the unconfigured state.

### Option B: Manual Configuration
Create or edit the configuration file at `/disk/heliox/config.json` via the shell:
```json
{
  "provider": "gemini",
  "api_host": "generativelanguage.googleapis.com",
  "api_port": 443,
  "api_key": "YOUR_GEMINI_API_KEY",
  "model_name": "default"
}
```
If you edit the file manually via the shell, reboot or run `services start heliox-daemon` (or signal the daemon via IPC) to reload the config.

## Design Rules

- Keep the kernel deterministic — no AI inference in kernel space.
- Every agent action goes through a real syscall — no stubs.
- Capability-checked boundaries between kernel and agent.
- Use Rust safety by default; keep unsafe blocks small and documented.
- Hardware first — if you want an agentic OS, you need drivers.
