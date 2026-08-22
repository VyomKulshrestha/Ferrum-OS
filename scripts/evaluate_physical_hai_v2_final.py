#!/usr/bin/env python3
"""Run the one registered HAI 21.03 final evaluation for the v2 artifact."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import fetch_physical_hai_v2 as fetch_v2
import train_physical_hai_v2 as v2


ROOT = Path(__file__).resolve().parents[1]
SELECTION_REPORT = ROOT / "docs" / "research" / "physical_hai_v2_selection.json"
ARTIFACT = (
    ROOT / "docs" / "research" / "artifacts" / "physical-hai-v2" / "selected_model.npz"
)
DEFAULT_REPORT = ROOT / "docs" / "research" / "physical_hai_v2_final_test.json"
SELECTION_COMMIT = "d083033"
FINAL_IDENTIFIERS = (
    tuple(f"A{100 + index}" for index in range(1, 6)),
    tuple(f"A{200 + index}" for index in range(1, 21)),
    tuple(f"A{300 + index}" for index in range(1, 9)),
    tuple(f"A{400 + index}" for index in range(1, 6)),
    tuple(f"A{500 + index}" for index in range(1, 13)),
)


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> dict:
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


def load_model(archive, metadata) -> dict:
    if metadata["model"]["kind"] != "ridge":
        raise AssertionError("final evaluator expects the committed ridge artifact")
    return {
        **metadata["model"],
        "coefficients": archive["target_model.coefficients"],
    }


def score_trace(
    raw: np.ndarray, archive, metadata: dict, model: dict
) -> tuple[np.ndarray, np.ndarray]:
    normalized = v2.normalize(raw, archive["target_center"], archive["target_scale"])
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
    return (
        v2.ewma_fast(row_score, score["ewma_span_seconds"]),
        normalized,
    )


def transition_results(
    model: dict,
    raw_traces: list[np.ndarray],
    normalized_traces: list[np.ndarray],
    columns: tuple[str, ...],
    archive,
    metadata: dict,
) -> dict:
    action_threshold = metadata["action_proxy_threshold"]
    action_mean = archive["action_mean"]

    def evaluate(kind: str, current_model: dict) -> dict:
        values = {
            f"h{horizon}_normalized_mae": v2.rollout_error(
                current_model,
                normalized_traces,
                raw_traces,
                horizon,
                kind,
                action_threshold,
                action_mean,
                columns,
            )
            for horizon in (1, 3, 5)
        }
        return {
            "rollout": values,
            "geometric_h1_h3_h5_error": math.prod(values.values()) ** (1.0 / 3.0),
        }

    persistence = evaluate("persistence", model)
    per_action = evaluate("action_mean", model)
    candidate = evaluate("model", model)
    predicted = []
    actual = []
    for trace in normalized_traces:
        features, target = v2.temporal.signal_examples(trace, model["context_seconds"])
        predicted.append(v2.predict(model, features))
        actual.append(target)
    variance_ratio = float(
        np.var(np.concatenate(predicted))
        / max(float(np.var(np.concatenate(actual))), 1e-12)
    )
    return {
        "persistence": persistence,
        "per_proxy_action_mean": per_action,
        "selected_model": candidate,
        "relative_error_reduction_vs_persistence": 1.0
        - candidate["geometric_h1_h3_h5_error"]
        / persistence["geometric_h1_h3_h5_error"],
        "relative_error_reduction_vs_per_proxy_action_mean": 1.0
        - candidate["geometric_h1_h3_h5_error"]
        / per_action["geometric_h1_h3_h5_error"],
        "anti_collapse_variance_ratio": variance_ratio,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    protocol = json.loads(v2.PROTOCOL.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION_REPORT.read_text(encoding="utf-8"))
    if not selection["all_selection_gates_pass"] or selection["final_test_opened"]:
        raise AssertionError("v2 selection is not eligible for final evaluation")
    if selection["selected_artifact_sha256"] != v2.sha256(ARTIFACT):
        raise AssertionError("selected artifact changed after selection")
    final_items = protocol["sealed_final_files"]
    for item in final_items:
        valid, reason = fetch_v2.verify(v2.TARGET_CACHE / item["name"], item)
        if not valid:
            raise RuntimeError(f"unverified final file {item['name']}: {reason}")

    archive = np.load(ARTIFACT, allow_pickle=False)
    metadata = json.loads(str(archive["metadata"]))
    if metadata["schema"] != "FERRUM_HAI_SITE_ADAPTED_V2":
        raise AssertionError("unexpected artifact schema")
    model = load_model(archive, metadata)
    columns = tuple(metadata["target_signal_columns"])
    raw_traces = []
    normalized_traces = []
    score_traces = []
    label_traces = []
    for item, identifiers in zip(final_items, FINAL_IDENTIFIERS, strict=True):
        path = v2.TARGET_CACHE / item["name"]
        frame = pd.read_csv(path, usecols=("time", *columns, *v2.LABEL_COLUMNS))
        timestamp = pd.to_datetime(frame["time"], errors="raise").to_numpy(
            dtype="datetime64[s]"
        )
        if len(timestamp) > 1 and not np.all(
            np.diff(timestamp).astype("timedelta64[s]").astype(int) == 1
        ):
            raise AssertionError(f"non-contiguous final trace: {item['name']}")
        raw = frame.loc[:, columns].to_numpy(dtype=np.float32)
        if not np.isfinite(raw).all():
            raise AssertionError(f"non-finite final trace: {item['name']}")
        labels = frame["attack"].to_numpy(dtype=np.int8)[model["context_seconds"] + 1 :]
        if len(v2.temporal.attack_windows(labels)) != len(identifiers):
            raise AssertionError(
                f"attack-window count mismatch in {item['name']}: "
                f"expected {len(identifiers)}"
            )
        scores, normalized = score_trace(raw, archive, metadata, model)
        if len(scores) != len(labels):
            raise AssertionError(f"score/label mismatch in {item['name']}")
        raw_traces.append(raw)
        normalized_traces.append(normalized)
        score_traces.append(scores)
        label_traces.append(labels)

    detection = v2.aggregate_detection(
        score_traces,
        label_traces,
        list(FINAL_IDENTIFIERS),
        metadata["score"]["numeric_threshold"],
    )
    transition = transition_results(
        model, raw_traces, normalized_traces, columns, archive, metadata
    )
    requirements = {
        "all_predictions_finite": bool(
            all(np.isfinite(scores).all() for scores in score_traces)
        ),
        "beats_persistence_geometric_error_relative": transition["selected_model"][
            "geometric_h1_h3_h5_error"
        ]
        <= transition["persistence"]["geometric_h1_h3_h5_error"] * 0.95,
        "beats_per_action_mean_geometric_error_relative": transition["selected_model"][
            "geometric_h1_h3_h5_error"
        ]
        <= transition["per_proxy_action_mean"]["geometric_h1_h3_h5_error"] * 0.98,
        "anti_collapse_variance_ratio": transition["anti_collapse_variance_ratio"]
        >= 0.10,
        "attack_window_recall": detection["attack_window_recall"] >= 0.70,
        "false_alerts_per_hour": detection["false_alerts_per_hour"] <= 2.0,
        "point_balanced_accuracy": detection["balanced_accuracy"] >= 0.60,
    }
    report = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "selection_commit": SELECTION_COMMIT,
        "selection_report_sha256": v2.sha256(SELECTION_REPORT),
        "selected_artifact_sha256": v2.sha256(ARTIFACT),
        "final_test_open_count": 1,
        "final_files": [
            {
                "name": item["name"],
                "bytes": (v2.TARGET_CACHE / item["name"]).stat().st_size,
                "git_blob_sha1": fetch_v2.git_blob_sha1(v2.TARGET_CACHE / item["name"]),
                "sha256": fetch_v2.sha256(v2.TARGET_CACHE / item["name"]),
            }
            for item in final_items
        ],
        "evidence": {
            "files": len(final_items),
            "recorded_seconds": sum(len(item) for item in raw_traces),
            "recorded_hours": sum(len(item) for item in raw_traces) / 3600.0,
            "attack_seconds": int(sum(labels.sum() for labels in label_traces)),
            "attack_windows": sum(
                len(v2.temporal.attack_windows(labels)) for labels in label_traces
            ),
            "source": "HAI 21.03 recorded realistic ICS testbed with hardware-in-the-loop simulation",
        },
        "locked_configuration": metadata,
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
        "transition": transition,
        "final_requirements": requirements,
        "all_registered_gates_pass_on_final_test": all(requirements.values()),
        "no_retraining_after_final_test_open": True,
        "claim_boundary": [
            "This is the one registered evaluation of the committed site-adapted procedure on all five HAI 21.03 test files.",
            "Target weights, robust scaling, residual scaling, PCA basis, percentile and numeric threshold were fitted from normal files and committed before the tests were downloaded.",
            "The experiment measures transfer of a self-supervised commissioning procedure, not zero-shot checkpoint transfer.",
            "HAI is external recorded HIL/testbed evidence, not a Ferrum hardware trial, field deployment, independent safety assessment or certification.",
            "The model remains advisory and has no permit, block, approval, adapter or actuation authority.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "FINAL HAI 21.03: "
        f"windows={detection['detected_attack_windows']}/50 "
        f"balanced_accuracy={detection['balanced_accuracy']:.4f} "
        f"false_alerts_per_hour={detection['false_alerts_per_hour']:.3f} "
        f"transition_error={transition['selected_model']['geometric_h1_h3_h5_error']:.6f} "
        f"all_gates={all(requirements.values())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
