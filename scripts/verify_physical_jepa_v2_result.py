#!/usr/bin/env python3
"""Verify that the failed v2 sweep is retained without accidental promotion."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "docs" / "research" / "physical_jepa_v2_result.json"
PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_v2_protocol.json"
DEPLOYED = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS\t{message}")


def main() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    require(sha256(PROTOCOL) == result["protocol_sha256"], "result binds the pre-registered protocol")
    require(result["selected_candidate"]["training_transitions"] == 80_000, "selected candidate used 80,000 training transitions")
    require(result["generated_incident_dataset"]["transitions"] == 37_440, "generated incident dataset records 37,440 transitions")
    require(result["relative_change"]["original_h3_error"] < -0.20, "candidate improved original H=3 error by more than twenty percent")
    require(result["relative_change"]["incident_h3_error"] < -0.20, "candidate improved incident H=3 error by more than twenty percent")
    require(-0.05 < result["relative_change"]["ood_one_step_error"] < 0.0, "candidate improved OOD error but missed the five-percent gate")
    require(result["promotion"]["passed"] is False, "failed frozen gate prevents promotion")
    require(result["decision"] == "rejected_without_runtime_or_artifact_change", "result records a rejected checkpoint")
    require(sha256(DEPLOYED) == "b1900179c91a80c6933272c41787fa16e72d39cbb815edbe1a82fc4dac7a5800", "deployed artifact remains unchanged")
    print("\nPhysical-JEPA v2 rejection evidence verified: 9/9 checks.")


if __name__ == "__main__":
    main()
