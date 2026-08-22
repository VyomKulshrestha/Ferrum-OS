#!/usr/bin/env python3
"""Evaluate the committed HAI model once on the registered final split."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import fetch_physical_hai as fetch
import physical_hai_data as hai
import train_physical_hai_temporal as temporal


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "docs" / "research" / "physical_hai_v1_final_test.json"
SELECTION_REPORT = (
    ROOT / "docs" / "research" / "physical_hai_v1_temporal_selection.json"
)
ARTIFACT = (
    ROOT
    / "docs"
    / "research"
    / "artifacts"
    / "physical-hai-v1"
    / "selected_temporal_model.npz"
)
FINAL_SIGNAL = "hai-test2.csv"
FINAL_LABEL = "label-test2.csv"
FINAL_ATTACK_IDS = tuple(f"A{200 + index}" for index in range(1, 39))
SELECTION_COMMIT = "01f797a"


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> dict:
    if total <= 0:
        return {"lower": 0.0, "upper": 1.0, "confidence": 0.95}
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    radius = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return {
        "lower": max(0.0, center - radius),
        "upper": min(1.0, center + radius),
        "confidence": 0.95,
    }


def verified_final_items(cache: Path, protocol: dict) -> list[dict]:
    items = protocol["dataset"]["final_test_files"]
    for item in items:
        valid, reason = fetch.verify(cache / item["name"], item)
        if not valid:
            raise RuntimeError(f"final file {item['name']} is not verified: {reason}")
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=hai.DEFAULT_CACHE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    protocol = hai.load_protocol()
    final_items = verified_final_items(args.cache, protocol)
    selection = json.loads(SELECTION_REPORT.read_text(encoding="utf-8"))
    if not selection["all_validation_gates_pass"] or selection["final_test_opened"]:
        raise AssertionError(
            "committed selection is not eligible for the one final evaluation"
        )
    if selection["selected_artifact_sha256"] != temporal.sha256(ARTIFACT):
        raise AssertionError("selected artifact changed after model selection")

    archive = np.load(ARTIFACT, allow_pickle=False)
    metadata = json.loads(str(archive["metadata"]))
    if metadata["schema"] != "FERRUM_HAI_TEMPORAL_V1":
        raise AssertionError("unexpected artifact schema")
    if metadata["signal_model"]["name"] != selection["selected_model"]:
        raise AssertionError("artifact and selection report disagree")
    if metadata["signal_model"]["kind"] != "ridge":
        raise AssertionError(
            "final evaluator only accepts the committed ridge artifact"
        )

    columns = tuple(metadata["signal_columns"])
    final_signals = temporal.read_signals(args.cache / FINAL_SIGNAL, columns)
    label_frame = pd.read_csv(args.cache / FINAL_LABEL)
    raw_labels = label_frame["label"].to_numpy(dtype=np.int8)
    label_timestamp = pd.to_datetime(label_frame["timestamp"], errors="raise").to_numpy(
        dtype="datetime64[m]"
    )
    signal_minute = final_signals.timestamp.astype("datetime64[m]")
    if len(label_timestamp) != len(signal_minute) or not np.array_equal(
        label_timestamp, signal_minute
    ):
        raise AssertionError(
            "official minute-resolution test2 labels do not align by row and minute"
        )
    labels = raw_labels[6:]
    if len(labels) != len(final_signals.values) - 6:
        raise AssertionError("final labels do not align with the five-second context")
    if len(temporal.attack_windows(labels)) != 38:
        raise AssertionError("registered final split must contain 38 attack windows")

    model = {
        "name": metadata["signal_model"]["name"],
        "kind": "ridge",
        "coefficients": archive["signal_coefficients"],
    }
    residual = temporal.signal_residuals(
        model, final_signals, archive["signal_center"], archive["signal_scale"]
    )
    standardized = (
        np.abs(residual - archive["residual_median"]) / archive["residual_mad"]
    )
    score = metadata["score"]
    scores = temporal.aggregate_residuals(
        standardized, score["top_k"], score["ewma_span_seconds"]
    )
    detection = temporal.detection_metrics(
        scores,
        labels,
        score["threshold"],
        len(scores) / 3600.0,
        FINAL_ATTACK_IDS,
    )

    fit_paths = [
        args.cache / item["name"] for item in protocol["dataset"]["train_files"]
    ]
    projection = hai.fit_projection(fit_paths)
    state_fit = [hai.project_trace(path, projection) for path in fit_paths]
    state_final = hai.project_trace(args.cache / FINAL_SIGNAL, projection)
    action_baseline = temporal.action_mean(state_fit)
    state_model = {
        "coefficients": archive["state_coefficients"],
        "window": metadata["state_window_seconds"],
    }
    persistence = temporal.transition_evaluation(state_final, "persistence")
    mean = temporal.transition_evaluation(
        state_final, "action_mean", mean=action_baseline
    )
    candidate = temporal.transition_evaluation(
        state_final, "temporal_ridge", state_model=state_model
    )
    state_features, actual_delta = temporal.state_features(state_final)
    predicted_delta = temporal.ridge_predict(
        state_features, state_model["coefficients"]
    )
    variance_ratio = float(
        np.var(predicted_delta) / max(float(np.var(actual_delta)), 1e-12)
    )
    final_requirements = {
        "all_predictions_finite": bool(
            np.isfinite(scores).all() and np.isfinite(predicted_delta).all()
        ),
        "beats_persistence_geometric_error_relative": candidate[
            "geometric_h1_h3_h5_error"
        ]
        <= persistence["geometric_h1_h3_h5_error"] * 0.95,
        "beats_per_action_mean_geometric_error_relative": candidate[
            "geometric_h1_h3_h5_error"
        ]
        <= mean["geometric_h1_h3_h5_error"] * 0.98,
        "attack_window_recall": detection["attack_window_recall"] >= 0.70,
        "false_alerts_per_hour": detection["false_alerts_per_hour"] <= 2.0,
        "point_balanced_accuracy": detection["balanced_accuracy"] >= 0.60,
        "anti_collapse_variance_ratio": variance_ratio >= 0.10,
    }
    report = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "selection_commit": SELECTION_COMMIT,
        "selection_report_sha256": temporal.sha256(SELECTION_REPORT),
        "selected_artifact_sha256": temporal.sha256(ARTIFACT),
        "final_test_open_count": 1,
        "final_files": [
            {
                "name": item["name"],
                "bytes": (args.cache / item["name"]).stat().st_size,
                "sha256": fetch.sha256(args.cache / item["name"]),
            }
            for item in final_items
        ],
        "label_alignment": {
            "method": "row order with minute-resolution timestamp equality",
            "reason": "The official label-test2.csv repeats minute timestamps for its per-second rows, unlike label-test1.csv. Row counts are equal and every label timestamp equals the corresponding signal timestamp floored to the minute.",
            "rows": len(raw_labels),
        },
        "evidence": {
            "recorded_seconds": len(final_signals.values),
            "recorded_hours": len(final_signals.values) / 3600.0,
            "attack_seconds": int(labels.sum()),
            "attack_windows": len(temporal.attack_windows(labels)),
            "source": "HAI 23.05 recorded realistic ICS testbed with hardware-in-the-loop simulation",
        },
        "locked_score": {
            "top_k": score["top_k"],
            "ewma_span_seconds": score["ewma_span_seconds"],
            "threshold": score["threshold"],
        },
        "detection": detection,
        "attack_window_recall_wilson_95": wilson(
            detection["detected_attack_windows"], detection["attack_windows"]
        ),
        "attack_second_recall_wilson_95": wilson(
            detection["tp"], detection["tp"] + detection["fn"]
        ),
        "normal_second_specificity_wilson_95": wilson(
            detection["tn"], detection["tn"] + detection["fp"]
        ),
        "masked_transition": {
            "persistence": persistence,
            "per_proxy_action_mean": mean,
            "selected_temporal_ridge": candidate,
            "relative_error_reduction_vs_persistence": 1.0
            - candidate["geometric_h1_h3_h5_error"]
            / persistence["geometric_h1_h3_h5_error"],
            "relative_error_reduction_vs_per_proxy_action_mean": 1.0
            - candidate["geometric_h1_h3_h5_error"] / mean["geometric_h1_h3_h5_error"],
            "anti_collapse_variance_ratio": variance_ratio,
        },
        "final_requirements": final_requirements,
        "all_registered_gates_pass_on_final_test": all(final_requirements.values()),
        "no_retraining_after_final_test_open": True,
        "claim_boundary": [
            "This is the one registered evaluation of the committed model on HAI test2.",
            "The threshold, model weights, projection and score were frozen before test2 was downloaded.",
            "HAI is external recorded HIL/testbed evidence; this is not a Ferrum hardware trial, field deployment, independent safety assessment or certification.",
            "The result measures anomaly prediction and transition forecasting, not proof that every dangerous cyber-physical action is prevented.",
            "The model remains advisory and has no permit, block, approval, adapter or actuation authority.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "FINAL HAI test2: "
        f"windows={detection['detected_attack_windows']}/{detection['attack_windows']} "
        f"balanced_accuracy={detection['balanced_accuracy']:.4f} "
        f"false_alerts_per_hour={detection['false_alerts_per_hour']:.3f} "
        f"transition_error={candidate['geometric_h1_h3_h5_error']:.6f} "
        f"all_gates={all(final_requirements.values())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
