# FerrumOS Architecture

## Core Boundary

The kernel owns deterministic primitives only:

- CPU and interrupt setup
- Memory mapping and allocation
- Scheduling metadata
- Hardware abstraction
- Capability policy checks
- Audit hooks
- Minimal filesystem and shell support for early development

## Filesystem

The current filesystem is a volatile RAM filesystem mounted at `/` as
`ramfs.root`. It supports directory listing, file reads/writes, removal,
metadata through `stat`, and usage reporting through `mounts`. This keeps the
early shell useful while block storage drivers are still pending.

## Device Registry

FerrumOS tracks device surfaces through a small registry. Online devices
represent hardware or kernel facilities that are available now: VGA text output,
COM1 serial, PIT timer, PS/2 keyboard, the RAM filesystem, and the RTL8139
PCI network controller. Planned devices represent contracts needed by future
runtime services: audio and camera surfaces.

The registry labels unavailable devices as `Planned` instead of claiming driver
support. This keeps integration honest while making the missing hardware work
visible from the shell through `devices`.

## Network

The network subsystem provides real TCP/IP networking via the RTL8139 PCI NIC
driver and the smoltcp embedded TCP/IP stack. The kernel exposes socket syscalls
(`sys_socket`, `sys_connect`, `sys_send`, `sys_recv`, `sys_bind`) that create
real smoltcp TCP sockets backed by the hardware NIC. The smoltcp interface is
configured with QEMU's default user-mode networking address (10.0.2.15/24,
gateway 10.0.2.2). A loopback interface (`lo` at 127.0.0.1/8) is also available
for local capability-checked packet delivery.

The kernel must not embed probabilistic systems, model inference, vector search,
semantic memory, or autonomous planning logic.

## Runtime Boundary

Runtime services are the correct integration point for the native `heliox-daemon`
and future Rust services. They should receive only the capabilities required
for their task and should communicate through IPC contracts or future
shared-memory handles.

Every service is described by a `ServiceManifest`:

- `layer` records whether it belongs to kernel, runtime, cognitive, or agent
  architecture.
- `required_capabilities` names the exact lifecycle capabilities needed to
  start or stop the service.
- `sandbox` records early isolation intent: IPC-only execution, isolated address
  space, memory budget, and syscall audit policy.

The service manager also tracks health-check counts and restart counts. This is
still an in-kernel supervisor model, but it gives runtime services a concrete
operational surface before userspace service managers are available.

Initial runtime service categories:

- `runtime.ipc`
- `runtime.agentd`
- input service for keyboard, voice, gesture, and multimodal events
- local inference service
- semantic memory service
- task orchestration service
- verification and audit export service

## Capability Model

Capabilities are explicit permission tokens. A service action is allowed only
when the caller holds a token that maps to the requested resource pattern.
Service lifecycle operations use exact token checks, while IPC and resource
access use resource-pattern checks.

The v0.1 shell includes debug session profiles so capability enforcement can be
exercised before real userspace exists:

- `root` holds `cap:system:all` and can exercise kernel management commands.
- `guest` holds only `cap:fs:read`, so filesystem reads work while writes,
  service control, agent commands, process management, and audit reads are
  denied and logged.

This is a development tool, not a final login model. Real identity,
authentication, and per-process capability assignment belong in the future
userspace/runtime layer.

## Userspace Model

FerrumOS has a functional userspace execution environment with Ring-3 entry,
ELF loading, per-process address spaces, and preemptive scheduling:

- Program manifests for `init`, `heliox-daemon`, and `audit-exporter`
- Delegated capability sets checked at launch
- Process records with PID, entry path, state, and syscall count
- Syscall dispatch that authorizes against the process capability table
- Bootstrapping of the manifest-backed `init` process after scheduler startup
- The `heliox-daemon` binary is the native Heliox-OS agent process

Important rules:

- Default deny.
- Delegation is explicit.
- Runtime services do not receive unrestricted kernel authority.
- Audit hooks record denied operations and lifecycle changes.

## System Layers

```text
Agent Layer (heliox-daemon):
  autonomous workflows, planning, verification

Cognitive Layer (heliox-daemon):
  semantic memory, vector search, context management

Runtime Layer:
  services, permissions, IPC, orchestration boundaries

Kernel Layer:
  scheduling, memory, isolation, hardware abstraction

Hardware / NIC Layer:
  RTL8139 driver, smoltcp TCP/IP stack, socket syscalls
```

The cognitive and agent layers run natively in the `heliox-daemon` userspace
process and can evolve quickly without destabilizing the kernel.

## Current Agent Boundary

The `heliox-daemon` userspace process acts as the true Agent Boundary. It runs
a native Rust LLM orchestrator, planner, and semantic memory vector store.

The manifest requires `cap:agent:control` to start the boundary or send
commands. The spawned task receives only delegatable capabilities, such as
`cap:ipc:send` and `cap:net:connect`, so agent-control authority is not
silently propagated into child tasks.

## Heliox-OS Native Integration Layer

FerrumOS implements the Heliox-OS architecture natively. The legacy network
JSON-RPC bridge has been completely removed in favor of a native freestanding
`heliox-daemon` userspace process.

The `heliox-daemon` provides:
- A pure Rust bare-metal Vector Store implementing cosine similarity.
- A cognitive planner and LLM orchestrator that constructs prompts with tool
  definitions and queries external LLM APIs.
- A bare-metal HTTP/1.1 TCP client and DNS resolver for communicating with
  Ollama and OpenAI-compatible endpoints over the RTL8139 NIC.
- A `no_std` JSON parser for decoding LLM API responses.
- A tool-to-syscall mapper that translates 8 LLM tool calls (`ipc_send`,
  `service_start`, `audit_write`, `net_connect`, etc.) into kernel syscalls.
- Direct capability-authorized invocation of kernel syscalls to enact the
  agent's decisions.

The remaining integration work focuses on persistent memory (ATA PIO driver +
Ext2 filesystem for vector store persistence) and the VFS / `sys_exec` syscall
for agent-spawned worker processes.
