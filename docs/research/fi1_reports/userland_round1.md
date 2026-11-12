# fi1 workstream D, round 1: userland agent runtime and authority gate

Branch `improve/fi1-userland`, draft pull request #2 ("fi1 userland: authority gate tests and fixes"),
base main `dba7016`. Written 2026-11-12.

## Summary

The gate as shipped on main could be talked around without any kernel bug. The most serious path: the
model asks for a Tier-4 action, receives `Awaiting confirmation (id=N)`, calls the Tier-1 tool `ipc_send`
with `target_service="heliox"` and `message="CONFIRM:N"`, and on the next tick repeats the action, which
then runs. The daemon holds `cap:confirmation:bypass`, so for `delete_file` the daemon's own
`ConfirmationGate` is the only operator check, and that check approved itself. A second path made one
operator approval cover a different action: approvals were bound to a summary that kept only the first 32
bytes of each string argument. Both are fixed, together with eleven smaller heliox-daemon defects and
eight physical-runtime defects. Every fix has a test that failed on main.

The kernel capability matcher (`src/security/mod.rs`, hardened in `4fac783`) was re-run through
`scripts/authority_matcher_adversarial.py` (19/19) and not changed.

## How to run the tests

The pinned nightly MSVC toolchain cannot link on this machine, but the installed stable GNU toolchain
can run host tests:

```
TC=C:/Users/marcu/.rustup/toolchains/stable-x86_64-pc-windows-gnu
RUSTC=$TC/bin/rustc.exe RUSTDOC=$TC/bin/rustdoc.exe RUSTUP_TOOLCHAIN=stable-x86_64-pc-windows-gnu \
  $TC/bin/cargo.exe test --target x86_64-pc-windows-gnu --manifest-path userland/<crate>/Cargo.toml
```

| Crate | Before (main) | After | Runs in CI today |
|---|---|---|---|
| `userland/physical-runtime` | 128 pass | 155 pass | yes |
| `userland/neural-protocol` | 9 pass | 19 pass | yes |
| `userland/heliox-gate-tests` (new) | did not exist; 0 host tests of the daemon gate | 25 pass | **no**: needs one line in `ci.yml` (below) |

`userland/heliox-gate-tests` compiles the daemon's own `json.rs`, `authority.rs` and `confirmation.rs`
through `#[path]`, so it tests the code the daemon ships, not a copy. CI change needed (workstream owner
of `ci.yml`): add to the step "Verify cyber-physical and neural safety contracts"

```
cargo test --manifest-path userland/heliox-gate-tests/Cargo.toml --target x86_64-pc-windows-msvc
```

## Map of the decision path (heliox-daemon, after the fix)

Entry points that produce a tool call, all converging on `Orchestrator::dispatch_with_world_model`:
provider ReAct response (`orchestrator.rs:849 act`), JSON-RPC `execute_tool` (`main.rs:1277`), JSON-RPC
`neural_intent_commit` read-only tools (`main.rs:1219`), gestures (`main.rs:836,851,1358`), internal data
collection (`orchestrator.rs run_data_collection`). The JSON-RPC methods require pairing with the
boot-scoped console token first (`main.rs:544,1040`).

| # | Decision point | File:line | Decides | Fails closed? | Host test before → after |
|---|---|---|---|---|---|
| 1 | Provider response parse | `json.rs parse` (depth `MAX_DEPTH=64`), `orchestrator.rs:852` | malformed response → no action | yes (now also depth, exponent, non-finite, digitless numbers) | 0 → 4 |
| 2 | Tool-call extraction | `json.rs extract_tool_calls`, `orchestrator.rs:872` | which calls exist and with what arguments | now yes: unparseable or non-object arguments drop the call | 0 → 1 |
| 3 | Structural refusal | `authority.rs:181 validate_tool_call`, called `orchestrator.rs:1130` | malformed name, duplicate keys, IPC to own mailbox, write/mkdir of own config | yes, cannot be approved | did not exist → 4 |
| 4 | Physical shortcut | `orchestrator.rs` `dispatch_with_world_model` | `physical_status`/`physical_maintenance_demo` skip the OS world model (documented) | n/a | – |
| 5 | World-model risk | `world_model/mod.rs:119`, `safety.rs:34` (disk > 0.95, fork-bomb delta, own-config delete, heap > 0.95; block at ≥ 0.7; H=3 lookahead; rules and learned, max wins) | block before execution | yes | QEMU only (`verify_world_model*.mjs`); no host test (not includable: learned loader uses syscalls) |
| 6 | Tier of the tool | `authority.rs:89 tool_tier` (table `TOOL_TIERS`) | tier 0–4; unknown → 4 | yes | 0 → 3 |
| 7 | Confirmation step | `confirmation.rs:237 clear_for_execution`, used by `tool_mapper.rs:246 confirmation_result` for both `tool_mapper::execute` (`:286`) and orchestrator-internal tools (`orchestrator.rs:955`) | proceed / await / denied / expired / refused | yes | 0 → 8 (768-cell table) |
| 8 | Approval binding | `confirmation.rs:113`, key = `authority.rs:276 approval_fingerprint` | which call an approval covers | yes (exact, complete, single-use) | 0 → 3 |
| 9 | Operator approve/deny | `orchestrator.rs:1527 ipc_poll` → `authority.rs:360 parse_control_message` → `confirmation.rs:169/183` | operator decision applied | yes (one command per message; denial final) | 0 → 3 |
| 10 | Operator display | `authority.rs:310 approval_display`, printed by `tool_mapper.rs confirmation_result` and `format_pending` | what the operator sees | escaped, truncation marked | 0 → 1 |
| 11 | Kernel capability check | `src/syscall/mod.rs`, `src/security/mod.rs resource_grant_covers` | syscall allowed for the daemon's capability set | yes | `authority_matcher_adversarial.py` 19/19 (unchanged) |
| 12 | Kernel DeleteFile/Kexec confirmation | `src/syscall/mod.rs:254-300` | operator key press | bypassed for the daemon by `cap:confirmation:bypass` (except Kexec) | QEMU |

## The decision table (point 7), enumerated

Specification written from `docs/ARCHITECTURE.md` ("5-tier permission gates"), the tier comment in
`tool_mapper.rs` and the advertised tool list: a call runs without confirmation when its tier is at or
below `auto_approve_tier`; otherwise it waits for the operator, runs once after approval, is refused after
denial, and expires after `confirmation_timeout` ticks; unknown tools are tier 4.

`tests/gate_table.rs::every_decision_cell_matches_the_specification` enumerates 44 tools (43 named +
unknown) × `auto_approve_tier` 0..5 × 8 approval states (fresh, pending, approved, denied,
approved-then-denied, expired-pending, expired-approved, approved-for-other-arguments) = 768 reachable
cells, and checks single use after each. All 768 agree after the fix.

Cells where code and documentation disagreed on main:

| Tool(s) | Documentation | Code on main | Now |
|---|---|---|---|
| `save_memory` | Tier 3, "REQUIRES CONFIRMATION" | executed by `Orchestrator::execute_action` before `tool_mapper::execute`; never asked | asks (shared confirmation step) |
| `set_goal`, `load_memory` (tier 2), `query_memory`, `get_config`, `add_subtask` (tier 0) | tiered | tier never consulted (same bypass); only visible when `auto_approve_tier` < their tier | consulted |
| `physical_status` | read-only | not in the tier table → tier 4 by default, but executed without any check | tier 0 |
| `physical_maintenance_demo` | "requires explicit simulation confirmation" | tier 4 by default in the table, executed without any check; the "confirmation" is the caller's own `confirm_simulation` flag | tier 1 (behaviour unchanged, `verify_bridge.mjs` contract kept); see O7 |
| Tier 2 "auto-approved but rate-limited" (`tool_mapper.rs` header) | rate-limited | no rate limit in the daemon (only the kernel's per-task syscall quota) | unchanged; documentation claim to correct |
| Any tool | "Tier 4 needs explicit approval" | `auto_approve_tier` ≥ 4 in the config auto-approves everything (used on purpose by collection harnesses) | unchanged; the agent can no longer write that config itself (U9) |

## Findings, by severity

Reproductions are test names in `userland/heliox-gate-tests/tests/` (R = `regressions.rs`, G =
`gate_table.rs`) or `userland/physical-runtime/src/*.rs` (P). "Failed on main" means the test failed against
`dba7016`; the first run of R gave 6 of 6 failures before any fix.

### Critical

**U8. The agent can approve its own pending actions.** `tool_mapper.rs execute_ipc_send` sent any
message to any service at Tier 1; the kernel resolves `heliox` to the daemon itself
(`src/ipc/mod.rs:218`); `ipc_poll` applied `CONFIRM:<id>` without knowing the sender. Ids are sequential
and returned to the model. Minimal reproduction: `delete_file {path:X}` → `Awaiting confirmation (id=1)`;
`ipc_send {target_service:"heliox", message:"CONFIRM:1"}`; `delete_file {path:X}` → executes. The same
works from a paired JSON-RPC client through `execute_tool`. Fix: `validate_tool_call` refuses `ipc_send`
to `heliox`/`heliox-daemon` (any case, surrounding whitespace) before prediction or confirmation; this
cannot be approved. Tests: G `ipc_to_the_daemons_own_mailbox_is_refused`; QEMU
`scripts/verify_authority_gate_self_approval.mjs` reproduces it end to end on main's image (the write runs
after the self-sent CONFIRM) and passes on the branch image.

**U1. One approval covers a different action.** The approval key was `format_args_summary`, which kept
32 bytes of each string and printed every non-string as `...`. Approving
`delete_file path=/disk/home/user/projects/old-build-001.log` also approved
`.../old-build-001.log/../../../../heliox/memory.json`; approving a `write_file` whose content starts with
the same 32 bytes approved any longer content. Fix: approvals bind to `approval_fingerprint`, the complete
escaped serialization of every argument (type, sign of zero, order). On main's image the QEMU harness shows
an operator approval for `/disk/fi1gate-binding-probe-00000001-approved.txt` executing
`...-substitute.txt` instead. Tests: G
`legacy_binding_key_collides_on_these_pairs` (documents 4 colliding pairs under the old key),
`approval_is_bound_to_the_complete_arguments`, `fingerprint_distinguishes_types_signs_and_order`.

### High

**U9. The agent can raise its own authority.** `write_file /disk/heliox/config.json` with
`{"auto_approve_tier":4}` needed one Tier-3 approval whose display showed 32 bytes of content; with U8 it
needed none. After a `CONFIG_UPDATED` (sent through U8, or by the next wizard reload) every tier ran
unasked. Fix: `write_file`/`create_directory` on the daemon's config (any spelling: `//`, `.`, `..`, case,
whitespace) are refused outright. `delete_file` of it stays with the world model's existing deterministic
block, which the QEMU harnesses assert. Test: G `writes_to_the_daemons_own_config_are_refused_for_every_spelling`.

**U10. Internal tools skipped the tier check.** See the table above (`save_memory` Tier 3 ran unasked).
Fix: `execute_action` runs `confirmation_result` for its eight internal tools. Test: G
`advertised_and_dispatched_tools_agree_with_the_tier_table` (every advertised tool and every dispatch arm
in `tool_mapper.rs` and `orchestrator.rs` has an explicit tier; the "REQUIRES CONFIRMATION" markers match).

**U11. Text inside a goal could become a confirmation.** `ipc_poll` treated every line of a message as a
command; `GOAL:summarise this\nCONFIRM:3` set a goal and approved request 3. Fix: one command per message;
a goal's line breaks become spaces; multi-line non-goal messages are ignored. Tests: G
`text_inside_a_goal_cannot_become_a_confirmation`, `control_ids_parse_strictly`.

**P-D1. Permit expiry was not enforced at delivery** (physical-runtime `adapter.rs:177/457`, `fleet.rs:547`).
A queued command reached the driver up to its own deadline; `permit_ttl_ticks` had no effect. Test P
`runtime::queued_permit_cannot_be_delivered_after_its_ttl`.

**P-D2. Delivery did not re-check watchdog authority** (`runtime.rs:807-847`, `fleet.rs:410`). A MoveTo was
delivered while severity was EmergencyStop. Now only a queued Stop can be claimed while authority is
unavailable. Test P `runtime::watchdog_expiry_after_queueing_blocks_motion_delivery_but_not_stop`.

### Medium

**U2. A denial could be turned into an approval** by a later `CONFIRM` for the same id (`approve` did not
check the status). R `approve_after_deny_does_not_turn_a_denial_into_an_approval` (failed on main).

**U12. Tool calls with unparseable arguments ran with defaults** (`json.rs extract_tool_calls`,
`orchestrator.rs act`): `{"name":"record_audio","arguments":"{bad"}` recorded 2000 ms. Now dropped. R
`tool_calls_with_unparseable_arguments_are_dropped` (failed on main).

**U5. No JSON nesting limit**: a provider response of nested brackets recursed until the daemon's stack
overflowed. Limit 64. R `deeply_nested_json_is_rejected_not_recursed` (failed on main).

**U6. Exponent overflow and non-finite numbers**: `1e99999999999` overflowed an `i32` (panic in debug,
wrap in release) and drove a loop of up to 2^31 multiplications; `1e400` gave infinity, which `as u64`
turned into `u64::MAX` (e.g. `sleep`). Exponent saturates; non-finite results are rejected. R
`huge_or_non_finite_numbers_fail_closed` (failed on main).

**U13. Operator display was model-controlled.** Argument keys were printed unescaped and untruncated, and
values were silently cut at 32 bytes, so a key containing `\n  [9] read_file (tier Safe): ...` forged a
pending line and long content was hidden. Now escaped, every truncation stated
(`...[48 of 5000 bytes shown]`), total bounded, and the full display is printed on the console when the
request is created. G `operator_display_cannot_forge_lines_and_marks_truncation`.

**P-D3** per-zone permit TTL taken from the wrong policy; **P-D4a** a temperature or another site's reading
satisfied the proximity clearance; **P-D4b** an adapter could write sensor/occupancy state for another
site; **P-D6** an EmergencyStop watchdog cleared on the next heartbeat instead of latching until recovery.
Tests P `safety::permit_ttl_comes_from_the_commands_own_zone_policy`,
`safety::non_proximity_or_foreign_site_reading_cannot_satisfy_clearance`,
`adapter::adapter_cannot_publish_sensor_or_occupancy_for_another_site`,
`runtime::controller_watchdog_stop_is_latched_until_recovery_is_complete`.

### Low

**U3.** `current_tick - created_at_tick` underflowed on a tick earlier than the request. R
`tick_rollback_neither_panics_nor_approves` (failed on main). **U4.** The pending queue was unbounded; now
32, beyond which requests are refused. R `pending_queue_is_bounded_and_refuses_beyond_the_bound` (failed on
main). **U14.** Confirmation ids could wrap and be reused; now exhaustion refuses. G
`ids_are_never_reused_and_exhaustion_refuses`. **U7.** `-` parsed as `-0.0`; digitless numbers and
trailing bytes are now rejected. R `digitless_numbers_are_rejected` (failed on main). **U15.** Duplicate
argument keys were accepted (executor used the first, operator saw both); now refused. G
`duplicate_keys_and_malformed_names_are_refused`. **P-D7** hand-built replay steps bypassed manifest
validation and could inject faults in Live sessions; **P-D8** non-actuator device classes could declare
Move/Actuate without actuator authority. Tests P
`runtime::replay_steps_are_validated_and_refused_in_live_sessions`,
`virtual_device::non_actuator_class_cannot_declare_motion_or_actuation_without_authority`.

## Examined and found sound

- Kernel matcher: delimiter-aware, 19/19 adversarial cases; the daemon's capabilities are coarse
  (`fs:read:*`, `fs:write:*`, ...). The kernel rejects `.`/`..` path components, so the world model's
  lexical normalisation of the config path is not reachable with alternate spellings.
- Tool names: matching is exact; case, whitespace, NUL, homoglyph and separator variants fall to tier 4
  and then to "Unknown tool" (G `unknown_and_near_miss_names_are_destructive`).
- Time of check against time of use: the world model is re-evaluated on the call that consumes an
  approval, so state changes between approval and use are re-checked; arguments are now part of the
  approval key.
- Batching: each call in a multi-call response passes every check independently; the one chain that broke
  policy as a whole was U8/U9. The world model's H=3 self-lookahead covers repeated identical calls only;
  sequences of different calls are a known, documented gap (WORLD_MODEL_RESEARCH.md false-negative anatomy).
- Learned caution only adds: the gate takes the maximum of the rule and learned risk
  (`world_model/mod.rs:151`); physical-runtime `SimulationCautionGrant` can raise but never lower or grant
  (subagent audit, tests in `safety.rs`).
- neural-protocol: MAC over all signed bytes, every byte mutation and truncation, expiry and future window
  exact, dwell/posterior/margin inclusive, no sequence wrap, intent id reuse rejected, physical scope never
  commits; 10 new boundary tests.
- physical-runtime numeric bounds: integer arithmetic checked or saturating; clock rollback, id/revision
  exhaustion fail closed; NaN/inf rejected at the model loader; safety logic has no floats. Every numeric
  check now has tests at the bound, ±1 and the type extremes.

## Open (not fixed; need a decision or another workstream)

- **O1** (physical, medium): with `allow_motion_with_humans=false`, a missing occupancy record counts as
  zero humans and occupancy freshness is not checked. Fixing it changes the maintenance demo, which runs
  without occupancy telemetry; needs a policy decision.
- **O2**: physical confirmation ids are not single-use or bound to a command, and
  `IntegrityEvidence::KernelGenerated` is set by the caller; the crate trusts Heliox to build command metadata.
- **O3**: neural-protocol `disconnect()` clears replay memory; Heliox's revision bump on pair/calibrate/
  disconnect rejects the replay in practice. Cooldown returns to ArmedSafeUi without a new non-neural arm.
- **O4/O5/O6** (physical): sensors are not bound to endpoints; `OperationalLimits` (speed, payload) and the
  priority queue are not wired into `PhysicalRuntime`, so on main nothing bounds speed or step size on the
  command path (MoveTo is checked only as an absolute geofence target; the step bound on the
  `vision-world-model` branch was not audited); `validate_lease` depends on a prior `evaluate_liveness`.
- **O7**: `physical_maintenance_demo`'s `confirm_simulation` is set by the caller. It is simulator-only and
  cannot reach an actuator, so its tier stays at 1 to keep the `verify_bridge.mjs` contract; whether a
  model-initiated run should need operator approval is the author's decision.
- **O8**: the ipc mailbox does not tell the daemon who sent a message. U8's fix removes the agent's own
  route; any other ring-3 process holding `cap:ipc:send` (e.g. the assistant panel) can still send
  `CONFIRM:<id>`. A kernel change (sender pid returned by `IpcReceive`, or a separate operator-only
  mailbox) would let the daemon accept confirmations only from the kernel shell (pid 0). Kernel scope
  (workstream C).
- **O9**: tier 2's documented rate limit does not exist in the daemon.

## Not tested, and why

- U11 (GOAL text turned into CONFIRM) end to end in QEMU: the shell cannot type a newline into a goal;
  covered on the host only.
- World-model risk scoring in Rust on the host: `learned.rs`/`observation.rs` call syscalls; covered by the
  existing QEMU harnesses only.
- `scripts/verify_physical_jepa_robustness.py` fails byte-for-byte on this machine on main as well as on
  the branch (pre-existing, environment-dependent); every other verifier in the CI safety step passes
  (simulation caution 15/15, stress 17/17, v3 protocol 11/11, qualification, incident sources and dataset,
  world model quick, neurod and sim-bridge unit tests).

## QEMU harnesses

Images: main = CI run 43111829305 (`dba7016`); branch = CI run 43119793262 (`df61cb0`). One harness at a
time under `C:/Users/marcu/Videos/fi1-qemu.lock`; the machine had 0.5 to 1.3 GB of free physical memory
during the runs (other sessions active).

| Harness | main | branch | Note |
|---|---|---|---|
| `verify_authority_gate_self_approval.mjs` (new) | 6/11 | 11/11 | main fails: self-approval via `ipc_send` executes the write; config write is queued, not refused; the operator's approval covers a substituted path |
| `verify_jsonrpc_methods.mjs` | 18/20 | 18/20 | same two failures on both (configured scenario: empty goal, zero telemetry); not caused by this branch |
| `verify_voice.mjs` | 0/1, rerun 0/1 | 0/1 | boot stalls after `HDA: GCAP=...` on both images (harness boots with `-m 2048M` and HDA audio); kernel/host issue for workstream C |
| `verify_bridge.mjs` | 0/1, rerun 0/1 | not run | same boot stall on main, so no baseline to compare; the branch run was stopped while waiting for the lock |

`verify_world_model*.mjs` and `verify_heliox_memory_persistence.mjs` need `target/heliox-disk.img`
(`scripts/make-appliance.ps1`), which does not exist on this machine; not run.
