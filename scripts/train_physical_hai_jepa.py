#!/usr/bin/env python3
"""Select a HAI-specific physical JEPA without opening the registered final test."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import time
from pathlib import Path

import numpy as np

import physical_hai_data as hai
import train_physical_jepa as jepa
import train_physical_world_model as mlp


ROOT = Path(__file__).resolve().parents[1]
DEPLOYED = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
DEFAULT_REPORT = ROOT / "docs" / "research" / "physical_hai_v1_selection.json"
DEFAULT_ARTIFACT = (
    ROOT / "docs" / "research" / "artifacts" / "physical-hai-v1" / "selected_model.npz"
)
MASK = hai.MASK


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_deployed_encoder(path: Path) -> dict:
    header_format = "<4sIIIIIIIIffI"
    header_size = struct.calcsize(header_format)
    values = struct.unpack_from(header_format, path.read_bytes(), 0)
    magic, version, state_size, action_count, feature_size, latent, hidden = values[:7]
    if (magic, version, state_size, action_count, feature_size) != (
        b"PJE1",
        1,
        hai.STATE_SIZE,
        hai.ACTION_COUNT,
        hai.ACTION_FEATURE_SIZE,
    ):
        raise ValueError("deployed physical artifact does not match the registered schema")
    raw = np.frombuffer(path.read_bytes(), dtype="<f4", offset=header_size)
    cursor = 0

    def take(shape):
        nonlocal cursor
        count = int(np.prod(shape))
        result = raw[cursor : cursor + count].reshape(shape).copy()
        cursor += count
        return result

    action_width = action_count + feature_size
    return {
        "encoder_w": take((state_size, latent)),
        "encoder_b": take((latent,)),
        "predictor_w1": take((latent + action_width, hidden)),
        "predictor_b1": take((hidden,)),
        "predictor_w2": take((hidden, latent)),
        "predictor_b2": take((latent,)),
        "state_w": take((latent, state_size)),
        "state_b": take((state_size,)),
    }


def ridge_fit(features: np.ndarray, targets: np.ndarray, penalty: float) -> np.ndarray:
    design = np.concatenate(
        (features.astype(np.float64), np.ones((len(features), 1))), axis=1
    )
    gram = design.T @ design
    regularizer = np.eye(gram.shape[0]) * penalty
    regularizer[-1, -1] = 0.0
    return np.linalg.solve(gram + regularizer, design.T @ targets).astype(np.float32)


def ridge_predict(features: np.ndarray, coefficients: np.ndarray) -> np.ndarray:
    return features @ coefficients[:-1] + coefficients[-1]


def model_delta(model: dict, state, action, action_features) -> np.ndarray:
    action_values = hai.action_matrix(action, action_features)
    kind = model["kind"]
    if kind == "persistence":
        return np.zeros_like(state)
    if kind == "action_mean":
        return model["mean"][action]
    if kind == "ridge":
        features = np.concatenate((state[:, MASK], action_values), axis=1)
        masked = ridge_predict(features, model["coefficients"])
        result = np.zeros_like(state)
        result[:, MASK] = masked
        return result
    if kind == "frozen_probe":
        latent = np.tanh(state @ model["encoder_w"] + model["encoder_b"])
        features = np.concatenate((latent, action_values), axis=1)
        masked = ridge_predict(features, model["coefficients"])
        result = np.zeros_like(state)
        result[:, MASK] = masked
        return result
    if kind == "deployed_direct":
        latent = np.tanh(state @ model["encoder_w"] + model["encoder_b"])
        hidden = np.maximum(
            np.concatenate((latent, action_values), axis=1) @ model["predictor_w1"]
            + model["predictor_b1"],
            0,
        )
        predicted_latent = hidden @ model["predictor_w2"] + model["predictor_b2"]
        return predicted_latent @ model["state_w"] + model["state_b"]
    if kind == "mlp":
        inputs = np.concatenate((state, action_values), axis=1).astype(np.float32)
        return mlp.predict(inputs, model["weights"])
    if kind == "jepa":
        return jepa.forward(state, action_values, model["weights"])[-1]
    raise ValueError(f"unsupported model kind: {kind}")


def masked_rollout_error(trace: hai.Trace, model: dict, horizon: int) -> float:
    count = len(trace.state) - horizon + 1
    predicted = trace.state[:count].copy()
    for offset in range(horizon):
        predicted += model_delta(
            model,
            predicted,
            trace.action[offset : offset + count],
            trace.action_features[offset : offset + count],
        )
        predicted[:, 2:] = np.clip(predicted[:, 2:], 0, 1)
        predicted[:, :2] = np.clip(predicted[:, :2], -1.25, 1.25)
    actual = trace.next_state[horizon - 1 : horizon - 1 + count]
    return float(np.mean(np.abs(predicted[:, MASK] - actual[:, MASK])))


def geometric_error(trace: hai.Trace, model: dict) -> tuple[dict, float]:
    values = {
        f"h{horizon}_normalized_mae": masked_rollout_error(trace, model, horizon)
        for horizon in (1, 3, 5)
    }
    geometric = math.prod(values.values()) ** (1.0 / len(values))
    return values, geometric


def residual_scores(trace: hai.Trace, model: dict) -> np.ndarray:
    predicted = trace.state + model_delta(
        model, trace.state, trace.action, trace.action_features
    )
    predicted[:, 2:] = np.clip(predicted[:, 2:], 0, 1)
    return np.mean(np.abs(predicted[:, MASK] - trace.next_state[:, MASK]), axis=1)


def rolling_alerts(scores: np.ndarray, threshold: float) -> np.ndarray:
    exceed = scores > threshold
    window = np.convolve(exceed.astype(np.int8), np.ones(5, dtype=np.int8), mode="full")[: len(exceed)]
    return window >= 3


def event_starts(alerts: np.ndarray, cooldown: int = 30) -> list[int]:
    starts = []
    next_allowed = 0
    previous = False
    for index, value in enumerate(alerts):
        if value and not previous and index >= next_allowed:
            starts.append(index)
            next_allowed = index + cooldown
        previous = bool(value)
    return starts


def attack_windows(labels: np.ndarray) -> list[tuple[int, int]]:
    padded = np.pad(labels.astype(np.int8), (1, 1))
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return list(zip(starts.tolist(), ends.tolist(), strict=True))


def detection_metrics(scores, labels, threshold, duration_hours) -> dict:
    alerts = rolling_alerts(scores, threshold)
    labels = labels.astype(bool)
    tp = int(np.sum(alerts & labels))
    fp = int(np.sum(alerts & ~labels))
    tn = int(np.sum(~alerts & ~labels))
    fn = int(np.sum(~alerts & labels))
    windows = attack_windows(labels)
    detected = sum(bool(np.any(alerts[start:end])) for start, end in windows)
    false_starts = sum(not labels[index] for index in event_starts(alerts))
    tpr = tp / max(1, tp + fn)
    tnr = tn / max(1, tn + fp)
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": tp / max(1, tp + fp),
        "recall": tpr,
        "f1": 2 * tp / max(1, 2 * tp + fp + fn),
        "balanced_accuracy": (tpr + tnr) / 2,
        "attack_windows": len(windows),
        "detected_attack_windows": detected,
        "attack_window_recall": detected / max(1, len(windows)),
        "false_alert_events": false_starts,
        "false_alerts_per_hour": false_starts / max(duration_hours, 1e-9),
    }


def calibrate_threshold(scores: np.ndarray, duration_hours: float) -> tuple[float, dict]:
    quantiles = np.unique(
        np.concatenate((np.linspace(0.90, 0.999, 100), np.linspace(0.9991, 0.99999, 90)))
    )
    selected = float(np.max(scores))
    selected_metrics = None
    zeros = np.zeros(len(scores), dtype=np.int8)
    for quantile in quantiles:
        threshold = float(np.quantile(scores, quantile))
        metrics = detection_metrics(scores, zeros, threshold, duration_hours)
        if metrics["false_alerts_per_hour"] <= 2.0:
            selected = threshold
            selected_metrics = {**metrics, "quantile": float(quantile)}
            break
    if selected_metrics is None:
        selected_metrics = {
            **detection_metrics(scores, zeros, selected, duration_hours),
            "quantile": 1.0,
        }
    return selected, selected_metrics


def variance_ratio(trace: hai.Trace, model: dict) -> float:
    predicted = model_delta(model, trace.state, trace.action, trace.action_features)[:, MASK]
    actual = (trace.next_state - trace.state)[:, MASK]
    return float(np.var(predicted) / max(float(np.var(actual)), 1e-12))


def latency(model: dict, trace: hai.Trace) -> dict:
    count = min(1024, len(trace.state))
    samples = []
    for _ in range(25):
        start = time.perf_counter_ns()
        model_delta(
            model,
            trace.state[:count],
            trace.action[:count],
            trace.action_features[:count],
        )
        samples.append((time.perf_counter_ns() - start) / count / 1000.0)
    return {
        "median_microseconds_per_row": float(np.median(samples)),
        "p99_microseconds_per_row": float(np.quantile(samples, 0.99)),
    }


def sample_trace(trace: hai.Trace, count: int, seed: int) -> hai.Trace:
    if len(trace.state) <= count:
        return trace
    indices = np.sort(np.random.default_rng(seed).choice(len(trace.state), count, replace=False))
    return hai.Trace(
        state=trace.state[indices],
        next_state=trace.next_state[indices],
        action=trace.action[indices],
        action_features=trace.action_features[indices],
        timestamp=trace.timestamp[indices],
        label=None if trace.label is None else trace.label[indices],
        source_file=trace.source_file,
    )


def rows(trace: hai.Trace) -> list[tuple]:
    return [
        (
            0,
            index,
            trace.state[index],
            int(trace.action[index]),
            trace.action_features[index],
            trace.next_state[index],
            False,
        )
        for index in range(len(trace.state))
    ]


def fit_models(fit: hai.Trace, validation: hai.Trace) -> list[dict]:
    delta = fit.next_state - fit.state
    action_mean = np.zeros((hai.ACTION_COUNT, hai.STATE_SIZE), dtype=np.float32)
    for action in range(hai.ACTION_COUNT):
        selected = delta[fit.action == action]
        if len(selected):
            action_mean[action] = np.mean(selected, axis=0)

    action_values = hai.action_matrix(fit.action, fit.action_features)
    raw_features = np.concatenate((fit.state[:, MASK], action_values), axis=1)
    ridge = ridge_fit(raw_features, delta[:, MASK], 1e-3)

    deployed = load_deployed_encoder(DEPLOYED)
    latent = np.tanh(fit.state @ deployed["encoder_w"] + deployed["encoder_b"])
    probe = ridge_fit(np.concatenate((latent, action_values), axis=1), delta[:, MASK], 1e-3)
    models = [
        {"name": "persistence", "kind": "persistence"},
        {"name": "per_proxy_action_mean", "kind": "action_mean", "mean": action_mean},
        {"name": "ridge_autoregression", "kind": "ridge", "coefficients": ridge},
        {"name": "deployed_simulator_jepa_direct", "kind": "deployed_direct", **deployed},
        {
            "name": "frozen_simulator_jepa_probe",
            "kind": "frozen_probe",
            "encoder_w": deployed["encoder_w"],
            "encoder_b": deployed["encoder_b"],
            "coefficients": probe,
        },
    ]

    train_sample = sample_trace(fit, 300_000, 20260822)
    val_sample = sample_trace(validation, 50_000, 20260823)
    train_input, train_delta = hai.make_input(train_sample)
    val_input, val_delta = hai.make_input(val_sample)
    for seed in (42, 17):
        weights, objective, epochs = mlp.train(
            train_input, train_delta, val_input, val_delta, 128, 6000, seed
        )
        models.append(
            {
                "name": f"matched_mlp_h128_seed{seed}",
                "kind": "mlp",
                "weights": weights,
                "trained_epochs": epochs,
                "training_objective": objective,
                "training_seed": seed,
            }
        )

    train_rows = rows(train_sample)
    val_rows = rows(val_sample)
    for latent_size, hidden_size, seed in ((64, 128, 42), (64, 128, 17), (96, 192, 91)):
        weights, objective, epochs = jepa.train(
            train_rows,
            val_rows,
            latent_size,
            hidden_size,
            8000,
            seed,
            validation_latent_weight=0.25,
        )
        models.append(
            {
                "name": f"hai_jepa_l{latent_size}_h{hidden_size}_seed{seed}",
                "kind": "jepa",
                "weights": weights,
                "trained_epochs": epochs,
                "training_objective": objective,
                "training_seed": seed,
                "latent": latent_size,
                "hidden": hidden_size,
            }
        )
    return models


def evaluate_model(
    model: dict,
    calibration: hai.Trace,
    validation: hai.Trace,
    persistence_error: float | None,
    mean_error: float | None,
) -> dict:
    rollout, geometric = geometric_error(validation, model)
    calibration_scores = residual_scores(calibration, model)
    threshold, calibration_metrics = calibrate_threshold(
        calibration_scores, len(calibration_scores) / 3600.0
    )
    validation_scores = residual_scores(validation, model)
    detection = detection_metrics(
        validation_scores,
        validation.label,
        threshold,
        len(validation_scores) / 3600.0,
    )
    ratio = variance_ratio(validation, model)
    finite = bool(
        np.isfinite(validation_scores).all()
        and all(np.isfinite(value) for value in rollout.values())
    )
    requirements = {
        "all_predictions_finite": finite,
        "beats_persistence_geometric_error_relative": (
            persistence_error is not None and geometric <= persistence_error * 0.95
        ),
        "beats_per_action_mean_geometric_error_relative": (
            mean_error is not None and geometric <= mean_error * 0.98
        ),
        "attack_window_recall": detection["attack_window_recall"] >= 0.70,
        "false_alerts_per_hour": detection["false_alerts_per_hour"] <= 2.0,
        "point_balanced_accuracy": detection["balanced_accuracy"] >= 0.60,
        "anti_collapse_variance_ratio": ratio >= 0.10,
    }
    return {
        "name": model["name"],
        "kind": model["kind"],
        "rollout": rollout,
        "geometric_h1_h3_h5_error": geometric,
        "residual_threshold": threshold,
        "normal_calibration": calibration_metrics,
        "validation_detection": detection,
        "anti_collapse_variance_ratio": ratio,
        "finite": finite,
        "latency": latency(model, validation),
        "requirements": requirements,
        "eligible": all(requirements.values()),
        **({"trained_epochs": model["trained_epochs"]} if "trained_epochs" in model else {}),
        **({"training_seed": model["training_seed"]} if "training_seed" in model else {}),
    }


def save_model(path: Path, model: dict, statistics: dict, evaluation: dict) -> None:
    arrays = {}
    metadata = {
        "name": model["name"],
        "kind": model["kind"],
        "projection": statistics,
        "evaluation": evaluation,
        "authority": "advisory diagnostic only; no permit, block, approval, adapter, or actuation authority",
    }
    if model["kind"] == "jepa":
        arrays.update({f"weight_{key}": value for key, value in model["weights"].items()})
    elif model["kind"] == "mlp":
        for index, value in enumerate(model["weights"]):
            arrays[f"weight_{index}"] = value
    else:
        for key, value in model.items():
            if isinstance(value, np.ndarray):
                arrays[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, metadata=json.dumps(metadata, sort_keys=True), **arrays)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=hai.DEFAULT_CACHE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args()

    protocol = hai.load_protocol()
    fit_paths = [args.cache / item["name"] for item in protocol["dataset"]["train_files"]]
    statistics = hai.fit_projection(fit_paths)
    fit = hai.concatenate([hai.project_trace(path, statistics) for path in fit_paths])
    calibration_item = protocol["dataset"]["normal_calibration_file"]
    calibration = hai.project_trace(args.cache / calibration_item["name"], statistics)
    validation_items = protocol["dataset"]["validation_files"]
    validation = hai.project_trace(
        args.cache / validation_items[0]["name"],
        statistics,
        args.cache / validation_items[1]["name"],
    )
    print(
        f"HAI fit={len(fit.state):,} calibration={len(calibration.state):,} "
        f"validation={len(validation.state):,} attack-seconds={int(validation.label.sum()):,}"
    )

    models = fit_models(fit, validation)
    evaluations = []
    persistence_error = geometric_error(validation, models[0])[1]
    mean_error = geometric_error(validation, models[1])[1]
    for model in models:
        evaluation = evaluate_model(
            model, calibration, validation, persistence_error, mean_error
        )
        evaluations.append(evaluation)
        print(
            f"{model['name']}: g={evaluation['geometric_h1_h3_h5_error']:.6f} "
            f"windows={evaluation['validation_detection']['detected_attack_windows']}/"
            f"{evaluation['validation_detection']['attack_windows']} "
            f"false_alerts/h={evaluation['validation_detection']['false_alerts_per_hour']:.3f} "
            f"eligible={evaluation['eligible']}"
        )

    eligible = [
        (model, evaluation)
        for model, evaluation in zip(models, evaluations, strict=True)
        if evaluation["eligible"] and model["kind"] not in ("persistence", "action_mean")
    ]
    eligible.sort(
        key=lambda pair: (
            pair[1]["geometric_h1_h3_h5_error"],
            -pair[1]["validation_detection"]["attack_window_recall"],
            pair[1]["validation_detection"]["false_alerts_per_hour"],
        )
    )
    selected = eligible[0] if eligible else None
    report = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "registered_final_test_open_count": 0,
        "baseline_artifact_sha256": sha256(DEPLOYED),
        "projection": statistics,
        "rows": {
            "fit": len(fit.state),
            "normal_calibration": len(calibration.state),
            "validation": len(validation.state),
            "validation_attack_seconds": int(validation.label.sum()),
            "validation_attack_windows": len(attack_windows(validation.label)),
        },
        "action_counts": {
            "fit": {str(k): int(v) for k, v in zip(*np.unique(fit.action, return_counts=True), strict=True)},
            "validation": {str(k): int(v) for k, v in zip(*np.unique(validation.action, return_counts=True), strict=True)},
        },
        "evaluations": evaluations,
        "selected_model": None if selected is None else selected[1]["name"],
        "all_validation_gates_pass": selected is not None,
        "final_test_opened": False,
        "claim_boundary": [
            "Selection used normal fit, normal calibration, and HAI test1 validation only.",
            "HAI test2 remained unopened during selection.",
            "This is external HIL/testbed evidence, not a field incident or Ferrum hardware trial.",
            "The selected model has advisory diagnostic authority only."
        ]
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if selected is not None:
        save_model(args.artifact, selected[0], statistics, selected[1])
        report["selected_artifact"] = str(args.artifact.relative_to(ROOT)).replace("\\", "/")
        report["selected_artifact_sha256"] = sha256(args.artifact)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"selected {selected[1]['name']} -> {args.artifact}")
        return 0
    print("No candidate passed every registered validation gate; final test remains sealed.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
