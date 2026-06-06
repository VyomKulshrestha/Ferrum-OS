# FerrumOS Architecture

## Design Principles

1. **Kernel is deterministic** — no AI inference, no probabilistic models in
   kernel space. The kernel owns scheduling, memory, interrupts, and drivers.
2. **Agent lives in userspace** — the AI brain (`heliox-daemon`) runs as a
   freestanding Ring-3 process with syscall-only access to hardware.
3. **Every action is a syscall** — the agent cannot bypass the kernel. All 35
   tools translate to real kernel syscalls (30 total, IDs 0–29).
4. **Capability-gated** — default deny. Services receive only the capabilities
   required for their task.
5. **Hardware first** — an agentic OS needs real drivers, not stubs.

## System Layers

```text
┌──────────────────────────────────────────────────────────┐
│ Agent Layer (heliox-daemon)                              │
│ ReAct orchestrator, multi-agent domain router,           │
│ web browsing, autonomous planning + reflection           │
├──────────────────────────────────────────────────────────┤
│ Cognitive Layer (heliox-daemon)                          │
│ TF-IDF vector store, cosine similarity search,           │
│ hierarchical planner, verifier, reflector                │
├──────────────────────────────────────────────────────────┤
│ Runtime Layer                                            │
│ Service manager, IPC broker, capability checks,          │
│ 35 tool ↔ syscall mapper, 5-tier permissions             │
├──────────────────────────────────────────────────────────┤
│ GUI & Compositor Layer                                   │
│ Window manager, desktop dock, event routing, compositor  │
├──────────────────────────────────────────────────────────┤
│ Kernel Layer                                             │
│ Boot, GDT/IDT, page tables, heap, preemptive scheduler,  │
│ ELF loader, Ring-3 entry, SMP, ACPI                      │
├──────────────────────────────────────────────────────────┤
│ Storage Layer                                            │
│ ATA PIO driver, Ext2 filesystem, RamFS, VFS mount table  │
├──────────────────────────────────────────────────────────┤
│ Hardware Layer                                           │
│ RTL8139 NIC, Intel HDA audio, XHCI USB 3.0, USB HID,    │
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
4. Kernel heap mapped (1 MiB at `0x4444_4444_0000`)
5. Preemptive scheduler with idle task
6. Device discovery (PCI bus scan, NIC, audio, USB)
7. Filesystem mount (RamFS at `/`, Ext2 at `/disk`)
8. Shell task spawned → interactive prompt

### Memory

- Boot-info frame allocator for physical pages
- 4-level page tables with mapper
- Kernel heap: 1 MiB, bump allocator with linked-list fallback
- DMA: `allocate_contiguous_frames(n)` for NIC TX/RX and HDA BDL buffers

### Scheduler

- Preemptive round-robin with 4 priority levels
- Context switching via `switch_to()` assembly stub
- Per-task kernel stacks, sleep/wake/yield syscalls
- PID assignment, task state tracking (Ready/Running/Blocked/Dead)

### Syscall Dispatch

30 syscalls (IDs 0–29) dispatched via `int 0x80`:

- Process: Yield(0), Exec(18), Wait(13)
- IPC: Send(1), Receive(2)
- Services: Start(3), Stop(4)
- Security: CapCheck(5), AuditWrite(6)
- Network: Socket(7), Bind(8), Listen(9), Accept(10), Recv(11), Send(12), Connect(14)
- Filesystem: ReadFile(15), WriteFile(16), ReadDir(17), CreateDir(21), DeleteFile(22)
- Graphics: ReadFbInfo(19), ReadTextBuffer(20)
- Audio: PlayAudio(23), RecordAudio(24), SetVolume(25)
- Input: InjectKey(26), InjectMouse(27), PollInput(28)
- Query: SystemQuery(29) — returns JSON for system info, processes, memory, devices

## Graphical Desktop Environment (GUI)

The OS features a fully integrated windowing system and compositor:

### Compositor & Window Manager
- Double-buffered rendering via VGA framebuffer (1024x768x32bpp)
- Z-indexed overlapping windows with focus management
- Interactive title bars (drag-to-move) and functioning close buttons
- Desktop taskbar dock for launching system applications

### Event Routing
- Unified `InputEvent` queue bridging PS/2 hardware, USB HID, and syscall injections
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

### Components

| Module | File | Role |
|--------|------|------|
| Orchestrator | `orchestrator.rs` | ReAct loop, telemetry, IPC polling |
| Planner | `planner.rs` | Goal decomposition, dependency DAG, prompt generation |
| Verifier | `verifier.rs` | Output checking, retry counting |
| Reflector | `reflector.rs` | Failure recording, lesson extraction |
| Confirmation | `confirmation.rs` | 5-tier permission gates for destructive tools |
| Tool Mapper | `tool_mapper.rs` | 35 tools → syscall dispatch + INTERNAL routing |
| Vector Store | `vector_store.rs` | TF-IDF embeddings, cosine search, disk persistence |
| Web Agent | `web_agent.rs` | HTML stripping, entity decode, link/title extract |
| Multi-Agent | `multi_agent.rs` | Domain classifier (Code/Web/System/Files/General) |
| Screen Vision | `screen_vision.rs` | Framebuffer text capture |
| Voice | `voice.rs` | Audio record/play/volume control |
| JSON | `json.rs` | `no_std` recursive-descent JSON parser |
| Config | `config.rs` | Runtime config from `/disk/heliox/config.json` |
| Network | `network.rs` | TCP socket wrapper, HTTP/WS client |

### Permission Tiers

| Tier | Level | Auto-approve | Example Tools |
|------|-------|-------------|---------------|
| 0 | Observe | ✅ Always | `system_info`, `query_memory`, `poll_input` |
| 1 | Safe | ✅ Default | `read_file`, `read_dir`, `read_screen` |
| 2 | Network | ✅ Default | `http_get`, `browse_url`, `net_connect` |
| 3 | Modify | ⚠️ Configurable | `write_file`, `play_audio`, `keyboard_type` |
| 4 | Destructive | 🔒 Confirmation | `exec_process`, `delete_file` |

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
capability set at launch.

| Profile | Token | Access |
|---------|-------|--------|
| root | `cap:system:all` | Full system management |
| guest | `cap:fs:read` | Read-only filesystem |

### Audit Log

All denied operations, lifecycle events, and agent reasoning telemetry are
recorded in the kernel audit log. Accessible via the `log` shell command.

### Agent Confirmation Gates

Tools at Tier 3–4 queue confirmation requests. The operator must approve
(`confirm <id>`) or deny (`deny <id>`) before execution proceeds.

## Configuration

The agent reads runtime config from `/disk/heliox/config.json`:

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
back.

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
├── devices/              # PCI, HDA audio, XHCI USB, VGA FB
├── input/                # Unified input queue, USB HID, PS/2
├── audio/                # Audio mixer, PCM interface
├── graphics/             # Drawing primitives, console
├── gui/                  # Compositor, window manager, desktop
├── security/             # Capabilities, audit log
├── services/             # Service manager, manifests
├── ipc/                  # IPC broker
├── syscall/              # Dispatch, fs, process, query
├── shell/                # Shell, commands, dashboard
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
│       ├── tool_mapper.rs    # 35 tools → syscalls
│       ├── verifier.rs       # Output verification
│       ├── reflector.rs      # Failure reflection
│       ├── confirmation.rs   # Permission gates
│       ├── web_agent.rs      # HTML scraping
│       ├── multi_agent.rs    # Domain routing
│       ├── screen_vision.rs  # Screen capture
│       ├── voice.rs          # Audio tools
│       └── json.rs           # no_std JSON parser
```
