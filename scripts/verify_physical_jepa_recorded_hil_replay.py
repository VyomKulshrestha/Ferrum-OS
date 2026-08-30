#!/usr/bin/env python3
"""Verify the registered Physical JEPA v5 recorded-HIL sensor replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/physical_jepa_recorded_hil_replay_protocol_v1.json"
DEFAULT_RESULT = ROOT / "docs/research/physical_jepa_recorded_hil_replay_result_v1.json"
DEFAULT_OUTPUT = (
    ROOT / "docs/research/physical_jepa_recorded_hil_replay_verification_v1.json"
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
    artifact = ROOT / protocol["frozen_artifact"]["path"]
    conditions = [item["name"] for item in result["replay"]["conditions"]]
    expected_conditions = [item["name"] for item in protocol["conditions"]]
    input_checks = []
    for registered, recorded in zip(protocol["replay_files"], result["inputs"]):
        data = ROOT / registered["data"]
        labels = ROOT / registered["labels"]
        input_checks.append(
            registered["data"] == recorded["data"]
            and registered["labels"] == recorded["labels"]
            and sha256(data) == registered["data_sha256"] == recorded["data_sha256"]
            and sha256(labels)
            == registered["labels_sha256"]
            == recorded["labels_sha256"]
        )
    checks = {
        "protocol_identity": result["protocol_id"] == protocol["protocol_id"]
        and result["protocol_sha256"] == sha256(PROTOCOL),
        "artifact_identity": sha256(artifact)
        == protocol["frozen_artifact"]["sha256"]
        == result["artifact"]["sha256_before"]
        == result["artifact"]["sha256_after"],
        "artifact_unchanged": result["artifact"]["unchanged"] is True,
        "registered_inputs": len(result["inputs"])
        == len(protocol["replay_files"])
        == len(input_checks)
        == 2
        and all(input_checks),
        "registered_conditions": conditions == expected_conditions,
        "finite": finite(result),
        "actuator_disabled": result["authority"]["mode"]
        == "actuator-disabled sensor replay",
        "zero_delivery_attempts": result["authority"]["actuator_delivery_attempts"]
        == 0,
        "zero_deliveries": result["authority"]["actuator_deliveries"] == 0,
        "no_hardware_authority": result["authority"]["may_actuate_hardware"] is False,
        "no_contact_claim": result["fault_recovery"]["contact_recovery_measured"]
        is False,
        "no_promotion": result["promotion_eligible"] is False,
        "result_gates": result["acceptance_gates_passed"] is True
        and all(result["checks"].values()),
        "claim_boundary": "does not establish" in result["claim_boundary"],
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
        "evidence_class": protocol["evidence_class"],
        "claim_boundary": protocol["interpretation"],
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
