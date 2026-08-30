#!/usr/bin/env python3
"""Verify the Physical JEPA v5 multi-embodiment 3D stress result."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/physical_jepa_multi_embodiment_3d_protocol_v1.json"
DEFAULT_RESULT = ROOT / "docs/research/physical_jepa_multi_embodiment_3d_result_v1.json"
DEFAULT_OUTPUT = (
    ROOT / "docs/research/physical_jepa_multi_embodiment_3d_verification_v1.json"
)


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
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    protocol = load(PROTOCOL)
    result = load(args.result)
    cases = result["cases"]
    unshielded = sum(item["unshielded_contact"] for item in cases)
    shielded = sum(item["shielded_contact"] for item in cases)
    interventions = sum(item["union_block"] for item in cases)
    completions = sum(item["task_completed"] for item in cases)
    learned_only = sum(
        item["learned_block"] and not item["rule_block"] for item in cases
    )
    learned_avoided = sum(
        item["learned_block"]
        and not item["rule_block"]
        and item["unshielded_contact"]
        and not item["shielded_contact"]
        for item in cases
    )
    recovery_cases = [item for item in cases if item["unshielded_contact"]]
    recovered = sum(item["recovery_success"] is True for item in recovery_cases)
    artifact = ROOT / protocol["artifact"]["path"]
    checks = {
        "protocol": result["protocol_id"] == protocol["protocol_id"]
        and result["protocol_sha256"] == sha256(PROTOCOL),
        "artifact": sha256(artifact)
        == protocol["artifact"]["sha256"]
        == result["artifact"]["sha256_before"]
        == result["artifact"]["sha256_after"],
        "case_count": len(cases) == protocol["expected_cases"],
        "cell_counts": all(
            sum(
                case["embodiment"] == embodiment["name"]
                and case["obstacle"] == obstacle["name"]
                for case in cases
            )
            == protocol["cases_per_embodiment_obstacle_pair"]
            for embodiment in protocol["embodiments"]
            for obstacle in protocol["obstacles"]
        ),
        "union_monotone": all(
            item["union_block"] == (item["rule_block"] or item["learned_block"])
            for item in cases
        ),
        "summary_recomputes": result["summary"]["unshielded_contacts"] == unshielded
        and result["summary"]["shielded_contacts"] == shielded
        and result["summary"]["interventions"] == interventions
        and result["summary"]["task_completions"] == completions
        and result["summary"]["learned_only_interventions"] == learned_only
        and result["summary"]["learned_only_contacts_avoided"] == learned_avoided
        and result["summary"]["contact_recovery_cases"] == len(recovery_cases)
        and result["summary"]["contact_recovery_successes"] == recovered,
        "finite": finite(result),
        "simulated": result["backend"]["evidence_class"]
        == "researcher-designed local software-physics stress test"
        and all(item["observation_evidence_class"] == "simulated" for item in cases),
        "zero_physical_actuator_authority": result["authority"][
            "physical_actuator_attempts"
        ]
        == 0
        and result["authority"]["physical_actuator_deliveries"] == 0,
        "no_promotion": result["promotion_eligible"] is False,
        "result_gates": result["acceptance_gates_passed"] is True
        and all(result["checks"].values()),
        "claim_boundary": "not blinded" in result["claim_boundary"]
        and "not" in result["claim_boundary"],
    }
    verification = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "result": {
            "path": str(args.result.resolve().relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256(args.result),
        },
        "checks": checks,
        "verification_passed": all(checks.values()),
        "promotion_eligible": False,
        "claim_boundary": protocol["claim_boundary"],
    }
    args.output.write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "verification_passed": verification["verification_passed"],
            },
            indent=2,
        )
    )
    return 0 if verification["verification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
