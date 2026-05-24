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
messages after capability checks and records the last command. It deliberately
does not run a model, planner, semantic memory, screen vision, or autonomous
workflow engine inside the kernel.

The current manifest requires `cap:agent:control` to start the boundary or send
commands. The spawned task receives only delegatable capabilities, such as
`cap:ipc:send`, so agent-control authority is not silently propagated into child
tasks.

The next implementation milestone is to replace the stub with a userspace
service once process loading, syscall entry, and IPC handles exist.
