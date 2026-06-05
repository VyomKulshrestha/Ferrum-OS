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
- Preemptive task scheduler with per-task context switching and priority queues
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
- Native Heliox-OS Agent Daemon (`heliox-daemon`) with:
  - Bare-metal orchestrator (ReAct loop), planner, and vector store
  - TCP networking layer with HTTP/1.1 client for LLM API calls
  - `no_std` JSON parser and LLM response decoder
  - Tool-to-Syscall mapper (25 tools mapped to kernel syscalls)
  - 5-tier permission model with operator confirmation gates
  - JSON-based runtime configuration from Ext2 disk
  - Reasoning telemetry emitted to kernel audit log

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
| `heliox status` | Show Heliox-OS native daemon state |
| `heliox methods` | List Heliox JSON-RPC methods with required capabilities |
| `heliox tiers` | List the 5-tier Heliox permission model |
| `heliox actions` | List the Heliox action catalog (120 actions) |
| `heliox services` | List Heliox runtime service slots |
| `heliox send <method> [input]` | Submit a Heliox JSON-RPC request envelope |
| `heliox execute <input>` | Submit a Heliox ReAct pipeline input |
| `log` | Show audit log |
| `uptime` | Show timer ticks |
| `uname` | Show system information |
| `whoami` | Show current shell capability profile |
| `session [root\|guest]` | Switch debug shell capability profile |
| `spawn <name>` | Spawn a task metadata record |
| `kill <pid>` | Mark a task dead |
| `security` | Show security status |
| `about` | Show FerrumOS architecture notes |

## Development Status

All core kernel phases are complete:

1. ✅ Real userspace execution (ELF loading, Ring-3 entry, `iretq` trampoline)
2. ✅ Preemptive scheduling (context switching, priority queues, `sleep`/`wait`)
3. ✅ SMP, ACPI shutdown/reboot, persistent PID 1 supervisor
4. ✅ RTL8139 NIC driver + smoltcp TCP/IP stack + socket syscalls
5. ✅ Native Heliox-OS agent daemon (orchestrator, planner, vector store)

6. ✅ Cognitive networking (bare-metal HTTP client, DNS resolver, LLM API integration)
7. ✅ Tool execution & JSON (no_std JSON parser, tool-to-syscall mapper)

Current focus: **Phase C — Hardware Drivers** (VGA Framebuffer, Intel HDA Audio).

## Heliox-OS Native Integration

FerrumOS has evolved into a true Agentic OS. Instead of relying on a host machine to run the [Heliox-OS](https://github.com/VyomKulshrestha/Heliox-OS) Python daemon via a network bridge, the intelligence has been ported natively to Rust!

The OS now contains `userland/heliox-daemon`, a native userspace binary that serves as the OS's brain. It implements:
- A bare-metal Vector Store utilizing TF-IDF bag-of-words embeddings and cosine similarity math.
- A native LLM orchestrator (ReAct loop) and hierarchical planner that constructs prompts and communicates over the RTL8139 NIC.
- A bare-metal HTTP/1.1 client and DNS resolver for querying Ollama/OpenAI-compatible LLM APIs.
- A `no_std` JSON parser for decoding LLM responses.
- A tool-to-syscall mapper that translates 25 LLM tool calls (`ipc_send`, `read_file`, `exec_process`, `net_connect`, etc.) into kernel syscalls.
- A 5-tier permission model that blocks destructive actions behind operator confirmation gates (`confirm <id>`).
- Direct capability-authorized `sys_ipc_send` access to control the kernel and emit reasoning telemetry to the audit log.

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

1. Build the ATA PIO block driver and an Ext2 filesystem so the vector store can persist its neural graphs across reboots.
2. Build the `sys_exec` syscall and Virtual File System so the agent can spawn child processes and workers autonomously.

## Design Rules

- Keep the kernel deterministic.
- Keep AI, semantic memory, and vector search outside kernel space.
- Prefer capability-checked service boundaries over global authority.
- Use Rust safety by default; keep unsafe blocks small and documented.
- Treat runtime services as replaceable modules.
- Favor maintainability over feature quantity in v1.
