# ADR-001: Defer Native Virtualization and Define Host-Managed Cells

Status: Accepted

Date: 2026-08-14

## Context

Ferrum runs learned and provider-driven intelligence outside deterministic
authority. Isolating those workloads in microVMs could reduce blast radius, but
the current kernel does not implement a virtualization backend, second-stage
page tables, virtual interrupts, IOMMU ownership, measured VM boot, or a VMM
lifecycle. Calling development-host-managed QEMU or Firecracker instances a
Ferrum security feature would therefore be inaccurate.

Physical safety also cannot depend on an AI VM. Deadline-critical motor control,
watchdogs, and the independent emergency stop must remain on the MCU, robot
controller, or separate electrical path even if every learned workload fails.

## Decision

Ferrum will keep native virtualization deferred. The current software defines a
host-cell contract for experiments managed by Windows or Linux:

- attested cell identity, kind, generation, and lifecycle;
- explicit observe/propose-only capabilities with no permit or actuator authority;
- bounded messages, rate, memory, CPU, and heartbeat budgets;
- replay-resistant IPC sequencing and restart generation;
- quarantine and termination on malformed, stale, forged, rolled-back, or
  exhausted input; and
- audit provenance that distinguishes host-managed isolation from native Ferrum.

The deterministic supervisor and permit issuer remain outside every test cell.
The contract can be exercised in-process today and used by a future external
QEMU/Firecracker harness without changing physical authorization semantics.

## Consequences

This provides a stable isolation research boundary and adversarial test target,
but it does not provide native VM containment, device assignment, or hard-real-
time guarantees. Host compromise remains outside the evaluated boundary.

Ferrum will not pursue a Type-1 hypervisor merely to strengthen product wording.
Native virtualization is reconsidered only if a measured host-managed experiment:

1. demonstrates a concrete threat that ordinary process isolation does not
   adequately contain;
2. shows a material containment benefit under malicious output, memory pressure,
   forged IPC, pause, rollback, and termination;
3. measures acceptable latency, jitter, memory, and operational cost; and
4. proves VM loss cannot affect deterministic authority or the independent
   controller.

If those gates pass, a separate ADR must select the minimum viable backend and
define CPU virtualization, memory translation, interrupts, timers, virtual
devices, IOMMU, image verification, attestation, resource accounting, fuzzing,
and recovery work. Until then, all public documentation must say
"host-managed cell contract," not "Ferrum microVM isolation" or "Ferrum
hypervisor."
