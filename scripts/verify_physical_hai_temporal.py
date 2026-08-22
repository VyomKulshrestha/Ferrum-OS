#!/usr/bin/env python3
"""Replay the selected HAI temporal artifact without opening final test2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import physical_hai_data as hai
import train_physical_hai_temporal as temporal


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "docs" / "research" / "physical_hai_v1_temporal_selection.json"
DEFAULT_ARTIFACT = (
    ROOT
    / "docs"
    / "research"
    / "artifacts"
    / "physical-hai-v1"
    / "selected_temporal_model.npz"
)


def close(actual: float, expected: float, tolerance: float = 1e-6) -> None:
    if not np.isclose(actual, expected, rtol=tolerance, atol=tolerance):
        raise AssertionError(f"metric mismatch: actual={actual} expected={expected}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=hai.DEFAULT_CACHE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args()
    temporal.require_sealed(args.cache)

    report = json.loads(args.report.read_text(encoding="utf-8"))
    if not report["all_validation_gates_pass"] or report["final_test_opened"]:
        raise AssertionError("selection report is not an eligible sealed-test result")
    if report["amendment_sha256"] != temporal.sha256(temporal.AMENDMENT):
        raise AssertionError("amendment hash mismatch")
    if report["selected_artifact_sha256"] != temporal.sha256(args.artifact):
        raise AssertionError("artifact hash mismatch")

    archive = np.load(args.artifact, allow_pickle=False)
    metadata = json.loads(str(archive["metadata"]))
    if metadata["schema"] != "FERRUM_HAI_TEMPORAL_V1":
        raise AssertionError("unexpected artifact schema")
    if metadata["signal_model"]["name"] != report["selected_model"]:
        raise AssertionError("selected model mismatch")
    if "advisory diagnostic only" not in metadata["authority"]:
        raise AssertionError("artifact authority boundary is missing")

    columns = tuple(metadata["signal_columns"])
    calibration = temporal.read_signals(args.cache / temporal.CALIBRATION_NAME, columns)
    validation = temporal.read_signals(args.cache / temporal.VALIDATION_NAME, columns)
    model = {
        "name": metadata["signal_model"]["name"],
        "kind": metadata["signal_model"]["kind"],
        "coefficients": archive["signal_coefficients"],
    }
    center = archive["signal_center"]
    scale = archive["signal_scale"]
    calibration_residual = temporal.signal_residuals(model, calibration, center, scale)
    validation_residual = temporal.signal_residuals(model, validation, center, scale)
    residual_median = archive["residual_median"]
    residual_mad = archive["residual_mad"]
    calibration_standardized = (
        np.abs(calibration_residual - residual_median) / residual_mad
    )
    validation_standardized = (
        np.abs(validation_residual - residual_median) / residual_mad
    )
    score = metadata["score"]
    calibration_scores = temporal.aggregate_residuals(
        calibration_standardized, score["top_k"], score["ewma_span_seconds"]
    )
    validation_scores = temporal.aggregate_residuals(
        validation_standardized, score["top_k"], score["ewma_span_seconds"]
    )
    labels = pd.read_csv(args.cache / temporal.VALIDATION_LABEL_NAME)["label"].to_numpy(
        dtype=np.int8
    )[6:]
    calibration_metrics = temporal.detection_metrics(
        calibration_scores,
        np.zeros(len(calibration_scores), dtype=np.int8),
        score["threshold"],
        len(calibration_scores) / 3600.0,
    )
    validation_metrics = temporal.detection_metrics(
        validation_scores,
        labels,
        score["threshold"],
        len(validation_scores) / 3600.0,
    )
    expected = report["selected_score"]["validation_detection"]
    close(validation_metrics["balanced_accuracy"], expected["balanced_accuracy"])
    close(
        validation_metrics["false_alerts_per_hour"], expected["false_alerts_per_hour"]
    )
    if validation_metrics["detected_attack_ids"] != expected["detected_attack_ids"]:
        raise AssertionError("detected attack-window identities do not replay")
    if calibration_metrics["false_alerts_per_hour"] > 2.0:
        raise AssertionError(
            "normal-calibration event rate exceeds the registered gate"
        )

    protocol = hai.load_protocol()
    fit_paths = [
        args.cache / item["name"] for item in protocol["dataset"]["train_files"]
    ]
    projection = hai.fit_projection(fit_paths)
    state_validation = hai.project_trace(
        args.cache / temporal.VALIDATION_NAME,
        projection,
        args.cache / temporal.VALIDATION_LABEL_NAME,
    )
    state_model = {
        "coefficients": archive["state_coefficients"],
        "window": metadata["state_window_seconds"],
    }
    replayed_transition = temporal.transition_evaluation(
        state_validation, "temporal_ridge", state_model=state_model
    )
    expected_transition = report["masked_transition"]["temporal_ridge"]
    close(
        replayed_transition["geometric_h1_h3_h5_error"],
        expected_transition["geometric_h1_h3_h5_error"],
    )
    if not np.isfinite(
        np.concatenate(
            [
                center,
                scale,
                residual_median,
                residual_mad,
                archive["signal_coefficients"].ravel(),
                archive["state_coefficients"].ravel(),
            ]
        )
    ).all():
        raise AssertionError("artifact contains non-finite values")

    print(
        "PASS HAI temporal selection: "
        f"{validation_metrics['detected_attack_windows']}/14 windows, "
        f"balanced_accuracy={validation_metrics['balanced_accuracy']:.4f}, "
        f"false_alerts_per_hour={validation_metrics['false_alerts_per_hour']:.3f}, "
        "test2 sealed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
