#!/usr/bin/env python3
"""Verify the staged physical qualification contract and runtime calibration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "research"
QUALIFICATION_PROTOCOL = RESEARCH / "physical_deployment_qualification_protocol_v1.json"
QUALIFICATION_RESULT = RESEARCH / "physical_deployment_qualification_evaluation_v1.json"
CALIBRATION_PROTOCOL = RESEARCH / "physical_jepa_runtime_calibration_v4_protocol.json"
CALIBRATION_RESULT = RESEARCH / "physical_jepa_runtime_calibration_v4.json"
BASELINE_ARTIFACT = RESEARCH / "artifacts" / "physical-jepa-v5" / "baseline_v3.bin"
RUNTIME_ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
QUALIFICATION_SOURCE = (
    ROOT / "userland" / "physical-runtime" / "src" / "qualification.rs"
)
RUNTIME_SOURCE = ROOT / "userland" / "physical-runtime" / "src" / "runtime.rs"
MODEL_SOURCE = ROOT / "userland" / "physical-runtime" / "src" / "model.rs"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def main() -> None:
    protocol = load(QUALIFICATION_PROTOCOL)
    result = load(QUALIFICATION_RESULT)
    calibration = load(CALIBRATION_RESULT)
    qualification_source = QUALIFICATION_SOURCE.read_text(encoding="utf-8")
    runtime_source = RUNTIME_SOURCE.read_text(encoding="utf-8")
    model_source = MODEL_SOURCE.read_text(encoding="utf-8")

    require(
        protocol["protocol_id"] == "ferrumos-physical-deployment-qualification-v1"
        and len(protocol["stages"]) == 4,
        "four progressive evidence stages are machine-readable",
    )
    statuses = {stage["id"]: stage["current_status"] for stage in protocol["stages"]}
    require(
        statuses["software_simulation"] == "software_evidence_available"
        and all(
            statuses[stage] == "external_evidence_required"
            for stage in (
                "hardware_in_loop_actuator_disabled",
                "supervised_low_energy_trial",
                "bounded_live_operation",
            )
        ),
        "hardware, robot-trial, and market stages remain explicitly unresolved",
    )
    require(
        len(protocol["primary_sources"]) >= 12
        and all(
            source["url"].startswith("https://")
            for source in protocol["primary_sources"]
        ),
        "primary standards, official guidance, and peer-reviewed methods are recorded",
    )
    require(
        all(
            stage["rust_stage"] in qualification_source for stage in protocol["stages"]
        ),
        "Rust stage evaluator implements every protocol stage",
    )
    for condition in protocol["condition_definitions"]:
        rust_name = "".join(part.title() for part in condition.split("_"))
        require(rust_name in qualification_source, f"Rust evaluator covers {condition}")

    require(
        "if session_mode == SessionMode::Live" in runtime_source
        and "Err(RuntimeError::DeploymentUnqualified)" in runtime_source
        and "SessionMode::Live, DriverExecutionMode::Physical" not in runtime_source,
        "unqualified live delivery is structurally closed before driver submission",
    )
    require(
        result["protocol_sha256"] == sha256(QUALIFICATION_PROTOCOL)
        and result["artifact_sha256"] == sha256(BASELINE_ARTIFACT)
        and result["selection_enabled"] is False,
        "historical boundary challenge remains bound to its registered protocol and archived v3 artifact",
    )
    require(
        result["rows"] == 12_288
        and len(result["case_counts"]) == 12
        and all(count == 1_024 for count in result["case_counts"].values()),
        "systematic challenge balances 12 boundary families across 12,288 rows",
    )
    require(
        result["passed"]
        and all(result["gates"].values())
        and result["rules_plus_jepa"]["fn"] < result["rules_only"]["fn"],
        "frozen challenge passes and learned caution reduces simulator false negatives",
    )

    require(
        calibration["protocol_sha256"] == sha256(CALIBRATION_PROTOCOL)
        and calibration["artifact_sha256"] == sha256(RUNTIME_ARTIFACT)
        and calibration["test_metrics_used_for_selection"] is False,
        "v5 runtime calibration is artifact-bound and keeps validation separate from its single test open",
    )
    require(
        calibration["selected_clearance_threshold"] == 0.2
        and calibration["promotion"]["passed"]
        and all(calibration["promotion"]["gates"].values()),
        "validation selected the 0.20 clearance margin and every frozen test gate passes",
    )
    require(
        calibration["test"]["fn"] == 4
        and calibration["test"]["false_positive_rate"] < 0.1,
        "unseen calibration test records 4 false negatives with bounded false positives",
    )
    require(
        "PHYSICAL_CLEARANCE_CAUTION_THRESHOLD: f32 = 0.20" in model_source
        and "next[2] < PHYSICAL_CLEARANCE_CAUTION_THRESHOLD" in model_source,
        "runtime uses the validation-selected monotonic caution threshold",
    )
    require(
        protocol["authority_boundary"]["learned_model"]
        == "predict_and_add_caution_only"
        and protocol["authority_boundary"]["deterministic_supervisor"]
        == "sole_permit_authority",
        "qualification work does not transfer permit authority to the JEPA",
    )
    print("\nPhysical deployment qualification verification passed.")


if __name__ == "__main__":
    main()
