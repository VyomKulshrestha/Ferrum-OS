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
CURRENT_EVIDENCE_DATE = "2026-08-23"

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
        r'((?:"[a-z0-9_]+"\s*\|\s*)*"[a-z0-9_]+")\s*=>\s*(?:\{\s*)?PermissionTier::(\w+)',
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
        BENCHMARK_DIR / "raw" / "2026-08-22" / "cyber-physical-software.json"
    )
    paper_path = ROOT / "docs" / "research" / "world_model_paper_evaluation.json"
    training_path = ROOT / "docs" / "research" / "world_model_training_config.json"
    physical_path = ROOT / "docs" / "research" / "physical_jepa_v3_evaluation.json"
    physical_selection_path = (
        ROOT / "docs" / "research" / "physical_jepa_v3_selection.json"
    )
    physical_baselines_path = (
        ROOT / "docs" / "research" / "physical_jepa_v3_baselines.json"
    )
    physical_sources_path = (
        ROOT / "docs" / "research" / "physical_incident_sources.json"
    )
    physical_qualification_path = (
        ROOT
        / "docs"
        / "research"
        / "physical_deployment_qualification_evaluation_v1.json"
    )
    physical_calibration_path = (
        ROOT / "docs" / "research" / "physical_jepa_runtime_calibration_v1.json"
    )
    physical_v5_selection_path = (
        ROOT / "docs" / "research" / "physical_jepa_v5_selection.json"
    )
    physical_v5_final_path = (
        ROOT / "docs" / "research" / "physical_jepa_v5_final_test.json"
    )
    physical_v5_calibration_path = (
        ROOT / "docs" / "research" / "physical_jepa_runtime_calibration_v4.json"
    )
    physical_sources_v2_path = (
        ROOT / "docs" / "research" / "physical_incident_sources_v2.json"
    )
    physical_sources_v5_path = (
        ROOT / "docs" / "research" / "physical_incident_v5_test_sources.json"
    )
    physical_hai_manifest_path = (
        ROOT / "docs" / "research" / "physical_hai_v2_evidence_manifest.json"
    )
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
        physical_selection_path,
        physical_baselines_path,
        physical_sources_path,
        physical_qualification_path,
        physical_calibration_path,
        physical_v5_selection_path,
        physical_v5_final_path,
        physical_v5_calibration_path,
        physical_sources_v2_path,
        physical_sources_v5_path,
        physical_hai_manifest_path,
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
    physical_selection = load_json(physical_selection_path)
    physical_baselines = load_json(physical_baselines_path)
    physical_sources = load_json(physical_sources_path)
    physical_qualification = load_json(physical_qualification_path)
    physical_calibration = load_json(physical_calibration_path)
    physical_v5_selection = load_json(physical_v5_selection_path)
    physical_v5_final = load_json(physical_v5_final_path)
    physical_v5_calibration = load_json(physical_v5_calibration_path)
    physical_sources_v2 = load_json(physical_sources_v2_path)
    physical_sources_v5 = load_json(physical_sources_v5_path)
    physical_hai = load_json(physical_hai_manifest_path)

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
    physical_before = physical["deployed_baseline_test_metrics"]
    physical_after = physical["test_metrics"]
    physical_combined = physical_after["original_test"]["diagnostics"][
        "rules_plus_jepa"
    ]
    physical_v5_current = physical_v5_final["candidate_final"]
    physical_v5_base = physical_v5_final["known_regression_suites"]["base_test"]
    physical_v5_stress = physical_v5_final["known_regression_suites"]["stress_test"]
    physical_v5_ood = physical_v5_final["known_regression_suites"]["registered_ood_v2"]
    physical_source_count = (
        len(physical_sources["sources"])
        + len(physical_sources_v2["additional_sources"])
        + len(physical_sources_v5["sources"])
    )

    summary = {
        "$schema": BENCHMARK_SCHEMA_URL,
        "schema_version": "2.1.0",
        "canonical_url": f"{REPOSITORY_URL}/blob/main/benchmarks.json",
        "snapshot_date": CURRENT_EVIDENCE_DATE,
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
            "evidence_grade": "deterministic-simulator-with-separate-external-recorded-hil",
            "protocol_id": physical_v5_final["protocol_id"],
            "artifact_sha256": physical_v5_final["candidate_artifact_sha256"],
            "training_transitions": (
                physical_v5_selection["fit"]["base_transitions"]
                + physical_v5_selection["fit"]["incident"]["transitions"]
                + physical_v5_selection["fit"]["stress"]["transitions"]
            ),
            "final_unseen_family_episodes": physical_v5_final["final_evidence"]["episodes"],
            "final_unseen_family_transitions": physical_v5_final["final_evidence"]["transitions"],
            "final_unseen_families": len(
                physical_v5_final["final_evidence"]["source_family_episode_counts"]
            ),
            "incident_source_count": physical_source_count,
            "incident_sources_are_trajectory_data": False,
            "final_rules_plus_jepa_balanced_accuracy": physical_v5_current[
                "diagnostics"
            ]["rules_plus_jepa"]["balanced_accuracy"],
            "final_false_negatives": physical_v5_current["diagnostics"][
                "rules_plus_jepa"
            ]["fn"],
            "final_false_positives": physical_v5_current["diagnostics"][
                "rules_plus_jepa"
            ]["fp"],
            "final_rollout_error": physical_v5_current["rollout"],
            "final_baseline_rollout_error": physical_v5_final["baseline_final"][
                "rollout"
            ],
            "final_geometric_h1_h3_h5_ratio": physical_v5_final[
                "candidate_to_baseline_rollout_ratios"
            ]["geometric_h1_h3_h5"],
            "final_h3_bootstrap_absolute_reduction": physical_v5_final[
                "h3_paired_bootstrap"
            ]["mean_absolute_normalized_error_reduction"],
            "final_h3_bootstrap_95_interval": physical_v5_final[
                "h3_paired_bootstrap"
            ]["percentile_95_interval"],
            "base_test_rows": physical_v5_base["candidate"]["diagnostics"]["rows"],
            "base_test_false_negatives": physical_v5_base["candidate"]["diagnostics"][
                "rules_plus_jepa"
            ]["fn"],
            "base_test_false_positives": physical_v5_base["candidate"]["diagnostics"][
                "rules_plus_jepa"
            ]["fp"],
            "base_test_h3_error": physical_v5_base["candidate"]["rollout"]["h3"],
            "stress_rows": physical_v5_stress["candidate"]["diagnostics"]["rows"],
            "stress_false_negatives": physical_v5_stress["candidate"]["diagnostics"][
                "rules_plus_jepa"
            ]["fn"],
            "stress_false_positives": physical_v5_stress["candidate"]["diagnostics"][
                "rules_plus_jepa"
            ]["fp"],
            "stress_h3_error": physical_v5_stress["candidate"]["rollout"]["h3"],
            "registered_ood_rows": physical_v5_ood["candidate"]["rows"],
            "registered_ood_invalid_observations_rejected": physical_v5_ood[
                "candidate"
            ]["invalid_observations_rejected"],
            "registered_ood_false_negatives": physical_v5_ood["candidate"][
                "rules_plus_jepa"
            ]["fn"],
            "registered_ood_false_positives": physical_v5_ood["candidate"][
                "rules_plus_jepa"
            ]["fp"],
            "all_registered_model_gates_passed": physical_v5_final[
                "all_model_evidence_gates_pass"
            ],
            "validated_for_gating": False,
            "validated_for_execution_authority": False,
            "runtime_simulation_caution": True,
            "runtime_hil_learned_gate": "shadow_only",
            "runtime_live_learned_gate": "shadow_only",
            "runtime_live_delivery": "disabled_until_authenticated_external_qualification",
            "runtime_clearance_caution_threshold": physical_v5_calibration[
                "selected_clearance_threshold"
            ],
            "calibration_test_rows": sum(
                physical_v5_calibration["test_case_counts"].values()
            ),
            "calibration_test_false_negatives": physical_v5_calibration["test"]["fn"],
            "calibration_test_false_positive_rate": physical_v5_calibration["test"][
                "false_positive_rate"
            ],
            "permit_authority": "deterministic_supervisor",
            "external_hil_diagnostic": {
                "evidence_id": physical_hai["evidence_id"],
                "evidence_grade": physical_hai["dataset"]["evidence_class"],
                "recorded_hours": physical_hai["dataset"]["recorded_hours"],
                "attack_seconds": physical_hai["dataset"]["attack_seconds"],
                "attack_windows": physical_hai["dataset"]["attack_windows"],
                "detected_attack_windows": physical_hai["final_metrics"][
                    "detected_attack_windows"
                ],
                "attack_window_recall": physical_hai["final_metrics"][
                    "attack_window_recall"
                ],
                "balanced_accuracy": physical_hai["final_metrics"][
                    "point_balanced_accuracy"
                ],
                "false_alerts_per_hour": physical_hai["final_metrics"][
                    "false_alerts_per_hour"
                ],
                "transition_geometric_h1_h3_h5_error": physical_hai[
                    "final_metrics"
                ]["transition_geometric_h1_h3_h5_error"],
                "persistence_geometric_h1_h3_h5_error": physical_hai[
                    "final_metrics"
                ]["persistence_geometric_h1_h3_h5_error"],
                "per_action_mean_geometric_h1_h3_h5_error": physical_hai[
                    "final_metrics"
                ]["per_action_mean_geometric_h1_h3_h5_error"],
                "runtime_loaded": physical_hai["artifacts"]["model"][
                    "runtime_loaded"
                ],
                "authority": physical_hai["authority"]["mode"],
                "claim_boundary": physical_hai["claim_boundary"],
            },
            "claim_boundary": "The 48-source catalog informs deterministic simulator priors; it does not provide real trajectories or labels. The separate HAI result uses external recorded HIL/testbed telemetry but is not a Ferrum hardware trial. Learned artifacts cannot grant permits, block commands, invoke adapters or actuate hardware; unqualified live delivery remains disabled, and robot trials plus independent assessment remain external.",
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
| Physical simulator JEPA | {physical["training_transitions"]:,} training transitions; unseen-family H=3 {percent(physical["final_rollout_error"]["h3"])} vs {percent(physical["final_baseline_rollout_error"]["h3"])} frozen baseline; {physical["final_false_negatives"]} FN/{physical["final_false_positives"]} FP | Digest-bound simulator caution; no execution or permit authority |
| External HIL diagnostic | HAI: {physical["external_hil_diagnostic"]["detected_attack_windows"]}/{physical["external_hil_diagnostic"]["attack_windows"]} attack windows, {physical["external_hil_diagnostic"]["false_alerts_per_hour"]:.3f} false alerts/hour | Separate advisory model; not Ferrum hardware, field deployment, certification, or runtime authority |
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

The current physical PJE1 checkpoint fits a domain-balanced decoder over {physical["training_transitions"]:,} deterministic simulator transitions while freezing the previous encoder and predictor. A catalog of {physical["incident_source_count"]} authoritative incident reports, regulatory filings, standards, postmortems, and papers supplies defensive state-distribution priors only; the simulator creates every transition and danger label. On the once-opened eight-family final set ({physical["final_unseen_family_transitions"]:,} transitions), H=3 error falls from {percent(physical["final_baseline_rollout_error"]["h3"])} to {percent(physical["final_rollout_error"]["h3"])} and the geometric H1/H3/H5 error ratio is {physical["final_geometric_h1_h3_h5_ratio"]:.4f}; the paired 10,000-resample H=3 reduction interval is [{percent(physical["final_h3_bootstrap_95_interval"][0])}, {percent(physical["final_h3_bootstrap_95_interval"][1])}]. The final set records {physical["final_false_negatives"]} FN/{physical["final_false_positives"]} FP. Known base, stress, and OOD suites record {physical["base_test_false_negatives"]}, {physical["stress_false_negatives"]}, and {physical["registered_ood_false_negatives"]} false negatives respectively; OOD also rejects {physical["registered_ood_invalid_observations_rejected"]} inconsistent observations. Fresh calibration retains a {physical["runtime_clearance_caution_threshold"]:.2f} clearance margin with {physical["calibration_test_false_negatives"]} false negatives and {percent(physical["calibration_test_false_positive_rate"])} FPR on {physical["calibration_test_rows"]:,} test rows.

Separately, the HAI site-adapted diagnostic is evaluated on {physical["external_hil_diagnostic"]["recorded_hours"]:.3f} hours of external recorded realistic ICS/HIL-testbed telemetry containing {physical["external_hil_diagnostic"]["attack_windows"]} attack windows. It detects {physical["external_hil_diagnostic"]["detected_attack_windows"]}/{physical["external_hil_diagnostic"]["attack_windows"]} windows, reaches {percent(physical["external_hil_diagnostic"]["balanced_accuracy"])} point balanced accuracy, and produces {physical["external_hil_diagnostic"]["false_alerts_per_hour"]:.3f} false alert events/hour. Its geometric H1/H3/H5 transition error is {percent(physical["external_hil_diagnostic"]["transition_geometric_h1_h3_h5_error"])} versus {percent(physical["external_hil_diagnostic"]["persistence_geometric_h1_h3_h5_error"])} persistence and {percent(physical["external_hil_diagnostic"]["per_action_mean_geometric_h1_h3_h5_error"])} per-action mean. This is separate advisory evidence, not a runtime-loaded PJE1 model, Ferrum-controlled hardware, a field trial, independent assessment, or certification. The deployed PJE1 may only add caution in a digest-bound simulation session; neither learned artifact can issue permits or invoke adapters, and unqualified live delivery remains structurally disabled.

The neural decoder evaluation is deterministic synthetic SSVEP evidence only: {neural["signal_trials"]} accepted signal trials at {percent(neural["accepted_signal_accuracy"])} accuracy, {neural["artifact_trials"]} artifact trials at {percent(neural["artifact_abstention_rate"])} abstention, and zero emitted candidates in {neural["no_control_windows"]:,} no-control windows. OS commit still requires pairing, calibration, non-neural arming, a signed preview, and revision checks.

## Simulator-backed cyber-physical software tier

At source `{cyber["source_commit"][:7]}`, {cyber["contract_tests_passed"]} deterministic contract tests passed across the physical runtime, signed neural protocol, `neurod`, and the simulator bridge; {cyber["model_and_decoder_gates_passed"]} physical-model, robustness, and neural-decoder gates also passed. The covered software boundary includes versioned provenance, deterministic replay/faults, virtual devices, simulator connectors, watchdog/recovery rules, ROS 2/MQTT/CAN conformance, actuator-disabled delivery, bounded neural proposals, host-managed agent-cell contracts, and privacy/reliability primitives.

This is local software regression evidence. It is not a live Gazebo/Webots deployment, real ROS 2/MQTT/CAN infrastructure, physical-clock or robot evidence, live EEG, native hypervisor containment, hard-real-time proof, certification, or independent replication.

## Reproduce

```powershell
python scripts/verify_world_model_paper_evaluation.py
python scripts/verify_physical_incident_sources.py
python scripts/verify_physical_incident_dataset.py
python scripts/verify_physical_world_model.py
python scripts/verify_physical_jepa_v5_final.py
python scripts/verify_physical_jepa_v5_runtime.py
python scripts/verify_physical_hai_v2_evidence.py
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
| Physical model | {physical["training_transitions"]:,} training transitions; unseen-family H=3 {percent(physical["final_rollout_error"]["h3"])} vs {percent(physical["final_baseline_rollout_error"]["h3"])} frozen baseline; digest-bound simulator caution |
| External HIL diagnostic | HAI {physical["external_hil_diagnostic"]["detected_attack_windows"]}/{physical["external_hil_diagnostic"]["attack_windows"]} windows at {physical["external_hil_diagnostic"]["false_alerts_per_hour"]:.3f} false alerts/hour; advisory and not runtime-loaded |
| Neural input | {neural["signal_trials"]} synthetic signals, {neural["artifact_trials"]} artifact abstentions, zero candidates in {neural["no_control_windows"]:,} no-control windows |
| QEMU command paths | {qemu["command_sweep_passed"]}/{qemu["command_sweep_cases"]} focused cases and {qemu["catalog_passed"]}/{qemu["catalog_entries"]} exhaustive entries for OS source `{qemu["os_source_commit"][:7]}` |
| Cyber-physical software | {cyber["contract_tests_passed"]} contract tests and {cyber["model_and_decoder_gates_passed"]} model/decoder gates passed at source `{cyber["source_commit"][:7]}` |

Read the [full benchmark protocol and limitations](docs/BENCHMARKS.md), [machine-readable benchmark summary](benchmarks.json), [capability catalog](capabilities.json), [full agent-readable context](llms-full.txt), [citation guide](docs/CITATION.md), [architecture](docs/ARCHITECTURE.md), [security policy](SECURITY.md), and [published research release](https://github.com/VyomKulshrestha/Ferrum-OS/releases/tag/world-model-study-v1.0.0).

## Claim boundaries

- The current release targets a documented QEMU/Bochs device profile, not broad physical-PC compatibility.
- Camera frames are synthetic; physical camera, gaze, and gesture accuracy are not claimed.
- Neural results are synthetic software evidence, not live EEG or medical evidence.
- Physical incident reports and papers supply defensive priors, not Ferrum trajectories or labels. Simulator results and the separate external recorded HIL diagnostic have distinct protocols; neither learned artifact has actuator authority.
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
| `{physical["protocol_id"]}` | {physical["training_transitions"]:,} training transitions; unseen-family H=3 {percent(physical["final_baseline_rollout_error"]["h3"])} to {percent(physical["final_rollout_error"]["h3"])}; final FN {physical["final_false_negatives"]}; stress FN {physical["stress_false_negatives"]}; OOD FN {physical["registered_ood_false_negatives"]} | Simulator evidence; learned execution authority still requires real-device qualification |
| `{physical["external_hil_diagnostic"]["evidence_id"]}` | {physical["external_hil_diagnostic"]["detected_attack_windows"]}/{physical["external_hil_diagnostic"]["attack_windows"]} HAI windows; {physical["external_hil_diagnostic"]["false_alerts_per_hour"]:.3f} false alerts/hour | External recorded testbed evidence; separate advisory model, not Ferrum hardware or certification |
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
python scripts/verify_physical_incident_sources.py
python scripts/verify_physical_incident_dataset.py
python scripts/verify_physical_world_model.py
python scripts/verify_physical_jepa_v5_final.py
python scripts/verify_physical_jepa_v5_runtime.py
python scripts/verify_physical_hai_v2_evidence.py
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
