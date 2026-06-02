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
- Capability registry and caller-held capability authorization helpers
- Debug shell session profiles for root and restricted guest capability checks
- Audit logging hooks for security and lifecycle events
- Modular service manager with typed service manifests and sandbox profiles
- Deterministic IPC message contracts for future runtime services
- Userspace program manifests and process capability table
- Capability-authorized syscall dispatch for IPC, service lifecycle checks,
  capability checks, and audit writes
- Capability-gated `agentd` runtime boundary stub for future agent integration

## Architecture

```text
+----------------------------------------------------------+
| Agent Layer (future)                                    |
| Autonomous workflows, planning, verification             |
+----------------------------------------------------------+
| Cognitive Layer (future)                                |
| Semantic memory, vector search, context management       |
+----------------------------------------------------------+
| Runtime Layer                                           |
| Services, permissions, IPC, AI orchestration boundaries  |
+----------------------------------------------------------+
| Kernel Layer                                            |
| Boot, memory, interrupts, scheduling, isolation, HAL     |
+----------------------------------------------------------+
```

The existing Python desktop agent can be treated as a future runtime or
agent-layer service. Its voice, gesture, local LLM, and autonomous task
execution logic should remain outside the kernel and communicate through
capability-checked runtime interfaces.

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
| `mkdir <dir>` | Create directory |
| `touch <file>` | Create empty file |
| `write <file> <text>` | Write text to file |
| `rm <path>` | Remove file or directory |
| `caps` | List security capabilities |
| `services` | List registered services |
| `services start <id>` | Start a service through capability checks |
| `services stop <id>` | Stop a service through capability checks |
| `ipc` | Show IPC broker statistics |
| `syscalls` | Show reserved syscall ABI numbers |
| `programs` | List userspace program manifests |
| `users` | List launched userspace process records |
| `run <program>` | Launch a manifest-backed userspace process |
| `syscall <pid> <num> [arg0]` | Dispatch a syscall as a userspace process |
| `agent status` | Show agent runtime boundary state |
| `agent start` | Start the sandboxed `agentd` boundary service |
| `agent send <text>` | Send a capability-checked IPC command to `agentd` |
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

Try it in QEMU:

```text
agent status
agent start
agent send ping
programs
run agent-bridge
syscall 3 5 1
syscall 3 1
agent status
ipc
syscalls
```

Future work should attach the real agent runtime above this boundary:

1. Add real userspace process loading.
2. Implement syscall entry from ring 3.
3. Move runtime services out of kernel modules.
4. Port or host the agent planner, orchestrator, verifier, sandbox, memory,
   and plugins as userspace services.
5. Add device drivers for audio, camera, display, input, storage, and network
   before enabling voice, gesture, screen vision, or desktop control.

## Design Rules

- Keep the kernel deterministic.
- Keep AI, semantic memory, and vector search outside kernel space.
- Prefer capability-checked service boundaries over global authority.
- Use Rust safety by default; keep unsafe blocks small and documented.
- Treat runtime services as replaceable modules.
- Favor maintainability over feature quantity in v1.
