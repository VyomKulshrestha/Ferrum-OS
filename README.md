# FerrumOS

A minimal modular Rust-based operating system designed as the long-term
foundation for an AI-native autonomous computing environment.

FerrumOS keeps the kernel deterministic, lightweight, and independent from
probabilistic AI systems. AI inference, semantic memory, vector databases, and
agent orchestration belong in runtime services above the kernel, not in the
kernel core.

## Current Status

Version 0.1.0 provides a bootable x86_64 Rust kernel foundation with:

- Bootloader integration through `bootloader`
- VGA text output and UART serial logging
- GDT, IDT, CPU exception handlers, PIC timer and keyboard IRQs
- Page-table setup, boot-info frame allocation, and a 256 KiB kernel heap
- Cooperative task scheduler with task state and priority metadata
- Interactive shell with inspection and management commands
- Volatile in-memory RAM filesystem
- Filesystem mount table, stat metadata, and usage reporting
- Device registry for online drivers and planned Heliox-facing hardware surfaces
- RTL8139 PCI NIC driver with real TCP/IP networking via smoltcp
- Socket syscalls (`sys_socket`, `sys_connect`, `sys_send`, `sys_recv`) wired to smoltcp
- Capability registry and caller-held capability authorization helpers
- Debug shell session profiles for root and restricted guest capability checks
- Audit logging hooks for security and lifecycle events
- Modular service manager with typed service manifests and sandbox profiles
- Service health reporting and restart counters for runtime supervision
- Deterministic IPC message contracts for future runtime services
- Userspace program manifests and process capability table
- Bootstrapped userspace `init` process metadata after scheduler startup
- Capability-authorized syscall dispatch for IPC, service lifecycle checks,
  capability checks, and audit writes
- Capability-gated `agentd` runtime boundary stub for future agent integration
- Native Heliox-OS Agent Daemon: The previous JSON-RPC bridge has been completely replaced by a true bare-metal agent orchestrator, planner, and vector store running as a native userspace process (`heliox-daemon`).

## Architecture

```text
+----------------------------------------------------------+
| Agent Layer (heliox-daemon)                             |
| Autonomous workflows, planning, verification             |
+----------------------------------------------------------+
| Cognitive Layer (heliox-daemon)                         |
| Semantic memory, vector search, context management       |
+----------------------------------------------------------+
| Runtime Layer                                           |
| Services, permissions, IPC, AI orchestration boundaries  |
+----------------------------------------------------------+
| Kernel Layer                                            |
| Boot, memory, interrupts, scheduling, isolation, HAL     |
+----------------------------------------------------------+
| Hardware / NIC Layer                                    |
| RTL8139 driver, smoltcp TCP/IP stack, socket syscalls    |
+----------------------------------------------------------+
```

The legacy Python desktop agent has been replaced. The AI brain (orchestrator, planner, and semantic memory) now runs natively as a freestanding userspace process (`heliox-daemon`) directly on the FerrumOS bare-metal kernel.

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

To run after installing QEMU:

```powershell
.\build.ps1 run
```

To run the command sweep headlessly:

```powershell
node .\scripts\command_sweep.mjs
```

To watch QEMU while the sweep types commands:

```powershell
node .\scripts\command_sweep.mjs --visible
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
| `mounts` | Show mounted filesystems and RAM filesystem usage |
| `mkdir <dir>` | Create directory |
| `touch <file>` | Create empty file |
| `write <file> <text>` | Write text to file |
| `rm <path>` | Remove file or directory |
| `devices` | List online and planned kernel-visible devices |
| `net` | Show network interfaces, routes, and counters |
| `net send <text>` | Deliver a capability-checked loopback packet |
| `caps` | List security capabilities |
| `services` | List registered services |
| `services health` | Show service supervisor health counters |
| `services start <id>` | Start a service through capability checks |
| `services stop <id>` | Stop a service through capability checks |
| `services restart <id>` | Restart a service through capability checks |
| `ipc` | Show IPC broker statistics |
| `syscalls` | Show reserved syscall ABI numbers |
| `programs` | List userspace program manifests |
| `users` | List launched userspace process records |
| `run <program>` | Launch a manifest-backed userspace process |
| `syscall <pid> <num> [arg0]` | Dispatch a syscall as a userspace process |
| `agent status` | Show agent runtime boundary state |
| `agent start` | Start the sandboxed `agentd` boundary service |
| `agent send <text>` | Send a capability-checked IPC command to `agentd` |
| `heliox status` | Show Heliox-OS JSON-RPC bridge state |
| `heliox methods` | List Heliox JSON-RPC methods with required capabilities |
| `heliox tiers` | List the 5-tier Heliox permission model |
| `heliox actions` | List the Heliox action catalog (120 actions) |
| `heliox services` | List Heliox runtime service slots |
| `heliox send <method> [input]` | Submit a Heliox JSON-RPC request envelope |
| `heliox notif <method>` | Prepare a Heliox notification envelope |
| `heliox voice start\|stop\|event` | Drive the Heliox voice listener state |
| `heliox screen on\|off\|context` | Drive the Heliox screen vision state |
| `heliox persona [add key=value]` | Inspect or append Heliox persona rules |
| `heliox confirm <plan_id>` | Resolve a Heliox confirmation gate |
| `heliox execute <input>` | Submit a Heliox ReAct pipeline input |
| `log` | Show audit log |
| `uptime` | Show timer ticks |
| `uname` | Show system information |
| `whoami` | Show current shell capability profile |
| `session [root|guest]` | Switch debug shell capability profile |
| `spawn <name>` | Spawn a task metadata record |
| `kill <pid>` | Mark a task dead |
| `security` | Show security status |
| `about` | Show FerrumOS architecture notes |

## Development Priorities

See `docs/ROADMAP.md` for the full completion plan. The current phase is
**Phase 1 — Real userspace execution**, broken into four sub-steps:

1. Workspace scaffolding and a tiny userspace `init` binary.
2. ELF64 parser.
3. Per-process address space.
4. Ring-3 entry and `load_elf` that actually runs the embedded `init`.

Earlier milestones (still listed for historical context):

1. Bootloader and kernel initialization
2. Memory management and interrupts
3. Scheduler and shell
4. Filesystem and isolation
5. Modular runtime services
6. Security and sandboxing

## Agent Integration Path

The current `agentd` service is a deterministic boundary, not the full AI
agent. It is registered through a runtime service manifest with a default
sandbox profile and requires `cap:agent:control` for lifecycle and command
operations. FerrumOS also includes a manifest-backed `agent-bridge` userspace
process placeholder that can exercise IPC syscalls with delegated capabilities.
The kernel boot sequence now also launches the manifest-backed `init` process
record after the scheduler starts.

## Heliox-OS Native Integration

FerrumOS has evolved into a true Agentic OS. Instead of relying on a host machine to run the [Heliox-OS](https://github.com/VyomKulshrestha/Heliox-OS) Python daemon via a network bridge, the intelligence has been ported natively to Rust!

The OS now contains `userland/heliox-daemon`, a native userspace binary that serves as the OS's brain. It implements:
- A bare-metal Vector Store utilizing pure cosine similarity math (replacing ChromaDB).
- A native LLM orchestrator and planner that can construct prompts and communicate over the RTL8139 NIC.
- Direct capability-authorized `sys_ipc_send` access to control the kernel.

Try it in QEMU:

```text
agent status
agent start
agent send ping
programs
users
run agent-bridge
syscall 4 5 1
syscall 4 1
agent status
ipc
syscalls
```

Future work for the native agent boundary:

1. Build the cognitive networking layer so the daemon can issue HTTP requests to LLM APIs over TCP.
2. Build the ATA PIO block driver and an Ext2 filesystem so the vector store can persist its neural graphs across reboots.
3. Build the `sys_exec` syscall and Virtual File System so the agent can spawn child processes and workers autonomously.

## Design Rules

- Keep the kernel deterministic.
- Keep AI, semantic memory, and vector search outside kernel space.
- Prefer capability-checked service boundaries over global authority.
- Use Rust safety by default; keep unsafe blocks small and documented.
- Treat runtime services as replaceable modules.
- Favor maintainability over feature quantity in v1.
