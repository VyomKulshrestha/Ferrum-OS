#!/usr/bin/env python3
"""Verify the complete cross-domain world-model improvement evidence chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs/research"
PROTOCOL = RESEARCH / "cross_domain_world_model_improvement_protocol_v1.json"
DEFAULT_OUTPUT = RESEARCH / "cross_domain_world_model_improvement_verification_v1.json"
EVIDENCE = {
    "architecture_selection": "cross_domain_world_model_selection_v1.json",
    "architecture_result": "cross_domain_world_model_architecture_result_v1.json",
    "architecture_verification": "cross_domain_world_model_verification_v1.json",
    "learned_selection": "cross_domain_learned_contribution_selection_v1.json",
    "learned_result": "cross_domain_learned_contribution_result_v1.json",
    "learned_verification": "cross_domain_learned_contribution_verification_v1.json",
    "os_shadow_runtime": "world_model_v3_4_shadow_runtime_v1.json",
    "os_shadow_concurrency": "world_model_v3_4_shadow_concurrency_v1.json",
    "os_shadow_verification": "world_model_v3_4_shadow_verification_v1.json",
    "multiclient_protocol": "world_model_multiclient_contention_protocol_v1.json",
    "multiclient_result": "world_model_multiclient_contention_result_v1.json",
    "multiclient_verification": "world_model_multiclient_contention_verification_v1.json",
    "natural_use_protocol": "world_model_natural_use_protocol_v1.json",
    "natural_use_prompts": "world_model_natural_use_prompts_v1.json",
    "natural_use_result": "world_model_natural_use_result_v1.json",
    "natural_use_verification": "world_model_natural_use_verification_v1.json",
    "external_intake_protocol": "world_model_external_case_intake_protocol_v1.json",
    "external_intake_result": "world_model_external_case_intake_result_v1.json",
    "external_intake_verification": "world_model_external_case_intake_verification_v1.json",
    "physical_replay_protocol": "physical_jepa_recorded_hil_replay_protocol_v1.json",
    "physical_replay_amendment1": "physical_jepa_recorded_hil_replay_protocol_v1_amendment1.json",
    "physical_replay_amendment2": "physical_jepa_recorded_hil_replay_protocol_v1_amendment2.json",
    "physical_replay_result": "physical_jepa_recorded_hil_replay_result_v1.json",
    "physical_replay_verification": "physical_jepa_recorded_hil_replay_verification_v1.json",
    "physical_3d_protocol": "physical_jepa_multi_embodiment_3d_protocol_v1.json",
    "physical_3d_result": "physical_jepa_multi_embodiment_3d_result_v1.json",
    "physical_3d_verification": "physical_jepa_multi_embodiment_3d_verification_v1.json",
    "physical_safety_gym_protocol": "physical_jepa_safety_gymnasium_protocol_v14.json",
    "physical_safety_gym_selection": "physical_jepa_safety_gymnasium_selection_v14.json",
    "physical_safety_gym_result": "physical_jepa_safety_gymnasium_result_v14.json",
    "physical_safety_gym_verification": "physical_jepa_safety_gymnasium_verification_v14.json",
    "physical_safety_gym_v12_result": "physical_jepa_safety_gymnasium_result_v12.json",
    "physical_safety_gym_v12_verification": "physical_jepa_safety_gymnasium_verification_v12.json",
    "physical_simplex_protocol": "physical_jepa_safety_gymnasium_protocol_v13.json",
    "physical_simplex_selection": "physical_jepa_safety_gymnasium_selection_v13.json",
}
HASH_ONLY_EVIDENCE = {
    "natural_use_telemetry": "world_model_natural_use_telemetry_v1.jsonl",
    "physical_safety_gym_cases": "physical_jepa_safety_gymnasium_cases_v14.jsonl",
    **{
        f"natural_use_amendment_{number}": f"world_model_natural_use_protocol_amendment_v{number}.json"
        for number in range(1, 14)
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value) -> bool:
    if value is None or isinstance(value, (bool, str)):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, list):
        return all(finite(item) for item in value)
    if isinstance(value, dict):
        return all(finite(item) for item in value.values())
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    protocol = load(PROTOCOL)
    records = {name: load(RESEARCH / path) for name, path in EVIDENCE.items()}
    artifacts = {
        name: {
            "path": f"docs/research/{path}",
            "sha256": sha256(RESEARCH / path),
        }
        for name, path in EVIDENCE.items()
    }
    artifacts.update({
        name: {
            "path": f"docs/research/{path}",
            "sha256": sha256(RESEARCH / path),
        }
        for name, path in HASH_ONLY_EVIDENCE.items()
    })
    deployed = {
        name: sha256(ROOT / item["path"])
        for name, item in protocol["protected_deployed_artifacts"].items()
    }
    expected_deployed = {
        name: item["sha256"]
        for name, item in protocol["protected_deployed_artifacts"].items()
    }
    architecture = records["architecture_result"]
    learned = records["learned_result"]
    os_shadow = records["os_shadow_verification"]
    multiclient = records["multiclient_result"]
    natural_use = records["natural_use_verification"]
    external_intake = records["external_intake_result"]
    external_physical_rows = sum(
        item["rows"] for item in external_intake["sources"]["physical"]["files"]
    )
    physical_replay = records["physical_replay_result"]
    physical_3d = records["physical_3d_result"]
    physical_safety_gym = records["physical_safety_gym_result"]
    physical_safety_gym_verification = records["physical_safety_gym_verification"]
    physical_safety_gym_union = physical_safety_gym["arms"][
        "planner_rules_plus_learned"
    ]["metrics"]
    checks = {
        "architecture_selection_never_opened_final": records["architecture_selection"][
            "final_test_opened"
        ]
        is False
        and records["architecture_selection"]["final_catalog_guard"]["attempted"]
        is False,
        "architecture_verified": architecture["evaluation_passed"] is True
        and records["architecture_verification"]["verification_passed"] is True,
        "architecture_final_opened_once": architecture["final_open_count"] == 1,
        "learned_selection_never_opened_final": records["learned_selection"][
            "final_test_opened"
        ]
        is False
        and records["learned_selection"]["checks"]["final_catalogs_absent"] is True,
        "learned_benchmark_verified": learned["evaluation_passed"] is True
        and records["learned_verification"]["verification_passed"] is True,
        "learned_final_opened_once": learned["final_open_count"] == 1,
        "learned_marginal_result_reported_honestly": all(
            learned["domains"][domain]["marginal_learned_contribution"][
                "additional_dangerous_cases_blocked"
            ]
            == 0
            for domain in ("ferrumos", "physical")
        ),
        "independence_not_claimed": learned["independent_assessment"] is False,
        "os_shadow_verified": os_shadow["verification_passed"] is True
        and os_shadow["promotion_eligible"] is False,
        "multiclient_contention_verified": records["multiclient_verification"]["verification_passed"] is True
        and records["multiclient_verification"]["result"]["sha256"] == artifacts["multiclient_result"]["sha256"]
        and multiclient["timed_responses"] == 128
        and multiclient["jain_throughput_fairness"] >= 0.95
        and multiclient["authority"]["execution_dataset_records_added"] == 0
        and multiclient["promotion_eligible"] is False,
        "natural_use_verified": natural_use["verification_passed"] is True
        and natural_use["artifacts"]["telemetry"]["sha256"] == artifacts["natural_use_telemetry"]["sha256"]
        and natural_use["artifacts"]["result"]["sha256"] == artifacts["natural_use_result"]["sha256"]
        and natural_use["observed"]["sessions"] == 3
        and natural_use["observed"]["records"] == 24
        and len(natural_use["observed"]["action_classes"]) == 6
        and natural_use["observed"]["background_model_pageins"] == 0
        and natural_use["observed"]["physical_actuator_deliveries"] == 0
        and natural_use["promotion_eligible"] is False,
        "external_case_intake_verified": records["external_intake_verification"]["verification_passed"] is True
        and records["external_intake_verification"]["result"]["sha256"] == artifacts["external_intake_result"]["sha256"]
        and external_intake["acceptance_gates_passed"] is True
        and external_intake["physical_compatibility"]["direct_physical_jepa_v5_replay_valid"] is False
        and external_intake["authority"]["model_inference_calls"] == 0
        and external_intake["authority"]["actuator_deliveries"] == 0
        and external_intake["promotion_eligible"] is False,
        "physical_replay_verified": records["physical_replay_verification"][
            "verification_passed"
        ]
        is True
        and physical_replay["acceptance_gates_passed"] is True,
        "physical_actuator_authority_zero": physical_replay["authority"][
            "actuator_delivery_attempts"
        ]
        == 0
        and physical_replay["authority"]["actuator_deliveries"] == 0,
        "live_hil_not_claimed": "live Ferrum hardware-in-the-loop"
        in physical_replay["unsupported_gaps"],
        "multi_embodiment_3d_negative_result_verified": records[
            "physical_3d_verification"
        ]["verification_passed"]
        is True
        and physical_3d["summary"]["intervention_rate"] == 1.0
        and physical_3d["summary"]["task_completion_rate"] == 0.0,
        "physical_3d_actuator_authority_zero": physical_3d["authority"][
            "physical_actuator_attempts"
        ]
        == 0
        and physical_3d["authority"]["physical_actuator_deliveries"] == 0,
        "physical_safety_gym_selection_never_opened_final": records[
            "physical_safety_gym_selection"
        ]["selection_passed"]
        is True
        and records["physical_safety_gym_selection"]["final_seed_accessed"] is False
        and records["physical_safety_gym_selection"][
            "final_seed_access_attempted"
        ]
        is False,
        "physical_safety_gym_frozen_pass_verified": physical_safety_gym_verification[
            "overall_pass"
        ]
        is True
        and all(physical_safety_gym_verification["checks"].values())
        and physical_safety_gym["all_frozen_gates_pass"] is True
        and all(physical_safety_gym["frozen_gates"].values())
        and physical_safety_gym["final_seed_access_count"] == 1,
        "physical_safety_gym_v12_negative_retained": records[
            "physical_safety_gym_v12_result"
        ]["all_frozen_gates_pass"]
        is False
        and records["physical_safety_gym_v12_verification"]["overall_pass"] is False,
        "physical_safety_gym_effective_interventions": physical_safety_gym_verification[
            "checks"
        ]["every_counted_intervention_changes_action"]
        is True
        and physical_safety_gym_union["learned_only_interventions"] > 0
        and physical_safety_gym["selected_candidate"][
            "learned_requires_rule_confirmation"
        ]
        is False
        and physical_safety_gym["selected_candidate"]["fallback_mode"]
        == "planner_tangent",
        "physical_safety_gym_external_scope_honest": physical_safety_gym[
            "externally_authored_benchmark"
        ]
        is True
        and physical_safety_gym["independent_execution"] is False
        and physical_safety_gym["physical_actuator_attempts"] == 0
        and physical_safety_gym["physical_actuator_deliveries"] == 0,
        "physical_simplex_failure_retained_without_final_access": records[
            "physical_simplex_selection"
        ]["selection_passed"]
        is False
        and records["physical_simplex_selection"]["final_seed_accessed"] is False
        and records["physical_simplex_selection"]["final_seed_access_attempted"]
        is False,
        "protected_deployed_artifacts_unchanged": deployed == expected_deployed,
        "all_results_finite": finite(architecture)
        and finite(learned)
        and finite(physical_replay)
        and finite(physical_3d)
        and finite(physical_safety_gym),
        "new_runtime_results_finite": finite(multiclient)
        and finite(natural_use)
        and finite(external_intake),
        "no_promotion": architecture["promotion_eligible"] is False
        and learned["promotion_eligible"] is False
        and os_shadow["promotion_eligible"] is False
        and multiclient["promotion_eligible"] is False
        and natural_use["promotion_eligible"] is False
        and external_intake["promotion_eligible"] is False
        and physical_replay["promotion_eligible"] is False
        and physical_3d["promotion_eligible"] is False
        and physical_safety_gym["promotion_eligible"] is False,
    }
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "evidence": artifacts,
        "protected_deployed_artifacts": {
            name: {
                "expected_sha256": expected_deployed[name],
                "observed_sha256": deployed[name],
                "unchanged": deployed[name] == expected_deployed[name],
            }
            for name in deployed
        },
        "checks": checks,
        "verification_passed": all(checks.values()),
        "promotion_eligible": False,
        "headline": {
            "architecture_controlled_evidence": True,
            "distributional_and_causal_evidence": True,
            "marginal_learned_hazards_avoided_ferrumos": 0,
            "marginal_learned_hazards_avoided_physical": 0,
            "os_authority_disabled_shadow": True,
            "os_natural_use_sessions": 3,
            "os_natural_use_records": 24,
            "os_multiclient_preview_clients": 4,
            "os_multiclient_preview_responses": 128,
            "physical_actuator_disabled_recorded_sensor_replay": True,
            "externally_authored_physical_rows_intake": external_physical_rows,
            "external_physical_data_direct_v5_compatible": False,
            "physical_multi_embodiment_3d_stress": True,
            "physical_3d_stress_task_completion_rate": 0.0,
            "physical_3d_stress_intervention_rate": 1.0,
            "physical_safety_gymnasium_frozen_pass_verified": True,
            "physical_safety_gymnasium_task_completion_rate": physical_safety_gym[
                "headline"
            ]["task_completion_rate"],
            "physical_safety_gymnasium_intervention_rate": physical_safety_gym[
                "headline"
            ]["intervention_rate"],
            "physical_safety_gymnasium_dangerous_recall": physical_safety_gym[
                "headline"
            ]["dangerous_proposal_recall"],
            "physical_safety_gymnasium_safe_fpr": physical_safety_gym["headline"][
                "safe_proposal_false_positive_rate"
            ],
            "physical_safety_gymnasium_hazard_cost_reduction": physical_safety_gym[
                "headline"
            ]["actual_hazard_cost_reduction_fraction"],
            "physical_safety_gymnasium_learned_only_interventions": physical_safety_gym[
                "headline"
            ]["learned_only_interventions"],
            "physical_safety_gymnasium_planner_task_completion_rate": physical_safety_gym[
                "arms"
            ]["planner_unshielded"]["metrics"]["task_completion_rate"],
            "physical_safety_gymnasium_planner_hazard_cost_events": physical_safety_gym[
                "arms"
            ]["planner_unshielded"]["metrics"]["actual_hazard_cost_events"],
            "physical_safety_gymnasium_naive_hazard_cost_events": physical_safety_gym[
                "arms"
            ]["naive_unshielded"]["metrics"]["actual_hazard_cost_events"],
            "independent_benchmark": False,
            "live_physical_hil": False,
        },
        "claim_boundary": [
            "The architecture results isolate model family under matched data, curriculum, parameter budget, update budget, seeds, and final cases.",
            "The new causal catalogs show counterfactual sensitivity but zero operational learned-only hazard avoidance at the frozen zero-false-positive threshold.",
            "The OS evidence is QEMU shadow execution and the physical evidence is host replay of externally recorded testbed data; neither is deployment or independent safety assessment.",
            "Natural-use evidence comprises 24 privacy-bounded records from three researcher-operated visible QEMU sessions; it is not production telemetry or labelled accuracy evidence.",
            "Four-client contention establishes read-only preview isolation and fairness in one serial QEMU guest, not parallel or distributed field execution.",
            "Externally authored Anchor-Lab telemetry is retained as semantically incompatible with direct Physical JEPA v5 replay rather than projected into a misleading result.",
            "The local multi-embodiment 3D stress run is retained as a negative result: its union policy intervened on every case and completed no task.",
            "The Safety-Gymnasium v14 result uses a third-party task and cost implementation but a researcher-authored adapter, privileged planner, deterministic tangent shield, local execution, and local analysis; the union passes its registered naive-baseline gates while increasing hazard cost relative to the planner.",
            "Every counted Safety-Gymnasium intervention changes the applied action; warning recall, effective action-change recall, and planner divergence are reported separately.",
            "A later planner-fallback Simplex amendment fails development and never opens its reserved final seed range; it is retained as a selection negative rather than promoted into another final test.",
            "No protected deployed artifact was promoted or replaced by this study.",
        ],
    }
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "verification_passed": result["verification_passed"],
            },
            indent=2,
        )
    )
    return 0 if result["verification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
