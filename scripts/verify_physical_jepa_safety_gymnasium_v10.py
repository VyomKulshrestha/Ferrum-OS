#!/usr/bin/env python3
"""Independently verify the fresh planner-factorized Safety-Gymnasium result."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/physical_jepa_safety_gymnasium_protocol_v10.json"
SELECTION = ROOT / "docs/research/physical_jepa_safety_gymnasium_selection_v10.json"
RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_result_v10.json"
CASES = ROOT / "docs/research/physical_jepa_safety_gymnasium_cases_v10.jsonl"
OUTPUT = ROOT / "docs/research/physical_jepa_safety_gymnasium_verification_v10.json"

COUNT_FIELDS = (
    "proposals", "dangerous_proposals", "safe_proposals", "interventions",
    "true_positive_interventions", "false_positive_interventions",
    "false_negative_proposals", "true_negative_proposals",
    "actual_hazard_cost_events", "learned_only_interventions",
    "learned_only_dangerous_interventions", "base_controller_divergences", "steps",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def aggregate(episodes: list[dict]) -> dict:
    total = {field: sum(int(item[field]) for item in episodes) for field in COUNT_FIELDS}
    total["episodes"] = len(episodes)
    total["task_completions"] = sum(bool(item["task_completed"]) for item in episodes)
    total["task_completion_rate"] = total["task_completions"] / max(1, total["episodes"])
    total["intervention_rate"] = total["interventions"] / max(1, total["proposals"])
    total["dangerous_proposal_recall"] = total["true_positive_interventions"] / max(
        1, total["dangerous_proposals"]
    )
    total["safe_proposal_false_positive_rate"] = total[
        "false_positive_interventions"
    ] / max(1, total["safe_proposals"])
    total["actual_hazard_cost_rate"] = total["actual_hazard_cost_events"] / max(
        1, total["proposals"]
    )
    total["base_controller_divergence_rate"] = total[
        "base_controller_divergences"
    ] / max(1, total["proposals"])
    total["episodes_with_actual_hazard_cost"] = sum(
        int(item["actual_hazard_cost_events"] > 0) for item in episodes
    )
    return total


def aggregate_matches(recorded: dict, recomputed: dict) -> bool:
    for name, value in recomputed.items():
        if isinstance(value, float):
            if not math.isclose(float(recorded[name]), value, rel_tol=0.0, abs_tol=1e-12):
                return False
        elif recorded[name] != value:
            return False
    return True


def gate_status(union: dict, baseline: dict, gates: dict) -> dict:
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
    }


def raw_counts(path: Path) -> tuple[int, dict, set[int]]:
    counts = {field: 0 for field in COUNT_FIELDS if field != "steps"}
    seeds: set[int] = set()
    rows = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            rows += 1
            seeds.add(int(item["seed"]))
            if item["arm"] != "planner_rules_plus_learned":
                raise ValueError("raw catalog contains unexpected arm")
            dangerous = bool(item["dangerous_proposal"])
            blocked = bool(item["intervention"])
            learned_only = bool(item["learned_block"] and not item["rule_block"])
            divergent = not all(
                math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12)
                for a, b in zip(item["proposed_action"], item["naive_proposed_action"])
            )
            counts["proposals"] += 1
            counts["dangerous_proposals"] += int(dangerous)
            counts["safe_proposals"] += int(not dangerous)
            counts["interventions"] += int(blocked)
            counts["true_positive_interventions"] += int(blocked and dangerous)
            counts["false_positive_interventions"] += int(blocked and not dangerous)
            counts["false_negative_proposals"] += int(not blocked and dangerous)
            counts["true_negative_proposals"] += int(not blocked and not dangerous)
            counts["actual_hazard_cost_events"] += int(item["actual_hazard_cost"])
            counts["learned_only_interventions"] += int(learned_only)
            counts["learned_only_dangerous_interventions"] += int(learned_only and dangerous)
            counts["base_controller_divergences"] += int(divergent)
    return rows, counts, seeds


def main() -> None:
    required = (PROTOCOL, SELECTION, RESULT, CASES)
    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing evidence: {missing}")
    protocol = load(PROTOCOL)
    selection = load(SELECTION)
    result = load(RESULT)
    rows, cases, seeds = raw_counts(CASES)
    arms = {
        arm: aggregate(payload["episode_summaries"])
        for arm, payload in result["arms"].items()
    }
    union_name = protocol["headline_arms"]["union"]
    baseline_name = protocol["headline_arms"]["baseline"]
    union = result["arms"][union_name]["metrics"]
    baseline = result["arms"][baseline_name]["metrics"]
    gates = gate_status(union, baseline, protocol["frozen_gates"])
    gates["protected_deployed_artifact_unchanged"] = result["protected_artifact"]["unchanged"]
    final_range = protocol["prospective_boundary"]["final_seed_range_unopened_at_registration"]
    expected_seeds = set(range(final_range["start"], final_range["start"] + final_range["count"]))
    artifact = ROOT / protocol["artifact"]["path"]
    deployment = ROOT / protocol["artifact"]["deployment_target"]
    checks = {
        "selection_passed_without_final_access": selection["selection_passed"] is True
        and selection["final_seed_accessed"] is False
        and selection["selected_candidate"] == result["selected_candidate"],
        "protocol_and_selection_hashes_exact": result["protocol"]["sha256"] == sha256(PROTOCOL)
        and result["selection"]["sha256"] == sha256(SELECTION),
        "fresh_final_access_once": result["final_seed_access_count"] == 1
        and result["recovery"] is None,
        "all_five_arms_present": set(result["arms"]) == set(protocol["final_arms"]),
        "all_arm_aggregates_recompute": all(
            aggregate_matches(result["arms"][name]["metrics"], value)
            for name, value in arms.items()
        ),
        "raw_union_catalog_recomputes": all(union[name] == value for name, value in cases.items()),
        "raw_catalog_manifest_exact": result["case_catalog"]["sha256"] == sha256(CASES)
        and result["case_catalog"]["rows"] == rows == union["proposals"],
        "fresh_seed_range_exact": seeds == expected_seeds,
        "all_frozen_gates_pass_independently": all(gates.values())
        and result["frozen_gates"] == gates
        and result["all_frozen_gates_pass"] is True,
        "planner_divergence_reported_separately": union["base_controller_divergence_rate"]
        == union["base_controller_divergences"] / union["proposals"],
        "artifact_and_deployment_unchanged": sha256(artifact) == protocol["artifact"]["sha256"]
        and sha256(deployment) == result["protected_artifact"]["deployment_sha256_after"]
        and result["protected_artifact"]["unchanged"] is True,
        "zero_physical_authority": result["physical_actuator_attempts"] == 0
        and result["physical_actuator_deliveries"] == 0,
        "non_promotion_preserved": result["promotion_eligible"] is False,
    }
    output = {
        "schema": "physical-jepa-safety-gymnasium-verification-v10",
        "overall_pass": all(checks.values()),
        "checks": checks,
        "recomputed": {
            "arms": arms,
            "union_raw_counts": cases,
            "union_raw_rows": rows,
            "fresh_seed_count": len(seeds),
            "frozen_gates": gates,
        },
        "artifacts": {
            "protocol_sha256": sha256(PROTOCOL), "selection_sha256": sha256(SELECTION),
            "result_sha256": sha256(RESULT), "cases_sha256": sha256(CASES),
        },
        "promotion_eligible": False,
    }
    OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"overall_pass": output["overall_pass"], "output": OUTPUT.relative_to(ROOT).as_posix()}))
    if not output["overall_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
