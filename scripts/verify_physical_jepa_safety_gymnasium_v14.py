#!/usr/bin/env python3
"""Independently verify the horizon-risk Safety-Gymnasium v14 evidence."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs/research"
PROTOCOL = RESEARCH / "physical_jepa_safety_gymnasium_protocol_v14.json"
SELECTION = RESEARCH / "physical_jepa_safety_gymnasium_selection_v14.json"
RESULT = RESEARCH / "physical_jepa_safety_gymnasium_result_v14.json"
CASES = RESEARCH / "physical_jepa_safety_gymnasium_cases_v14.jsonl"
RUNTIME = RESEARCH / "physical_jepa_safety_gymnasium_runtime_verification_v14.json"
OUTPUT = RESEARCH / "physical_jepa_safety_gymnasium_verification_v14.json"
COUNT_FIELDS = (
    "proposals",
    "dangerous_proposals",
    "safe_proposals",
    "interventions",
    "true_positive_interventions",
    "false_positive_interventions",
    "false_negative_proposals",
    "true_negative_proposals",
    "warnings",
    "true_positive_warnings",
    "false_positive_warnings",
    "false_negative_warnings",
    "true_negative_warnings",
    "dangerous_recall_numerator",
    "safe_false_positive_numerator",
    "actual_hazard_cost_events",
    "actual_total_cost_events",
    "actual_vase_cost_events",
    "learned_only_interventions",
    "learned_only_dangerous_interventions",
    "base_controller_divergences",
    "steps",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def aggregate(episodes: list[dict]) -> dict:
    total = {
        field: sum(int(episode[field]) for episode in episodes)
        for field in COUNT_FIELDS
    }
    total["episodes"] = len(episodes)
    total["task_completions"] = sum(bool(item["task_completed"]) for item in episodes)
    total["task_completion_rate"] = total["task_completions"] / max(1, total["episodes"])
    total["intervention_rate"] = total["interventions"] / max(1, total["proposals"])
    total["dangerous_proposal_recall"] = total["dangerous_recall_numerator"] / max(
        1, total["dangerous_proposals"]
    )
    total["safe_proposal_false_positive_rate"] = total[
        "safe_false_positive_numerator"
    ] / max(1, total["safe_proposals"])
    total["warning_recall"] = total["true_positive_warnings"] / max(
        1, total["dangerous_proposals"]
    )
    total["warning_false_positive_rate"] = total[
        "false_positive_warnings"
    ] / max(1, total["safe_proposals"])
    total["effective_intervention_recall"] = total[
        "true_positive_interventions"
    ] / max(1, total["dangerous_proposals"])
    total["actual_hazard_cost_rate"] = total["actual_hazard_cost_events"] / max(
        1, total["proposals"]
    )
    total["base_controller_divergence_rate"] = total[
        "base_controller_divergences"
    ] / max(1, total["proposals"])
    total["episodes_with_actual_hazard_cost"] = sum(
        item["actual_hazard_cost_events"] > 0 for item in episodes
    )
    return total


def recorded_aggregate_matches(recorded: dict, recomputed: dict) -> bool:
    for key, value in recomputed.items():
        if key not in recorded:
            return False
        if isinstance(value, float):
            if not math.isclose(float(recorded[key]), value, rel_tol=0.0, abs_tol=1e-12):
                return False
        elif recorded[key] != value:
            return False
    return True


def gate_status(union: dict, baseline: dict, protocol: dict) -> dict:
    gates = protocol["frozen_gates"]
    reduction = (
        baseline["actual_hazard_cost_events"] - union["actual_hazard_cost_events"]
    ) / max(1, baseline["actual_hazard_cost_events"])
    return {
        "task_completion_rate": union["task_completion_rate"]
        >= gates["task_completion_rate_minimum"],
        "intervention_rate": union["intervention_rate"]
        <= gates["intervention_rate_maximum"],
        "dangerous_proposal_recall": union["dangerous_proposal_recall"]
        >= gates["dangerous_proposal_recall_minimum"],
        "safe_proposal_false_positive_rate": union["safe_proposal_false_positive_rate"]
        <= gates["safe_proposal_false_positive_rate_maximum"],
        "actual_hazard_cost_reduction_fraction": reduction
        >= gates["actual_hazard_cost_reduction_fraction_minimum"],
        "physical_actuator_attempts": gates["physical_actuator_attempts"] == 0,
        "physical_actuator_deliveries": gates["physical_actuator_deliveries"] == 0,
        "protected_deployed_artifact_unchanged": union.get(
            "protected_deployed_artifact_unchanged",
            True,
        ),
    }


def raw_counts(path: Path, expected_arm: str) -> tuple[dict, set[int], dict]:
    counts = {field: 0 for field in COUNT_FIELDS if field != "steps"}
    seeds = set()
    checks = {
        "rows": 0,
        "unchanged_interventions": 0,
        "union_trigger_mismatches": 0,
        "learned_only_rows": 0,
        "learned_only_dangerous_rows": 0,
        "hazard_not_total_rows": 0,
        "warned_unchanged_actions": 0,
    }
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item["arm"] != expected_arm:
                raise ValueError("raw catalog contains an unexpected arm")
            checks["rows"] += 1
            seeds.add(int(item["seed"]))
            dangerous = bool(item["dangerous_proposal"])
            intervention = bool(item["intervention"])
            warning = bool(item["warning"])
            changed = not all(
                math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)
                for left, right in zip(item["proposed_action"], item["applied_action"])
            )
            learned_only = intervention and item["intervention_source"] == "learned"
            counts["proposals"] += 1
            counts["dangerous_proposals"] += int(dangerous)
            counts["safe_proposals"] += int(not dangerous)
            counts["interventions"] += int(intervention)
            counts["true_positive_interventions"] += int(intervention and dangerous)
            counts["false_positive_interventions"] += int(intervention and not dangerous)
            counts["false_negative_proposals"] += int(not intervention and dangerous)
            counts["true_negative_proposals"] += int(not intervention and not dangerous)
            counts["warnings"] += int(warning)
            counts["true_positive_warnings"] += int(warning and dangerous)
            counts["false_positive_warnings"] += int(warning and not dangerous)
            counts["false_negative_warnings"] += int(not warning and dangerous)
            counts["true_negative_warnings"] += int(not warning and not dangerous)
            counts["dangerous_recall_numerator"] += int(warning and dangerous)
            counts["safe_false_positive_numerator"] += int(warning and not dangerous)
            counts["actual_hazard_cost_events"] += int(item["actual_hazard_cost"])
            counts["actual_total_cost_events"] += int(item["actual_total_cost"])
            counts["actual_vase_cost_events"] += int(item["actual_vase_cost"])
            counts["learned_only_interventions"] += int(learned_only)
            counts["learned_only_dangerous_interventions"] += int(
                learned_only and dangerous
            )
            counts["base_controller_divergences"] += int(
                not all(
                    math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)
                    for left, right in zip(
                        item["proposed_action"], item["naive_proposed_action"]
                    )
                )
            )
            checks["unchanged_interventions"] += int(intervention and not changed)
            checks["warned_unchanged_actions"] += int(warning and not changed)
            checks["union_trigger_mismatches"] += int(
                item["base_intervention"]
                and not (item["rule_block"] or item["learned_block"])
            )
            checks["learned_only_rows"] += int(learned_only)
            checks["learned_only_dangerous_rows"] += int(learned_only and dangerous)
            checks["hazard_not_total_rows"] += int(
                item["actual_hazard_cost"] and not item["actual_total_cost"]
            )
    return counts, seeds, checks


def main() -> None:
    required = (PROTOCOL, SELECTION, RESULT, CASES, RUNTIME)
    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing v14 evidence: {missing}")
    protocol = load(PROTOCOL)
    selection = load(SELECTION)
    result = load(RESULT)
    runtime = load(RUNTIME)
    union_name = protocol["headline_arms"]["union"]
    baseline_name = protocol["headline_arms"]["baseline"]
    arm_recomputations = {
        name: aggregate(payload["episode_summaries"])
        for name, payload in result["arms"].items()
    }
    union = result["arms"][union_name]["metrics"]
    baseline = result["arms"][baseline_name]["metrics"]
    raw, seeds, raw_checks = raw_counts(CASES, union_name)
    final_range = protocol["prospective_boundary"]["final_seed_range_unopened_at_registration"]
    expected_seeds = set(
        range(final_range["start"], final_range["start"] + final_range["count"])
    )
    gates = gate_status(union, baseline, protocol)
    gates["protected_deployed_artifact_unchanged"] = result["protected_artifact"][
        "unchanged"
    ]
    adapter_record = protocol["learned_risk_adapter"]
    adapter = ROOT / adapter_record["path"]
    development = ROOT / adapter_record["development_catalog"]["path"]
    checks = {
        "runtime_repair_verified": runtime["verification_passed"] is True,
        "warning_recall_basis_registered": protocol["oracle_and_metrics"][
            "dangerous_recall_basis"
        ]
        == "warning"
        and protocol["oracle_and_metrics"]["danger_rollout_mode"]
        == "nominal_controller",
        "selection_passed_without_final_access": selection["selection_passed"] is True
        and selection["final_seed_accessed"] is False
        and selection["final_seed_access_attempted"] is False,
        "protocol_and_selection_hashes_exact": result["protocol"]["sha256"] == sha256(PROTOCOL)
        and result["selection"]["sha256"] == sha256(SELECTION),
        "adapter_and_development_catalog_exact": sha256(adapter) == adapter_record["sha256"]
        and sha256(development) == adapter_record["development_catalog"]["sha256"],
        "fresh_final_access_once": result["final_seed_access_count"] == 1
        and result["recovery"] is None,
        "all_registered_arms_present": set(result["arms"]) == set(protocol["final_arms"]),
        "all_arm_aggregates_recompute": all(
            recorded_aggregate_matches(result["arms"][name]["metrics"], recomputed)
            for name, recomputed in arm_recomputations.items()
        ),
        "raw_union_catalog_recomputes": all(union[name] == value for name, value in raw.items()),
        "raw_catalog_manifest_exact": result["case_catalog"]["sha256"] == sha256(CASES)
        and result["case_catalog"]["rows"] == raw_checks["rows"] == union["proposals"],
        "fresh_seed_range_exact": seeds == expected_seeds,
        "all_frozen_gates_pass_independently": all(gates.values())
        and result["frozen_gates"] == gates
        and result["all_frozen_gates_pass"] is True,
        "every_counted_intervention_changes_action": raw_checks[
            "unchanged_interventions"
        ]
        == 0,
        "monotone_union_trigger_exact": raw_checks["union_trigger_mismatches"] == 0,
        "learned_branch_has_measured_marginal_caution": raw_checks["learned_only_rows"]
        == union["learned_only_interventions"]
        and raw_checks["learned_only_dangerous_rows"]
        == union["learned_only_dangerous_interventions"],
        "hazard_cost_never_exceeds_total_cost": raw_checks["hazard_not_total_rows"] == 0,
        "artifact_and_deployment_unchanged": result["protected_artifact"]["unchanged"] is True,
        "zero_physical_authority": result["physical_actuator_attempts"] == 0
        and result["physical_actuator_deliveries"] == 0,
        "non_promotion_preserved": result["promotion_eligible"] is False,
    }
    output = {
        "schema": "physical-jepa-safety-gymnasium-verification-v14",
        "overall_pass": all(checks.values()),
        "checks": checks,
        "recomputed": {
            "arms": arm_recomputations,
            "union_raw_counts": raw,
            "raw_checks": raw_checks,
            "frozen_gates": gates,
        },
        "artifacts": {
            "protocol_sha256": sha256(PROTOCOL),
            "selection_sha256": sha256(SELECTION),
            "result_sha256": sha256(RESULT),
            "cases_sha256": sha256(CASES),
            "runtime_verification_sha256": sha256(RUNTIME),
            "adapter_sha256": sha256(adapter),
            "development_catalog_sha256": sha256(development),
        },
        "promotion_eligible": False,
    }
    OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"overall_pass": output["overall_pass"], "output": OUTPUT.relative_to(ROOT).as_posix()}))
    if not output["overall_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
