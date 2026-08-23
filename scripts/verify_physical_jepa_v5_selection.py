#!/usr/bin/env python3
"""Verify the frozen v5 decoder selection before or after final evaluation."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402


PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_v5_protocol.json"
REPORT = ROOT / "docs" / "research" / "physical_jepa_v5_selection.json"
BASELINE = ROOT / "docs" / "research" / "artifacts" / "physical-jepa-v5" / "baseline_v3.bin"
FINAL_REPORT = ROOT / "docs" / "research" / "physical_jepa_v5_final_test.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    require(report["protocol_id"] == protocol["protocol_id"], "protocol ID drift")
    require(report["protocol_sha256"] == sha256(PROTOCOL), "protocol hash drift")
    require(report["baseline_artifact_sha256"] == sha256(BASELINE), "baseline drift")
    require(not report["final_test_opened"], "selection opened final test")
    if FINAL_REPORT.exists():
        final_report = json.loads(FINAL_REPORT.read_text(encoding="utf-8"))
        require(
            final_report["selection_report_sha256"] == sha256(REPORT),
            "post-final selection report drift",
        )
        require(
            final_report["no_retraining_after_final_test_open"],
            "post-final retraining was disclosed",
        )
    accepted = [
        index
        for index, candidate in enumerate(report["candidates"])
        if candidate["selection"]["accepted"]
    ]
    require(accepted == report["accepted_candidate_indices"], "accepted set drift")
    require(len(accepted) == 28, "unexpected accepted-arm count")
    selected_index = report["selected_candidate_index"]
    require(selected_index in accepted, "selected arm was not accepted")
    expected = min(
        accepted,
        key=lambda index: report["candidates"][index]["selection"]["selection_score"],
    )
    require(selected_index == expected, "selection rule drift")
    selected = report["candidates"][selected_index]
    require(all(selected["selection"]["checks"].values()), "selected gate failed")
    require(selected["decoder_ridge_lambda"] == 0.0001, "selected ridge drift")
    require(selected["decoder_blend"] == 1.0, "selected blend drift")
    require(
        all(value < 0.70 for value in selected["selection"]["incident_ratios"].values()),
        "incident validation improvement drifted",
    )
    require(
        selected["incident"]["diagnostics"]["rules_plus_jepa"]["fn"] == 0,
        "incident validation false negatives drifted",
    )
    artifact = ROOT / report["selected_artifact"]
    require(report["selected_artifact_sha256"] == sha256(artifact), "artifact drift")
    baseline = robustness.load_artifact(BASELINE)
    candidate = robustness.load_artifact(artifact)
    for name in (
        "encoder_w",
        "encoder_b",
        "predictor_w1",
        "predictor_b1",
        "predictor_w2",
        "predictor_b2",
    ):
        require(np.array_equal(baseline[name], candidate[name]), f"{name} was not frozen")
    require(
        not np.array_equal(baseline["state_w"], candidate["state_w"])
        and not np.array_equal(baseline["state_b"], candidate["state_b"]),
        "decoder did not change",
    )
    print(
        "PASS physical v5 selection: 28/30 arms accepted; decoder-only candidate "
        f"{report['selected_artifact_sha256'][:12]} remains frozen"
    )


if __name__ == "__main__":
    main()
