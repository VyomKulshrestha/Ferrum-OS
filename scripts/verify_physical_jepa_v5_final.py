#!/usr/bin/env python3
"""Reproduce and verify the committed v5 final simulator result."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_incident_scenarios as incidents  # noqa: E402
import select_physical_jepa_v5 as v5  # noqa: E402


PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_v5_protocol.json"
SELECTION = ROOT / "docs" / "research" / "physical_jepa_v5_selection.json"
REPORT = ROOT / "docs" / "research" / "physical_jepa_v5_final_test.json"
BASELINE = ROOT / "docs" / "research" / "artifacts" / "physical-jepa-v5" / "baseline_v3.bin"
CATALOG = ROOT / "docs" / "research" / "physical_incident_v5_test_sources.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def close_tree(actual, expected, path="root") -> None:
    if isinstance(expected, dict):
        require(set(actual) == set(expected), f"key drift at {path}")
        for key in expected:
            close_tree(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, float):
        require(np.isclose(actual, expected, rtol=1e-7, atol=1e-8), f"value drift at {path}")
    else:
        require(actual == expected, f"value drift at {path}")


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    artifact = ROOT / selection["selected_artifact"]
    require(report["protocol_id"] == protocol["protocol_id"], "protocol ID drift")
    require(report["protocol_sha256"] == sha256(PROTOCOL), "protocol hash drift")
    require(report["selection_report_sha256"] == sha256(SELECTION), "selection drift")
    require(report["candidate_artifact_sha256"] == sha256(artifact), "artifact drift")
    require(report["baseline_artifact_sha256"] == sha256(BASELINE), "baseline drift")
    require(report["final_test_open_count"] == 1, "final test open count drift")
    require(report["no_retraining_after_final_test_open"], "post-test retraining disclosed")
    require(all(report["final_requirements"].values()), "registered final gate failed")
    require(report["all_model_evidence_gates_pass"], "model evidence did not pass")
    require(report["h3_paired_bootstrap"]["interval_excludes_zero"], "bootstrap failed")
    require(
        report["candidate_to_baseline_rollout_ratios"]["geometric_h1_h3_h5"]
        < 0.50,
        "v5 final improvement drifted",
    )

    rows, metadata = incidents.generate_partition("test", 320, 8, 20260829, CATALOG)
    prepared = v5.prepare_evaluation(rows)
    baseline = robustness.load_artifact(BASELINE)
    candidate = robustness.load_artifact(artifact)
    close_tree(
        v5.batched_evaluation(prepared, baseline),
        report["baseline_final"],
        "baseline_final",
    )
    close_tree(
        v5.batched_evaluation(prepared, candidate),
        report["candidate_final"],
        "candidate_final",
    )
    require(incidents.summarize(rows, metadata) == report["final_evidence"], "evidence drift")
    require(
        report["final_catalog_resolved_sha256"] == incidents.catalog_sha256(CATALOG),
        "catalog drift",
    )
    print(
        "PASS physical v5 final: 20,480 transitions, H1/H3/H5 geometric ratio "
        f"{report['candidate_to_baseline_rollout_ratios']['geometric_h1_h3_h5']:.4f}, "
        "FN 2->0"
    )


if __name__ == "__main__":
    main()
