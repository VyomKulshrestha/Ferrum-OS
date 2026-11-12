# fi2 workstream P: the gate-policy questions, decided

Branch `improve/fi2-policy`, draft pull request 8 against `main`. Written 2026-11-12. The owner's
answer to the policy questions of the fi1 gate rounds was "add whatever strengthens FerrumOS". For
each question this round took the option that strengthens the gate and keeps a way for the operator
to widen it in `config.json`, replaced the test that pinned the old behaviour (`documents_...`) with
tests of the new behaviour, and ran each new test against the tree with the change held back
(negative control).

Line numbers refer to the head of the branch. The changes went in as four commits rather than one
per question, because the daemon questions share `authority.rs`, `confirmation.rs` and
`orchestrator.rs`: ff8083a (O1, O5), 7a04b5b (daemon gate: Q1, Q2, Q3, Q5, Q-J2a, Q-J2c, Q-J2d),
598d006 (kernel: Q2, Q4, Q5, Q6, Q-J2c), 091cd02 and c0f2655 (scripts and the new harness).

## Summary

| Question | Done | Negative control |
|---|---|---|
| Q1 read, then send | yes | 8 host tests fail with the change held back |
| Q2 approval by id | yes | 5 host tests fail |
| Q3 config fallback | yes | 2 host tests fail |
| Q4 startup test hooks | yes | harness check (see Q4) |
| Q5 service name, autosave, tier clamp, wizard escaping | yes | 5 host tests fail |
| Q6 audit ring | yes | runtime switch in the image: the victim keeps 0 of 10 entries |
| Q-J2a panel flag | yes | 4 host tests fail |
| Q-J2b boot-time panel | left as is, pinned (reason below) | not applicable |
| Q-J2c focus binding | yes | 1 host test fails; kernel self-test |
| Q-J2d ancestor delete | yes | 3 host tests fail |
| O1 occupancy | yes | 6 of 179 runtime tests fail with the interlocks held back (O1 and O5 together) |
| O5 step, payload, battery | yes; speed field left open | as O1 |

Host tests: `heliox-gate-tests` 78 to 99, `physical-runtime` 175 to 179, `neural-protocol` 19 (unchanged).
The controls were run with `C:/Users/marcu/Videos/fi2-tools-p/controls.py` (daemon) and
`control.py` with `controls/o1o5.json` (physical runtime); each replaces the changed lines with the
old behaviour, runs the suite, records the failing tests and restores the files.

## Q1. Read, then send

**Chosen**: options (b) and (d) of round 3, plus the rate limit.

- **What changed**:
  - `authority.rs:802 network_destination`, `:829 host_allowed`, `:841 effective_tier`: a call to
    `http_get`, `browse_url`, `net_connect` or `net_send` is decided at tier 3 unless its host is on
    the allowlist. The `browse_url` host is parsed exactly as `web_agent::parse_url` parses it
    (`authority.rs browse_url_host`), so `https://provider.example@evil.com/` is the host
    `provider.example@evil.com` and asks. `net_send` carries only a descriptor: it is decided by the
    host the agent's own `net_connect` opened that descriptor to (`tool_mapper.rs:375
    agent_socket_host`, recorded at connect); a descriptor the agent did not open asks.
  - The allowlist is the configured provider host (`api_host`), the speech host (`stt_host`) and a new
    `network_allowlist` array in `config.json` (`config_parse.rs network_hosts`), installed at start
    and after every `CONFIG_UPDATED` (`orchestrator.rs:483 install_gate_sources`, and the reload).
  - The notice names the destination: `[reaches host "attacker.example", not on the network
    allowlist]`, or `[sends on connection fd 9.0 to host that cannot be established, ...]`.
  - `poll_input` is tier 3 (`authority.rs:84`).
  - Tier-2 calls that run without approval are limited to 16 per window of 100 daemon ticks
    (`authority.rs:886`, `confirmation.rs:304 admit_tier2`); a call over the limit gets
    `Clearance::RateLimited` and is neither run nor queued. The `tool_mapper.rs` header now names
    the limit.
- **Tests**: `policy_fi2.rs` `q1_read_then_send_to_an_unlisted_host_asks_the_operator`,
  `q1_sends_to_allowlisted_hosts_run_unasked_at_the_default_tier`, `q1_hosts_that_only_look_allowed_are_not`,
  `q1_poll_input_needs_approval`, `q1_tier_2_calls_are_rate_limited_per_window`,
  `q1_the_allowlist_is_the_provider_and_speech_hosts_plus_the_config_field`; `gate_table.rs` (tier
  table and the decision table, 789 to 803 cells). Harness `verify_gate_policy`: an `http_get` to
  `attacker.example` waits with a tier-3 notice naming the host; `poll_input` waits.
- **Control**: with `effective_tier` returning the table tier, `poll_input` at tier 1 and no rate
  limit, 8 tests fail (the four Q1 tests that assert asking, the two tier-table tests, the pending
  test that lists a `poll_input` request).
- **For the operator**: web lookups and connections to hosts other than the model provider and the
  speech server now ask for approval unless the host is listed in `network_allowlist`. The agent can
  no longer read typed keys without approval. A burst of more than 16 network or goal calls within
  100 ticks is refused until the window passes.
- **Residual, stated**: a GET to an allowed host can still carry data in its path or query, and the
  provider receives the model's context anyway (`q1_residual_a_get_to_an_allowed_host_can_carry_data_in_its_path`
  pins it). At `auto_approve_tier` 3 every send runs unasked, as the operator chose.

## Q2. Approval by id

**Chosen**: option (a) of round 3 in the daemon, option (b) in the kernel shell, option (c) for slots.

- **What changed**:
  - `confirmation.rs:540 confirm`: a CONFIRM approves only the request whose full notice was printed
    last (`last_notice`, set when a notice is printed, `confirmation.rs:813`). For any other pending
    request it returns the request's full notice, which the daemon prints again
    (`orchestrator.rs:1736`), and that request becomes the last notice; a second CONFIRM of the same
    id approves it. A notice printed in between starts this over (fails closed: the agent can stall
    the operator, not mislead them). A denial needs no fresh notice and stays final.
  - `PENDING` control message (`authority.rs parse_control_message`), accepted only from the kernel
    shell; the daemon prints every pending request in full (`orchestrator.rs:1749`,
    `confirmation.rs:564 pending_notices`). Kernel shell: `heliox pending` (`src/shell/commands.rs:1524`)
    and `heliox deny <id>` (already present since fi1), both through `send_daemon_control` with the
    kernel-shell sender flag (`commands.rs:1536`).
  - Reserved slots: the agent's own requests fill at most 28 of the 32 slots
    (`confirmation.rs:50 RESERVED_FOR_OPERATOR`); requests from camera gestures are marked by
    `orchestrator.rs:470 execute_operator_gesture_tool`, used by the two gesture handlers in `main.rs`.
- **Tests**: `q2_only_the_request_printed_last_is_approved_by_one_confirm`,
  `q2_a_notice_printed_between_the_two_confirms_starts_over`,
  `q2_heliox_pending_reprints_every_request_and_the_last_one_is_approvable`,
  `q2_the_agent_cannot_fill_the_slots_kept_for_the_operator`; `regressions.rs`
  `pending_queue_is_bounded_and_refuses_beyond_the_bound` (now 28). Harness: a CONFIRM of a request
  that was not printed last approves nothing and prints it again; the second CONFIRM approves it;
  `heliox pending` reprints; `heliox deny` denies.
- **Control**: with every CONFIRM approving and no reservation, 5 tests fail.
- **For the operator**: if another request was printed after the one you confirm, the daemon shows
  you that request again and you confirm it once more. `heliox pending` shows every waiting request
  in full; `heliox deny <id>` refuses one.

## Q3. A configuration that exists and cannot be used

- **What changed**: parsing moved to `userland/heliox-daemon/src/config_parse.rs` (no syscalls,
  compiled by the host tests). `Config::parse` (`:130`) returns `Rejected` with tier 0 (`:137`) when the
  file exists and is larger than the 8192-byte read buffer, is not UTF-8, is not JSON or is not an
  object. `config.rs load_reporting` prints one line per load:
  `[heliox-daemon] /disk/heliox/config.json exists but cannot be used (not valid JSON): running with
  auto_approve_tier 0 until it is fixed`. `tick_interval` and `save_interval` are at least 1
  (`config_parse.rs:189`), and the orchestrator also uses `.max(1)` and a saturating multiply where it
  divides by them.
- **Tests**: `q3_a_config_that_exists_and_does_not_parse_gives_tier_0` (5 broken inputs),
  `q3_zero_intervals_cannot_crash_the_daemon`. Harness: a `config.json` reading `notjson` gives the
  console line, and a tier-1 `read_file` then waits for the operator.
- **Control**: with the tier-0 fallback and the floors removed, both tests fail.
- **For the operator**: a damaged configuration no longer raises the agent to tier 2; it drops it to
  0 (everything asks) and says so once on the console.

## Q4. Startup test hooks

**Chosen**: a trigger only the kernel shell can create. A cargo feature would need a second image
(CI builds one, and every harness boots it), and routing the hooks through the gate would still let
an approved agent write start them.

- **Scripts that use the hooks** (all type `write /tmp/<hook> ...` at the kernel shell):
  `verify_net.mjs` (`net_test`), `verify_mmap.mjs` (`mmap_test`), `verify_audio_nonblocking.mjs`
  (`audio_test`), `verify_daemon.mjs` (`daemon_exit_once`), `collect_world_model_dataset.mjs`
  (`world_model_collect`), `benchmark_world_model_runtime.mjs` (`world_model_benchmark`); plus
  `docs/research/fi1_reports/kernel_round1_tools/spawnbench.sh`, a record of a past fi1 run, left
  unchanged.
- **What changed**: every hook in `main.rs` reads its trigger from `/tmp/heliox-hooks/<name>`
  (`main.rs:150` and the five others). The kernel creates the directory at boot (`src/fs/mod.rs:136`)
  and refuses any ring-3 create or write at or below it (`src/syscall/fs.rs:113 is_shell_only_path`,
  used at `:237` WriteFile/WriteFileIfVersion and `:320` CreateDir); the kernel shell's `write` does
  not go through a syscall and still works. Removing a trigger stays allowed (the daemon deletes each
  one after reading it; removal can only stop a hook). The six scripts now write under
  `/tmp/heliox-hooks`. In addition, `net_test` prints the response body as one escaped line of at most
  512 bytes (`main.rs:105 escape_console_text`), and `world_model_collect` runs at most 100 000
  actions (`main.rs:399`).
- **Tests**: `q4_every_startup_hook_reads_its_trigger_from_the_shell_only_directory` (source checks);
  self-test `hook-dir`; harness: the operator approves the agent's `write_file
  /tmp/heliox-hooks/net_test`, and the kernel still refuses it (`write to a shell-only path denied`).
- **Control**: before this branch a Tier-3 write to `/tmp/net_test` plus a restart ran an ungated GET
  (round 3); on this branch the approved write itself fails in the kernel, which the harness shows.
  No separate image without the change was booted.
- **For the operator**: the test hooks work as before from the shell, under the new directory name.

## Q5

- **P1, service name**: `service_start` and `service_stop` notices end with `[stops service 7
  "audit-exporter"]` (`authority.rs:933 service_note`, `confirmation.rs:747`). The name comes from a
  new SystemQuery type 5 (`src/syscall/query.rs:69`, read by `orchestrator.rs:129
  kernel_service_name`); a registry the kernel cannot report refuses the call; an id that is not a
  whole number is shown as such and the executor refuses it (`tool_mapper.rs:961`), so the number run
  is the number shown.
- **P2, autosave**: chosen mechanism: autosave runs only when `save_memory` would run unasked
  (`authority.rs:912 autosave_allowed`, used at `orchestrator.rs:724`). At the default tier, memory
  reaches disk only through an approved `save_memory`, which persists the same documents. The other
  options considered (dropping model-authored categories from autosave) would still persist tool
  results that contain remote text.
- **P3, tier 4**: `auto_approve_tier` 4 or more is read as 3 (`authority.rs:897
  clamp_auto_approve_tier`), so tier 4 always asks. Four tools set 4 on purpose (the world-model
  collection scripts `collect_world_model_dataset.mjs` and `collect_world_model_hybrid.mjs`, and the
  harnesses `verify_world_model.mjs` and `verify_world_model_learned.mjs`): they now also write
  `/tmp/heliox-hooks/allow_auto_approve_tier_4` from the kernel shell, the one condition under which
  4 is kept (`config.rs TIER_4_UNLOCK`); the daemon prints a warning when it is.
- **H1, wizard escaping**: the panel writes `config.json` through
  `userland/heliox-assistant-panel/src/config_json.rs setup_config_json`, which escapes every string;
  the host tests parse its output with the daemon's own parser.
- **Tests**: `q5_service_calls_name_the_service`, `q5_autosave_runs_only_when_save_memory_would_run_unasked`,
  `q5_auto_approve_tier_4_or_more_is_clamped_to_3`, `q5_the_setup_wizard_escapes_what_it_writes`;
  self-test `service-query`; harness: the `service_stop` notice names service 1.
- **Control**: with the note, the autosave rule, the clamp and the escaping held back, 5 tests fail.
- **For the operator**: approval texts for services say which service. Memory is saved
  automatically only at `auto_approve_tier` 3. Setting 4 in the configuration gives 3.

## Q6. The audit ring

**Chosen**: per-source share, and never another source's unflushed entry.

- **What changed** (`src/logging/audit.rs`): every entry records its source, the pid that called
  AuditWrite (`src/syscall/mod.rs:554 log_event_from`) or, for kernel events, the task running when
  it was logged. `insert_entry` (`:121`): a source holding more than 64 unflushed entries loses its
  own oldest one; when the 256-entry ring is full, a flushed entry is dropped first, otherwise the
  writer's own oldest unflushed entry (at worst the one just written). A process can therefore drop
  only its own entries. `SOURCE_QUOTA` (`:59`) switches the rule off for the negative control.
- **Tests**: self-test `audit-quota` (a victim's 10 entries, then 300 from a flooder);
  `audit-quota-off` (same with the rule off); host source check `q6_...`.
- **Control**: with the rule off the flood leaves the victim 0 of its 10 entries; with it on, 10 of 10.
- **Residual**: the daemon's own audit events and the agent's `audit_write` share the daemon's pid, so
  the agent can push out the daemon's own unflushed entries. Kernel events logged while a process runs
  count against that process.

## Q-J2a. The panel's flag

- **What changed**: `authority.rs:703 control_command_allowed`: GOAL and CONFIG_UPDATED from the
  kernel shell or the operator's panel; CONFIRM, DENY, PENDING and NEURAL_ARM from the kernel shell
  only; NEURAL_DISARM from anyone.
- **Tests**: `joint2.rs j2_qa_the_panel_flag_authorises_only_goal_and_config_updated` (replaces
  `documents_j2_q_...`), `joint.rs k4_sender_table_is_exhaustive_over_commands_and_senders` (64 cells).
- **Control**: with the panel flag accepted for every command, 4 tests fail.

## Q-J2b. The boot-time setup panel: left as is, pinned

The panel the kernel launches at boot when no configuration exists runs first-run setup and then,
in the same window, takes the operator's first request as a GOAL; `verify_assistant_panel` checks
both. Marking only launcher and shell launches would refuse that first GOAL (and, before the
operator reopened the panel, the CONFIG_UPDATED), so first-run setup would no longer complete end to
end. After Q-J2a the flag this panel holds authorises only GOAL and CONFIG_UPDATED, which is what
first-run setup needs and nothing more, so no further change was made.
`qj2b_the_boot_setup_panel_holds_only_what_first_run_setup_needs` pins it.

## Q-J2c. Typed text bound to the focused window

- **What changed**: kernel `FocusTarget = 67` (`src/syscall/mod.rs:147`, `src/syscall/hud.rs
  sys_focus_target`, needs `hud:overlay` like PointerTarget) reports the focused window, its owner and
  title (window 0 when nothing has focus or the privacy lock is up; `src/gui/compositor.rs:594`).
  `InjectKey` with `args[1] = 1` binds the key to a window and owner: refused with -7 unless that window
  has focus now (`src/syscall/input.rs`), and dropped by the desktop if focus moved before the key is
  processed (`src/gui/cursor.rs:121`, `GUARDED_KEYS_DROPPED`); bound keys never reach the kernel
  shell (`src/input/mod.rs:393 inject_key_on`). Daemon: the gate binds an approval of
  `keyboard_type` to the focused window (`confirmation.rs:732`), the notice says `[types into window
  N "title" of pid P]`, a focus change withdraws the approval (`TargetChanged`), and the executor
  types with the bound variant (`tool_mapper.rs:1137`).
- **Tests**: `qj2c_typed_text_is_bound_to_the_window_focused_when_it_was_requested`,
  `qj2c_the_daemon_and_kernel_carry_the_binding_to_delivery`; self-test `focus-target`; harness: the
  notice names the window.
- **Control**: with the binding off, 1 host test fails.

## Q-J2d. Deleting a directory that holds the configuration

- **What changed**: `authority.rs:260` refuses `delete_file` of the configuration or any directory
  containing it (`/`, `/disk`, `/disk/heliox`, any spelling; `authority.rs:208`), before any request is
  made (`Refusal::DeletesOwnConfiguration`).
- **Tests**: `qj2d_deleting_any_ancestor_of_the_configuration_is_refused`, the refusal table in
  `round2_api.rs` (6 new path shapes), `gate_table.rs writes_to_the_daemons_own_config_are_refused_for_every_spelling`.
  Harness: `delete_file /disk/heliox` is refused with no request.
- **Control**: with the refusal removed, 3 tests fail.

## O1. Missing or stale occupancy

- **What changed** (`userland/physical-runtime/src/safety.rs`): `SafetyPolicy.maximum_occupancy_age_ticks`
  (`:58`, required, so every policy states it). In `apply_deterministic_interlocks` (`:469`, shared by
  issue and delivery) a zone whose policy does not allow humans blocks motion when it has no occupancy
  record (`MissingOccupancy`, reason code 19) or one observed more than that many ticks ago
  (`StaleOccupancy`, 20). The maintenance demo publishes an empty-zone frame before moving
  (`scenario.rs empty_zone_frame`).
- **Tests**: `runtime.rs o1_a_missing_occupancy_record_blocks_motion_when_humans_are_not_allowed`,
  `o1_a_stale_occupancy_record_blocks_motion_at_the_age_limit_plus_one` (replace
  `documents_o1_missing_or_stale_occupancy_counts_as_zero_humans`). The runtime test fixture records
  the zone as observed empty at tick 100 without an event, so the other tests keep their event ids.
- **Control**: with the interlocks held back, both fail (6 of 179 runtime tests fail in that control,
  with O5's four).

## O5. Step, payload and battery bounds

- **What changed**: `SafetyPolicy.maximum_step_mm: Option<i64>` (`:52`) with the reasons
  `MoveStepTooLong` (17) and `StaleActorPosition` (18), the names and codes of commit 090e8a2 on
  `vision-world-model`, but checked in the shared interlocks so the delivery re-check applies it too.
  `SafetyPolicy.operational_limits: Option<OperationalLimits>` (`:62`): a MoveTo needs the controlled
  actor's fresh telemetry with battery at or above the minimum and carried payload
  (`load_permille x max_payload_grams / 1000`) at or below the maximum (`OperationalLimitExceeded`, 21).
  Invalid steps or limits are refused at install. The maintenance demo runs with a 500 mm step, 20
  percent minimum battery and a 2 kg payload limit.
- **Tests**: `o5_the_step_bound_limits_one_command_to_its_distance_from_the_tracked_position`,
  `o5_a_stale_tracked_position_blocks_a_bounded_step`, `o5_alternating_corners_no_longer_fit_in_one_rate_window`,
  `o5_battery_and_payload_limits_are_checked_on_the_command_path`, `safety.rs
  o5_step_bound_and_operational_limits_must_be_valid` (replace the two `documents_o5_...` tests).
- **Control**: the four runtime tests fail with the interlocks held back.
- **Open**: speed. `AdapterCommand` has no speed field; adding one changes the wire contract for the
  bridge and every adapter, so the limits check passes speed 0 and `maximum_speed_mm_per_second` is not
  enforced on the command path. Merging with `vision-world-model` needs `maximum_occupancy_age_ticks`
  and `operational_limits` added to the policies in `car_arena.rs`, and the reason codes deduplicated.

## Images and harnesses

Every image is a CI artifact (`bootimage-ferrumos`), booted in QEMU (WHPX, 4096 MiB), one harness at a
time under `C:/Users/marcu/Videos/fi1-qemu.lock`, `FERRUMOS_BOOT_SECONDS=600`.

| CI run | Commit | sha256 | size |
|---|---|---|---|
| 43247615665 | db05b73 (first push) | 8f9b45ca9ac792e1c6201f34f4b7d85f972ef01eb25f553bd529d5f1fea6348d | 6 969 856 |
| 43249780605 | c0f2655 (last code commit; it changed only a harness check's wording) | 8f9b45ca9ac792e1c6201f34f4b7d85f972ef01eb25f553bd529d5f1fea6348d | 6 969 856 |

The build is reproducible here: both runs gave the same image, which is left at
`target/x86_64-unknown-none/debug/bootimage-ferrumos.bin`. Later commits change only this report. Both
workflows (CI and Public Evidence Reproduction) passed on both pushes.

| Harness | Result on 8f9b45ca |
|---|---|
| verify_gate_policy | 26/26 checks passed |
| verify_authority_gate_joint | 37/37 checks passed |
| verify_authority_gate_self_approval | 11/11 checks passed |
| verify_authority_gate_input_injection | 7/7 checks passed |
| verify_core_apps | 24/24 checks passed |
| verify_assistant_panel | 5/5 checks passed |
| verify_app_window | 13/13 checks passed |
| verify_ipc_isolation | 6/6 checks passed |
| verify_net | 5/5 checks passed |
| verify_net_k2 | 12/12 checks passed |
| verify_kernel_selftests | 18/18 checks passed |
| verify_kernel_selftests_k2 | 37/37 checks passed |
| verify_kernel_k3 | 48/48 checks passed |
| verify_ring3 | 7/7 checks passed |
| verify_kernel_k4 | 39/39 checks passed |

15 harnesses, 295 checks, every one passed on its first run on this image; none was rerun.
`verify_gate_policy` ran once earlier on the same image (run 43247615665) with 26 of 26 as well.
The fi1 harnesses that use the startup hooks (`verify_net`) or the shell's `heliox` commands (the
joint, self-approval and input-injection harnesses) needed no change other than the hook path.
The world-model collection scripts and `verify_world_model*.mjs` were updated (hook path and tier-4
unlock) but not run: they need a model or a host collector and are outside this round's list.

Host suites on the final head: `heliox-gate-tests` 99 passed, `physical-runtime` 179, `neural-protocol`
19; `generate_public_evidence.py --check` and the four public-evidence verifiers pass;
`verify_physical_simulation_caution.py` 15/15, `verify_physical_deployment_qualification.py` and
`verify_physical_jepa_v5_runtime.py` pass. The kernel was type-checked on the host from a scratch copy
before the push (as in fi1); it links only in CI.

## Claim after this round

> With `auto_approve_tier` at most 3 (the configuration cannot set more; a shell-only test unlock
> can), a tool call proposed by the language model runs only if one of three things holds. (i) Its
> tier, as decided for that call, is at or below the configured tier: a network send to a host outside
> the allowlist (the provider and speech hosts and `network_allowlist`) is decided at tier 3, and at
> most 16 tier-2 calls run unasked per 100 ticks. (ii) An operator approved that tool with exactly
> those arguments, from the kernel shell, after the daemon printed that request's full text as the
> last notice: the approval is bound to a complete, injective serialization of every argument, is
> used once, expires, cannot override a denial, and is withdrawn when the file it is about changes
> (the kernel acts only on the approved version), when the click target under the pointer changes, or
> when the window with keyboard focus changes. (iii) For physical commands, the deterministic
> interlocks hold at issue and again at delivery, including a fresh occupancy record where humans are
> not allowed and, where the policy sets them, the step bound and the battery and payload limits. The
> operator is shown every byte of the arguments, escaped, and the file, click target, focused window,
> service name or network host the action is about. The model has no tool that sends to the daemon's
> control mailbox, writes its configuration, deletes a directory holding it, submits keystrokes, reads
> the operator's keystrokes without approval, or blocks the daemon for more than 10 s. A configuration
> that cannot be used gives tier 0. The agent cannot plant a startup-hook trigger. No process can push
> another process's unflushed entries out of the kernel's audit ring.
>
> Exclusions. The gate does not guarantee: that data stays on the machine when it is sent to an
> allowed host (a GET path can carry it, and the provider receives the prompt); what the owning
> application does with an approved click or typed text; that a physical click or keystroke after an
> approved pointer move or focus change goes where the operator meant; that the daemon's own audit
> entries survive the agent's `audit_write` (same process); that a commanded speed is bounded (no
> speed field). Physical replay protection is per runtime instance, and confirmation ids are not
> single-use (R-P1, R-P3). The sender check trusts the kernel shell's input: whoever types on the
> physical keyboard or the serial console is the operator.
