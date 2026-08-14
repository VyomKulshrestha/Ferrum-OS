#!/usr/bin/env python3
"""Generate FerrumOS public capability and benchmark evidence from source data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "docs" / "benchmarks"
RAW_DIR = BENCHMARK_DIR / "raw" / "2026-08-13"
REPOSITORY_URL = "https://github.com/VyomKulshrestha/Ferrum-OS"
WEBSITE_URL = "https://ferrum-os.vercel.app"
RAW_MAIN_URL = "https://raw.githubusercontent.com/VyomKulshrestha/Ferrum-OS/main"
CAPABILITY_SCHEMA_URL = f"{RAW_MAIN_URL}/schemas/capabilities.schema.json"
BENCHMARK_SCHEMA_URL = f"{RAW_MAIN_URL}/schemas/benchmarks.schema.json"

ACTION_CATEGORIES = {
    "ipc_send": "interprocess-communication",
    "audit_write": "audit",
    "yield_cpu": "scheduling",
    "camera_capture": "camera",
    "gesture_status": "camera",
    "report_status": "system-observation",
    "capability_check": "security",
    "read_file": "filesystem",
    "read_dir": "filesystem",
    "query_memory": "agent-memory",
    "get_config": "configuration",
    "system_info": "system-observation",
    "list_processes": "process",
    "net_connect": "network",
    "net_send": "network",
    "net_recv": "network",
    "http_get": "network",
    "write_file": "filesystem",
    "create_directory": "filesystem",
    "save_memory": "agent-memory",
    "load_memory": "agent-memory",
    "set_goal": "orchestration",
    "sleep": "scheduling",
    "service_start": "service-management",
    "service_stop": "service-management",
    "exec_process": "process",
    "delete_file": "filesystem",
    "local_inference": "inference",
    "trigger_kernel_upgrade": "system-update",
    "hud_update": "desktop-ui",
    "hit_test": "desktop-ui",
    "read_screen": "desktop-ui",
    "add_subtask": "orchestration",
    "record_audio": "audio",
    "play_audio": "audio",
    "set_volume": "audio",
    "keyboard_type": "desktop-input",
    "mouse_click": "desktop-input",
    "mouse_move": "desktop-input",
    "browse_url": "browser",
    "poll_input": "desktop-input",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def portable_text_sha256(path: Path) -> str:
    """Hash UTF-8 source text after normalizing checkout-specific line endings."""
    normalized = (
        path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def source_records(paths: list[Path]) -> list[dict[str, str]]:
    records = []
    for path in paths:
        records.append(
            {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": portable_text_sha256(path),
            }
        )
    return records


def median(values: list[float]) -> float:
    return round(float(statistics.median(values)), 3)


def parse_capabilities() -> dict:
    world_model_path = (
        ROOT
        / "userland"
        / "heliox-daemon"
        / "src"
        / "cognitive"
        / "world_model"
        / "mod.rs"
    )
    mapper_path = (
        ROOT / "userland" / "heliox-daemon" / "src" / "cognitive" / "tool_mapper.rs"
    )
    world_model = world_model_path.read_text(encoding="utf-8")
    mapper = mapper_path.read_text(encoding="utf-8")

    names_match = re.search(
        r"pub const TOOL_NAMES: \[&str; \d+\] = \[(.*?)\];", world_model, re.S
    )
    if not names_match:
        raise RuntimeError("could not parse TOOL_NAMES")
    names = re.findall(r'"([a-z0-9_]+)"', names_match.group(1))

    tier_names = ["Observe", "Safe", "Network", "Modify", "Destructive"]
    function_match = re.search(r"fn tool_tier\(.*?match name \{(.*?)_ =>", mapper, re.S)
    if not function_match:
        raise RuntimeError("could not parse tool_tier")
    tiers: dict[str, int] = {}
    arm_pattern = re.compile(
        r'((?:"[a-z0-9_]+"\s*\|\s*)*"[a-z0-9_]+")\s*=>\s*PermissionTier::(\w+)',
        re.S,
    )
    for arm in arm_pattern.finditer(function_match.group(1)):
        tier_name = arm.group(2)
        if tier_name not in tier_names:
            raise RuntimeError(f"unknown permission tier {tier_name}")
        level = tier_names.index(tier_name)
        for name in re.findall(r'"([a-z0-9_]+)"', arm.group(1)):
            tiers[name] = level

    if len(names) != 41 or set(names) != set(tiers):
        raise RuntimeError(
            f"capability registry mismatch: {len(names)} names, {len(tiers)} tiered"
        )
    if set(names) != set(ACTION_CATEGORIES):
        missing = sorted(set(names) - set(ACTION_CATEGORIES))
        stale = sorted(set(ACTION_CATEGORIES) - set(names))
        raise RuntimeError(
            f"action category mismatch: missing={missing}, stale={stale}"
        )

    actions = []
    for name in names:
        tier = tiers[name]
        actions.append(
            {
                "availability": "current-main-source",
                "category": ACTION_CATEGORIES[name],
                "execution_route": "Ring-3 orchestrator -> world-model decision -> capability-gated syscall",
                "name": name,
                "permission_tier": tier,
                "permission_tier_name": tier_names[tier].lower(),
                "operator_confirmation_required": tier >= 3,
                "world_model_mediation": "required on the orchestrator execution path",
                "verification": {
                    "catalog_source_parity": True,
                    "qemu_runtime_suite": "collective command and bridge coverage",
                    "semantic_postcondition_verified_per_action": False,
                },
            }
        )

    inputs = source_records([world_model_path, mapper_path])
    return {
        "$schema": CAPABILITY_SCHEMA_URL,
        "schema_version": "2.0.0",
        "project": "FerrumOS",
        "canonical_url": f"{REPOSITORY_URL}/blob/main/capabilities.json",
        "catalog_scope": {
            "source_channel": "current main source tree",
            "latest_tagged_software_release": "v0.1.1",
            "release_compatibility": "Not asserted: current main contains substantial post-v0.1.1 development.",
            "distribution": "Build from source; the v0.1.1 release has no prebuilt OS image.",
        },
        "platform": "bootable x86_64 research OS; documented QEMU/Bochs profile",
        "canonical_action_count": len(actions),
        "permission_tier_count": len(tier_names),
        "unknown_action_policy": "destructive tier; fail closed",
        "actions": actions,
        "provenance": {
            "generator": "scripts/generate_public_evidence.py",
            "inputs": inputs,
            "action_catalog_sha256": canonical_sha256(actions),
        },
        "claim_boundary": [
            "Catalog membership does not mean each action has an independent semantic postcondition verifier.",
            "The catalog describes current main source, not the older v0.1.1 tagged source tree.",
            "Camera input is synthetic in the current release; broad physical-PC compatibility is not claimed.",
            "Neural physical intents remain proposal-only and cannot invoke an actuator adapter.",
        ],
    }


def aggregate_benchmarks() -> dict:
    manifest_path = RAW_DIR / "manifest.json"
    runtime_paths = [RAW_DIR / f"runtime-run-{index}.json" for index in range(1, 4)]
    queue_before_paths = [
        RAW_DIR / f"concurrency-baseline-run-{index}.json" for index in range(1, 4)
    ]
    queue_after_paths = [
        RAW_DIR / f"concurrency-optimized-run-{index}.json" for index in range(1, 4)
    ]
    neural_path = RAW_DIR / "neural-synthetic.json"
    qemu_command_path = RAW_DIR / "qemu-command-audit.json"
    cyber_physical_path = (
        BENCHMARK_DIR / "raw" / "2026-08-14" / "cyber-physical-software.json"
    )
    paper_path = ROOT / "docs" / "research" / "world_model_paper_evaluation.json"
    training_path = ROOT / "docs" / "research" / "world_model_training_config.json"
    physical_path = ROOT / "docs" / "research" / "physical_world_model_evaluation.json"
    evidence_paths = [
        manifest_path,
        *runtime_paths,
        *queue_before_paths,
        *queue_after_paths,
        neural_path,
        qemu_command_path,
        cyber_physical_path,
        paper_path,
        training_path,
        physical_path,
    ]

    manifest = load_json(manifest_path)
    runtime_runs = [load_json(path) for path in runtime_paths]
    queue_before = [load_json(path) for path in queue_before_paths]
    queue_after = [load_json(path) for path in queue_after_paths]
    neural = load_json(neural_path)
    qemu_command = load_json(qemu_command_path)
    cyber_physical = load_json(cyber_physical_path)
    paper = load_json(paper_path)
    training = load_json(training_path)
    physical = load_json(physical_path)

    horizons = []
    for horizon in range(1, 6):
        rows = [run["horizons"][horizon - 1] for run in runtime_runs]
        means = [row["mean_microseconds"] for row in rows]
        horizons.append(
            {
                "horizon": horizon,
                "mean_microseconds_range": [min(means), max(means)],
                "median_run_mean_microseconds": median(means),
                "median_microseconds_across_runs": [
                    row["median_microseconds"] for row in rows
                ],
                "p95_microseconds_across_runs": [
                    row["p95_microseconds"] for row in rows
                ],
                "blocked_previews_each_run": [row["blocked_previews"] for row in rows],
            }
        )

    before_ms = [run["batch_wall_milliseconds"] for run in queue_before]
    after_ms = [run["batch_wall_milliseconds"] for run in queue_after]
    before_median = median(before_ms)
    after_median = median(after_ms)
    improvement = round((before_median - after_median) / before_median * 100.0, 2)

    full_pipeline = training["full_pipeline_seed_evaluation"]
    paper_combined = paper["baselines"]["rules_plus_jepa"]
    paper_mean = paper["baselines"]["rules_plus_mean_delta"]
    physical_combined = physical["safety"]["rules_plus_jepa"]

    summary = {
        "$schema": BENCHMARK_SCHEMA_URL,
        "schema_version": "2.1.0",
        "canonical_url": f"{REPOSITORY_URL}/blob/main/benchmarks.json",
        "snapshot_date": cyber_physical["snapshot_date"],
        "benchmark_scope": {
            "source_channel": "current main evidence plus frozen research artifacts",
            "latest_tagged_software_release": "v0.1.1",
            "comparability": "Each section has a distinct protocol; cross-section ranking is invalid.",
        },
        "environment": manifest["environment"],
        "paper_release": {
            "evidence_grade": "authored-balanced-fixture",
            "protocol_id": "world-model-study-v1.0.0/episode-disjoint-500",
            "release_tag": "world-model-study-v1.0.0",
            "evidence_commit": "42ea7b8",
            "accepted_rows": paper["dataset_accounting"]["stages"][0]["rows"],
            "eligible_transitions": paper["dataset_accounting"]["stages"][3]["rows"],
            "episodes": paper["dataset_accounting"]["all_episodes"],
            "fixture_episodes": 500,
            "rules_plus_jepa_balanced_accuracy": paper_combined["balanced_accuracy"],
            "rules_plus_jepa_false_negative_rate": 1.0 - paper_combined["recall"],
            "rules_plus_jepa_false_positive_rate": 1.0 - paper_combined["specificity"],
            "rules_plus_mean_balanced_accuracy": paper_mean["balanced_accuracy"],
            "five_pipeline_balanced_accuracy_mean": full_pipeline[
                "combined_balanced_accuracy_mean"
            ],
            "claim_boundary": "Authored balanced safety fixture; no material JEPA safety advantage over the per-action mean baseline was established.",
        },
        "current_ring3_preview": {
            "evidence_grade": "repeated-emulator-measurement",
            "protocol_id": "ring3-preview-whpx-2026-08-13",
            "source_commit": manifest["runtime_source_commit"],
            "runs": len(runtime_runs),
            "iterations_per_horizon_per_run": runtime_runs[0]["iterations_per_horizon"],
            "warmup_previews_per_run": runtime_runs[0]["warmup_previews"],
            "accelerator": runtime_runs[0]["accelerator"],
            "horizons": horizons,
            "model_load_milliseconds_range": [
                min(
                    run["model_load"]["pit_elapsed_microseconds"]
                    for run in runtime_runs
                )
                / 1000,
                max(
                    run["model_load"]["pit_elapsed_microseconds"]
                    for run in runtime_runs
                )
                / 1000,
            ],
            "heap_growth_bytes_each_run": [
                run["memory"]["heap_growth_bytes"] for run in runtime_runs
            ],
            "scope": runtime_runs[0]["scope"],
        },
        "paired_preview_queue": {
            "evidence_grade": "paired-repeated-emulator-measurement",
            "protocol_id": "paired-preview-queue-whpx-2026-08-13",
            "baseline_source_commit": manifest["queue_baseline_source_commit"],
            "optimized_source_commit": manifest["queue_optimized_source_commit"],
            "requests_per_run": queue_before[0]["outstanding_requests"],
            "runs_each": len(queue_before),
            "baseline_batch_milliseconds": before_ms,
            "optimized_batch_milliseconds": after_ms,
            "baseline_median_batch_milliseconds": before_median,
            "optimized_median_batch_milliseconds": after_median,
            "median_improvement_percent": improvement,
            "optimized_median_milliseconds_per_serialized_request": round(
                after_median / queue_after[0]["outstanding_requests"], 3
            ),
            "responses_received_each_run": [
                run["responses_received"] for run in queue_after
            ],
            "execution_records_added_each_run": [
                run["execution_dataset_records_added"] for run in queue_after
            ],
            "guest_fault_free_each_run": [
                run["guest_fault_free"] for run in queue_after
            ],
            "limitation": queue_after[0]["limitation"],
        },
        "physical_simulator_jepa": {
            "evidence_grade": "deterministic-simulator",
            "protocol_id": "physical-jepa-simulator-v1",
            "episodes": physical["episodes"],
            "transitions": physical["transitions"],
            "rules_plus_jepa_balanced_accuracy": physical_combined["balanced_accuracy"],
            "false_negatives": physical_combined["fn"],
            "false_positives": physical_combined["fp"],
            "normalized_rollout_error": physical["normalized_rollout_error"],
            "validated_for_gating": physical["validated_for_gating"],
            "claim_boundary": "Deterministic simulator evidence; the artifact is permanently shadow-only and has no actuator authority.",
        },
        "neural_synthetic": {
            "evidence_grade": "deterministic-synthetic-signal",
            "protocol_id": "neural-ssvep-synthetic-v1",
            "signal_trials": neural["signal"]["trials"],
            "accepted_signal_accuracy": neural["signal"]["accepted_accuracy"],
            "artifact_trials": neural["artifact"]["trials"],
            "artifact_abstention_rate": neural["artifact"]["abstention_rate"],
            "no_control_windows": neural["no_control_soak"]["windows"],
            "emitted_intents": neural["no_control_soak"]["emitted_intents"],
            "passed": neural["passed"],
            "claim_boundary": neural["claim_boundary"],
        },
        "qemu_command_audit": {
            "evidence_grade": "dated-emulator-measurement",
            "protocol_id": qemu_command["protocol"],
            "os_source_commit": qemu_command["os_source_commit"],
            "audit_source_commit": qemu_command["audit_source_commit"],
            "command_sweep_cases": qemu_command["harness"]["command_sweep"]["cases"],
            "command_sweep_passed": qemu_command["harness"]["command_sweep"]["passed"],
            "catalog_entries": qemu_command["harness"]["exhaustive_catalog"]["entries"],
            "catalog_passed": qemu_command["harness"]["exhaustive_catalog"]["passed"],
            "unknown_command_paths": qemu_command["harness"]["exhaustive_catalog"][
                "unknown_command_paths"
            ],
            "claim_boundary": qemu_command["claim_boundary"],
        },
        "cyber_physical_software": {
            "evidence_grade": "local-deterministic-regression",
            "protocol_id": cyber_physical["protocol_id"],
            "source_commit": cyber_physical["source_commit"],
            "environment": cyber_physical["environment"],
            "contract_suites": cyber_physical["contract_suites"],
            "model_and_decoder_gates": cyber_physical["model_and_decoder_gates"],
            "contract_tests_passed": cyber_physical["contract_tests_passed"],
            "contract_tests_failed": cyber_physical["contract_tests_failed"],
            "model_and_decoder_gates_passed": cyber_physical[
                "model_and_decoder_gates_passed"
            ],
            "model_and_decoder_gates_failed": cyber_physical[
                "model_and_decoder_gates_failed"
            ],
            "covered_software_boundaries": cyber_physical[
                "covered_software_boundaries"
            ],
            "claim_boundary": cyber_physical["claim_boundary"],
        },
        "metric_definitions": {
            "balanced_accuracy": {
                "unit": "ratio",
                "range": [0.0, 1.0],
                "higher_is_better": True,
                "definition": "Mean of sensitivity and specificity within the named fixture.",
            },
            "false_negative_rate": {
                "unit": "ratio",
                "range": [0.0, 1.0],
                "lower_is_better": True,
            },
            "false_positive_rate": {
                "unit": "ratio",
                "range": [0.0, 1.0],
                "lower_is_better": True,
            },
            "preview_latency": {
                "unit": "microseconds",
                "clock": "virtualized 1 kHz PIT with raw TSC retained in source runs",
                "lower_is_better": True,
            },
            "queue_batch_latency": {
                "unit": "milliseconds",
                "request_count": queue_before[0]["outstanding_requests"],
                "lower_is_better": True,
            },
        },
        "provenance": {
            "generator": "scripts/generate_public_evidence.py",
            "inputs": source_records(evidence_paths),
        },
        "global_limitations": [
            "The paper, physical simulator, neural synthetic, QEMU, and cyber-physical software evaluations use different protocols and are not directly comparable.",
            "No live EEG, human neural calibration, robot hardware-in-the-loop, or broad physical-PC benchmark is claimed.",
            "Ring-3 timing uses a virtualized 1 kHz PIT; provider, tool execution, and operator-confirmation latency are excluded.",
            "A passing benchmark is evidence for its named fixture and protocol, not formal safety proof.",
        ],
    }
    return summary


def percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def benchmark_markdown(summary: dict) -> str:
    paper = summary["paper_release"]
    runtime = summary["current_ring3_preview"]
    queue = summary["paired_preview_queue"]
    physical = summary["physical_simulator_jepa"]
    neural = summary["neural_synthetic"]
    qemu = summary["qemu_command_audit"]
    cyber = summary["cyber_physical_software"]
    runtime_rows = "\n".join(
        f"| H={row['horizon']} | {row['mean_microseconds_range'][0] / 1000:.2f}-{row['mean_microseconds_range'][1] / 1000:.2f} ms | "
        f"{row['median_run_mean_microseconds'] / 1000:.2f} ms | {max(row['p95_microseconds_across_runs']) / 1000:.2f} ms |"
        for row in runtime["horizons"]
    )
    return (
        f"""# FerrumOS Benchmarks and Evidence Boundaries

This page is generated by `scripts/generate_public_evidence.py` from committed raw results and research artifacts. Run `python scripts/generate_public_evidence.py --check` to detect stale public claims. The machine-readable companion is [benchmarks.json](../benchmarks.json), validated against [its versioned schema](../schemas/benchmarks.schema.json).

The latest tagged software release is `v0.1.1`, while this evidence page also covers later source and frozen research artifacts. Each evidence section names its own protocol and must not be compared as if the populations or measurements were interchangeable.

## Evidence map

| Evidence | Result | What it does not prove |
| --- | --- | --- |
| Published OS world-model study | Rules + JEPA: {percent(paper["rules_plus_jepa_balanced_accuracy"])} balanced accuracy; rules + per-action mean: {percent(paper["rules_plus_mean_balanced_accuracy"])} | JEPA superiority, formal safety, or natural-use prevalence |
| Current Ring-3 preview | Three runs, 100 previews per H=1..5 per run; zero heap growth | Provider, action execution, or approval latency |
| Paired preview queue | 96/96 responses in every run; median batch {queue["optimized_median_batch_milliseconds"] / 1000:.3f} s after optimization | Parallel inference; the daemon intentionally serializes previews |
| Physical JEPA | {percent(physical["rules_plus_jepa_balanced_accuracy"])} balanced accuracy, {physical["false_negatives"]} FN, {physical["false_positives"]} FP | Real robot safety; the artifact is shadow-only |
| Neural decoder | {neural["signal_trials"]}/{neural["signal_trials"]} synthetic signals, {neural["artifact_trials"]}/{neural["artifact_trials"]} artifact abstentions, {neural["emitted_intents"]} candidates in {neural["no_control_windows"]:,} no-control windows | Live EEG accuracy, usability, or medical performance |
| QEMU command paths | {qemu["command_sweep_passed"]}/{qemu["command_sweep_cases"]} focused cases and {qemu["catalog_passed"]}/{qemu["catalog_entries"]} exhaustive entries | Broad physical-PC compatibility or independent replication |
| Cyber-physical software tier | {cyber["contract_tests_passed"]} contract tests and {cyber["model_and_decoder_gates_passed"]} model/decoder gates passed | Installed simulators or transports, hardware, hard-real-time behavior, certification, or independent replication |

## Published world-model study

The frozen `world-model-study-v1.0.0` release accounts for {paper["accepted_rows"]:,} rows from {paper["episodes"]:,} episodes; {paper["eligible_transitions"]:,} executed transitions enter episode-disjoint fitting/evaluation. On the authored balanced {paper["fixture_episodes"]}-episode safety fixture, rules + JEPA reach {percent(paper["rules_plus_jepa_balanced_accuracy"])} balanced accuracy with {percent(paper["rules_plus_jepa_false_negative_rate"])} FNR and {percent(paper["rules_plus_jepa_false_positive_rate"])} FPR. Rules + a per-action mean reach {percent(paper["rules_plus_mean_balanced_accuracy"])}; the report therefore does not establish a material JEPA safety advantage. Five independently trained pipelines average {percent(paper["five_pipeline_balanced_accuracy_mean"])} balanced accuracy.

- [Technical report release](https://github.com/VyomKulshrestha/Ferrum-OS/releases/tag/world-model-study-v1.0.0)
- [Technical report DOI](https://doi.org/10.5281/zenodo.21829808)
- [Dataset DOI](https://doi.org/10.5281/zenodo.21829193)
- [Reproduction guide](research/WORLD_MODEL_PAPER_EVALUATION.md)

## Current Ring-3 preview latency

Environment: {summary["environment"]["host_os"]}, QEMU {summary["environment"]["qemu_version"]}, {runtime["accelerator"]}, 512 MiB guest RAM. Each of three sequential runs performs 64 H=5 warmups and then 100 measured previews at each horizon.

| Horizon | Run-mean range | Median run mean | Worst recorded p95 |
| --- | ---: | ---: | ---: |
{runtime_rows}

Model loading was {runtime["model_load_milliseconds_range"][0]:.0f}-{runtime["model_load_milliseconds_range"][1]:.0f} ms. Heap growth was {set(runtime["heap_growth_bytes_each_run"]).pop()} bytes in every run. PIT percentiles have 1 ms resolution; raw TSC cycles remain in the JSON files.

## Paired preview queue optimization

Three baseline runs at `{queue["baseline_source_commit"][:7]}` took {min(queue["baseline_batch_milliseconds"]) / 1000:.3f}-{max(queue["baseline_batch_milliseconds"]) / 1000:.3f} s for 96 outstanding requests. After replacing the connected-client ten-tick sleep with a one-tick cooperative cadence at `{queue["optimized_source_commit"][:7]}`, three runs took {min(queue["optimized_batch_milliseconds"]) / 1000:.3f}-{max(queue["optimized_batch_milliseconds"]) / 1000:.3f} s; median batch time improved {queue["median_improvement_percent"]:.2f}%.

Every optimized run returned 96/96 correlated responses, produced zero execution-dataset records, remained deterministic across six action classes, and stayed guest-fault-free. This is queue responsiveness, not parallel inference.

## Post-paper physical and neural evidence

The physical JEPA uses {physical["transitions"]:,} transitions from {physical["episodes"]:,} deterministic simulator episodes. Rules + JEPA record {percent(physical["rules_plus_jepa_balanced_accuracy"])} balanced accuracy with {physical["false_negatives"]} false negative and {physical["false_positives"]} false positives. Its artifact is `validated_for_gating=false`; it cannot issue permits or invoke adapters.

The neural decoder evaluation is deterministic synthetic SSVEP evidence only: {neural["signal_trials"]} accepted signal trials at {percent(neural["accepted_signal_accuracy"])} accuracy, {neural["artifact_trials"]} artifact trials at {percent(neural["artifact_abstention_rate"])} abstention, and zero emitted candidates in {neural["no_control_windows"]:,} no-control windows. OS commit still requires pairing, calibration, non-neural arming, a signed preview, and revision checks.

## Simulator-backed cyber-physical software tier

At source `{cyber["source_commit"][:7]}`, {cyber["contract_tests_passed"]} deterministic contract tests passed across the physical runtime, signed neural protocol, `neurod`, and the simulator bridge; {cyber["model_and_decoder_gates_passed"]} physical-model, robustness, and neural-decoder gates also passed. The covered software boundary includes versioned provenance, deterministic replay/faults, virtual devices, simulator connectors, watchdog/recovery rules, ROS 2/MQTT/CAN conformance, actuator-disabled delivery, bounded neural proposals, host-managed agent-cell contracts, and privacy/reliability primitives.

This is local software regression evidence. It is not a live Gazebo/Webots deployment, real ROS 2/MQTT/CAN infrastructure, physical-clock or robot evidence, live EEG, native hypervisor containment, hard-real-time proof, certification, or independent replication.

## Reproduce

```powershell
python scripts/verify_world_model_paper_evaluation.py
python scripts/verify_physical_world_model.py
python scripts/evaluate_neural_simulator.py --output target/neural.json
python -m unittest discover -s tools/neurod -p "test_*.py" -v
python -m unittest tools.physical_sim_bridge.test_bridge -v
python scripts/verify_physical_jepa_robustness.py
python scripts/verify_qemu_command_evidence.py
node scripts/benchmark_world_model_runtime.mjs --iterations 100
node scripts/verify_world_model_preview_concurrency.mjs
python scripts/generate_public_evidence.py --check
```

## Global limitations

"""
        + "\n".join(f"- {item}" for item in summary["global_limitations"])
        + "\n"
    )


def proof_markdown(summary: dict, capabilities: dict) -> str:
    paper = summary["paper_release"]
    queue = summary["paired_preview_queue"]
    physical = summary["physical_simulator_jepa"]
    neural = summary["neural_synthetic"]
    qemu = summary["qemu_command_audit"]
    cyber = summary["cyber_physical_software"]
    return f"""# FerrumOS Proof Center

FerrumOS is a bootable x86_64 Rust research OS with a deterministic kernel, a Ring-3 agent daemon, capability-gated syscalls, and a provider-independent predictive safety screen. This page links claims to reproducible evidence; it is not a formal safety certificate. The latest tagged software release is `v0.1.1`; current-main capability and benchmark evidence is labeled separately and does not retroactively describe that tag.

| Surface | Current evidence |
| --- | --- |
| Build | GitHub Actions builds the kernel and userland on Windows with the pinned Rust/LLVM setup |
| Agent actions | {capabilities["canonical_action_count"]} canonical operations across {capabilities["permission_tier_count"]} permission tiers; unknown tools fail closed |
| OS world model | Published fixture: {percent(paper["rules_plus_jepa_balanced_accuracy"])} rules + JEPA vs {percent(paper["rules_plus_mean_balanced_accuracy"])} rules + mean baseline |
| Ring-3 preview | Three H=1..5 runs, 100 measured previews per horizon, zero heap growth |
| Preview queue | 96/96 responses in every run; {queue["median_improvement_percent"]:.2f}% median batch improvement after cadence optimization |
| Physical model | {percent(physical["rules_plus_jepa_balanced_accuracy"])} simulator balanced accuracy; permanently shadow-only |
| Neural input | {neural["signal_trials"]} synthetic signals, {neural["artifact_trials"]} artifact abstentions, zero candidates in {neural["no_control_windows"]:,} no-control windows |
| QEMU command paths | {qemu["command_sweep_passed"]}/{qemu["command_sweep_cases"]} focused cases and {qemu["catalog_passed"]}/{qemu["catalog_entries"]} exhaustive entries for OS source `{qemu["os_source_commit"][:7]}` |
| Cyber-physical software | {cyber["contract_tests_passed"]} contract tests and {cyber["model_and_decoder_gates_passed"]} model/decoder gates passed at source `{cyber["source_commit"][:7]}` |

Read the [full benchmark protocol and limitations](docs/BENCHMARKS.md), [machine-readable benchmark summary](benchmarks.json), [capability catalog](capabilities.json), [full agent-readable context](llms-full.txt), [citation guide](docs/CITATION.md), [architecture](docs/ARCHITECTURE.md), [security policy](SECURITY.md), and [published research release](https://github.com/VyomKulshrestha/Ferrum-OS/releases/tag/world-model-study-v1.0.0).

## Claim boundaries

- The current release targets a documented QEMU/Bochs device profile, not broad physical-PC compatibility.
- Camera frames are synthetic; physical camera, gaze, and gesture accuracy are not claimed.
- Neural results are synthetic software evidence, not live EEG or medical evidence.
- Physical-world results use a deterministic simulator; the learned artifact has no actuator authority.
- Simulator connectors and ROS 2/MQTT/CAN contracts are software-tested boundaries, not evidence of installed infrastructure or physical delivery.
- Host-managed agent cells define an isolation contract; Ferrum does not claim a native hypervisor or measured microVM containment.
- The published 500-episode safety fixture is authored and balanced; it is not natural-use prevalence.
- JEPA does not materially outperform the per-action mean safety baseline on the published fixture.
- Passing automated checks does not establish formal safety or independent replication.
"""


def llms_full_markdown(summary: dict, capabilities: dict) -> str:
    paper = summary["paper_release"]
    runtime = summary["current_ring3_preview"]
    queue = summary["paired_preview_queue"]
    physical = summary["physical_simulator_jepa"]
    neural = summary["neural_synthetic"]
    qemu = summary["qemu_command_audit"]
    cyber = summary["cyber_physical_software"]
    action_rows = "\n".join(
        "| `{name}` | {category} | {tier} ({tier_name}) | {confirmation} |".format(
            name=action["name"],
            category=action["category"],
            tier=action["permission_tier"],
            tier_name=action["permission_tier_name"],
            confirmation="yes" if action["operator_confirmation_required"] else "no",
        )
        for action in capabilities["actions"]
    )
    return f"""# FerrumOS: full agent-readable project context

FerrumOS is a bootable x86_64 Rust research operating system. Its deterministic kernel exposes capability-gated syscalls to a freestanding Ring-3 agent daemon. The daemon can run local or configured remote inference, but probabilistic inference does not run in Ring 0.

## Distribution and scope

- Latest tagged software release: `v0.1.1`.
- Distribution: build from source; the `v0.1.1` release has no prebuilt OS image.
- Capability catalog scope: current `main` source tree, not a claim about the older `v0.1.1` tag.
- Verified device profile: QEMU/Bochs x86_64 configuration documented in the repository.
- Current camera: deterministic synthetic YUYV frames, not a UVC hardware camera.

## Safety architecture

- Unknown tools map to the destructive tier and fail closed.
- Canonical action execution uses the Ring-3 orchestrator, world-model decision, permission tier, capability check, and—at the default policy—operator confirmation for tiers 3 and 4.
- Learned risk is monotonic: it may add caution but cannot remove a deterministic rule warning.
- Catalog membership is not an independent semantic postcondition proof for every action.
- Neural physical intent remains proposal-only and cannot invoke an actuator adapter.
- The simulator-backed cyber-physical tier includes deterministic session/replay, virtual-device, bridge, supervisor, transport-conformance, actuator-disabled, host-cell, privacy, and reliability contracts. It does not establish live deployment or hardware safety.

## Canonical actions ({capabilities["canonical_action_count"]})

| Action | Category | Permission tier | Default operator confirmation |
| --- | --- | ---: | --- |
{action_rows}

## Evidence snapshot

| Protocol | Measurement | Boundary |
| --- | --- | --- |
| `{paper["protocol_id"]}` | Rules + JEPA {percent(paper["rules_plus_jepa_balanced_accuracy"])}; rules + per-action mean {percent(paper["rules_plus_mean_balanced_accuracy"])} balanced accuracy | Authored balanced fixture; no material JEPA advantage established |
| `{runtime["protocol_id"]}` | {runtime["runs"]} WHPX runs, 100 previews per H=1..5, zero heap growth | Excludes provider, execution, and approval latency |
| `{queue["protocol_id"]}` | 96/96 responses each run; {queue["median_improvement_percent"]:.2f}% median batch improvement | Serialized queue responsiveness, not parallel inference |
| `{physical["protocol_id"]}` | {percent(physical["rules_plus_jepa_balanced_accuracy"])}, {physical["false_negatives"]} FN, {physical["false_positives"]} FP | Deterministic simulator; permanently shadow-only |
| `{neural["protocol_id"]}` | {neural["signal_trials"]} synthetic signals, {neural["artifact_trials"]} artifact abstentions, {neural["emitted_intents"]} candidates in {neural["no_control_windows"]:,} no-control windows | No live EEG, human, medical, or usability claim |
| `{qemu["protocol_id"]}` | {qemu["command_sweep_passed"]}/{qemu["command_sweep_cases"]} focused cases and {qemu["catalog_passed"]}/{qemu["catalog_entries"]} exhaustive entries | Dated QEMU evidence, not broad physical-PC coverage |
| `{cyber["protocol_id"]}` | {cyber["contract_tests_passed"]} contract tests and {cyber["model_and_decoder_gates_passed"]} model/decoder gates passed | Local deterministic software regression; no installed simulator/transport, hardware, real-time, certification, or independent-replication claim |

The seven evidence sections use different protocols and are not directly comparable. Passing them is evidence for their named fixtures, not formal safety proof or independent replication.

## Canonical evidence and documentation

- Website: {WEBSITE_URL}
- README: {REPOSITORY_URL}/blob/main/README.md
- Proof center: {REPOSITORY_URL}/blob/main/proof.md
- Capability JSON: {RAW_MAIN_URL}/capabilities.json
- Capability schema: {RAW_MAIN_URL}/schemas/capabilities.schema.json
- Benchmark JSON: {RAW_MAIN_URL}/benchmarks.json
- Benchmark schema: {RAW_MAIN_URL}/schemas/benchmarks.schema.json
- Benchmark protocols: {REPOSITORY_URL}/blob/main/docs/BENCHMARKS.md
- Architecture: {REPOSITORY_URL}/blob/main/docs/ARCHITECTURE.md
- Security: {REPOSITORY_URL}/blob/main/SECURITY.md
- Citation guide: {REPOSITORY_URL}/blob/main/docs/CITATION.md
- Technical report DOI: https://doi.org/10.5281/zenodo.21829808
- Dataset DOI: https://doi.org/10.5281/zenodo.21829193

## Reproduction entry points

```powershell
python scripts/generate_public_evidence.py --check
python scripts/verify_public_evidence_contract.py
python scripts/verify_repository_discovery.py
python scripts/verify_world_model_paper_evaluation.py
python scripts/verify_physical_world_model.py
python scripts/verify_physical_jepa_robustness.py
python -m unittest tools.physical_sim_bridge.test_bridge
python scripts/evaluate_neural_simulator.py --output target/neural.json
python scripts/verify_qemu_command_evidence.py
```
"""


def write_or_check(path: Path, content: str, check: bool) -> bool:
    if check:
        actual = path.read_text(encoding="utf-8") if path.exists() else None
        if actual != content:
            print(f"STALE {path.relative_to(ROOT)}")
            return False
        print(f"PASS  {path.relative_to(ROOT)}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"WROTE {path.relative_to(ROOT)}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail if generated artifacts are stale"
    )
    args = parser.parse_args()
    capabilities = parse_capabilities()
    benchmarks = aggregate_benchmarks()
    outputs = {
        ROOT / "capabilities.json": dump_json(capabilities),
        ROOT / "benchmarks.json": dump_json(benchmarks),
        ROOT / "proof.md": proof_markdown(benchmarks, capabilities),
        ROOT / "llms-full.txt": llms_full_markdown(benchmarks, capabilities),
        ROOT / "docs" / "BENCHMARKS.md": benchmark_markdown(benchmarks),
    }
    passed = all(
        write_or_check(path, content, args.check) for path, content in outputs.items()
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
