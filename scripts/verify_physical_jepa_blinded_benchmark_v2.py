#!/usr/bin/env python3
"""Verify the controller-amended v2 sealed benchmark and its retained v1 failure."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_protocol.json"
CATALOG = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_catalog.json"
COMMITMENT = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_commitment.json"
SELECTION = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_selection.json"
RESULT = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_result.json"
RUNNER = ROOT / "scripts" / "run_physical_jepa_blinded_benchmark_v2.py"
DEFAULT_OUTPUT = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_verification.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    protocol = read_json(PROTOCOL)
    catalog = read_json(CATALOG)
    commitment = read_json(COMMITMENT)
    selection = read_json(SELECTION)
    result = read_json(RESULT)
    records = result["cases"]
    summary = result["summary"]
    v1 = ROOT / protocol["frozen_v1_negative_result"]["path"]
    base_runner = ROOT / protocol["base_runner"]["path"]
    deployed = ROOT / protocol["deployed_artifact"]["path"]
    artifact = ROOT / protocol["artifact"]["path"]

    spec = importlib.util.spec_from_file_location("sealed_benchmark_v2", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    selector_source = inspect.getsource(module.select_policy)

    unshielded = sum(record["unshielded_collision"] for record in records)
    shielded = sum(record["shielded_collision"] for record in records)
    interventions = sum(record["shield_command"] == "stop" for record in records)
    completions = sum(record["task_completed"] for record in records)
    learned_hits = sum(
        record["learned_alert"] and record["unshielded_collision"] for record in records
    )
    incremental = sum(
        record["learned_alert"] and not record["deterministic_block"] for record in records
    )
    expected_episodes = sum(protocol["case_distribution"]["families"].values())
    checks = {
        "protocol_registered_before_v2_artifacts": not protocol["status_at_registration"]["sealed_catalog_generated"]
        and not protocol["status_at_registration"]["policy_selected"]
        and not protocol["status_at_registration"]["sealed_evaluation_run"],
        "v1_failure_known_and_retained": protocol["status_at_registration"]["v1_completion_gate_known_failed"]
        and sha256(v1) == protocol["frozen_v1_negative_result"]["sha256"]
        and not read_json(v1)["all_sealed_gates_pass"],
        "base_runner_is_frozen": sha256(base_runner) == protocol["base_runner"]["sha256"]
        == selection["base_runner_sha256"]
        == result["base_runner_sha256"],
        "commitment_binds_protocol_and_catalog": commitment["protocol_sha256"] == sha256(PROTOCOL)
        and commitment["catalog_sha256"] == sha256(CATALOG),
        "catalog_binds_protocol": catalog["protocol_sha256"] == sha256(PROTOCOL),
        "catalog_precedes_selection_and_withholds_cases": commitment["generated_before_policy_selection"]
        and commitment["seed_withheld_from_selector"]
        and commitment["cases_withheld_from_selector"]
        and not selection["blind_seed_seen"]
        and not selection["blind_catalog_opened"],
        "selector_has_no_catalog_reference": "CATALOG" not in selector_source
        and "cases" not in selector_source,
        "selection_binds_commitment": selection["commitment_sha256"] == sha256(COMMITMENT)
        and selection["committed_catalog_sha256"] == sha256(CATALOG),
        "selection_binds_current_sources": selection["selector_sha256"] == sha256(RUNNER)
        and selection["base_runner_sha256"] == sha256(base_runner),
        "result_binds_full_lineage": result["protocol_sha256"] == sha256(PROTOCOL)
        and result["commitment_sha256"] == sha256(COMMITMENT)
        and result["catalog_sha256"] == sha256(CATALOG)
        and result["selection_sha256"] == sha256(SELECTION)
        and result["runner_sha256"] == sha256(RUNNER)
        and result["frozen_v1_result_sha256"] == sha256(v1),
        "single_final_open_without_retuning": result["final_open_count"]
        == protocol["blinding"]["final_open_count"]
        == 1
        and not result["retuned_after_open"],
        "registered_episode_and_family_counts": len(records) == catalog["episodes"] == expected_episodes
        and all(
            sum(record["family"] == family for record in records) == count
            for family, count in protocol["case_distribution"]["families"].items()
        ),
        "summary_counts_recompute": summary["unshielded_collisions"] == unshielded
        and summary["shielded_collisions"] == shielded
        and summary["interventions"] == interventions
        and summary["task_completions"] == completions
        and summary["incremental_learned_interventions"] == incremental,
        "summary_rates_recompute": close(summary["task_completion_rate"], completions / len(records))
        and close(summary["intervention_rate"], interventions / len(records))
        and close(summary["collision_reduction"], (unshielded - shielded) / max(1, unshielded))
        and close(summary["learned_collision_recall"], learned_hits / max(1, unshielded)),
        "controller_budget_and_completion_are_exact": result["controller"] == protocol["controller"]
        and all(record["control_cycles"] == (1 if record["shield_command"] == "stop" else 2) for record in records)
        and all(
            not record["task_completed"]
            or record["final_target_error_m"] <= protocol["controller"]["target_tolerance_m"]
            for record in records
        ),
        "all_sealed_gates_pass": result["all_sealed_gates_pass"]
        and all(result["sealed_gates"].values()),
        "simulator_boundary_is_explicit": result["backend"]["connection_mode"] == "DIRECT"
        and result["backend"]["evidence_class"] == "simulated"
        and not result["backend"]["actuator_enabled"],
        "all_bridge_evidence_is_simulated_and_accepted": summary["all_observations_simulated"]
        and summary["all_acknowledgements_accepted"],
        "deployment_unchanged": result["deployment_integrity"]["unchanged"]
        and result["deployment_integrity"]["before_sha256"]
        == result["deployment_integrity"]["after_sha256"]
        == sha256(deployed),
        "deployed_and_evaluated_artifacts_match_registration": sha256(deployed)
        == protocol["deployed_artifact"]["sha256"]
        and sha256(artifact) == protocol["artifact"]["sha256"],
        "claim_boundary_rejects_hil_and_physical_deployment": any(
            "not HIL or physical deployment" in statement for statement in result["claim_boundary"]
        ),
    }
    evidence = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "artifacts": {
            "protocol_sha256": sha256(PROTOCOL),
            "catalog_sha256": sha256(CATALOG),
            "commitment_sha256": sha256(COMMITMENT),
            "selection_sha256": sha256(SELECTION),
            "result_sha256": sha256(RESULT),
            "runner_sha256": sha256(RUNNER),
            "base_runner_sha256": sha256(base_runner),
            "v1_negative_result_sha256": sha256(v1),
            "deployed_artifact_sha256": sha256(deployed),
        },
        "primary_metrics": {
            key: summary[key]
            for key in (
                "task_completion_rate",
                "intervention_rate",
                "unshielded_collisions",
                "shielded_collisions",
                "collision_reduction",
            )
        },
        "claim_boundary": "Locally executed, selection-blinded PyBullet evidence with a retained failed v1 run; not independent, HIL, physical deployment, or certification evidence.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if evidence["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
