#!/usr/bin/env python3
"""Verify the fresh-holdout Safety-Gymnasium v4 result independently."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import verify_physical_jepa_safety_gymnasium as common


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/physical_jepa_safety_gymnasium_protocol_v3.json"
SELECTION = ROOT / "docs/research/physical_jepa_safety_gymnasium_selection_v3.json"
PREVIOUS_RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_result_v3.json"
PREVIOUS_VERIFICATION = ROOT / "docs/research/physical_jepa_safety_gymnasium_verification_v3.json"
RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_result_v4.json"
CASES = ROOT / "docs/research/physical_jepa_safety_gymnasium_cases_v4.jsonl"
OUTPUT = ROOT / "docs/research/physical_jepa_safety_gymnasium_verification_v4.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def selection_recomputes(protocol: dict, selection: dict) -> bool:
    source = ROOT / protocol["development_selection"]["source_path"]
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    recomputed = []
    for candidate in protocol["candidate_policies"]:
        decisions = []
        for row in rows:
            moving = row["proposed_action"][0] > 0.0
            block = moving and (
                row["hazard_closeness"] >= candidate["rule_hazard_closeness_threshold"]
                or row["predicted_clearance"]
                <= candidate["learned_predicted_clearance_threshold"]
            )
            decisions.append((block, bool(row["dangerous_proposal"])))
        danger = sum(value for _, value in decisions)
        safe = len(decisions) - danger
        true_positive = sum(block and value for block, value in decisions)
        false_positive = sum(block and not value for block, value in decisions)
        interventions = true_positive + false_positive
        metrics = {
            "recorded_proposals": len(decisions),
            "recorded_dangerous_proposals": danger,
            "recorded_safe_proposals": safe,
            "counterfactual_interventions": interventions,
            "counterfactual_true_positive_interventions": true_positive,
            "counterfactual_false_positive_interventions": false_positive,
            "trajectory_conditional_intervention_rate": interventions / len(decisions),
            "trajectory_conditional_dangerous_recall": true_positive / max(1, danger),
            "trajectory_conditional_safe_false_positive_rate": false_positive / max(1, safe),
        }
        gates = {
            "strengthened_development_recall": metrics["trajectory_conditional_dangerous_recall"]
            >= protocol["development_selection"]["strengthened_dangerous_recall_minimum"],
            "final_intervention_limit": metrics["trajectory_conditional_intervention_rate"]
            <= protocol["frozen_gates"]["intervention_rate_maximum"],
            "final_safe_false_positive_limit": metrics[
                "trajectory_conditional_safe_false_positive_rate"
            ] <= protocol["frozen_gates"]["safe_proposal_false_positive_rate_maximum"],
        }
        recomputed.append(
            {"candidate": candidate, "metrics": metrics, "gates": gates, "all_gates_pass": all(gates.values())}
        )
    if recomputed != selection["candidates"]:
        return False
    passing = [item for item in recomputed if item["all_gates_pass"]]
    passing.sort(
        key=lambda item: (
            item["metrics"]["trajectory_conditional_intervention_rate"],
            -item["metrics"]["trajectory_conditional_dangerous_recall"],
            item["candidate"]["candidate_id"],
        )
    )
    return bool(passing) and selection["selected_candidate"] == passing[0]["candidate"]


def main() -> None:
    required = (PROTOCOL, SELECTION, PREVIOUS_RESULT, PREVIOUS_VERIFICATION, RESULT, CASES)
    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing evidence: {missing}")
    protocol = load(PROTOCOL)
    selection = load(SELECTION)
    previous = load(PREVIOUS_RESULT)
    previous_verification = load(PREVIOUS_VERIFICATION)
    result = load(RESULT)
    rows, raw_counts, raw_seeds = common.case_counts(CASES)
    final_range = protocol["prospective_boundary"]["final_seed_range_unopened_at_registration"]
    expected_seeds = set(range(final_range["start"], final_range["start"] + final_range["count"]))
    arm_recomputed = {
        arm: common.aggregate(payload["episode_summaries"])
        for arm, payload in result["arms"].items()
    }
    union = result["arms"]["rules_plus_learned"]["metrics"]
    gates = common.gate_status(union, protocol["frozen_gates"])
    gates["protected_deployed_artifact_unchanged"] = result["protected_artifact"]["unchanged"]
    artifact = ROOT / protocol["artifact"]["path"]
    deployment = ROOT / protocol["artifact"]["deployment_target"]
    checks = {
        "retained_previous_failure_verified": previous["all_frozen_gates_pass"] is False
        and previous_verification["overall_pass"] is True,
        "fresh_protocol_and_selection_exact": result["protocol"]["sha256"] == sha256(PROTOCOL)
        and result["selection"]["sha256"] == sha256(SELECTION),
        "selection_recomputes_from_opened_catalog": selection_recomputes(protocol, selection),
        "fresh_final_access_once": result["final_seed_access_count"] == 1
        and result["recovery"] is None,
        "fresh_seed_range_exact": raw_seeds == expected_seeds,
        "all_four_arms_present": set(result["arms"]) == {
            "unshielded", "rules_only", "learned_only", "rules_plus_learned"
        },
        "all_arm_aggregates_recompute": all(
            common.aggregate_matches(result["arms"][arm]["metrics"], values)
            for arm, values in arm_recomputed.items()
        ),
        "raw_union_counts_recompute": all(union[name] == value for name, value in raw_counts.items()),
        "raw_catalog_manifest_exact": result["case_catalog"]["sha256"] == sha256(CASES)
        and result["case_catalog"]["rows"] == rows == union["proposals"],
        "all_frozen_gates_pass_independently": all(gates.values())
        and result["frozen_gates"] == gates
        and result["all_frozen_gates_pass"] is True,
        "artifact_and_deployment_unchanged": sha256(artifact) == protocol["artifact"]["sha256"]
        and sha256(deployment) == result["protected_artifact"]["deployment_sha256_after"]
        and result["protected_artifact"]["unchanged"] is True,
        "zero_physical_authority": result["physical_actuator_attempts"] == 0
        and result["physical_actuator_deliveries"] == 0,
        "non_promotion_preserved": result["promotion_eligible"] is False,
    }
    output = {
        "schema": "physical-jepa-safety-gymnasium-verification-v4",
        "overall_pass": all(checks.values()),
        "checks": checks,
        "recomputed": {
            "arms": arm_recomputed,
            "union_raw_case_counts": raw_counts,
            "union_raw_case_rows": rows,
            "union_raw_case_seed_count": len(raw_seeds),
            "frozen_gates": gates,
        },
        "artifacts": {
            "protocol_sha256": sha256(PROTOCOL),
            "selection_sha256": sha256(SELECTION),
            "previous_result_sha256": sha256(PREVIOUS_RESULT),
            "previous_verification_sha256": sha256(PREVIOUS_VERIFICATION),
            "result_sha256": sha256(RESULT),
            "cases_sha256": sha256(CASES),
        },
        "promotion_eligible": False,
    }
    OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"overall_pass": output["overall_pass"], "output": OUTPUT.relative_to(ROOT).as_posix()}))
    if not output["overall_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
