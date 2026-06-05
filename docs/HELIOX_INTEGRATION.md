# Heliox-OS Integration

FerrumOS is built to host a [Heliox-OS](https://github.com/VyomKulshrestha/Heliox-OS)
style agent runtime above the kernel boundary. The kernel ships with a
deterministic, capability-checked integration surface for Heliox today, so
that when the Heliox Python daemon (or a ported userspace runtime) attaches
to FerrumOS the protocol, policy, and service topology are already in place.

This document describes the wire contract, the kernel-side bridge, and the
porting path.

## Goals

- **Deterministic boundary.** All AI inference, vector search, planning, and
  semantic memory stay in runtime services above the kernel. The kernel only
  holds the protocol, capability policy, and audit hooks.
- **Stable JSON-RPC 2.0 surface.** The kernel knows the full Heliox method
  registry, action catalog, and permission tier model so transport can be
  upgraded (WebSocket now, anything else later) without changing runtime
  services.
- **Default-deny capability policy.** Heliox authority is broken into six
  capability tokens (`cap:heliox:bridge`, `:execute`, `:voice`, `:gesture`,
  `:screen`, `:persona`) so a misbehaving runtime service cannot escalate.
- **Service topology pre-registered.** The nine Heliox runtime slots
  (`runtime.heliox.bridge`, `runtime.heliox.input`, `runtime.heliox.inference`,
  `runtime.heliox.memory`, `runtime.heliox.orchestrator`,
  `runtime.heliox.screen`, `runtime.heliox.persona`, `runtime.heliox.plugins`,
  `runtime.heliox.audit`) are registered at boot as sandboxed runtime
  service manifests.

## Wire Contract

The Heliox-OS daemon talks to its Tauri front-end over JSON-RPC 2.0. FerrumOS
mirrors that contract in kernel-visible types (`src/heliox/mod.rs`).

| Property      | Value                       |
| ------------- | --------------------------- |
| Transport     | `ws://127.0.0.1:8785`       |
| Protocol      | `jsonrpc/2.0`               |
| Request       | `{ jsonrpc, method, params, id }` |
| Response      | `{ jsonrpc, result, id }`   |
| Error         | `{ jsonrpc, error: { code, message }, id }` |
| Notification  | `{ jsonrpc, method, params }` (no `id`) |

Standard error codes follow JSON-RPC 2.0:

- `-32700` parse error
- `-32600` invalid request
- `-32601` method not found
- `-32602` invalid params
- `-32603` internal error

FerrumOS does not parse JSON in kernel space; it records the envelope shape
and routes the deterministic metadata through the kernel IPC broker. The
actual JSON serialisation belongs in the future userspace Heliox runtime.

## Method Registry

The kernel registers the full Heliox method surface split into two classes:

- **Request** (synchronous, expects `result` or `error`): `execute`, `confirm`,
  `get_config`, `update_config`, `get_history`, `store_api_key`,
  `delete_api_key`, `list_api_keys`, `ping`, `health`, `system_status`,
  `capabilities`, `list_ollama_models`, `agent_routing`, `agent_stats`,
  `agent_capabilities`, `agent_spawn`, `voice_event`, `gesture_event`,
  `multimodal_stats`, `reasoning_log`, `reasoning_stats`, `decompose_task`,
  `simulate_plan`, `prompt_strategies`, `prompt_stats`, `plugin_list`,
  `plugin_tools`, `plugin_toggle`, `persona_rules`, `persona_consolidate`,
  `persona_add_preference`, `subconscious_stats`, `screen_context`,
  `screen_current_app`, `screen_vision_stats`, `screen_vision_toggle`,
  `cognitive_stats`, `cognitive_state`, `attention_toggle`,
  `stress_gate_toggle`, `intent_predictor_toggle`, `tribe_model_toggle`,
  `voice_listener_start`, `voice_listener_stop`, `voice_listener_stats`,
  `autonomous_submit`, `autonomous_cancel`, `autonomous_jobs`,
  `autonomous_job`, `proactive_start`, `proactive_stop`, `proactive_stats`,
  `proactive_accept`, `proactive_dismiss`, `background_tasks`,
  `background_start`, `background_stop`, `reflection_stats`,
  `resolve_git_conflict`, `apply_git_resolution`.
- **Notification** (broadcast, no `id`): `status`, `agent_routing`,
  `plan_preview`, `confirm_required`, `action_start`, `action_complete`,
  `orchestrator_routing`, `reasoning_event`, `voice_command`, `voice_status`,
  `voice_result`, `multimodal_intent`, `feature_announcement`.

Each method declares the capability required to invoke it. The kernel
rejects any invocation that does not hold that capability.

## Permission Tiers

Heliox-OS uses a five-tier permission model. FerrumOS reproduces it in
`heliox::PermissionTier` and `heliox::list_action_categories()`.

| Tier | Label             | Auto-Execute | Examples |
| ---- | ----------------- | ------------ | -------- |
| 0    | Read Only         | Yes          | `file_read`, `system_info`, `screenshot`, `screen_ocr` |
| 1    | User Write        | Yes          | `file_write`, `clipboard_write`, `mouse_click`, `browser_navigate` |
| 2    | System Modify     | Confirm      | `package_install`, `service_restart`, `shell_command`, `disk_mount` |
| 3    | Destructive       | Confirm      | `file_delete`, `process_kill`, `power_shutdown`, `disk_unmount` |
| 4    | Root Critical     | Confirm      | `power_sleep`, `power_lock`, `dbus_call` |

Total action count: 120 (mirrors the Heliox `daemon/pilot/actions.py`
enumeration). Use `heliox actions` in the shell to inspect them.

## Runtime Service Topology

At boot, the Heliox bridge registers nine sandboxed runtime service manifests
so the kernel's service registry already matches the Heliox runtime
architecture before userspace services exist:

| Slot                          | Purpose                                           | Required Capability        |
| ----------------------------- | ------------------------------------------------- | -------------------------- |
| `runtime.heliox.bridge`       | JSON-RPC bridge, envelope dispatch, audit fan-out | `cap:heliox:bridge`        |
| `runtime.heliox.input`        | Voice, gesture, multimodal event intake           | `cap:heliox:voice`         |
| `runtime.heliox.inference`    | Local model inference (Ollama, TRIBE, cloud LLM)  | `cap:heliox:execute`       |
| `runtime.heliox.memory`       | Semantic memory and vector store                  | `cap:heliox:bridge`        |
| `runtime.heliox.orchestrator` | Planner, orchestrator, verifier, reflector        | `cap:heliox:execute`       |
| `runtime.heliox.screen`       | Screen vision and active app detection            | `cap:heliox:screen`        |
| `runtime.heliox.persona`      | Subconscious persona learning and consolidation   | `cap:heliox:persona`       |
| `runtime.heliox.plugins`      | Plugin registry, Ed25519 signature verification   | `cap:heliox:bridge`        |
| `runtime.heliox.audit`        | Audit exporter for Heliox-OS lifecycle events     | `cap:heliox:bridge`        |

All slots are registered with `SandboxProfile::runtime_default()` (IPC-only,
isolated address space, 64 KiB memory budget, syscall auditing).

## Userspace Bridge Manifest

`userspace::init()` registers a `heliox-bridge` program manifest at
`/srv/heliox-bridge` with `cap:ipc:send`. The manifest is the future adapter
that the Heliox Python daemon (or a Rust port) attaches to. Capability
escalation beyond `cap:ipc:send` happens at the kernel IPC broker, not in
the bridge process.

## Shell Surface

The `heliox` shell command group surfaces the integration state for
operators:

| Command                                 | Description |
| --------------------------------------- | ----------- |
| `heliox status`                         | Bridge counters, listener state, screen vision state, persona rule count |
| `heliox methods`                        | Full JSON-RPC method table with required capabilities |
| `heliox tiers`                          | Five-tier permission model with action counts |
| `heliox actions`                        | Full Heliox action catalog grouped by tier |
| `heliox services`                       | Registered Heliox runtime slots with service IDs and state |
| `heliox send <method> [input]`          | Submit a JSON-RPC request envelope (capability-checked) |
| `heliox notif <method>`                 | Prepare a Heliox notification envelope |
| `heliox voice start\|stop\|event <txt>` | Drive the voice listener state machine |
| `heliox screen on\|off\|context`        | Drive the screen vision state machine |
| `heliox persona [add key=value]`        | Inspect or append persona rules |
| `heliox confirm <plan_id>`              | Resolve a pending confirmation gate |
| `heliox execute <input>`                | Submit a full ReAct pipeline input |

The full sweep of these commands is exercised by `scripts/command_sweep.mjs`.

## Porting Heliox-OS to FerrumOS

The porting path is intentionally incremental. The kernel does not need to
change again to host Heliox-OS; everything below is userspace work.

1. **Implement ring-3 userspace execution.** Add ELF loading, isolated
   address spaces, and a real `iret` syscall entry in the kernel.
2. **Replace kernel-side stubs with userspace services.** The
   `runtime.heliox.*` service manifests already exist; the real implementations
   live in userspace (like the native `heliox-daemon` mapping 25 LLM tools).
   into Rust or wrap the Python daemon inside a `heliox-bridge` userspace
   process that talks to the kernel IPC broker.
3. **Add a userspace WebSocket transport.** The `HELIOX_TRANSPORT` constant
   points to `ws://127.0.0.1:8785`. The kernel records the contract; a
   userspace netstack or loopback-only transport implements the bytes.
4. **Port the multimodal / screen vision / persona / plugin subsystems.**
   The kernel has registered capability tokens for each subsystem, so the
   ported services must hold the matching token at runtime.
5. **Replace the `agentd` boundary with the real planner/orchestrator.**
   The existing `agentd` remains as a sandboxed stub. When the real planner
   is ported, the orchestrator service in the `runtime.heliox.orchestrator`
   slot takes over without changing the IPC contract.

## Audit Surface

Every Heliox envelope dispatch and method denial is recorded in the kernel
audit log:

- Successful envelope dispatch -> `AuditEvent::FileAccess` with
  `heliox envelope dispatched: <method>`.
- Denied invocation -> `AuditEvent::PermissionDenied` with the missing
  capability token.
- Voice / gesture / screen / persona state changes -> `AuditEvent::FileAccess`.

The `audit-exporter` userspace manifest forwards the same log to runtime
services for export to the Heliox append-only audit trail.
