#!/usr/bin/env python3
"""Select and fit the site-adapted HAI v2 model without opening 21.03 tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import lfilter

import fetch_physical_hai_v2 as fetch_v2
import physical_hai_data as hai
import train_physical_hai_temporal as temporal


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "research" / "physical_hai_v2_cross_version_protocol.json"
AMENDMENT = ROOT / "docs" / "research" / "physical_hai_v2_cross_version_amendment4.json"
SOURCE_CACHE = hai.DEFAULT_CACHE
TARGET_CACHE = fetch_v2.DEFAULT_CACHE
DEFAULT_REPORT = ROOT / "docs" / "research" / "physical_hai_v2_selection.json"
DEFAULT_ARTIFACT = (
    ROOT / "docs" / "research" / "artifacts" / "physical-hai-v2" / "selected_model.npz"
)
SOURCE_FIT = ("hai-train1.csv", "hai-train2.csv", "hai-train3.csv")
SOURCE_CALIBRATION = "hai-train4.csv"
SOURCE_SELECTION = (
    ("hai-test1.csv", "label-test1.csv", tuple(f"A{100 + i}" for i in range(1, 15))),
    ("hai-test2.csv", "label-test2.csv", tuple(f"A{200 + i}" for i in range(1, 39))),
)
TARGET_FIT = ("train1.csv.gz", "train2.csv.gz")
TARGET_CALIBRATION = "train3.csv.gz"
LABEL_COLUMNS = ("attack", "attack_P1", "attack_P2", "attack_P3")
PERCENTILES = np.unique(
    np.concatenate((np.linspace(0.90, 0.999, 100), np.linspace(0.9991, 0.99999, 90)))
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_target_final_sealed(protocol: dict, cache: Path) -> None:
    present = [
        item["name"]
        for item in protocol["sealed_final_files"]
        if (cache / item["name"]).exists()
    ]
    if present:
        raise RuntimeError(f"HAI 21.03 final files must remain sealed: {present}")


def source_columns() -> tuple[str, ...]:
    columns = tuple(pd.read_csv(SOURCE_CACHE / SOURCE_FIT[0], nrows=0).columns)
    if columns[0] != "timestamp" or len(columns) != 87:
        raise ValueError("unexpected HAI 23.05 schema")
    return columns[1:]


def target_columns() -> tuple[str, ...]:
    columns = tuple(pd.read_csv(TARGET_CACHE / TARGET_FIT[0], nrows=0).columns)
    if columns[0] != "time":
        raise ValueError("unexpected HAI 21.03 time column")
    signals = tuple(column for column in columns[1:] if column not in LABEL_COLUMNS)
    if len(signals) != 79:
        raise ValueError(f"expected 79 HAI 21.03 signals, observed {len(signals)}")
    return signals


def read_values(path: Path, columns: tuple[str, ...]) -> np.ndarray:
    values = (
        pd.read_csv(path, usecols=columns).loc[:, columns].to_numpy(dtype=np.float32)
    )
    if not np.isfinite(values).all():
        raise ValueError(f"non-finite values in {path.name}")
    return values


def fit_normalizer(traces: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    values = np.concatenate(traces)
    center = np.median(values, axis=0)
    lower, upper = np.quantile(values, (0.005, 0.995), axis=0)
    return center.astype(np.float32), np.maximum(upper - lower, 1e-5).astype(np.float32)


def normalize(values, center, scale) -> np.ndarray:
    return np.clip((values - center) / scale, -5.0, 5.0).astype(np.float32)


def fit_ridge(traces: list[np.ndarray], window: int) -> dict:
    features = []
    targets = []
    for trace in traces:
        x, y = temporal.signal_examples(trace, window)
        features.append(x[::5])
        targets.append(y[::5])
    x = np.concatenate(features)
    y = np.concatenate(targets)
    return {
        "name": f"temporal_ridge_w{window}",
        "kind": "ridge",
        "context_seconds": window,
        "coefficients": temporal.ridge_fit(x, y, 0.01),
        "fit_examples": len(x),
    }


def as_signal_traces(
    traces: list[np.ndarray], prefix: str
) -> list[temporal.SignalData]:
    return [
        temporal.SignalData(
            values=trace,
            timestamp=np.arange(len(trace), dtype=np.int64).astype("datetime64[s]"),
            source=f"{prefix}{index}",
        )
        for index, trace in enumerate(traces)
    ]


def fit_jepa(traces: list[np.ndarray], window: int) -> dict:
    size = traces[0].shape[1]
    model = temporal.fit_signal_jepa(
        as_signal_traces(traces, "normal-"),
        np.zeros(size, dtype=np.float32),
        np.ones(size, dtype=np.float32),
        latent_size=64,
        hidden_size=128,
        seed=17,
        epochs=40,
        window=window,
        sample_step=5,
    )
    model["name"] = f"temporal_jepa_w{window}_l64_h128_seed17"
    return model


def predict(model: dict, features: np.ndarray) -> np.ndarray:
    if model["kind"] == "ridge":
        return temporal.ridge_predict(features, model["coefficients"])
    if model["kind"] == "jepa":
        return temporal.jepa_signal_predict(model, features)
    raise ValueError(model["kind"])


def prediction_residual(model: dict, trace: np.ndarray) -> np.ndarray:
    features, target = temporal.signal_examples(trace, model["context_seconds"])
    return np.abs(target - predict(model, features)).astype(np.float32)


def robust_standardizer(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    median = np.median(values, axis=0)
    mad = np.maximum(np.median(np.abs(values - median), axis=0), 1e-5)
    return median.astype(np.float32), mad.astype(np.float32)


def standardized(values, median, mad) -> np.ndarray:
    return (np.abs(values - median) / mad).astype(np.float32)


def fit_pca(traces: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    sample = np.concatenate([trace[::10] for trace in traces])
    mean = np.mean(sample, axis=0)
    covariance = np.cov(sample - mean, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    components = eigenvectors[:, np.argsort(eigenvalues)[::-1]]
    return mean.astype(np.float32), components.astype(np.float32)


def reconstruction_residual(
    values: np.ndarray, mean: np.ndarray, components: np.ndarray, rank: int
) -> np.ndarray:
    centered = values - mean
    basis = components[:, :rank]
    return np.abs(centered - (centered @ basis) @ basis.T).astype(np.float32)


def ewma_fast(values: np.ndarray, span: int) -> np.ndarray:
    if span == 1:
        return values.copy()
    alpha = 2.0 / (span + 1.0)
    return lfilter(
        [alpha], [1.0, -(1.0 - alpha)], values, zi=[(1.0 - alpha) * values[0]]
    )[0]


def alerts(scores: np.ndarray, threshold: float) -> np.ndarray:
    exceed = scores > threshold
    count = np.convolve(exceed.astype(np.int8), np.ones(5, dtype=np.int8), mode="full")[
        : len(scores)
    ]
    return count >= 3


def event_count(values: np.ndarray, cooldown: int = 30) -> int:
    starts = np.flatnonzero(values & ~np.r_[False, values[:-1]])
    count = 0
    next_allowed = -1
    for index in starts:
        if index >= next_allowed:
            count += 1
            next_allowed = index + cooldown
    return count


def false_alert_rate(scores: np.ndarray, threshold: float) -> float:
    return event_count(alerts(scores, threshold)) / (len(scores) / 3600.0)


def shared_percentile(
    source_scores: np.ndarray, target_scores: np.ndarray
) -> tuple[float, float, float, float, float] | None:
    source_thresholds = np.quantile(source_scores, PERCENTILES)
    target_thresholds = np.quantile(target_scores, PERCENTILES)

    def eligible(index: int) -> bool:
        return (
            false_alert_rate(source_scores, source_thresholds[index]) <= 2.0
            and false_alert_rate(target_scores, target_thresholds[index]) <= 2.0
        )

    low = 0
    high = len(PERCENTILES) - 1
    if not eligible(high):
        return None
    while low < high:
        middle = (low + high) // 2
        if eligible(middle):
            high = middle
        else:
            low = middle + 1
    while low > 0 and eligible(low - 1):
        low -= 1
    return (
        float(PERCENTILES[low]),
        float(source_thresholds[low]),
        float(target_thresholds[low]),
        false_alert_rate(source_scores, source_thresholds[low]),
        false_alert_rate(target_scores, target_thresholds[low]),
    )


def labels_23(name: str) -> np.ndarray:
    return pd.read_csv(SOURCE_CACHE / name)["label"].to_numpy(dtype=np.int8)


def aggregate_detection(
    score_traces: list[np.ndarray],
    label_traces: list[np.ndarray],
    attack_ids: list[tuple[str, ...]],
    threshold: float,
) -> dict:
    tp = fp = tn = fn = false_events = detected = windows = 0
    hours = 0.0
    detected_ids = []
    missed_ids = []
    per_file = []
    for scores, labels, identifiers in zip(
        score_traces, label_traces, attack_ids, strict=True
    ):
        current = temporal.detection_metrics(
            scores, labels, threshold, len(scores) / 3600.0, identifiers
        )
        tp += current["tp"]
        fp += current["fp"]
        tn += current["tn"]
        fn += current["fn"]
        false_events += current["false_alert_events"]
        detected += current["detected_attack_windows"]
        windows += current["attack_windows"]
        hours += len(scores) / 3600.0
        detected_ids.extend(current["detected_attack_ids"])
        missed_ids.extend(current["missed_attack_ids"])
        per_file.append(current)
    recall = tp / max(1, tp + fn)
    specificity = tn / max(1, tn + fp)
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": tp / max(1, tp + fp),
        "recall": recall,
        "f1": 2 * tp / max(1, 2 * tp + fp + fn),
        "balanced_accuracy": (recall + specificity) / 2.0,
        "attack_windows": windows,
        "detected_attack_windows": detected,
        "attack_window_recall": detected / max(1, windows),
        "detected_attack_ids": detected_ids,
        "missed_attack_ids": missed_ids,
        "false_alert_events": false_events,
        "false_alerts_per_hour": false_events / hours,
        "false_alert_seconds_per_hour": fp / hours,
        "per_file": per_file,
    }


def proxy_actions(
    raw: np.ndarray,
    normalized: np.ndarray,
    threshold: float,
    columns: tuple[str, ...],
) -> np.ndarray:
    aggregate = np.mean(np.abs(np.diff(normalized, axis=0)), axis=1)
    action = (aggregate > threshold).astype(np.int8)
    stop = np.zeros(len(action), dtype=bool)
    if "P2_Emerg" in columns:
        stop |= raw[1:, columns.index("P2_Emerg")] > 0.5
    if "P2_TripEx" in columns:
        stop |= raw[1:, columns.index("P2_TripEx")] < 0.5
    if "P2_OnOff" in columns:
        onoff = raw[:, columns.index("P2_OnOff")]
        stop |= (onoff[:-1] > 0.5) & (onoff[1:] < 0.5)
    action[stop] = 2
    return action


def fit_action_baseline(
    raw_traces: list[np.ndarray],
    normalized_traces: list[np.ndarray],
    columns: tuple[str, ...],
) -> tuple[float, np.ndarray]:
    aggregates = np.concatenate(
        [np.mean(np.abs(np.diff(trace, axis=0)), axis=1) for trace in normalized_traces]
    )
    threshold = float(np.quantile(aggregates, 0.90))
    totals = np.zeros((3, normalized_traces[0].shape[1]), dtype=np.float64)
    counts = np.zeros(3, dtype=np.int64)
    for raw, normalized in zip(raw_traces, normalized_traces, strict=True):
        action = proxy_actions(raw, normalized, threshold, columns)
        delta = np.diff(normalized, axis=0)
        for value in (0, 1, 2):
            selected = delta[action == value]
            totals[value] += np.sum(selected, axis=0)
            counts[value] += len(selected)
    totals[counts > 0] /= counts[counts > 0, None]
    return threshold, totals.astype(np.float32)


def rollout_error(
    model: dict | None,
    traces: list[np.ndarray],
    raw_traces: list[np.ndarray],
    horizon: int,
    kind: str,
    action_threshold: float,
    action_mean: np.ndarray,
    columns: tuple[str, ...],
) -> float:
    total_error = 0.0
    total_values = 0
    window = 5 if model is None else model["context_seconds"]
    for trace, raw in zip(traces, raw_traces, strict=True):
        count = len(trace) - window - horizon
        starts = np.arange(window, window + count)
        sequence = [trace[starts - offset].copy() for offset in range(window, -1, -1)]
        action = proxy_actions(raw, trace, action_threshold, columns)
        for offset in range(horizon):
            current = sequence[-1]
            if kind == "persistence":
                delta = np.zeros_like(current)
            elif kind == "action_mean":
                delta = action_mean[action[starts + offset]]
            else:
                previous = sequence[-2]
                lagged = sequence[-1 - window]
                features = np.concatenate(
                    (current, current - previous, (current - lagged) / window), axis=1
                )
                delta = predict(model, features)
            sequence.append(np.clip(current + delta, -5.0, 5.0))
        actual = trace[starts + horizon]
        total_error += float(np.sum(np.abs(sequence[-1] - actual)))
        total_values += actual.size
    return total_error / total_values


def transition_evaluation(
    model: dict,
    normal_raw: list[np.ndarray],
    normal: list[np.ndarray],
    selection_raw: list[np.ndarray],
    selection: list[np.ndarray],
    columns: tuple[str, ...],
) -> dict:
    action_threshold, action_mean = fit_action_baseline(normal_raw, normal, columns)

    def evaluate(kind: str, current_model: dict | None) -> dict:
        values = {
            f"h{horizon}_normalized_mae": rollout_error(
                current_model,
                selection,
                selection_raw,
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
    for trace in selection:
        features, target = temporal.signal_examples(trace, model["context_seconds"])
        predicted.append(predict(model, features))
        actual.append(target)
    variance_ratio = float(
        np.var(np.concatenate(predicted))
        / max(float(np.var(np.concatenate(actual))), 1e-12)
    )
    requirements = {
        "all_predictions_finite": bool(
            all(np.isfinite(item).all() for item in predicted)
        ),
        "beats_persistence_geometric_error_relative": candidate[
            "geometric_h1_h3_h5_error"
        ]
        <= persistence["geometric_h1_h3_h5_error"] * 0.95,
        "beats_per_action_mean_geometric_error_relative": candidate[
            "geometric_h1_h3_h5_error"
        ]
        <= per_action["geometric_h1_h3_h5_error"] * 0.98,
        "anti_collapse_variance_ratio": variance_ratio >= 0.10,
    }
    return {
        "persistence": persistence,
        "per_proxy_action_mean": per_action,
        "candidate": candidate,
        "anti_collapse_variance_ratio": variance_ratio,
        "requirements": requirements,
        "action_proxy_threshold": action_threshold,
        "action_mean": action_mean,
    }


def model_metadata(model: dict) -> dict:
    return {
        key: value
        for key, value in model.items()
        if not isinstance(value, (np.ndarray, dict))
    }


def compact_evaluation(evaluation: dict) -> dict:
    detection = evaluation["source_detection"]
    compact_detection = {
        key: value
        for key, value in detection.items()
        if key not in ("detected_attack_ids", "missed_attack_ids", "per_file")
    }
    return {**evaluation, "source_detection": compact_detection}


def model_arrays(prefix: str, model: dict) -> dict[str, np.ndarray]:
    if model["kind"] == "ridge":
        return {f"{prefix}.coefficients": model["coefficients"]}
    result = {}
    for group in ("encoder", "target_encoder", "predictor", "delta_head"):
        for key, value in model[group].items():
            result[f"{prefix}.{group}.{key}"] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--skip-jepa", action="store_true")
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    require_target_final_sealed(protocol, TARGET_CACHE)
    for item in protocol["target_domain_normal_files"]:
        valid, reason = fetch_v2.verify(TARGET_CACHE / item["name"], item)
        if not valid:
            raise RuntimeError(
                f"target normal file is not verified: {item['name']} {reason}"
            )

    source_names = source_columns()
    target_names = target_columns()
    source_fit_raw = [
        read_values(SOURCE_CACHE / name, source_names) for name in SOURCE_FIT
    ]
    source_calibration_raw = read_values(
        SOURCE_CACHE / SOURCE_CALIBRATION, source_names
    )
    source_selection_raw = [
        read_values(SOURCE_CACHE / signal, source_names)
        for signal, _, _ in SOURCE_SELECTION
    ]
    target_fit_raw = [
        read_values(TARGET_CACHE / name, target_names) for name in TARGET_FIT
    ]
    target_calibration_raw = read_values(
        TARGET_CACHE / TARGET_CALIBRATION, target_names
    )
    source_center, source_scale = fit_normalizer(source_fit_raw)
    target_center, target_scale = fit_normalizer(target_fit_raw)
    source_fit = [
        normalize(item, source_center, source_scale) for item in source_fit_raw
    ]
    source_calibration = normalize(source_calibration_raw, source_center, source_scale)
    source_selection = [
        normalize(item, source_center, source_scale) for item in source_selection_raw
    ]
    target_fit = [
        normalize(item, target_center, target_scale) for item in target_fit_raw
    ]
    target_calibration = normalize(target_calibration_raw, target_center, target_scale)

    source_pca_mean, source_components = fit_pca(source_fit)
    target_pca_mean, target_components = fit_pca(target_fit)
    source_models = []
    target_models = []
    for window in (5, 15, 30):
        source_models.append(fit_ridge(source_fit, window))
        target_models.append(fit_ridge(target_fit, window))
    if not args.skip_jepa:
        for window in (5, 15, 30):
            source_models.append(fit_jepa(source_fit, window))
            target_models.append(fit_jepa(target_fit, window))

    target_action_threshold, target_action_mean = fit_action_baseline(
        target_fit_raw, target_fit, target_names
    )
    transitions = []
    all_evaluations = []
    eligible = []
    for source_model, target_model in zip(source_models, target_models, strict=True):
        if (
            source_model["kind"],
            source_model["context_seconds"],
        ) != (target_model["kind"], target_model["context_seconds"]):
            raise AssertionError("source and target model grids diverged")
        window = source_model["context_seconds"]
        current_labels = [
            labels_23(label)[window + 1 :] for _, label, _ in SOURCE_SELECTION
        ]
        transition = transition_evaluation(
            source_model,
            source_fit_raw,
            source_fit,
            source_selection_raw,
            source_selection,
            source_names,
        )
        transition_index = len(transitions)
        transitions.append(
            {
                "model": model_metadata(source_model),
                **{k: v for k, v in transition.items() if k not in ("action_mean",)},
            }
        )

        source_prediction_calibration = prediction_residual(
            source_model, source_calibration
        )
        source_prediction_selection = [
            prediction_residual(source_model, trace) for trace in source_selection
        ]
        target_prediction_calibration = prediction_residual(
            target_model, target_calibration
        )
        source_prediction_median, source_prediction_mad = robust_standardizer(
            source_prediction_calibration
        )
        target_prediction_median, target_prediction_mad = robust_standardizer(
            target_prediction_calibration
        )
        source_prediction_calibration_z = standardized(
            source_prediction_calibration,
            source_prediction_median,
            source_prediction_mad,
        )
        source_prediction_selection_z = [
            standardized(item, source_prediction_median, source_prediction_mad)
            for item in source_prediction_selection
        ]
        target_prediction_calibration_z = standardized(
            target_prediction_calibration,
            target_prediction_median,
            target_prediction_mad,
        )

        for rank in (8, 16, 32):
            source_reconstruction_calibration = reconstruction_residual(
                source_calibration[window + 1 :],
                source_pca_mean,
                source_components,
                rank,
            )
            source_reconstruction_selection = [
                reconstruction_residual(
                    trace[window + 1 :],
                    source_pca_mean,
                    source_components,
                    rank,
                )
                for trace in source_selection
            ]
            target_reconstruction_calibration = reconstruction_residual(
                target_calibration[window + 1 :],
                target_pca_mean,
                target_components,
                rank,
            )
            source_reconstruction_median, source_reconstruction_mad = (
                robust_standardizer(source_reconstruction_calibration)
            )
            target_reconstruction_median, target_reconstruction_mad = (
                robust_standardizer(target_reconstruction_calibration)
            )
            source_reconstruction_calibration_z = standardized(
                source_reconstruction_calibration,
                source_reconstruction_median,
                source_reconstruction_mad,
            )
            source_reconstruction_selection_z = [
                standardized(
                    item, source_reconstruction_median, source_reconstruction_mad
                )
                for item in source_reconstruction_selection
            ]
            target_reconstruction_calibration_z = standardized(
                target_reconstruction_calibration,
                target_reconstruction_median,
                target_reconstruction_mad,
            )

            for prediction_weight in (0.5, 0.75, 1.0):
                if prediction_weight == 1.0 and rank != 8:
                    continue
                source_combined_calibration = (
                    prediction_weight * source_prediction_calibration_z
                    + (1.0 - prediction_weight) * source_reconstruction_calibration_z
                )
                source_combined_selection = [
                    prediction_weight * prediction
                    + (1.0 - prediction_weight) * reconstruction
                    for prediction, reconstruction in zip(
                        source_prediction_selection_z,
                        source_reconstruction_selection_z,
                        strict=True,
                    )
                ]
                target_combined_calibration = (
                    prediction_weight * target_prediction_calibration_z
                    + (1.0 - prediction_weight) * target_reconstruction_calibration_z
                )

                for top_k in (1, 3, 5, 10, 20):
                    source_base = np.mean(
                        np.partition(source_combined_calibration, -top_k, axis=1)[
                            :, -top_k:
                        ],
                        axis=1,
                    )
                    source_selection_base = [
                        np.mean(np.partition(item, -top_k, axis=1)[:, -top_k:], axis=1)
                        for item in source_combined_selection
                    ]
                    target_base = np.mean(
                        np.partition(target_combined_calibration, -top_k, axis=1)[
                            :, -top_k:
                        ],
                        axis=1,
                    )
                    for span in (1, 3, 5, 15, 30, 60, 120):
                        source_scores = ewma_fast(source_base, span)
                        selection_scores = [
                            ewma_fast(item, span) for item in source_selection_base
                        ]
                        target_scores = ewma_fast(target_base, span)
                        threshold = shared_percentile(source_scores, target_scores)
                        if threshold is None:
                            continue
                        (
                            percentile,
                            source_threshold,
                            target_threshold,
                            source_fa,
                            target_fa,
                        ) = threshold
                        detection = aggregate_detection(
                            selection_scores,
                            current_labels,
                            [item[2] for item in SOURCE_SELECTION],
                            source_threshold,
                        )
                        requirements = {
                            **transition["requirements"],
                            "attack_window_recall": detection["attack_window_recall"]
                            >= 0.70,
                            "source_normal_false_alerts_per_hour": source_fa <= 2.0,
                            "target_normal_false_alerts_per_hour": target_fa <= 2.0,
                            "source_selection_false_alerts_per_hour": detection[
                                "false_alerts_per_hour"
                            ]
                            <= 2.0,
                            "point_balanced_accuracy": detection["balanced_accuracy"]
                            >= 0.60,
                        }
                        evaluation = {
                            "model": model_metadata(source_model),
                            "transition_index": transition_index,
                            "reconstruction_rank": rank,
                            "prediction_weight": prediction_weight,
                            "top_k": top_k,
                            "ewma_span_seconds": span,
                            "percentile": percentile,
                            "source_numeric_threshold": source_threshold,
                            "target_numeric_threshold": target_threshold,
                            "source_normal_false_alerts_per_hour": source_fa,
                            "target_normal_false_alerts_per_hour": target_fa,
                            "source_detection": detection,
                            "requirements": requirements,
                            "eligible": all(requirements.values()),
                        }
                        all_evaluations.append(evaluation)
                        if evaluation["eligible"]:
                            eligible.append(
                                {
                                    "evaluation": evaluation,
                                    "source_model": source_model,
                                    "target_model": target_model,
                                    "transition": transition,
                                    "target_prediction_median": target_prediction_median,
                                    "target_prediction_mad": target_prediction_mad,
                                    "target_reconstruction_median": target_reconstruction_median,
                                    "target_reconstruction_mad": target_reconstruction_mad,
                                }
                            )
        print(
            f"{source_model['name']}: transition_g="
            f"{transition['candidate']['geometric_h1_h3_h5_error']:.6f} "
            f"eligible_scores={sum(item['evaluation']['model']['name'] == source_model['name'] for item in eligible)}",
            flush=True,
        )

    eligible.sort(
        key=lambda item: (
            -item["evaluation"]["source_detection"]["attack_window_recall"],
            -item["evaluation"]["source_detection"]["balanced_accuracy"],
            item["evaluation"]["target_normal_false_alerts_per_hour"],
            item["evaluation"]["source_detection"]["false_alert_seconds_per_hour"],
            item["transition"]["candidate"]["geometric_h1_h3_h5_error"],
        )
    )
    selected = eligible[0] if eligible else None
    report = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "amendment_id": json.loads(AMENDMENT.read_text(encoding="utf-8"))[
            "amendment_id"
        ],
        "amendment_sha256": sha256(AMENDMENT),
        "registered_final_test_open_count": 0,
        "source_schema_signals": len(source_names),
        "target_schema_signals": len(target_names),
        "rows": {
            "source_fit": sum(len(item) for item in source_fit),
            "source_calibration": len(source_calibration),
            "source_selection": sum(len(item) for item in source_selection),
            "source_attack_windows": 52,
            "target_fit": sum(len(item) for item in target_fit),
            "target_calibration": len(target_calibration),
        },
        "transition_evaluations": transitions,
        "score_evaluations": [
            compact_evaluation(evaluation) for evaluation in all_evaluations
        ],
        "eligible_candidates": len(eligible),
        "selected": None if selected is None else selected["evaluation"],
        "all_selection_gates_pass": selected is not None,
        "final_test_opened": False,
        "claim_boundary": [
            "HAI 23.05 test1 and test2 are known model-selection data in v2.",
            "HAI 21.03 train1 through train3 contain no attacks and were used only for local self-supervised fit and normal calibration.",
            "HAI 21.03 test1 through test5 remained absent during selection.",
            "The experiment tests a site-adapted training procedure, not zero-shot checkpoint transfer.",
            "The artifact remains advisory and cannot authorize or actuate.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if selected is None:
        print("No v2 candidate passed every selection gate; final tests remain sealed.")
        return 2

    evaluation = selected["evaluation"]
    target_model = selected["target_model"]
    rank = evaluation["reconstruction_rank"]
    arrays = {
        "target_center": target_center,
        "target_scale": target_scale,
        "prediction_residual_median": selected["target_prediction_median"],
        "prediction_residual_mad": selected["target_prediction_mad"],
        "pca_mean": target_pca_mean,
        "pca_components": target_components[:, :rank],
        "reconstruction_residual_median": selected["target_reconstruction_median"],
        "reconstruction_residual_mad": selected["target_reconstruction_mad"],
        "action_mean": target_action_mean,
        **model_arrays("target_model", target_model),
    }
    metadata = {
        "schema": "FERRUM_HAI_SITE_ADAPTED_V2",
        "target_signal_columns": list(target_names),
        "model": model_metadata(target_model),
        "score": {
            "reconstruction_rank": rank,
            "prediction_weight": evaluation["prediction_weight"],
            "top_k": evaluation["top_k"],
            "ewma_span_seconds": evaluation["ewma_span_seconds"],
            "percentile": evaluation["percentile"],
            "numeric_threshold": evaluation["target_numeric_threshold"],
        },
        "action_proxy_threshold": target_action_threshold,
        "authority": "advisory diagnostic only; no permit, block, approval, adapter or actuation authority",
    }
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.artifact, metadata=json.dumps(metadata, sort_keys=True), **arrays
    )
    report["selected_artifact"] = str(
        args.artifact.resolve().relative_to(ROOT)
    ).replace("\\", "/")
    report["selected_artifact_sha256"] = sha256(args.artifact)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    detection = evaluation["source_detection"]
    print(
        f"selected {target_model['name']}: source_windows="
        f"{detection['detected_attack_windows']}/52 balanced="
        f"{detection['balanced_accuracy']:.4f} target_normal_fa/h="
        f"{evaluation['target_normal_false_alerts_per_hour']:.3f}; final tests sealed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
