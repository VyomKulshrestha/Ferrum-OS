# FerrumOS Architecture

## Design Principles

1. **Kernel is deterministic** — no AI inference, no probabilistic models in
   kernel space. The kernel owns scheduling, memory, interrupts, and drivers.
2. **Agent lives in userspace** — the AI brain (`heliox-daemon`) runs as a
   freestanding Ring-3 process with syscall-only access to hardware.
3. **Every kernel effect crosses a syscall** — the agent cannot bypass the
   kernel. Its internal planning/memory operations remain in Ring 3; hardware,
   process, filesystem, service, and network effects use the 61-syscall ABI
   (IDs 0–60). The remaining calls back GUI/app-window, signed packages, audio,
   and other non-agent userland surfaces.
4. **Capability-gated** — default deny. Services receive only the capabilities
   required for their task.
5. **Hardware claims are scoped** — real drivers and emulator-backed fallbacks
   are named separately; synthetic devices are never presented as physical hardware.

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
2. GDT, IDT, PIC (8259) remapped, PIT programmed at 1 kHz
3. Page tables from boot info, frame allocator initialized
4. Kernel heap mapped (12 MiB at `0x4444_4444_0000` to support double-buffering)
5. Preemptive scheduler with idle task
6. Device discovery (PCI bus scan, NIC, audio, USB)
7. Filesystem mount (RamFS at `/`, Ext2 at `/disk`)
8. Shell task spawned → interactive prompt

### Memory

- Boot-info frame allocator for physical pages; returned user frames enter a
  validated LIFO free list and are zeroed before reuse so process churn does not
  leak data or consume fresh memory forever
- 4-level page tables with mapper
- Kernel heap: 12 MiB, bump allocator with linked-list fallback
- DMA: `allocate_contiguous_frames(n)` for NIC TX/RX and HDA BDL buffers
- Demand paging: Page-fault handler resolved via on-demand file block reads from Ext2/VFS for memory-mapped files (`mmap`)

### Scheduler

- Preemptive round-robin with 4 priority levels
- Context switching via `switch_to()` assembly stub
- Per-task kernel stacks, sleep/wake/yield syscalls
- PID assignment, task state tracking (Ready/Running/Blocked/Dead)
- 275 ms default time slice, derived from the PIT period so timer-rate changes
  do not silently alter scheduling or quota durations

### Syscall Dispatch

61 syscalls (IDs 0–60) dispatched via `int 0x80`:

- Process: Yield(0), Exec(18), Wait(13), Exit(30), GetPid(31), Sleep(32),
  WaitPid(33), LaunchContext(59). `Wait` is a blocking wait-any compatibility
  alias through the same scheduler lifecycle path as `WaitPid(u64::MAX)`.
- Task control: ProcessKill(58) — privileged termination of non-critical tasks; self, init, and quota-exempt system agents are protected
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
- Clipboard: ClipboardRead(53), ClipboardWrite(54) — a volatile 64 KiB
  kernel broker gated independently by `clipboard:read` and `clipboard:write`
- Notifications: NotificationPost(55), NotificationList(56),
  NotificationDismiss(57) — a 32-entry broker with separate post/read/manage
  authority and caller-owned serialization buffers
- Desktop preferences: DesktopPreferences(60) — a narrow, capability-gated
  validator for live theme/accent changes

## Graphical Desktop Environment (GUI)

The OS features a fully integrated windowing system and compositor:

### Compositor & Window Manager
- Double-buffered rendering via VGA framebuffer (1024x768x32bpp)
- Z-indexed overlapping windows with focus management
- Interactive title bars (drag-to-move) with close, minimize, and maximize buttons, all computed from shared rect helpers on `Window` (`close_btn_rect`/`maximize_btn_rect`/`minimize_btn_rect` in `src/gui/window.rs`) so rendering and hit-testing can't drift apart
- Minimized windows are skipped by rendering and hit-testing but keep a taskbar entry; maximize snaps a window to the desktop content area and remembers its prior geometry to restore
- Alt+Tab is normalized by both PS/2 and USB HID drivers into an internal compositor token. The switch executes under the existing compositor lock, restores a minimized target, raises it atomically, and consumes the token before application input dispatch.
- Desktop taskbar with a Start-menu launcher, seven visible per-window slots,
  previous/next paging that keeps every running app reachable, a Power/session
  popup (`Lock`, `Sign out`, `Restart`, `Shut down`, `Cancel`), and a UTC clock
  sourced from the CMOS RTC (`security::time::read_rtc_time`). All positions are
  computed by `desktop::compute_taskbar_layout()` and shared between rendering
  and click/hover hit-testing. Window placement supports minimize,
  maximize/restore, and left/right/top edge dragging; snapped windows retain
  their pre-drag floating rectangle for deterministic restoration.
- Lock is a privacy surface, not credential authentication: the account registry
  has no password field, the screen states that limitation, and Enter resumes.
  Sign out tears down the desktop/ambient surface and hands input back to the
  shell. Restart and shut down flush audit state before entering hardware paths.
- System Monitor samples scheduler task-tick deltas against PIT wall ticks and
  renders live CPU activity, task count, heap use, and uptime. The ambient
  Heliox compositor pump refreshes the same telemetry outside the compositor
  lock, avoiding a renderer/metrics lock inversion.
- App Store: two discovery surfaces for built-in apps and the verified local signed-package cache, with capability-aware install, confirmed remove, rollback, and launch controls
- Notification service: ring-3 apps post bounded title/body records into a kernel-owned history; the compositor renders a toast from a cloned snapshot and Notification Center lists or clears records through separately gated syscalls, so it never shares an application lock or address space with the renderer
- Task Manager: reads the live `SystemQuery(29)` process list and holds the non-delegatable `cap:process:kill` token only because the trusted launcher assigns its compiled-in manifest directly. `ProcessKill(58)` rejects self/critical targets, marks the scheduler task dead, drains run queues, and removes that PID's windows/input queues before redraw.

### Generic App-Window Framework
Beyond the three kernel-drawn window types (`Normal`, `SystemMonitor`, `Terminal`), `WindowType::App(pid)` lets **any** userland process own a real window — including the Heliox Assistant, which used to be a fourth kernel-hardcoded type (`AgentHud`) before it was rebuilt as an ordinary app on this framework:
- `CreateWindow(title, canvas_w, canvas_h)` allocates a window whose total size is the requested canvas plus shared chrome (`CHROME_SIDE`/`CHROME_TOP`/`CHROME_BOTTOM` in `src/gui/window.rs`) — apps never need to know about title-bar/border geometry.
- `PresentWindow(window_id, rgba8_buf)` copies a caller-owned RGBA8 buffer into the window's canvas (`src/gui/app_window.rs`); `render()` blits it verbatim for `App` windows, the same title bar/border/close-button chrome as every other window type.
- `PollWindowInput(window_id)` drains a per-window input queue (keyboard + mouse-down, capped at 64 events) fed by `compositor::handle_key_press`/`handle_mouse_down` whenever an `App` window is focused.
- The keyboard paths normalize PS/2 and USB Ctrl+C/Ctrl+V into the same control-byte ABI. Text Editor uses the clipboard SDK wrappers to copy its full buffer or paste at the cursor, so content crosses process boundaries without granting either process access to the other's memory.
- Gated behind the `gui:window:*` capability (`cap:gui:window`), following the same capability-registry pattern as every other resource-gated syscall.
- App windows persist across `desktop` re-entry and keep focus across it
  (`spawn_demo_windows()` only resets the kernel-drawn demo set). Closing an
  app's main window marks its Ring-3 process dead, removes all owned windows and
  input queues, unmaps its user pages, returns its frames, and removes its
  pid-scoped launch context; secondary-window close only removes that window.

### App Launcher & Installed Apps
The Start-menu launcher (`src/gui/desktop.rs` popup, `src/gui/compositor.rs::LAUNCHER_ENTRIES`) can spawn real new processes, not just the kernel-drawn built-ins:
- `crate::process::spawn_elf(name, elf_bytes, granted_caps)` (`src/process/mod.rs`) loads an ELF and registers it as a Ready scheduler task directly from kernel context — the same load/register logic `sys_exec` uses for a ring-3 caller, but with capabilities taken straight from the program's `crate::userspace` manifest instead of delegated from a caller. It only registers the task and returns; it never itself enters ring 3, so it's safe to call from the compositor's own render loop.
- Installed apps (`userland/heliox-assistant-panel/`, `userland/text-editor/`, `userland/calculator/`, `userland/file-manager/`, `userland/settings/`, `userland/browser/`, `userland/app-store/`, `userland/notification-center/`, `userland/task-manager/`) are ordinary ELF binaries built on `userland/libferrumgui/` — a shared `no_std` SDK (window/input, IPC, clipboard, notifications, system query, task control, launch-context, desktop-preference, trusted-launcher, and signed-package syscall wrappers; an `InputEvent`; and an RGBA8 `Canvas`) — registered in the same `crate::userspace` manifest table as `init`/`heliox-daemon`. The Heliox Assistant panel exchanges structured state with `heliox-daemon`; Browser uses raw socket syscalls; App Store uses the narrow `cap:app:launch` and `cap:pkg:request` broker APIs described below. File Manager launches associated documents through that broker with a kernel-owned, pid-scoped context copied by Text Editor; no app receives another process's pointer. Settings persists validated theme/accent choices to `/disk/desktop.conf` and applies them through `DesktopPreferences(60)`.

Ordinary `Exec` delegates only capabilities the parent holds. App Store therefore does not receive every target app's filesystem/network authority and does not use raw `Exec`: `AppLaunch(51)` accepts only a compiled-in desktop-app name and launches it with that trusted program's manifest, while `PackageLaunch(52)` atomically validates/loads an installed signed package and launches it with its signed, allow-listed capabilities. Both broker calls are separately capability-gated; a GUI-only ring-3 probe is denied access to them.
- Each app owns a fixed-size heap (`#[global_allocator]` over a static array)
  sized comfortably above its own canvas buffer (`canvas_w * canvas_h * 4`
  bytes); undersizing causes allocation failure and process exit on the first
  frame. The process ABI has no general argv array. Narrow startup metadata is
  copied through `LaunchContext(59)`, currently used for associated documents;
  otherwise apps use their own state/default paths. File Manager owns its path
  and Back/Forward history in Ring 3 and exposes Back, Forward, Up, Refresh, and
  associated Open controls; file previews retain their parent directory so Back
  never resets unrelated browsing state.

### Package Manager (`src/pkg/mod.rs`)

Packages under `/disk/pkgs-available/<name>/` carry a strict format-v1 `manifest.txt`, detached Ed25519 `manifest.sig`, and ELF `bin`. The kernel verifies the manifest against its release public key, requires the manifest name to match the sandbox directory, rejects unknown/duplicate fields and undelegatable capabilities, and compares the ELF's SHA-256 digest with the signed value before install or launch. The corresponding private release key is intentionally not part of the repository.

The ring-3 filesystem syscalls enforce `cap:fs:read` and `cap:fs:write` at their common kernel dispatch boundary. `/disk/pkgs` and `/disk/pkgs-available` are a second, protected trust domain: even a process holding both ordinary filesystem tokens is denied unless it directly holds the non-delegatable `cap:pkg:manage` token. User paths must be absolute and reject `.`/`..` components, preventing alternate path spellings from bypassing that boundary. `gui-smoke-test` and Text Editor exercise both denial cases from real scheduled ring-3 processes. Clipboard authority is separate again: Text Editor and Heliox receive delegatable read/write tokens, while an ordinary guest shell receives neither.

Real `pkg list|verify|install|remove|run|status|rollback` semantics, honestly scoped: packages
are a local cache staged onto the appliance disk at *build* time
(`scripts/make-appliance.ps1`, via `debugfs` - the same mechanism that
packages the real model checkpoint), not fetched from any network
repository. Two on-disk locations:
- `/disk/pkgs-available/<name>/{manifest.txt,manifest.sig,bin}` - every package that
  exists on the image, whether installed or not. `manifest.txt` is a flat
  `key=value` format (no JSON parser exists in kernel space), declaring
  `capabilities` from a fixed allow-list (`cap:gui:window`, `cap:fs:read`,
  `cap:fs:write`, `cap:audio:play` - never network/exec/quota/confirmation
  tokens).
- `/disk/pkgs/registry.a` and `registry.b` - checksummed, monotonically
  generation-numbered snapshots binding every installed name to its exact
  signed version and ELF digest. A package mutation holds the package-state
  mutex across read/modify/write, writes the inactive slot, reads it back,
  verifies it, and syncs it; the prior slot remains a rollback/recovery point.
  A legacy `registry.txt` is imported on first mutation. A package's
  (potentially large) `bin` is never physically copied at install time -
  ext2's own `create_file` only supports direct blocks (12 max), far too
  small for a compiled ELF, so the same bytes `debugfs` staged are read
  from `pkgs-available` either way; install/remove only toggle whether
  `sys_exec` (`src/syscall/process.rs`) will actually run them.

Capabilities that access files or audio require an explicit confirmation
(`pkg install <name> --confirm`; the App Store presents the same authority
before its confirmed request). Package launch calls `pkg::load_installed`,
which holds the same transaction mutex while it validates the registry's
version/digest binding and loads the signed ELF. Therefore remove/rollback
cannot race the authorization check into loading replacement bytes; already
running processes are intentionally not killed by uninstall.

The App Store cannot read or write either package directory. Its delegatable
`cap:pkg:request` token only reaches `PackageList(47)`, `PackageInstall(48)`,
`PackageRemove(49)`, `PackageRollback(50)`, and `PackageLaunch(52)`; the kernel
then performs the operation through ferrumpkg. Direct path access still needs
the non-delegatable `cap:pkg:manage` token. This separates UI/request authority
from repository mutation authority.

`sys_exec`'s VFS-read fallback path recognizes a `pkgs-available/<name>/bin`
path shape and resolves both the verified ELF and capabilities through the
same atomic `pkg::load_installed` operation instead of the empty result
`capabilities_for_program` would otherwise return for a name it wasn't
compiled with. The `pkg run` shell command (kernel context) additionally
calls `userspace::register_dynamic_program` before `process::enter_registered`
(see "Ring-3 scheduling from a cold shell" below) so that first-entry path's
own capability re-derivation sees the same clamped set. `pkg remove` calls
the matching `userspace::unregister_dynamic_program` so that the plain
`run <name>` shell command - which dispatches off this same dynamic table,
not ferrumpkg's own install registry - stops finding a package once it's
removed (previously it didn't, and kept launching removed packages
indefinitely; see `work.md` finding 2.2).

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
- Before the desktop receives a pointer click, keyboard events remain owned by
  the debug shell; the first desktop click transfers keyboard ownership to the
  compositor and drains stale shell keystrokes. Sign out reverses ownership.
  This prevents the background Heliox desktop pump and foreground shell from
  consuming the same physical key event.
- Console, serial, and userspace `SYS_WRITE` output is emitted in bounded
  chunks with hardware interrupts serviceable between chunks. Long log lines
  therefore cannot starve the PS/2 keyboard IRQ while Heliox or an audit is
  printing.
- `cursor::process_input()` is the single shared entry point every render/input pump goes through (both `run_desktop()`'s loop and `SYS_HUD_UPDATE`'s ambient pump call it) — the first time it's ever called it discards only queued *keyboard* events (`input::discard_stale_keyboard_events`), so keystrokes typed before anything was compositing yet don't replay into whatever window happens to get focus first. Mouse events are left untouched: they were never typed at a shell prompt, so blanket-clearing the whole queue here used to risk silently eating a real, freshly-issued click if it landed in the same narrow window as this one-time flush (the actual cause of a `verify_core_apps.mjs` Text Editor regression - see `work.md`)
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

The VFS exposes separate text and raw-byte paths. `WriteFile(16)` and offset
reads preserve arbitrary bytes on both mounts; text consumers still receive a
strict UTF-8 error. This keeps ELF/model files binary-safe without constructing
invalid Rust strings or weakening per-process filesystem capability checks.

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
- `Accept(10)` and `net serve` report success only when smoltcp says the socket
  is in `Established`; Listen/SYN states never produce a false accepted
  connection. The high descriptor bit requests a non-blocking probe (zero means
  no client yet), which Heliox uses so an absent controller cannot suspend its
  autonomous audio/camera/planner loop.

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

The agent daemon samples 250 ms audio windows every ten loop iterations. When
voice activity is detected, it records the 3-second command, transcribes it,
and generates a new `GOAL:`, bridging the physical world with the ReAct loop.
It also periodically screenshots the desktop to proactively solve GUI errors.
A stable Pointing gesture triggers an immediate VAD sample and is retained for
an 8.2-second multimodal association window (8,200 ticks at the 1 kHz PIT),
allowing a phrase such as "open this" to resolve through `HitTest` to the
pointed window. Camera, audio, IPC, and controller frames are ingested before
the planner runs, so inference cannot race ahead with a partial observation.

The `network.rs` client is dynamically driven by the daemon's runtime configuration, supporting two payload schemas:
1. **Ollama Format:** Flat `{"model", "prompt"}` JSON.
2. **OpenAI Chat Format:** `{"messages": [{"role", "content"}]}` with `Authorization: Bearer` headers (supporting OpenAI, Gemini, and Claude via host proxy wrappers).

The on-device ("local") brain is a real, trained checkpoint — a quantized int8 llama2.c-format model, memory-mapped from `/disk/heliox/models/` and packaged onto the appliance disk image by `scripts/make-appliance.ps1` (see `appliance/models/README.md` for provenance). It is not a placeholder: the daemon dequantizes and runs the actual weights, producing genuine generated text rather than a synthetic fixture.

Until a configuration file actually exists on disk, the daemon stays idle: no ticking, no autonomous inference, `provider` stays `"auto"` unresolved. A missing config file is never treated as an implicit choice of hardware-tier-appropriate provider — that resolution only happens once a config file is present (whether written by the setup wizard or by hand), so the daemon never starts real computation before the user has actually chosen anything.

### JSON-RPC Interface

The daemon exposes JSON-RPC 2.0 over WebSocket port 8785: `ping`, `pair`,
`set_control_mode`, `execute_tool`, `agent_step`, `world_model_preview`,
`gesture_event`, `health`, `get_config`, `system_status`, and `agent_stats`.
The boot-scoped pairing token is printed only on the physical console. Before
pairing, privileged calls fail closed. A paired client defaults to an exclusive
lease, pausing built-in planning so two controllers cannot race; cooperative
mode leaves native planning active and is used for controlled data collection.
Configuration output excludes the API key. Tick counts are monotonic and may
remain stable while an exclusive lease intentionally pauses planning.

### Chat IPC with the Heliox Assistant App

The daemon and the Heliox Assistant app-window (`userland/heliox-assistant-panel/`) exchange state over two IPC channels rather than one hardcoded telemetry string:
- `CHAT:{role}:{state}:{content}` — sent by the daemon to the `"assistant"` IPC service on every think/act cycle, with `state` one of `thinking`, `error`, or `done`, and `content` the actual human-readable response text once done. The app parses this into a real chat history.
- `GOAL:{text}` — sent by the app to the `"heliox"` service when the user submits a chat message, reusing the same mechanism the setup wizard uses for `CONFIG_UPDATED` reloads.

The kernel binds receive authority to the owning live task (including the
stable `heliox`, `assistant`, and `runtime.agentd` aliases) and accepts bounded
boot control for registered ring-3 services before their first dispatch.
Unknown targets are rejected. Each service has its own queue quota, so an
absent or stalled assistant cannot fill the broker and block model control.
Shell `voice_event` requests are forwarded as `GOAL:` messages and therefore
survive the init/daemon startup boundary.

### Components

| Module | File | Role |
|--------|------|------|
| Orchestrator | `orchestrator.rs` | ReAct loop, telemetry, IPC polling |
| Planner | `planner.rs` | Goal decomposition, dependency DAG, prompt generation |
| Verifier | `verifier.rs` | Output checking, retry counting |
| Reflector | `reflector.rs` | Failure recording, lesson extraction |
| Confirmation | `confirmation.rs` | 5-tier permission gates for destructive tools |
| Tool Mapper | `tool_mapper.rs` | 41 executable actions (37 LLM-advertised) → syscall dispatch + INTERNAL routing |
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

A predictive layer in front of every Heliox tool dispatch, alongside (not
instead of) the reactive `ConfirmationGate` above. Provider-generated ReAct
actions, internal memory/planner actions, and public JSON-RPC `execute_tool`
calls all converge on `dispatch_with_world_model`; there is no second public
execution path that bypasses prediction or data recording. `agent_step` exposes
one provider-backed ReAct cycle for controlled episode collection. Before any
tool call reaches its real implementation, it is evaluated against a small
internal model of what the call would do to the system and blocked if the
prediction looks dangerous.

- **Observation** — samples live OS state (process count, heap usage,
  filesystem entries, screen text) through the same syscalls the
  daemon's existing tools already use (`SystemQuery`, `ReadDir`,
  `read_screen`'s `ReadTextBuffer`) - no new syscalls, no new
  capabilities.
- **Encoding** — compresses the snapshot into a fixed-size vector. Process
  count, heap/disk usage, action id, and every deterministic risk input remain
  hand-crafted. Release 0.1.1 fills the remaining 77 dimensions with an
  action-conditioned JEPA encoder trained with an EMA target,
  reconstruction/action auxiliaries, and anti-collapse gates. A deterministic
  zero tail remains the load-failure fallback, so learned coordinates never
  replace policy fields.
- **Action conditioning** — provider output is first normalized into the same
  canonical `ToolCall` used by every other path. The learned transition input is
  the 128-float state, a 41-wide tool one-hot, and 16 bounded argument features
  (counts and lengths, stable path/host hashes, numeric values, and explicit
  critical/missing-path flags). Provider name, model size, and response style
  are audit metadata only and never become model inputs.
- **Transition prediction** — two interchangeable sources behind the
  same `predict_next_state` call: a hand-coded rule table mapping each
  higher-consequence tool (`write_file`, `delete_file`, `exec_process`,
  `create_directory`, `service_start`/`stop`, `trigger_kernel_upgrade`,
  `net_connect`) to its predicted effect on that vector, or - when
  present - a small MLP (`cognitive/world_model/learned.rs`) trained
  offline on real collected data (`scripts/collect_world_model_hybrid.mjs`
  + `scripts/train_world_model.py`, pure numpy) and loaded at boot as a flat
  `f32` binary via `SYS_READ_FILE`. The accepted release MLP is 512 units
  wide. The v2 `FWM2` file header includes the argument-feature
  width and a 64-bit trained-tool coverage mask. A tool absent from training
  falls back to the rule table instead of consuming random, untrained one-hot
  weights. The loader rejects non-finite values, impossible shapes, empty or
  out-of-range coverage, and learned claims over the policy-only kernel
  upgrade. Legacy 169-input checkpoints still load with conservative known-tool
  coverage. The learned model predicts an embedding *delta*, not the absolute
  next state; whether a config-deleting `delete_file` call gets caught is always
  a direct argument check, independent of which source produced the numeric
  prediction.
- **Risk scoring** — flags specific predicted outcomes (disk nearly
  full, the daemon's own config file about to be deleted, heap nearly
  exhausted) and blocks the real syscall if the combined score crosses
  a threshold, logging the block to the console.
- **Lookahead** — rather than checking only the single-step prediction,
  the gate simulates the proposed action repeated a few times in a row
  through the transition model and keeps the worst risk seen across
  that chain, catching effects that only emerge as they compound (an
  action whose first application looks harmless but whose repetition
  would fill the disk or exhaust the heap). The number of simulated
  steps it took to reach the reported risk is logged alongside every block.
  Process deltas accumulate across the chain; QEMU probes prove disk pressure
  at H=2 and a threshold-equality fork pattern at H=3. Fixed-split held-out
  results support H=3. H=5 raises raw compounding error, so the release does not
  trade safety confidence for an unmeasured deeper search.
- **Experience buffer** — every tool call, allowed or blocked, is
  recorded as a compact fixed-size record to `/disk/heliox/world/exp.bin`
  (front-truncated once capped, the same pattern the audit log uses) -
  passive training data for a future learned version of the same gate.
  Capped well below ext2's direct-block write ceiling (`create_file`
  only supports up to 12 direct blocks - a real, previously-undiscovered
  filesystem limit this surfaced), since the buffer is rewritten in full
  on every append.
- **Hybrid host corpus** — `generate_world_model_hybrid_corpus.mjs` creates a
  deterministic balanced goal set across all 41 canonical executable actions.
  Thirty-seven LLM-advertised tools remain provider-driven; the four controlled
  runtime actions (`local_inference`, `trigger_kernel_upgrade`, `hud_update`,
  and `hit_test`) receive deterministic replay calls so they cannot be silently
  under-sampled. The collector records the expected and actual tool separately
  and reports realized coverage rather than assuming prompt balance equals
  action balance.
  `prefetch_world_model_responses.mjs` can acquire strict, resumable batches
  from any OpenAI/Ollama-compatible endpoint and rejects mismatched tools or
  missing/out-of-range arguments before QEMU time is spent.
  `collect_world_model_hybrid.mjs` runs goals through `agent_step`, joins
  raw provider responses to the daemon's real before/action/after rows, appends
  each episode atomically, supports sharded collection and multiple RAM
  profiles, reconciles interrupted publishes, and resumes complete episodes.
  Offline replay responses make the same path deterministic in CI.
  `upgrade_world_model_dataset.mjs` preserves the existing 9,700 real syscall
  transitions while reconstructing the exact historical arguments used to
  create them. The encoder and transition trainers split by complete episode,
  preserve metadata, report per-tool/core metrics, and optionally restore the
  best validation checkpoint with `--patience`. The release corpus contains
  13,697 transitions, 3,639 episodes, 1,300 multi-step episodes, all 41 actions,
  and 13,270 executed non-policy fitting rows. The release includes 128 freshly
  collected successful `ipc_send` transitions replacing episode-atomic rows
  recorded against the retired syscall ABI. Each row distinguishes result
  `success` from whether execution was actually attempted. Blocked and
  confirmation-only rows stay available for policy analysis but are excluded
  from transition fitting and trained-tool coverage, preventing a refusal's
  unchanged state from being learned as a safe action outcome.
- **Selection and packaging** — autoencoder and JEPA candidates use the same
  episode-disjoint 9,104/2,197/1,969 split and dataset fingerprint.
  Cross-representation error is normalized against each representation's
  held-out zero-delta baseline. The accepted JEPA model improves every guarded
  metric (one-step 1.68%, macro-tool 1.71%, H3 3.87%, H5 4.03%) and is stored as
  a matched, hash-verified pair under `appliance/world-model/`. Clean builds
  package those assets; local overrides must supply both files.
- **Verification** — permanent suites cover corpus schema/coverage/diversity,
  split leakage, JEPA rejection and promotion, weight integrity, protected-path
  aliases, disk/process lookahead, provider chunking, a 300-request socket soak,
  real local inference, and a four-outcome ReAct smoke. Learned predictions are
  advisory; deterministic policy and confirmation gates remain independent and
  fail closed.

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

The `Exec` syscall itself is gated on `process:spawn`; this check happens
before ELF resolution/loading. First-party programs that legitimately launch
children such as Heliox declare `cap:process:spawn`; App Store instead uses
the narrow trusted-launcher brokers. The GUI-only ring-3 smoke test proves
that window authority alone cannot spawn a process or call either broker.

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

There is intentionally no password/credential field yet. `login` selects a
stored authorization profile but does not prove identity, and the desktop lock
is correspondingly labeled as a privacy resume screen rather than an
authentication boundary.

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
- **Continuous CPU execution limit**: The scheduler monitors tasks and reaps any user task that executes consecutively for more than 5,500 ticks (~5.5s at the 1 kHz PIT) without yielding (`sys_yield`) or sleeping (`sys_sleep`). Reaped processes exit with code 140.
- **Syscall Rate Limiting**: Restricts processes to 5,000 system calls per 11,000-tick window (~11s at the 1 kHz PIT) — sized to comfortably accommodate a real interactive GUI app's normal poll/sleep loop, not just brief scripted interactions. Violations result in immediate process termination (exit code 140) and logging.

### Audit Log

All denied operations, lifecycle events, and agent reasoning telemetry are
recorded in the kernel audit log. Accessible via the `log` shell command.
- **Out-of-Interrupt Persistence**: Disk writes inside interrupts (such as timer IRQs) are avoided to prevent deadlocks. An atomic `FLUSH_PENDING` flag is set by the timer interrupt.
- **Deferred Disk Sync**: The log is flushed from memory to `/disk/heliox/audit.log` during safe out-of-interrupt contexts: syscall returns, process termination/reaping, and system shutdown/reboot.
- **Log Truncation**: The persistent log is capped at 128KB, using character/newline-aligned front-truncation when the size limit is exceeded.

### Agent Confirmation Gates

Kernel-side confirmation gates are enforced for destructive Tier-4 operations (specifically `DeleteFile`, syscall 22):
- **Syscall Suspension & Sleep Timeout**: When a gated syscall is called by a process lacking `cap:confirmation:bypass`, the calling process is placed into a `Blocked` state and given a 5-second default-deny sleep timeout.
- **Modal idle handoff**: The blocked requester parks on the scheduler's
  dedicated idle stack until a PIT deadline or physical key IRQ wakes it. This
  avoids depending on a previously parked kernel UI task to hand control back
  to the only deadline-bearing ring-3 task.
- **Instruction Pointer Rewinding (RIP-2)**: The saved user context frame's `rip` is decremented by 2 bytes. Because the `int 0x80` assembly instruction is exactly 2 bytes (`CD 80`), rewinding the instruction pointer causes the process to re-execute the system call immediately upon waking.
- **Physical vs. Injected Key Filter**: Gates can only be approved by typing `y` (or denied with `n`) on a physical serial console or keyboard. Synthetic keystrokes injected by the agent via `sys_inject_key` are filtered using the `INJECTING_AGENT_KEY` atomic boolean, preventing the agent from autonomously bypassing its own security gates.
- **Retry-and-Cache State**: When resumed, the process re-executes `int 0x80` and references the cached `confirmation_approved` or `confirmation_denied` fields on the task context to either complete the operation or return `-2` (`PermissionDenied`) without prompting again.

Heliox tools also have a daemon-owned logical confirmation gate. A numeric
`heliox confirm <id>` request is authorized by the kernel bridge and forwarded
as `CONFIRM:<id>` through capability-checked IPC to `heliox-daemon`; the caller
then retries the pending tool. Destructive kernel operations such as kexec still
encounter their separate physical confirmation gate, so approving a model plan
does not bypass kernel authority.
Control IPC is polled both on the daemon's normal tick (even while cognition is
paused) and immediately after a WebSocket frame wakes the task, before that
frame is dispatched. This closes the approval-vs-retry race when the daemon was
blocked in socket receive.


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

## Release Verification

The release harness has two layers:

- `node scripts/verify_all_audits.mjs` runs the 98-case shell command sweep and
  the independent 65-case exhaustive command catalog sequentially, failing on
  the first non-zero child result.
- The 71 `scripts/verify_*.mjs` verification scripts are available individually
  for isolated QEMU evidence across Ring-3, scheduling, GUI apps, networking,
  storage, accounts, Heliox, real/synthetic inference, voice/fusion, and both
  rule-based and learned world-model safety paths.

The current release baseline also includes focused verifiers for desktop power
actions, live System Monitor telemetry, legacy wait-any behavior, physical-frame
recycling/scrubbing, established-only TCP accept, document associations,
persistent desktop preferences, taskbar paging, and close-to-reap lifecycle.

The dashboard/shell coexistence checks require a scheduler-trace boot image:

```powershell
$env:Path = "$env:USERPROFILE\.rustup\toolchains\nightly-x86_64-pc-windows-msvc\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
cargo bootimage --features sched-trace
node scripts\verify_dashboard_scheduling.mjs
node scripts\verify_shell_coexistence.mjs
```

Rebuild the normal image with `.\build.ps1 build` afterward; scheduler tracing
is intentionally disabled in release builds because synchronous per-switch
serial output increases interrupt latency.

## Release Scope and Known Limits

The supported v0.1.1 product is the documented x86_64 QEMU appliance and its
included Ring-3 environment, not general Windows compatibility:

- Camera frames come from `camera_synth`; UVC enumeration/streaming is absent.
- SMP loads an AP trampoline and reports ACPI topology but does not send
  INIT/SIPI or schedule work on application processors. Lock ownership still
  uses a placeholder core id.
- Shutdown uses common QEMU/Bochs/VirtualBox ports instead of evaluating ACPI
  AML `_S5`; reboot uses the 8042 reset pulse.
- Accounts are capability profiles without passwords, and ext2 uid/mode fields
  are not enforced against the current account.
- Ring-3 app canvases are fixed at creation. Maximizing pads the unchanged
  canvas; no resize event or dynamic reallocation protocol exists.
- VirtIO-GPU remains 2D/full-frame and optional, networking assumes the
  documented QEMU profile, and broad physical-PC driver compatibility,
  accessibility, installer/update UX, and production secret storage are not
  release claims.

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
│       ├── tool_mapper.rs    # 41 executable actions (37 LLM-advertised) → syscalls
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
userland/libferrumgui/            # Shared no_std SDK: window/input, IPC, app/package brokers, Canvas drawing
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
