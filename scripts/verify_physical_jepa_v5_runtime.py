#!/usr/bin/env python3
"""Verify the promoted v5 PJE1 bytes, calibration, and authority boundary."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "research"
ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
ARCHIVED_BASELINE = RESEARCH / "artifacts" / "physical-jepa-v5" / "baseline_v3.bin"
SELECTION = RESEARCH / "physical_jepa_v5_selection.json"
FINAL = RESEARCH / "physical_jepa_v5_final_test.json"
CALIBRATION = RESEARCH / "physical_jepa_runtime_calibration_v4.json"
SERVICE = ROOT / "userland" / "heliox-daemon" / "src" / "physical.rs"
SAFETY = ROOT / "userland" / "physical-runtime" / "src" / "safety.rs"
RUNTIME = ROOT / "userland" / "physical-runtime" / "src" / "runtime.rs"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def main() -> None:
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    final = json.loads(FINAL.read_text(encoding="utf-8"))
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    digest = sha256(ARTIFACT)
    require(digest == selection["selected_artifact_sha256"], "runtime uses selected v5 bytes")
    require(digest == final["candidate_artifact_sha256"], "runtime matches final evidence")
    require(digest == calibration["artifact_sha256"], "runtime matches calibration")
    require(
        sha256(ARCHIVED_BASELINE) == final["baseline_artifact_sha256"],
        "historical v3 baseline remains immutable",
    )
    header = struct.unpack("<4sIIIIIIIIffI", ARTIFACT.read_bytes()[:48])
    require(header[:5] == (b"PJE1", 1, 16, 7, 3), "runtime artifact schema is PJE1")
    require(header[5:9] == (128, 256, 187200, 10), "runtime dimensions are bounded")
    require(header[-1] == 0, "serialized model cannot self-promote")
    require(header[9] < header[10], "recorded H3 error beats per-action mean")
    require(final["all_model_evidence_gates_pass"], "unseen-family and regression gates pass")
    require(
        final["candidate_to_baseline_rollout_ratios"]["geometric_h1_h3_h5"] < 0.50,
        "unseen-family geometric rollout error is less than half the baseline",
    )
    require(
        calibration["promotion"]["passed"]
        and calibration["selected_clearance_threshold"] == 0.2
        and calibration["test"]["fn"] == 4
        and calibration["test"]["fp"] == 380,
        "fresh checkpoint-bound caution calibration passes",
    )
    service = SERVICE.read_text(encoding="utf-8")
    safety = SAFETY.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")
    require(digest in service, "Heliox status binds the exact v5 digest")
    require(
        "physical-jepa-baseline-anchored-v5" in service
        and "physical-jepa-runtime-clearance-calibration-v4" in service,
        "Heliox reports the selected model and calibration revisions",
    )
    require(
        "SimulationCaution" in runtime
        and "descriptor.mode != SessionMode::Simulation" in runtime
        and "descriptor.model_sha256 != grant.model_sha256" in runtime,
        "learned caution is simulation-only and digest-bound",
    )
    require(
        "decision.verdict = decision.verdict.max(verdict)" in safety
        and "PredictiveShadowOnly" in safety,
        "learned evidence can only increase severity and remains shadow outside simulation",
    )
    print("\nPhysical-JEPA v5 runtime evidence verified.")


if __name__ == "__main__":
    main()
