#!/usr/bin/env python3
"""Independently verify the planner-fallback Simplex Safety-Gymnasium result."""

from __future__ import annotations

import json
import math
from pathlib import Path

from verify_physical_jepa_safety_gymnasium_v10 import (
    COUNT_FIELDS,
    ROOT,
    aggregate,
    aggregate_matches,
    gate_status,
    load,
    sha256,
)


PROTOCOL = ROOT / "docs/research/physical_jepa_safety_gymnasium_protocol_v13.json"
SELECTION = ROOT / "docs/research/physical_jepa_safety_gymnasium_selection_v13.json"
RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_result_v13.json"
CASES = ROOT / "docs/research/physical_jepa_safety_gymnasium_cases_v13.jsonl"
OUTPUT = ROOT / "docs/research/physical_jepa_safety_gymnasium_verification_v13.json"


def raw_counts(path: Path) -> tuple[int, dict, set[int], dict]:
    counts = {field: 0 for field in COUNT_FIELDS if field != "steps"}
    effective = {
        "interventions": 0,
        "unchanged_interventions": 0,
        "simplex_switches": 0,
        "simplex_interventions": 0,
        "learned_only_interventions": 0,
        "learned_only_dangerous_interventions": 0,
    }
    seeds: set[int] = set()
    rows = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            rows += 1
            seeds.add(int(item["seed"]))
            if item["arm"] != "rules_plus_learned":
                raise ValueError("raw catalog contains unexpected arm")
            dangerous = bool(item["dangerous_proposal"])
            blocked = bool(item["intervention"])
            learned_only = bool(blocked and item["learned_block"] and not item["rule_block"])
            changed = not all(
                math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12)
                for a, b in zip(item["proposed_action"], item["applied_action"])
            )
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
            effective["interventions"] += int(blocked)
            effective["unchanged_interventions"] += int(blocked and not changed)
            effective["simplex_switches"] += int(item["recovery_phase"] == "simplex_planner")
            effective["simplex_interventions"] += int(
                blocked and item["recovery_phase"] == "simplex_planner"
            )
            effective["learned_only_interventions"] += int(learned_only)
            effective["learned_only_dangerous_interventions"] += int(
                learned_only and dangerous
            )
    return rows, counts, seeds, effective


def main() -> None:
    required = (PROTOCOL, SELECTION, RESULT, CASES)
    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing evidence: {missing}")
    protocol = load(PROTOCOL)
    selection = load(SELECTION)
    result = load(RESULT)
    rows, cases, seeds, effective = raw_counts(CASES)
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
        "all_registered_arms_present": set(result["arms"]) == set(protocol["final_arms"]),
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
        "every_counted_intervention_is_effective_simplex_switch": effective["interventions"]
        == union["interventions"]
        and effective["unchanged_interventions"] == 0
        and effective["simplex_interventions"] == union["interventions"],
        "learned_alerts_have_no_independent_authority": effective[
            "learned_only_interventions"
        ]
        == 0
        and union["learned_only_interventions"] == 0
        and result["selected_candidate"]["learned_requires_rule_confirmation"] is True,
        "oracle_not_used_by_fallback_policy": protocol["independence"]["oracle_use"]
        == "evaluation labels only; never used to select the applied action",
        "artifact_and_deployment_unchanged": sha256(artifact) == protocol["artifact"]["sha256"]
        and sha256(deployment) == result["protected_artifact"]["deployment_sha256_after"]
        and result["protected_artifact"]["unchanged"] is True,
        "zero_physical_authority": result["physical_actuator_attempts"] == 0
        and result["physical_actuator_deliveries"] == 0,
        "non_promotion_preserved": result["promotion_eligible"] is False,
    }
    output = {
        "schema": "physical-jepa-safety-gymnasium-verification-v13",
        "overall_pass": all(checks.values()),
        "checks": checks,
        "recomputed": {
            "arms": arms,
            "union_raw_counts": cases,
            "union_raw_rows": rows,
            "fresh_seed_count": len(seeds),
            "effective_simplex_checks": effective,
            "frozen_gates": gates,
        },
        "artifacts": {
            "protocol_sha256": sha256(PROTOCOL),
            "selection_sha256": sha256(SELECTION),
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
