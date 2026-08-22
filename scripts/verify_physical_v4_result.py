#!/usr/bin/env python3
"""Verify the preserved negative v4 simulator result and non-promotion."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import physical_incident_scenarios as incidents  # noqa: E402

REPORT = ROOT / "docs" / "research" / "physical_jepa_v4_evaluation.json"
PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_v4_protocol.json"
CATALOG = ROOT / "docs" / "research" / "physical_incident_sources_v2.json"
DEPLOYED = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    require(report["protocol_id"] == "physical-jepa-real-evidence-v4", "protocol drift")
    require(report["candidate_config_sha256"] == sha256(PROTOCOL), "protocol hash drift")
    require(report["catalog"] == "docs/research/physical_incident_sources_v2.json", "catalog drift")
    require(
        report["catalog_sha256"] == incidents.catalog_sha256(CATALOG),
        "catalog hash drift",
    )
    require(report["current_artifact_sha256"] == sha256(DEPLOYED), "baseline changed")
    require(not report["test_metrics_used_for_selection"], "test influenced selection")
    require(not report["validated_for_gating"], "negative candidate marked for gating")
    require(not report["selected_candidate"]["selection"]["accepted"], "selection changed")
    require(not report["promotion"]["passed"], "negative result changed")
    require(
        all(not candidate["selection"]["accepted"] for candidate in report["candidates"]),
        "a validation-accepted candidate was omitted",
    )
    require(report["incident_test"]["episodes"] == 2560, "incident test size drift")
    require(report["incident_test"]["transitions"] == 20480, "incident rows drift")
    require(
        report["current_test"]["incident_test"]["diagnostics"]["rules_plus_jepa"]["fn"]
        == 2,
        "baseline incident false negatives drifted",
    )
    require(
        report["candidate_test"]["incident_test"]["diagnostics"]["rules_plus_jepa"]["fn"]
        == 6,
        "candidate incident false negatives drifted",
    )
    dataset = ROOT / report["dataset"]
    if dataset.exists():
        require(report["dataset_sha256"] == sha256(dataset), "cached dataset hash drift")
    print(
        "PASS physical v4 negative result: no candidate accepted; "
        "deployed v3 artifact retained"
    )


if __name__ == "__main__":
    main()
