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
- Interactive Desktop Taskbar with a Start-menu launcher, one entry per open window, and a working Exit button
- Movable, focusable GUI windows with close, minimize, and maximize buttons and interactive titles
- **Generic app-window framework**: any userland process can call `CreateWindow`/`PresentWindow`/`PollWindowInput` to own a real window backed by its own RGBA8 canvas and a per-window input queue — every window on the desktop, including the AI assistant panel, is a real userland app, not a kernel-hardcoded window type
- The launcher spawns real new ELF processes on demand (`crate::process::spawn_elf`), not just a fixed set of kernel-drawn windows
- App Store: a discovery surface listing every installed app with a description, so you don't need to already know an app exists to launch it
- PS/2 Mouse integration with 9-bit signed delta parsing and auto-recovery
- CPU-efficient main loop with interrupt-driven `hlt` architecture and off-screen double-buffering
- Hardware cursor rendering with dynamic drop-shadows
- Optional VirtIO-GPU 2D acceleration (`-device virtio-gpu-pci`) — when present, every composited frame is also delivered through the GPU's own resource/transfer/flush command set instead of only a raw framebuffer copy; purely additive, the existing Bochs VBE path remains the fallback when the device isn't attached

### Userland Apps
- **Heliox Assistant** — the AI agent's chat panel: setup wizard, message history, and live thinking/error/done state, all driven over a structured IPC protocol with the agent daemon (see Agent Daemon below)
- **Text Editor**, **Calculator**, **File Manager**, **Settings**, **Browser**, **App Store** — installed apps built on the generic app-window framework, all launchable from the desktop's Start menu or the App Store
- **`libferrumgui`** — shared `no_std` SDK crate (syscall wrappers including IPC send/receive, an RGBA8 `Canvas` with drawing primitives, input polling) so new apps don't hand-roll pixel math or the raw syscall ABI

### Package Manager (`ferrumpkg`)
- Real `pkg list|install|remove|run` shell command — install/remove genuinely gate whether a package can be launched at all, backed by a registry that persists across reboots, not a cosmetic UI toggle
- Packages are ordinary ELF binaries staged onto the appliance disk at build time (`scripts/make-appliance.ps1`), loaded and executed at runtime via the VFS — the kernel runs genuinely new code it was never compiled with, not just bookkeeping around pre-embedded apps
- Honestly scoped: this is a local package cache, not a network-fetched repository — no package server exists or is pretended to

### Multi-User Accounts
- Real, persistent user accounts (`useradd`, `login`, `whoami`, `accounts`) with a username, uid, capability profile, and home directory, stored at `/disk/accounts.txt`
- Logging in as a different account genuinely swaps the shell's held capabilities — a non-root `user` account can spawn processes and open GUI windows but is denied admin-only actions (reading the audit log, bypassing confirmation gates, quota exemption), not just cosmetically relabeled
- Three profiles: `root` (full access), `user` (a real usable desktop account), `guest` (read-only)

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
- VirtIO-GPU 2D driver (PCI modern-capability discovery, virtqueues, `RESOURCE_CREATE_2D`/`ATTACH_BACKING`/`SET_SCANOUT`/`TRANSFER_TO_HOST_2D`/`RESOURCE_FLUSH`), optional and additive
- Intel HDA audio controller with play/record/volume DMA
- XHCI USB 3.0 host controller with device enumeration
- USB HID keyboard and mouse (boot protocol)
- PS/2 keyboard and mouse via 8042 controller (IRQ1 & IRQ12)
- PIT 8254 timer, UART 16550 serial

### Agent Daemon (`heliox-daemon`)
- Bare-metal ReAct orchestrator (observe → think → act → verify → reflect)
- Multi-Provider Support: Natively connects to local Ollama or cloud models (OpenAI, Gemini, Claude) via host proxy
- Ambient Background Logic: Actively records voice from mic and performs anomaly screen vision checks
- Chat state (thinking / done / error, with the actual response text) streamed to the Heliox Assistant app over a structured IPC channel; user messages flow back the same way
- Stays genuinely idle — no autonomous ticking or inference — until the user has completed setup; a missing config file is never treated as an implicit choice
- JSON-RPC 2.0 surface over its WebSocket server: `ping`, `execute_tool`, `gesture_event`, `health`, `get_config`, `system_status`, `agent_stats`
- **World model safety gate**: before any tool call reaches real execution, a predictive layer estimates its effect and blocks it if the prediction looks dangerous (e.g. deleting the daemon's own config, a disk-filling write) — a second, predictive check alongside the existing reactive Tier 3/4 confirmation gate, not a replacement for it. Every tool call (allowed or blocked) is recorded as a training example to `/disk/heliox/world/exp.bin`. The prediction itself comes from a small MLP trained offline on real collected data (`scripts/train_world_model.py`) and loaded at boot the same way the real LLM checkpoint is, falling back to a hand-coded rule table whenever no trained weights are staged.
- Hierarchical planner with dependency-ordered task decomposition
- TF-IDF vector store with cosine similarity for persistent memory
- `no_std` JSON parser and LLM response decoder supporting OpenAI Chat Completions format
- 39 tools mapped to 39 kernel syscalls
- Config-driven setup via `/disk/heliox/config.json`

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
| Window manager, generic app-window framework, taskbar    |
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

## Appliance Packaging (Real Local Model)

`scripts/make-appliance.ps1` builds the kernel and packages a real, trained language-model checkpoint onto a disk image the OS mounts at `/disk` — this is what powers Heliox's on-device ("local") brain, as opposed to the tiny synthetic fixture used only by the automated test suite. It builds the boot image, then packages `appliance/models/stories15M-q8.bin` and `appliance/models/tokenizer.bin` (real weights and vocabulary — see `appliance/models/README.md` for provenance and how to regenerate them) into a fresh ext2 disk image at `target/heliox-disk.img`. The script fails loudly if those model assets are missing rather than silently shipping a placeholder.

```powershell
.\scripts\make-appliance.ps1
.\build.ps1 run-appliance
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
| `pkg list\|install\|remove\|run [name]` | Manage packages (ferrumpkg) |
| `useradd <name> [root\|user\|guest]` | Create a real user account |
| `login <name>` | Log in as an account, switching capabilities |
| `accounts` | List all registered user accounts |
| `whoami` | Show the current identity and held capabilities |
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

## JSON-RPC Methods (WebSocket, port 8785)

| Method | Description |
|---|---|
| `ping` | Liveness check, returns `"pong"` |
| `execute_tool` | Run one of the 39 agent tools by name with args |
| `gesture_event` | Report a gesture/HUD input event |
| `health` | Whether the daemon is configured yet, and which provider is active |
| `get_config` | Current runtime configuration (excludes the API key) |
| `system_status` | Live tick count, current goal, and hardware info |
| `agent_stats` | Telemetry ring-buffer summary: event count and the last event |

## Agent Tools (39 total)

| Tier | Tools |
|------|-------|
| **0 — Observe** | `system_info`, `list_processes`, `query_memory`, `get_config`, `add_subtask`, `camera_capture`, `gesture_status` |
| **1 — Safe** | `ipc_send`, `audit_write`, `yield_cpu`, `report_status`, `capability_check`, `read_file`, `read_dir`, `sleep`, `read_screen`, `set_volume`, `poll_input`, `local_inference` |
| **2 — Network** | `net_connect`, `net_send`, `net_recv`, `http_get`, `load_memory`, `set_goal`, `record_audio`, `browse_url` |
| **3 — Modify** | `write_file`, `create_directory`, `save_memory`, `service_start`, `service_stop`, `play_audio`, `keyboard_type`, `mouse_click`, `mouse_move` |
| **4 — Destructive** | `exec_process`, `delete_file`, `trigger_kernel_upgrade` |

## Heliox Daemon Setup

Heliox is always the OS's native agent — it isn't something you choose to enable. The only thing setup decides is **which brain powers it**: an on-device model, or a cloud provider's API. There are two ways to set this up:

> [!NOTE]
> **RAM Filesystem Fallback**: The kernel pre-creates `/disk/heliox/` as a directory within the RAM filesystem (`RamFS`) at boot. If a physical Ext2 formatted ATA disk is not mounted at `/disk`, all configuration writing and loading will transparently fall back to the RAM filesystem, allowing you to use the setup wizard or shell without any partition setup.

### Option A: Interactive Setup (Heliox Assistant)
1. Boot the OS and launch the graphical desktop:
   ```
   FerrumOS:~$ desktop
   ```
   If no configuration exists yet, the **Heliox Assistant** app window launches automatically.
2. Click inside the **Heliox Assistant** window to focus it.
3. Follow the setup wizard by typing your choice at each step and pressing **Enter**:
   * **Step 1 — Local or Cloud?** Type `local` (on-device, works offline) or `cloud` (OpenAI / Claude / Gemini).
   * If **local**: choose `tiny` (the built-in model, auto-sized to your hardware tier) or `ollama` (a local Ollama server — you'll then be asked for its `host:port`, e.g. `10.0.2.2:11434`).
   * If **cloud**: choose a provider (`openai`, `claude`, or `gemini`), then enter your API key.
4. Once completed, the GUI compositor writes `/disk/heliox/config.json` and signals the daemon via IPC (`CONFIG_UPDATED`) to reload configuration and wake from the unconfigured state.

### Option B: Manual Configuration
Create or edit the configuration file at `/disk/heliox/config.json` via the shell. For a cloud provider:
```json
{
  "provider": "gemini",
  "api_host": "generativelanguage.googleapis.com",
  "api_port": 443,
  "api_key": "YOUR_GEMINI_API_KEY",
  "model_name": "default"
}
```
For the on-device model, set `"provider": "local"` (auto-sizes to your hardware tier) and omit the API fields. If you edit the file manually via the shell, reboot or run `services start heliox-daemon` (or signal the daemon via IPC) to reload the config.

## Design Rules

- Keep the kernel deterministic — no AI inference in kernel space.
- Every agent action goes through a real syscall — no stubs.
- Capability-checked boundaries between kernel and agent.
- Use Rust safety by default; keep unsafe blocks small and documented.
- Hardware first — if you want an agentic OS, you need drivers.
