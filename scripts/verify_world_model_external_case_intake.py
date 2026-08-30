#!/usr/bin/env python3
"""Independently verify the external case and physical-data intake record."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/world_model_external_case_intake_protocol_v1.json"
DEFAULT_RESULT = ROOT / "docs/research/world_model_external_case_intake_result_v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/world_model_external_case_intake_verification_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    result = json.loads(args.result.read_text(encoding="utf-8"))
    registered = next(item for item in protocol["sources"] if item["source_id"] == "nvidia-anchor-lab")
    files = result["sources"]["physical"]["files"]
    file_checks = []
    for expected, recorded in zip(registered["selected_files"], files):
        local = ROOT / recorded["local_path"]
        file_checks.append(
            expected == recorded["source_path"]
            and local.is_file()
            and sha256(local) == recorded["sha256"]
            and local.stat().st_size == recorded["bytes"]
            and recorded["rows"] > 0
            and recorded["unique_timestamps"] > 1
            and recorded["nonfinite_values"] == 0
        )
    artifact = ROOT / result["artifact"]["path"]
    checks = {
        "protocol_identity": result["protocol_id"] == protocol["protocol_id"]
        and result["protocol_sha256"] == sha256(PROTOCOL),
        "registered_revision": result["sources"]["physical"]["revision"] == registered["revision"],
        "registered_files": len(files) == len(file_checks) == 6 and all(file_checks),
        "external_heldout_cases": sum("heldout" in item["source_path"] for item in files) == 3,
        "semantic_boundary": result["physical_compatibility"]["direct_physical_jepa_v5_replay_valid"] is False,
        "zero_model_inference": result["authority"]["model_inference_calls"] == 0,
        "actuator_disabled": result["authority"]["actuator_delivery_attempts"] == 0
        and result["authority"]["actuator_deliveries"] == 0
        and result["authority"]["physical_hardware_connected"] is False,
        "artifact_unchanged": sha256(artifact)
        == result["artifact"]["sha256_before"]
        == result["artifact"]["sha256_after"]
        and result["artifact"]["unchanged"] is True,
        "result_gates": result["acceptance_gates_passed"] is True and all(result["checks"].values()),
        "no_promotion": result["promotion_eligible"] is False,
    }
    verification = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "result": {"path": str(args.result.resolve().relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(args.result)},
        "checks": checks,
        "verification_passed": all(checks.values()),
        "promotion_eligible": False,
        "claim_boundary": protocol["claim_boundary"],
    }
    args.output.write_text(json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "verification_passed": verification["verification_passed"]}, indent=2))
    return 0 if verification["verification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
