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
Heliox desktop agent and future Rust services. They should receive only the
capabilities required for their task and should communicate through IPC
contracts or future shared-memory handles.

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

The next implementation milestone is to replace the stub with a userspace
service once process loading, syscall entry, and IPC handles exist.
