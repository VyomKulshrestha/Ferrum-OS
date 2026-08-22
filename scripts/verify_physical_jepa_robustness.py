#!/usr/bin/env python3
"""Verify the committed physical-JEPA robustness report byte-for-byte."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALUATOR = ROOT / "scripts" / "evaluate_physical_jepa_robustness.py"
REPORT = ROOT / "docs" / "research" / "physical_jepa_robustness.json"
ARTIFACT = (
    ROOT
    / "docs"
    / "research"
    / "artifacts"
    / "physical-jepa-stress-v3"
    / "incident-v1-baseline.bin"
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def main():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    require(report["passed"], "registered robustness gates pass")
    require(
        not report["validated_for_gating"]
        and not report["checkpoint_selected_by_this_suite"],
        "stress evaluation cannot promote or select the physical model",
    )
    require(
        report["context_counterfactuals"]["pairs"] == 256
        and report["context_counterfactuals"]["directional_accuracy"] >= 0.95,
        "context counterfactual direction is evaluated on 256 paired states",
    )
    require(
        report["out_of_distribution"]["rows"] == 512
        and report["out_of_distribution"]["rules_plus_jepa"]["fn"] > 0,
        "OOD stress retains observed failures instead of hiding them",
    )
    require(
        report["calibration"]["brier_score"] >= 0
        and report["calibration"]["expected_calibration_error"] >= 0,
        "threshold-score calibration diagnostics are recorded",
    )
    require(
        [point["episodes"] for point in report["data_scaling"]["points"]]
        == [250, 500, 1000, 1750]
        and report["data_scaling"]["selection_split_only"]
        and not report["data_scaling"]["test_split_used"],
        "fixed-capacity data scaling is fit without opening the test split",
    )
    require(
        report["matched_autoencoder"]["latent"] == 64
        and report["matched_autoencoder"]["hidden"] == 128
        and not report["matched_autoencoder"]["latent_target_prediction_loss"]
        and set(report["matched_autoencoder"]["test_rollout"])
        == {"h1", "h2", "h3", "h4", "h5"},
        "matched autoencoder baseline reports H=1 through H=5 without JEPA target loss",
    )
    with tempfile.TemporaryDirectory(prefix="ferrum-physical-robustness-") as temp:
        output = Path(temp) / "report.json"
        subprocess.run(
            [
                sys.executable,
                str(EVALUATOR),
                "--artifact",
                str(ARTIFACT),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        require(
            output.read_bytes() == REPORT.read_bytes(),
            "robustness report reproduces byte-for-byte",
        )
    print("\nPhysical JEPA robustness verification passed.")


if __name__ == "__main__":
    main()
