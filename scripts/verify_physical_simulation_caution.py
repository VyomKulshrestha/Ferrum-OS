#!/usr/bin/env python3
"""Verify the evidence and source boundary for simulator-only JEPA caution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
IMPROVEMENT = ROOT / "docs" / "research" / "physical_incident_jepa_improvement.json"
RUNTIME = ROOT / "userland" / "physical-runtime" / "src" / "runtime.rs"
SAFETY = ROOT / "userland" / "physical-runtime" / "src" / "safety.rs"
SERVICE = ROOT / "userland" / "heliox-daemon" / "src" / "physical.rs"
BRIDGE = ROOT / "scripts" / "verify_bridge.mjs"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS\t{message}")


def main() -> None:
    report = json.loads(IMPROVEMENT.read_text(encoding="utf-8"))
    runtime = RUNTIME.read_text(encoding="utf-8")
    safety = SAFETY.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")
    digest = hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()

    candidate = report["candidate_test"]
    held_out = candidate["original_test"]["diagnostics"]
    incident = candidate["incident_test"]["diagnostics"]
    ood = candidate["ood_test"]

    require(digest == report["candidate_artifact_sha256"], "selected checkpoint digest matches the registered candidate")
    require(report["promotion"]["passed"] is True, "pre-registered simulator promotion checks passed")
    require(report["test_metrics_used_for_selection"] is False, "test partitions did not select the checkpoint")
    require(report["validated_for_gating"] is False, "model bytes remain unable to self-promote")
    require(
        held_out["rows"] == 2250
        and held_out["rules_plus_jepa"]["fn"] == 0
        and held_out["rules_plus_jepa"]["fp"] == 16,
        "original held-out union records 2250 rows, 0 FN, and 16 FP",
    )
    require(
        incident["rows"] == 2880
        and incident["rules_plus_jepa"]["fn"] == 1
        and incident["rules_plus_jepa"]["fp"] == 21,
        "source-family-disjoint incident challenge records 2880 rows, 1 FN, and 21 FP",
    )
    require(
        ood["rows"] == 512
        and ood["rules_plus_jepa"]["fn"] == 41
        and ood["rules_plus_jepa"]["fp"] == 4,
        "registered OOD fixture records 512 rows, 41 FN, and 4 FP",
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
    print("\nSimulator-only learned-caution contract verified: 12/12 checks passed.")


if __name__ == "__main__":
    main()
