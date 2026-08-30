#!/usr/bin/env python3
"""Independently verify the effective tangent-shield Safety-Gymnasium result."""

from __future__ import annotations

import json
import math
from pathlib import Path

from verify_physical_jepa_safety_gymnasium_v10 import (
    ROOT,
    aggregate,
    aggregate_matches,
    gate_status,
    load,
    raw_counts,
    sha256,
)


PROTOCOL = ROOT / "docs/research/physical_jepa_safety_gymnasium_protocol_v12.json"
SELECTION = ROOT / "docs/research/physical_jepa_safety_gymnasium_selection_v12.json"
RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_result_v12.json"
CASES = ROOT / "docs/research/physical_jepa_safety_gymnasium_cases_v12.jsonl"
OUTPUT = ROOT / "docs/research/physical_jepa_safety_gymnasium_verification_v12.json"


def effective_case_checks(path: Path) -> dict:
    interventions = 0
    unchanged_interventions = 0
    learned_only_interventions = 0
    learned_only_dangerous_interventions = 0
    tangent_actions = 0
    tangent_interventions = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            changed = not all(
                math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12)
                for a, b in zip(item["proposed_action"], item["applied_action"])
            )
            intervention = bool(item["intervention"])
            interventions += int(intervention)
            unchanged_interventions += int(intervention and not changed)
            learned_only_interventions += int(
                intervention and item["learned_block"] and not item["rule_block"]
            )
            learned_only_dangerous_interventions += int(
                intervention
                and item["learned_block"]
                and not item["rule_block"]
                and item["dangerous_proposal"]
            )
            tangent_actions += int(item["recovery_phase"] == "tangent")
            tangent_interventions += int(
                intervention and item["recovery_phase"] == "tangent"
            )
    return {
        "interventions": interventions,
        "unchanged_interventions": unchanged_interventions,
        "learned_only_interventions": learned_only_interventions,
        "learned_only_dangerous_interventions": learned_only_dangerous_interventions,
        "tangent_actions": tangent_actions,
        "tangent_interventions": tangent_interventions,
    }


def main() -> None:
    required = (PROTOCOL, SELECTION, RESULT, CASES)
    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing evidence: {missing}")
    protocol = load(PROTOCOL)
    selection = load(SELECTION)
    result = load(RESULT)
    rows, cases, seeds = raw_counts(CASES)
    effective = effective_case_checks(CASES)
    cases["learned_only_interventions"] = effective["learned_only_interventions"]
    cases["learned_only_dangerous_interventions"] = effective[
        "learned_only_dangerous_interventions"
    ]
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
        "every_counted_intervention_changes_action": effective["interventions"]
        == union["interventions"]
        and effective["unchanged_interventions"] == 0
        and effective["tangent_interventions"] == union["interventions"],
        "learned_alerts_have_no_independent_authority": effective["learned_only_interventions"] == 0
        and union["learned_only_interventions"] == 0
        and result["selected_candidate"]["learned_requires_rule_confirmation"] is True,
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
        "schema": "physical-jepa-safety-gymnasium-verification-v12",
        "overall_pass": all(checks.values()),
        "checks": checks,
        "recomputed": {
            "arms": arms,
            "union_raw_counts": cases,
            "union_raw_rows": rows,
            "fresh_seed_count": len(seeds),
            "effective_intervention_checks": effective,
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
