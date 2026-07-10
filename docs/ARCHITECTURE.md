# FerrumOS Architecture

## Design Principles

1. **Kernel is deterministic** — no AI inference, no probabilistic models in
   kernel space. The kernel owns scheduling, memory, interrupts, and drivers.
2. **Agent lives in userspace** — the AI brain (`heliox-daemon`) runs as a
   freestanding Ring-3 process with syscall-only access to hardware.
3. **Every action is a syscall** — the agent cannot bypass the kernel. All 37
   agent tools translate to real kernel syscalls, out of 47 syscalls total
   (IDs 0–46) — the rest back GUI/app-window, audio, and other non-agent
   userland surfaces.
4. **Capability-gated** — default deny. Services receive only the capabilities
   required for their task.
5. **Hardware first** — an agentic OS needs real drivers, not stubs.

## System Layers

```text
┌──────────────────────────────────────────────────────────┐
│ Agent Layer (heliox-daemon)                              │
│ ReAct orchestrator, multi-provider network client (LLM), │
│ ambient mic/vision recording, multi-agent domain routing │
├──────────────────────────────────────────────────────────┤
│ Cognitive Layer (heliox-daemon)                          │
│ Vector store, TF-IDF, planner, reflector, JSON decoder   │
├──────────────────────────────────────────────────────────┤
│ Runtime Layer                                            │
│ Service manager, IPC broker, capability checks,          │
│ 37 tool ↔ syscall mapper, 5-tier permissions             │
├──────────────────────────────────────────────────────────┤
│ GUI & Compositor Layer                                   │
│ Window manager, generic app-window framework, taskbar    │
├──────────────────────────────────────────────────────────┤
│ Kernel Layer                                             │
│ Boot, GDT/IDT, page tables, heap, preemptive scheduler,  │
│ ELF loader, Ring-3 entry, SMP, ACPI                      │
├──────────────────────────────────────────────────────────┤
│ Storage Layer                                            │
│ ATA PIO driver, Ext2 filesystem, RamFS, VFS mount table  │
├──────────────────────────────────────────────────────────┤
│ Hardware Layer                                           │
│ RTL8139 NIC, Intel HDA audio, XHCI USB 3.0, USB HID,     │
│ VGA/Bochs framebuffer, PS/2 keyboard/mouse, PIT, UART    │
└──────────────────────────────────────────────────────────┘
```

The cognitive and agent layers run inside the `heliox-daemon` userspace binary
and can evolve without destabilizing the kernel.

## Kernel Core

### Boot Sequence

1. BIOS/UEFI → `bootloader` crate hands control to `_start`
2. GDT, IDT, PIC (8259) remapped, PIT configured
3. Page tables from boot info, frame allocator initialized
4. Kernel heap mapped (12 MiB at `0x4444_4444_0000` to support double-buffering)
5. Preemptive scheduler with idle task
6. Device discovery (PCI bus scan, NIC, audio, USB)
7. Filesystem mount (RamFS at `/`, Ext2 at `/disk`)
8. Shell task spawned → interactive prompt

### Memory

- Boot-info frame allocator for physical pages
- 4-level page tables with mapper
- Kernel heap: 12 MiB, bump allocator with linked-list fallback
- DMA: `allocate_contiguous_frames(n)` for NIC TX/RX and HDA BDL buffers
- Demand paging: Page-fault handler resolved via on-demand file block reads from Ext2/VFS for memory-mapped files (`mmap`)

### Scheduler

- Preemptive round-robin with 4 priority levels
- Context switching via `switch_to()` assembly stub
- Per-task kernel stacks, sleep/wake/yield syscalls
- PID assignment, task state tracking (Ready/Running/Blocked/Dead)

### Syscall Dispatch

47 syscalls (IDs 0–46) dispatched via `int 0x80`:

- Process: Yield(0), Exec(18), Wait(13), Exit(30), GetPid(31), Sleep(32), WaitPid(33)
- IPC: Send(1), Receive(2)
- Services: Start(3), Stop(4)
- Security: CapCheck(5), AuditWrite(6), GetRandom(42)
- Network: Socket(7), Bind(8), Listen(9), Accept(10), Recv(11), Send(12), Connect(14), Close(35)
- Filesystem: ReadFile(15), WriteFile(16), ReadDir(17), CreateDir(21), DeleteFile(22)
- Memory: Mmap(41)
- Graphics: ReadFbInfo(19), ReadTextBuffer(20), HudUpdate(39), HitTest(40)
- GUI app windows: CreateWindow(44), PresentWindow(45), PollWindowInput(46) — generic per-process windows, see below
- Audio: PlayAudio(23), RecordAudio(24), SetVolume(25)
- Input: InjectKey(26), InjectMouse(27), PollInput(28)
- Camera: ReadCameraFrame(36), CameraInfo(37)
- Query: SystemQuery(29) — returns JSON for system info, processes, memory, devices; Write(34) (write to console/serial); GetTime(43) (RTC read, e.g. for TLS cert validity checks)
- Kexec: Kexec(38)

## Graphical Desktop Environment (GUI)

The OS features a fully integrated windowing system and compositor:

### Compositor & Window Manager
- Double-buffered rendering via VGA framebuffer (1024x768x32bpp)
- Z-indexed overlapping windows with focus management
- Interactive title bars (drag-to-move) with close, minimize, and maximize buttons, all computed from shared rect helpers on `Window` (`close_btn_rect`/`maximize_btn_rect`/`minimize_btn_rect` in `src/gui/window.rs`) so rendering and hit-testing can't drift apart
- Minimized windows are skipped by rendering and hit-testing but keep a taskbar entry; maximize snaps a window to the desktop content area and remembers its prior geometry to restore
- Desktop taskbar with a Start-menu launcher, a dynamic per-window button (one slot per open window, up to `MAX_TASKBAR_SLOTS`), and a working Exit button — all positions computed once by `desktop::compute_taskbar_layout()` and shared between rendering and every click/hover hit-test
- App Store: a discovery surface listing every installed app with a description, launching any of them via the same mechanism as the Start-menu launcher

### Generic App-Window Framework
Beyond the three kernel-drawn window types (`Normal`, `SystemMonitor`, `Terminal`), `WindowType::App(pid)` lets **any** userland process own a real window — including the Heliox Assistant, which used to be a fourth kernel-hardcoded type (`AgentHud`) before it was rebuilt as an ordinary app on this framework:
- `CreateWindow(title, canvas_w, canvas_h)` allocates a window whose total size is the requested canvas plus shared chrome (`CHROME_SIDE`/`CHROME_TOP`/`CHROME_BOTTOM` in `src/gui/window.rs`) — apps never need to know about title-bar/border geometry.
- `PresentWindow(window_id, rgba8_buf)` copies a caller-owned RGBA8 buffer into the window's canvas (`src/gui/app_window.rs`); `render()` blits it verbatim for `App` windows, the same title bar/border/close-button chrome as every other window type.
- `PollWindowInput(window_id)` drains a per-window input queue (keyboard + mouse-down, capped at 64 events) fed by `compositor::handle_key_press`/`handle_mouse_down` whenever an `App` window is focused.
- Gated behind the `gui:window:*` capability (`cap:gui:window`), following the same capability-registry pattern as every other resource-gated syscall.
- App windows persist across `desktop` re-entry and keep focus across it (`spawn_demo_windows()` only resets the kernel-drawn demo set) — closing one via its `[X]` cleans up its input queue (`app_window::on_window_closed`).

### App Launcher & Installed Apps
The Start-menu launcher (`src/gui/desktop.rs` popup, `src/gui/compositor.rs::LAUNCHER_ENTRIES`) can spawn real new processes, not just the kernel-drawn built-ins:
- `crate::process::spawn_elf(name, elf_bytes, granted_caps)` (`src/process/mod.rs`) loads an ELF and registers it as a Ready scheduler task directly from kernel context — the same load/register logic `sys_exec` uses for a ring-3 caller, but with capabilities taken straight from the program's `crate::userspace` manifest instead of delegated from a caller. It only registers the task and returns; it never itself enters ring 3, so it's safe to call from the compositor's own render loop.
- Installed apps (`userland/heliox-assistant-panel/`, `userland/text-editor/`, `userland/calculator/`, `userland/file-manager/`, `userland/settings/`, `userland/browser/`, `userland/app-store/`) are ordinary ELF binaries built on `userland/libferrumgui/` — a shared `no_std` SDK (syscall wrappers including `ipc_send`/`ipc_receive`, an `InputEvent` type, an RGBA8 `Canvas` with `fill_rect`/`draw_string`/`present`, using a userland copy of the kernel's bitmap font) — registered in the same `crate::userspace` program-manifest registry as `init`/`heliox-daemon`. The Heliox Assistant panel additionally uses `ipc_send`/`ipc_receive` to exchange chat state with `heliox-daemon`; Browser uses the raw socket syscalls (`Socket`/`Connect`/`Send`/`Recv`) directly; App Store calls `spawn_elf` to launch other installed apps by path.
- Each app owns a fixed-size heap (`#[global_allocator]` over a static array) sized comfortably above its own canvas buffer (`canvas_w * canvas_h * 4` bytes) — undersizing this causes a silent allocation failure and process exit on the very first frame, with no panic message, since apps don't need argv (there's no mechanism for it) and instead operate on fixed paths (Text Editor) or read-only browsing (File Manager).

### Package Manager (`src/pkg/mod.rs`)

Real `pkg list|install|remove|run` semantics, honestly scoped: packages
are a local cache staged onto the appliance disk at *build* time
(`scripts/make-appliance.ps1`, via `debugfs` - the same mechanism that
packages the real model checkpoint), not fetched from any network
repository. Two on-disk locations:
- `/disk/pkgs-available/<name>/{manifest.txt,bin}` - every package that
  exists on the image, whether installed or not. `manifest.txt` is a flat
  `key=value` format (no JSON parser exists in kernel space), declaring
  `capabilities` from a fixed allow-list (`cap:gui:window`, `cap:fs:read`,
  `cap:fs:write`, `cap:audio:play` - never network/exec/quota/confirmation
  tokens).
- `/disk/pkgs/registry.txt` - the only thing `install`/`remove` actually
  write at runtime: a small list of installed package names. A package's
  (potentially large) `bin` is never physically copied at install time -
  ext2's own `create_file` only supports direct blocks (12 max), far too
  small for a compiled ELF, so the same bytes `debugfs` staged are read
  from `pkgs-available` either way; install/remove only toggle whether
  `sys_exec` (`src/syscall/process.rs`) will actually run them.

`sys_exec`'s VFS-read fallback path recognizes a `pkgs-available/<name>/bin`
path shape, checks `pkg::is_installed(name)` before reading the file at
all, and resolves capabilities from the package's own manifest
(`pkg::capabilities_for`) instead of the empty result
`capabilities_for_program` would otherwise return for a name it wasn't
compiled with. The `pkg run` shell command (kernel context) additionally
calls `userspace::register_dynamic_program` before `process::enter_registered`
(see "Ring-3 scheduling from a cold shell" below) so that first-entry path's
own capability re-derivation sees the same clamped set.

**A real bug this uncovered:** ext2's `Filesystem::read_file` does a
strict `String::from_utf8` over the raw inode bytes - correct for
config/text files, but a real ELF binary is essentially never valid
UTF-8. `sys_exec`'s fallback for loading *any* program from the VFS
(compiled-in or a package) went through this and would have failed on
every real binary; this was never caught before because every app until
now loaded from an embedded `include_bytes!` constant, never through this
path. Fixed by `fs::read_file_bytes` (`src/fs/mod.rs`), which pulls the
whole file through the already binary-safe `read_file_offset` (the same
call `mmap`'s demand-paging already proved safe for the model checkpoint)
instead of a single UTF-8-checked slurp.

**Ring-3 scheduling from a cold shell.** Timer-interrupt-driven preemption
(`timer_interrupt_entry_inner`) only ever switches *away* from a
currently-running ring-3 task (`frame.cs & 3 == 3`) - it never switches
*into* one. Every existing verified app launch happens either from
`run_desktop()`'s loop (which is itself continuously entering/preempting
ring-3 code every frame) or from `ring3 init`'s explicit first entry. A
package launched via `pkg run` from a plain, otherwise-idle kernel shell
prompt hit this directly: `spawn_elf` registered the task as Ready, but
with nothing already executing in ring 3 to preempt from, it sat Ready
forever and never printed a single line. Fixed by having `pkg run` call
`process::enter_registered` right after `spawn_elf` - the same explicit
first ring0→ring3 transition the `ring3 <pid>` shell command already uses
for compiled-in programs.

### Event Routing
- Unified `InputEvent` queue bridging PS/2 hardware, USB HID, and syscall injections
- `cursor::process_input()` is the single shared entry point every render/input pump goes through (both `run_desktop()`'s loop and `SYS_HUD_UPDATE`'s ambient pump call it) — it discards whatever piled up in the queue the first time it's ever called, so keystrokes typed before anything was compositing yet don't replay into whatever window happens to get focus first
- Main GUI loop utilizes `hlt` for 0% idle CPU usage, waking only on hardware IRQs
- Mouse events support 9-bit signed deltas with overflow protection
- Real-time hover state feedback for dock buttons and window controls

## Filesystem

### VFS

Longest-prefix mount matching. Currently two mounts:

| Mount | Type | Description |
|-------|------|-------------|
| `/` | RamFS | Volatile in-memory filesystem |
| `/disk` | Ext2 | ATA PIO block storage, persistent |

### Ext2

- Superblock, block groups, inode table parsing
- File read/write with direct and singly-indirect blocks
- Directory traversal and entry creation
- Block and inode allocation bitmaps
- Sync writes back to ATA disk

## Hardware Drivers

### RTL8139 NIC

- PCI device discovery, BAR0 MMIO mapping
- TX descriptor ring with static frame pool (no leak)
- RX ring buffer with wrap-around parsing
- smoltcp TCP/IP stack integration with socket API
- IP: 10.0.2.15/24, gateway: 10.0.2.2 (QEMU user mode)

### Intel HDA Audio

- PCI BAR0 MMIO register access
- CORB/RIRB command/response ring buffers
- Codec discovery via verb/parameter walking
- Output stream: BDL + DMA buffer, 48 kHz 16-bit stereo
- Input stream: same configuration for recording
- Volume control via output amplifier gain verbs

### XHCI USB 3.0

- PCI BAR0 capability register parsing
- Device context array and command ring allocation
- TRB (Transfer Request Block) ring management
- Port status change detection and device slot assignment
- MMIO-based controller reset and initialization

### PS/2 & USB Input Subsystem

- 8042 PS/2 Controller: IRQ1 (Keyboard) and IRQ12 (Mouse) edge-triggered handlers
- Mouse packet synchronization with auto-recovery timeouts
- USB HID: Boot protocol keyboard and mouse support via endpoint polling
- Scancode-to-ASCII translation

### VGA Framebuffer

- Bochs VBE mode switching to 1024×768×32bpp
- Pixel drawing primitives: fill_rect, draw_char, draw_string
- Console with scrolling text renderer
- Screen vision: capture framebuffer text for agent read_screen tool

### VirtIO-GPU 2D Driver (`src/devices/virtio_gpu.rs`) — optional, additive

Real hardware-mediated 2D acceleration, honestly scoped: Bochs VBE (the
driver above, and the only display path every other boot configuration
uses) is a bare linear framebuffer with no blit/fill engine at all, so a
genuine "GPU acceleration" claim needs a device that actually has
resource/transfer semantics - VirtIO-GPU in 2D mode (no virgl/3D) is that
device.

- **PCI modern-capability discovery** — walks the standard PCI
  capability list (not the XHCI-style extended-capability list used
  elsewhere) looking for the vendor-specific `virtio_pci_cap` structures
  (`find_virtio_cap`) to locate the COMMON_CFG and NOTIFY_CFG BAR
  regions, rather than assuming a fixed BAR/offset layout.
- **Virtqueue** — a deliberately minimal split-ring implementation: one
  descriptor table, one available ring, one used ring (each its own
  page, wasteful but simple), and only ever one command in flight at a
  time (`send_sync`) — always descriptor slots 0/1, polling the used
  ring for completion rather than handling interrupts, matching this
  codebase's existing ATA PIO polling precedent.
- **2D command set** — `RESOURCE_CREATE_2D` + `RESOURCE_ATTACH_BACKING`
  + `SET_SCANOUT` once at first present; `TRANSFER_TO_HOST_2D` +
  `RESOURCE_FLUSH` every frame after. The backing store is a contiguous
  DMA buffer (`allocate_contiguous_frames`) the CPU still composites
  into — the acceleration is in how the finished frame reaches the
  display (a GPU-mediated resource/transfer/flush instead of a raw
  synchronous MMIO copy loop), not in offloading the composition itself.
- **Purely additive integration** — `src/devices/vga_fb.rs`'s
  `swap_buffers()` (the single existing present chokepoint) still always
  does its original raw MMIO copy unconditionally, and *additionally*
  calls `virtio_gpu::present()` when `is_available()`. Every existing
  boot configuration (every `verify_*.mjs` script that doesn't add
  `-device virtio-gpu-pci`) never even calls into this module —
  confirmed by rerunning the full GUI regression suite unchanged after
  this driver landed.
- **Not yet implemented**: per-frame dirty-rect transfer (today's
  `present()` always transfers the whole frame) and `GET_DISPLAY_INFO`-driven
  scanout sizing (the resolution is matched to `vga_fb`'s fixed
  1024×768 instead of queried from the device) — both real, natural
  follow-ups, not silently assumed done.

### Verification — `scripts/verify_virtio_gpu.mjs` — 5/5 PASS
The only script that adds `-device virtio-gpu-pci`: confirms the device
initializes, confirms the desktop's normal compositor loop runs several
real frames through it (driven by actual mouse-move events forcing
redraws) with no `present()` failure logged and no fault/panic.

## Networking Stack

### TCP/IP (smoltcp)

- Full TCP state machine with connection tracking
- Socket handle table (16 slots)
- Periodic polling in timer IRQ handler

### HTTP Client

- `http_get(host, port, path)` — bare-metal HTTP/1.1 GET
- `http_post(host, port, path, body)` — JSON POST for LLM APIs
- 32 KB response buffer
- Hardcoded DNS resolver for QEMU gateway addresses

### WebSocket Client (RFC 6455)

- HTTP Upgrade handshake
- Frame parsing: FIN, opcodes (text/binary/close/ping/pong)
- Client-side masking via RDTSC
- Extended payload lengths (126/127 modes)
- Auto ping/pong and close handshake
- Used for streaming LLM responses

## Agent Daemon (heliox-daemon)

### Cognitive Architecture

```text
         ┌─────────┐
         │  GOAL    │
         └────┬─────┘
              │
     ┌────────▼────────┐
     │    OBSERVE       │ ← domain classification, RAG, lessons
     └────────┬─────────┘
              │
     ┌────────▼────────┐
     │     THINK        │ → LLM query (Ollama/OpenAI)
     └────────┬─────────┘
              │
     ┌────────▼────────┐
     │      ACT         │ → parse tool call → syscall
     └────────┬─────────┘
              │
     ┌────────▼────────┐
     │    VERIFY        │ ← check output, keyword match
     └────────┬─────────┘
              │
     ┌────────▼────────┐
     │    REFLECT       │ → record failure, update lessons
     └────────┬─────────┘
              │
              └──→ loop back to OBSERVE
```

### Ambient Intelligence & Multi-Provider Support

The agent daemon continuously buffers 1-second chunks of audio from the Intel HDA hardware. When voice activity is detected, it transcribes the audio and generates a new `GOAL:`, bridging the physical world with the ReAct loop. It also periodically screenshots the desktop to proactively solve GUI errors.

The `network.rs` client is dynamically driven by the daemon's runtime configuration, supporting two payload schemas:
1. **Ollama Format:** Flat `{"model", "prompt"}` JSON.
2. **OpenAI Chat Format:** `{"messages": [{"role", "content"}]}` with `Authorization: Bearer` headers (supporting OpenAI, Gemini, and Claude via host proxy wrappers).

The on-device ("local") brain is a real, trained checkpoint — a quantized int8 llama2.c-format model, memory-mapped from `/disk/heliox/models/` and packaged onto the appliance disk image by `scripts/make-appliance.ps1` (see `appliance/models/README.md` for provenance). It is not a placeholder: the daemon dequantizes and runs the actual weights, producing genuine generated text rather than a synthetic fixture.

Until a configuration file actually exists on disk, the daemon stays idle: no ticking, no autonomous inference, `provider` stays `"auto"` unresolved. A missing config file is never treated as an implicit choice of hardware-tier-appropriate provider — that resolution only happens once a config file is present (whether written by the setup wizard or by hand), so the daemon never starts real computation before the user has actually chosen anything.

### JSON-RPC Interface

The daemon exposes a JSON-RPC 2.0 surface over its WebSocket server (port 8785): `ping`, `execute_tool` (runs one of the 39 agent tools), `gesture_event`, `health` (configured state + active provider), `get_config` (live config fields, excluding the API key), `system_status` (tick count, current goal, hardware info), and `agent_stats` (telemetry ring-buffer summary). All are backed by real orchestrator/config state rather than stubs — `system_status`'s tick count strictly advances between calls, and `agent_stats` correctly reports an empty buffer while the daemon is idle/unconfigured.

### Chat IPC with the Heliox Assistant App

The daemon and the Heliox Assistant app-window (`userland/heliox-assistant-panel/`) exchange state over two IPC channels rather than one hardcoded telemetry string:
- `CHAT:{role}:{state}:{content}` — sent by the daemon to the `"assistant"` IPC service on every think/act cycle, with `state` one of `thinking`, `error`, or `done`, and `content` the actual human-readable response text once done. The app parses this into a real chat history.
- `GOAL:{text}` — sent by the app to the `"heliox"` service when the user submits a chat message, reusing the same mechanism the setup wizard uses for `CONFIG_UPDATED` reloads.

### Components

| Module | File | Role |
|--------|------|------|
| Orchestrator | `orchestrator.rs` | ReAct loop, telemetry, IPC polling |
| Planner | `planner.rs` | Goal decomposition, dependency DAG, prompt generation |
| Verifier | `verifier.rs` | Output checking, retry counting |
| Reflector | `reflector.rs` | Failure recording, lesson extraction |
| Confirmation | `confirmation.rs` | 5-tier permission gates for destructive tools |
| Tool Mapper | `tool_mapper.rs` | 37 tools → syscall dispatch + INTERNAL routing |
| Vector Store | `vector_store.rs` | TF-IDF embeddings, cosine search, disk persistence |
| Web Agent | `web_agent.rs` | HTML stripping, entity decode, link/title extract |
| Multi-Agent | `multi_agent.rs` | Domain classifier (Code/Web/System/Files/General) |
| Screen Vision | `screen_vision.rs` | Framebuffer text capture |
| Voice | `voice.rs` | Audio record/play/volume control |
| JSON | `json.rs` | `no_std` recursive-descent JSON parser |
| Config | `config.rs` | Runtime config from `/disk/heliox/config.json` |
| Network | `network.rs` | TCP socket wrapper, HTTP/WS client |
| World Model | `world_model/` | Predictive safety gate + experience buffer (see below) |

### World Model Safety Gate (`cognitive/world_model/`)

A predictive layer in front of `act()`'s tool dispatch, alongside (not
instead of) the reactive `ConfirmationGate` above. Before any tool call
reaches `tool_mapper::execute`, it's evaluated against a small internal
model of what the call would do to the system, and blocked if the
prediction looks dangerous - catching classes of harm a fixed permission
tier can't enumerate (a `write_file` call isn't Tier 4, but predicting
that it targets the daemon's own config file is still worth blocking).

- **Observation** — samples live OS state (process count, heap usage,
  filesystem entries, screen text) through the same syscalls the
  daemon's existing tools already use (`SystemQuery`, `ReadDir`,
  `read_screen`'s `ReadTextBuffer`) - no new syscalls, no new
  capabilities.
- **Encoding** — compresses that snapshot into a fixed-size numeric
  vector, hand-crafted today (no machine learning), with room reserved
  for a learned encoder later without changing anything above it.
- **Transition prediction** — two interchangeable sources behind the
  same `predict_next_state` call: a hand-coded rule table mapping each
  higher-consequence tool (`write_file`, `delete_file`, `exec_process`,
  `create_directory`, `service_start`/`stop`, `trigger_kernel_upgrade`,
  `net_connect`) to its predicted effect on that vector, or - when
  present - a small MLP (`cognitive/world_model/learned.rs`) trained
  offline on real collected data (`scripts/collect_world_model_dataset.mjs`
  + `scripts/train_world_model.py`, pure numpy) and loaded at boot the
  same way the real LLM checkpoint is (a flat `f32` binary read via
  `SYS_READ_FILE`). The learned model predicts an embedding *delta*, not
  the absolute next state; whether a config-deleting `delete_file` call
  gets caught is always a direct argument check, independent of which
  source produced the numeric prediction.
- **Risk scoring** — flags specific predicted outcomes (disk nearly
  full, the daemon's own config file about to be deleted, heap nearly
  exhausted) and blocks the real syscall if the combined score crosses
  a threshold, logging the block to the console.
- **Experience buffer** — every tool call, allowed or blocked, is
  recorded as a compact fixed-size record to `/disk/heliox/world/exp.bin`
  (front-truncated once capped, the same pattern the audit log uses) -
  passive training data for a future learned version of the same gate.
  Capped well below ext2's direct-block write ceiling (`create_file`
  only supports up to 12 direct blocks - a real, previously-undiscovered
  filesystem limit this surfaced), since the buffer is rewritten in full
  on every append.

### Permission Tiers

| Tier | Level | Auto-approve | Example Tools |
|------|-------|-------------|---------------|
| 0 | Observe | ✅ Always | `system_info`, `query_memory`, `camera_capture`, `gesture_status` |
| 1 | Safe | ✅ Default | `read_file`, `read_dir`, `read_screen`, `poll_input`, `local_inference` |
| 2 | Network | ✅ Default | `http_get`, `browse_url`, `net_connect` |
| 3 | Modify | ⚠️ Configurable | `write_file`, `play_audio`, `keyboard_type` |
| 4 | Destructive | 🔒 Confirmation | `exec_process`, `delete_file`, `trigger_kernel_upgrade` |

### Multi-Agent Domain Routing

The orchestrator classifies each goal into a domain and appends a specialized
prompt suffix to focus the LLM:

| Domain | Keywords | Prompt Focus |
|--------|----------|-------------|
| Code | code, function, debug, compile | `read_file`, `write_file`, `exec_process` |
| Web | browse, url, http, website | `browse_url`, `http_get` |
| System | process, memory, device, status | `system_info`, `list_processes` |
| Files | file, directory, read, write | `read_file`, `write_file`, `read_dir` |
| General | (fallback) | All tools |

Per-domain success rates are tracked and reported.

## Security Model

### Capabilities

Explicit permission tokens. Default deny. Each process receives a delegated
capability set at launch from its parent process via `sys_exec`, which filters
delegatable tokens.

| Profile | Token | Access |
|---------|-------|--------|
| root | `cap:system:all` | Full system management |
| guest | `cap:fs:read` | Read-only filesystem |
| daemon | `cap:quota:exempt` | Bypasses syscall rate & continuous CPU limits |
| daemon | `cap:confirmation:bypass` | Bypasses kernel-side confirmation gates |

### Multi-User Accounts

Real accounts (`src/accounts/mod.rs`), not just the two debug session
profiles above: a persistent registry at `/disk/accounts.txt` (one
colon-separated `uid:username:profile:home` record per line, deliberately
shaped like a classic `/etc/passwd` line). `useradd <name> [root|user|guest]`
creates an account and its home directory (`/disk/home/<name>/`); `login
<name>` swaps the interactive shell's active session to that account,
which resolves to a real capability set via
`accounts::capabilities_for_profile` - not merely a display-name change.

The `user` profile is a genuinely usable middle ground between `root` and
`guest`: `cap:fs:read`, `cap:fs:write`, `cap:process:spawn`,
`cap:gui:window`, `cap:ipc:send`, `cap:net:connect`, `cap:audio:play`,
`cap:camera:read` - enough to run apps and use the desktop, but none of
root's admin-only tokens (`cap:quota:exempt`, `cap:confirmation:bypass`,
`cap:system:kexec`, `cap:process:kill`, `cap:audit:read`,
`cap:agent:control`, `cap:net:listen`, `cap:service:register`). A
logged-in non-root account is provably denied capability-gated commands
(e.g. `log`, which requires `audit:read`) until logging back in as root -
verified end-to-end by `scripts/verify_accounts.mjs`.

Deliberately out of scope: per-file ownership/permission-bit enforcement
on ext2 inodes (the inode format has `uid`/`mode` fields, but nothing
currently checks them against the calling process's account). Access
control today is entirely at the capability layer, not the filesystem
layer.

### Resource Quotas

To prevent rogue or runaway agent scripts from degrading system performance or freezing the kernel:
- **Memory Mapping Bounds**: Processes are restricted to a maximum memory mapping quota of 2048 pages (8 MiB) inside `map_user`. Exceeding this triggers a frame allocation error.
- **Continuous CPU execution limit**: The scheduler monitors tasks and reaps any user task that executes consecutively for more than 100 ticks (~5.5s) without yielding (`sys_yield`) or sleeping (`sys_sleep`). Reaped processes exit with code 140.
- **Syscall Rate Limiting**: Restricts processes to 5000 system calls per 200-tick window (~11s) — sized to comfortably accommodate a real interactive GUI app's normal poll/sleep loop, not just brief scripted interactions. Violations result in immediate process termination (exit code 140) and logging.

### Audit Log

All denied operations, lifecycle events, and agent reasoning telemetry are
recorded in the kernel audit log. Accessible via the `log` shell command.
- **Out-of-Interrupt Persistence**: Disk writes inside interrupts (such as timer IRQs) are avoided to prevent deadlocks. An atomic `FLUSH_PENDING` flag is set by the timer interrupt.
- **Deferred Disk Sync**: The log is flushed from memory to `/disk/heliox/audit.log` during safe out-of-interrupt contexts: syscall returns, process termination/reaping, and system shutdown/reboot.
- **Log Truncation**: The persistent log is capped at 128KB, using character/newline-aligned front-truncation when the size limit is exceeded.

### Agent Confirmation Gates

Kernel-side confirmation gates are enforced for destructive Tier-4 operations (specifically `DeleteFile`, syscall 22):
- **Syscall Suspension & Sleep Timeout**: When a gated syscall is called by a process lacking `cap:confirmation:bypass`, the calling process is placed into a `Blocked` state and given a 5-second default-deny sleep timeout.
- **Instruction Pointer Rewinding (RIP-2)**: The saved user context frame's `rip` is decremented by 2 bytes. Because the `int 0x80` assembly instruction is exactly 2 bytes (`CD 80`), rewinding the instruction pointer causes the process to re-execute the system call immediately upon waking.
- **Physical vs. Injected Key Filter**: Gates can only be approved by typing `y` (or denied with `n`) on a physical serial console or keyboard. Synthetic keystrokes injected by the agent via `sys_inject_key` are filtered using the `INJECTING_AGENT_KEY` atomic boolean, preventing the agent from autonomously bypassing its own security gates.
- **Retry-and-Cache State**: When resumed, the process re-executes `int 0x80` and references the cached `confirmation_approved` or `confirmation_denied` fields on the task context to either complete the operation or return `-2` (`PermissionDenied`) without prompting again.


## Configuration

Heliox is always the OS's native agent — it isn't a setup choice. Configuration only decides which brain powers it, and can be set in two ways:

> [!NOTE]
> **RAM Filesystem Fallback**: The directory `/disk/heliox/` is pre-created within the RAM filesystem (`RamFS`) during boot. If a physical Ext2 disk is not mounted at `/disk`, configuration writing (via the assistant app) and reading (via the daemon) will fall back to memory transparently, avoiding any errors.

### 1. Interactive Desktop Wizard (Heliox Assistant app)
If no configuration exists at boot, the **Heliox Assistant** app-window auto-launches in setup mode on the desktop (triggered once, from `sys_hud_update`, the first time the daemon's ambient loop pumps after boot), walking through a branching choice rather than a flat list:
- **Step 1 — Local or Cloud?** `local` (on-device, works offline) or `cloud` (OpenAI / Claude / Gemini).
- **If local:** `tiny` (the built-in model, auto-sized to hardware tier) or `ollama` (prompts for a `host:port`, e.g. `10.0.2.2:11434`).
- **If cloud:** pick a provider (`openai` / `claude` / `gemini`), then enter its API key.

Once completed, the app writes the `/disk/heliox/config.json` file and sends an IPC event `CONFIG_UPDATED` to wake/reload the agent daemon.

### 2. Manual Configuration File
Alternatively, the agent reads runtime config directly from `/disk/heliox/config.json`:

```json
{
  "model_name": "llama3",
  "api_host": "10.0.2.2",
  "api_port": 11434,
  "api_path": "/api/generate",
  "max_retries": 3,
  "tick_interval": 100,
  "save_interval": 1000,
  "confirmation_timeout": 600,
  "log_level": "info",
  "auto_approve_tier": 2
}
```

All fields have sensible defaults. Missing or malformed config silently falls
back. If manually editing this file, restart the daemon (`services stop heliox-daemon` then `services start heliox-daemon`) or reboot the system to apply changes.

## Source Tree

```text
src/
├── main.rs               # Kernel entry point
├── memory/               # Heap, frame allocator, page tables
├── scheduler/            # Preemptive scheduler, context switch
├── interrupts/           # IDT, PIC, keyboard, timer
├── fs/                   # VFS, RamFS, Ext2
├── ata/                  # ATA PIO block driver
├── net/                  # RTL8139 NIC, smoltcp interface
├── devices/              # PCI, HDA audio, XHCI USB, VGA FB, VirtIO-GPU (optional)
├── input/                # Unified input queue, USB HID, PS/2
├── audio/                # Audio mixer, PCM interface
├── graphics/             # Drawing primitives, console
├── gui/                  # Compositor, window manager, desktop, app windows
├── security/             # Capabilities, audit log
├── services/             # Service manager, manifests
├── ipc/                  # IPC broker
├── syscall/              # Dispatch, fs, process, query, gui windows
├── shell/                # Shell, commands, dashboard
├── pkg/                  # Package manager (ferrumpkg): install/remove/list
├── accounts/             # Multi-user account registry
└── process/              # ELF loader, Ring-3, address spaces

userland/heliox-daemon/
├── src/
│   ├── main.rs           # Daemon entry, main tick loop
│   ├── config.rs         # Runtime configuration
│   ├── network.rs        # TCP, HTTP, WebSocket client
│   ├── memory/
│   │   └── vector_store.rs   # TF-IDF vector store
│   └── cognitive/
│       ├── orchestrator.rs   # ReAct loop
│       ├── planner.rs        # Task decomposition
│       ├── tool_mapper.rs    # 37 tools → syscalls
│       ├── gesture.rs        # Classical CV skin & hand gesture recognition
│       ├── inference.rs      # Local no_std GGUF/Q4 toy inference runner
│       ├── self_evolve.rs    # Host-assisted self-evolution kexec trigger
│       ├── verifier.rs       # Output verification
│       ├── reflector.rs      # Failure reflection
│       ├── confirmation.rs   # Permission gates
│       ├── web_agent.rs      # HTML scraping
│       ├── multi_agent.rs    # Domain routing
│       ├── screen_vision.rs  # Screen capture
│       ├── voice.rs          # Audio tools
│       ├── json.rs           # no_std JSON parser
│       └── world_model/      # Predictive safety gate + experience buffer
│           ├── observation.rs   # OS state snapshot collector
│           ├── encoder.rs       # Snapshot -> fixed-size numeric vector
│           ├── transition.rs    # Rule-based effect prediction
│           ├── safety.rs        # Risk scoring + block threshold
│           ├── experience.rs    # exp.bin training-data buffer
│           └── learned.rs       # Trained MLP inference, optional

userland/gui-smoke-test/          # App-window framework verification binary
userland/libferrumgui/            # Shared no_std SDK: syscalls, IPC send/receive, Canvas drawing, input polling
userland/heliox-assistant-panel/  # Installed app: agent chat panel + setup wizard
userland/text-editor/             # Installed app: edit/save a text file
userland/calculator/              # Installed app: mouse-driven arithmetic
userland/file-manager/            # Installed app: browse /disk, preview files
userland/settings/                # Installed app: view live daemon config + hardware info
userland/browser/                 # Installed app: minimal HTTP client over raw sockets
userland/app-store/               # Installed app: discovery/launch surface for installed apps
userland/notes/                   # ferrumpkg demo package - never embedded in the kernel binary
userland/init/                    # First userspace process (PID 2), supervises heliox-daemon
```
