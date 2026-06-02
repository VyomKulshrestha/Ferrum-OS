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

FerrumOS tracks device surfaces through a small registry before full driver
probing exists. Online devices represent hardware or kernel facilities that are
available now: VGA text output, COM1 serial, PIT timer, PS/2 keyboard, and the
RAM filesystem. Planned devices represent contracts needed by future
HelioxOS-style runtime services: primary network, audio, and camera surfaces.

The registry deliberately labels unavailable devices as `Planned` instead of
claiming driver support. This keeps integration honest while making the missing
hardware work visible from the shell through `devices`.

The kernel must not embed probabilistic systems, model inference, vector search,
semantic memory, or autonomous planning logic.

## Runtime Boundary

Runtime services are the correct integration point for the existing Python
desktop agent and future Rust services. They should receive only the
capabilities required for their task and should communicate through IPC
contracts or future shared-memory handles.

Every service is described by a `ServiceManifest`:

- `layer` records whether it belongs to kernel, runtime, cognitive, or agent
  architecture.
- `required_capabilities` names the exact lifecycle capabilities needed to
  start or stop the service.
- `sandbox` records early isolation intent: IPC-only execution, isolated address
  space, memory budget, and syscall audit policy.

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

FerrumOS now has an early userspace process registry. It does not yet execute
ring-3 code, but it provides the kernel-visible contracts needed before real
loading exists:

- program manifests for `init`, `agent-bridge`, and `audit-exporter`
- delegated capability sets checked at launch
- process records with PID, entry path, state, and syscall count
- syscall dispatch that authorizes against the process capability table

This lets the kernel exercise realistic runtime-service policy before ELF
loading, process address spaces, and CPU privilege transitions are complete.
The `agent-bridge` manifest is the intended future adapter for HelioxOS-style
agent runtime services.

Important rules:

- Default deny.
- Delegation is explicit.
- Runtime services do not receive unrestricted kernel authority.
- Audit hooks record denied operations and lifecycle changes.

## Future Layers

```text
Kernel Layer:
  scheduling, memory, isolation, hardware abstraction

Runtime Layer:
  services, permissions, IPC, local inference boundary

Cognitive Layer:
  semantic memory, vector search, graph memory, context management

Agent Layer:
  autonomous workflows, planning, verification
```

The cognitive and agent layers can evolve quickly without destabilizing the
kernel because their state, policy, and probabilistic behavior are isolated in
runtime services.

## Current Agent Boundary

`runtime.agentd` is currently a sandboxed service stub. It accepts bounded IPC
messages after capability checks and records the last command. The userspace
`agent-bridge` manifest can exercise IPC syscalls toward runtime services, but
it deliberately does not run a model, planner, semantic memory, screen vision,
or autonomous workflow engine inside the kernel.

The current manifest requires `cap:agent:control` to start the boundary or send
commands. The spawned task receives only delegatable capabilities, such as
`cap:ipc:send`, so agent-control authority is not silently propagated into child
tasks.

The next implementation milestone is true userspace execution: ELF loading,
isolated address spaces, and syscall entry from ring 3.
