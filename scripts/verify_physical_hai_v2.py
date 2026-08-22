#!/usr/bin/env python3
"""Verify the committed HAI v2 target artifact while final tests stay sealed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import fetch_physical_hai_v2 as fetch_v2
import train_physical_hai_v2 as v2


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "docs" / "research" / "physical_hai_v2_selection.json"
DEFAULT_ARTIFACT = (
    ROOT / "docs" / "research" / "artifacts" / "physical-hai-v2" / "selected_model.npz"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args()
    protocol = json.loads(v2.PROTOCOL.read_text(encoding="utf-8"))
    v2.require_target_final_sealed(protocol, v2.TARGET_CACHE)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if not report["all_selection_gates_pass"] or report["final_test_opened"]:
        raise AssertionError("v2 selection is not an eligible sealed-final result")
    if report["amendment_sha256"] != v2.sha256(v2.AMENDMENT):
        raise AssertionError("v2 amendment hash mismatch")
    if report["selected_artifact_sha256"] != v2.sha256(args.artifact):
        raise AssertionError("v2 artifact hash mismatch")

    for item in protocol["target_domain_normal_files"]:
        valid, reason = fetch_v2.verify(v2.TARGET_CACHE / item["name"], item)
        if not valid:
            raise AssertionError(f"unverified normal file {item['name']}: {reason}")
        labels = pd.read_csv(v2.TARGET_CACHE / item["name"], usecols=v2.LABEL_COLUMNS)
        if int(labels.to_numpy(dtype=np.int64).sum()) != 0:
            raise AssertionError(
                f"normal fit file contains attack labels: {item['name']}"
            )

    archive = np.load(args.artifact, allow_pickle=False)
    metadata = json.loads(str(archive["metadata"]))
    if metadata["schema"] != "FERRUM_HAI_SITE_ADAPTED_V2":
        raise AssertionError("unexpected v2 artifact schema")
    if metadata["model"]["name"] != report["selected"]["model"]["name"]:
        raise AssertionError("selected model mismatch")
    if metadata["model"]["kind"] != "ridge":
        raise AssertionError("selected v2 verifier expects the committed ridge arm")
    if "advisory diagnostic only" not in metadata["authority"]:
        raise AssertionError("artifact authority boundary is missing")

    columns = tuple(metadata["target_signal_columns"])
    raw = v2.read_values(v2.TARGET_CACHE / v2.TARGET_CALIBRATION, columns)
    normalized = v2.normalize(raw, archive["target_center"], archive["target_scale"])
    model = {
        **metadata["model"],
        "coefficients": archive["target_model.coefficients"],
    }
    prediction = v2.prediction_residual(model, normalized)
    prediction_z = v2.standardized(
        prediction,
        archive["prediction_residual_median"],
        archive["prediction_residual_mad"],
    )
    window = model["context_seconds"]
    reconstruction = v2.reconstruction_residual(
        normalized[window + 1 :],
        archive["pca_mean"],
        archive["pca_components"],
        archive["pca_components"].shape[1],
    )
    reconstruction_z = v2.standardized(
        reconstruction,
        archive["reconstruction_residual_median"],
        archive["reconstruction_residual_mad"],
    )
    score = metadata["score"]
    combined = (
        score["prediction_weight"] * prediction_z
        + (1.0 - score["prediction_weight"]) * reconstruction_z
    )
    top_k = score["top_k"]
    row_score = np.mean(np.partition(combined, -top_k, axis=1)[:, -top_k:], axis=1)
    smoothed = v2.ewma_fast(row_score, score["ewma_span_seconds"])
    false_rate = v2.false_alert_rate(smoothed, score["numeric_threshold"])
    expected_rate = report["selected"]["target_normal_false_alerts_per_hour"]
    if not np.isclose(false_rate, expected_rate, rtol=1e-7, atol=1e-7):
        raise AssertionError(
            f"target false-alert rate mismatch: {false_rate} != {expected_rate}"
        )
    if false_rate > 2.0:
        raise AssertionError("target normal false-alert ceiling is not satisfied")
    if not all(report["selected"]["requirements"].values()):
        raise AssertionError("selected source requirements are not all satisfied")
    if not np.isfinite(
        np.concatenate(
            [
                archive["target_center"],
                archive["target_scale"],
                archive["target_model.coefficients"].ravel(),
                archive["prediction_residual_median"],
                archive["prediction_residual_mad"],
                archive["reconstruction_residual_median"],
                archive["reconstruction_residual_mad"],
            ]
        )
    ).all():
        raise AssertionError("v2 artifact contains non-finite values")
    detection = report["selected"]["source_detection"]
    print(
        "PASS HAI v2 selection: "
        f"source={detection['detected_attack_windows']}/52 windows, "
        f"balanced_accuracy={detection['balanced_accuracy']:.4f}, "
        f"target_normal_false_alerts_per_hour={false_rate:.3f}, finals sealed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
