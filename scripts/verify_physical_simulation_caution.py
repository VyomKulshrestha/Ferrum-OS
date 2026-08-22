#!/usr/bin/env python3
"""Verify the evidence and source boundary for simulator-only JEPA caution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
EVALUATION = ROOT / "docs" / "research" / "physical_jepa_v3_evaluation.json"
SELECTION = ROOT / "docs" / "research" / "physical_jepa_v3_selection.json"
RUNTIME = ROOT / "userland" / "physical-runtime" / "src" / "runtime.rs"
SAFETY = ROOT / "userland" / "physical-runtime" / "src" / "safety.rs"
SERVICE = ROOT / "userland" / "heliox-daemon" / "src" / "physical.rs"
BRIDGE = ROOT / "scripts" / "verify_bridge.mjs"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS\t{message}")


def main() -> None:
    report = json.loads(EVALUATION.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    runtime = RUNTIME.read_text(encoding="utf-8")
    safety = SAFETY.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")
    digest = hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()

    tests = report["test_metrics"]
    held_out = tests["original_test"]["diagnostics"]
    incident = tests["incident_test"]["diagnostics"]
    stress = tests["stress_test"]["diagnostics"]
    ood = tests["ood_test"]

    require(
        digest == report["artifact_sha256"],
        "selected checkpoint digest matches the registered candidate",
    )
    require(
        report["promotion"]["passed"] is True,
        "pre-registered simulator promotion checks passed",
    )
    require(
        selection["test_metrics_used_for_selection"] is False,
        "test partitions did not select the checkpoint",
    )
    require(
        report["validated_for_gating"] is False,
        "model bytes remain unable to self-promote",
    )
    require(
        held_out["rows"] == 14400
        and held_out["rules_plus_jepa"]["fn"] == 8
        and held_out["rules_plus_jepa"]["fp"] == 133,
        "ordinary held-out union records 14400 rows, 8 FN, and 133 FP",
    )
    require(
        incident["rows"] == 7680
        and incident["rules_plus_jepa"]["fn"] == 1
        and incident["rules_plus_jepa"]["fp"] == 56,
        "source-family-disjoint incident challenge records 7680 rows, 1 FN, and 56 FP",
    )
    require(
        stress["rows"] == 16000
        and stress["rules_plus_jepa"]["fn"] == 1
        and stress["rules_plus_jepa"]["fp"] == 101,
        "valid edge-state stress test records 16000 rows, 1 FN, and 101 FP",
    )
    require(
        ood["rows"] == 4096
        and ood["invalid_observations_rejected"] == 682
        and ood["rules_plus_jepa"]["fn"] == 0
        and ood["rules_plus_jepa"]["fp"] == 18,
        "registered OOD fixture records 4096 rows, 682 rejects, 0 FN, and 18 FP",
    )
    require(
        "descriptor.mode != SessionMode::Simulation" in runtime
        and "descriptor.model_sha256 != grant.model_sha256" in runtime,
        "runtime binds learned caution to a simulation session and exact model digest",
    )
    require(
        "SessionMode::HardwareInLoopActuatorDisabled" in runtime
        and "SessionMode::Live" in runtime
        and "SimulationCautionUnavailable" in runtime,
        "HIL and live sessions are covered by fail-closed promotion tests",
    )
    require(
        "decision.verdict = decision.verdict.max(verdict)" in safety
        and "caller_supplied_gating_flag_fails_closed" in safety,
        "learned decisions are monotonic and a caller-supplied promotion flag fails closed",
    )
    require(
        "live_learned_gate" in service
        and "shadow_only" in service
        and "permit_authority" in service
        and "deterministic_supervisor" in service,
        "boot service reports the live and permit authority boundary",
    )
    require(
        "rules_plus_jepa_blocked" in bridge
        and "rejected_command_received_permit" in bridge
        and "bounded_safe_command_delivered" in bridge,
        "QEMU verifier checks incremental blocking, no rejected permit, and a safe control",
    )
    print("\nSimulator-only learned-caution contract verified: 13/13 checks passed.")


if __name__ == "__main__":
    main()
