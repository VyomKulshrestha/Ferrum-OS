#!/usr/bin/env python3
"""Select a causal HAI temporal diagnostic while keeping test2 sealed."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import physical_hai_data as hai


ROOT = Path(__file__).resolve().parents[1]
AMENDMENT = (
    ROOT / "docs" / "research" / "physical_hai_transfer_protocol_v1_amendment2.json"
)
DEFAULT_REPORT = ROOT / "docs" / "research" / "physical_hai_v1_temporal_selection.json"
DEFAULT_ARTIFACT = (
    ROOT
    / "docs"
    / "research"
    / "artifacts"
    / "physical-hai-v1"
    / "selected_temporal_model.npz"
)
FIT_NAMES = ("hai-train1.csv", "hai-train2.csv", "hai-train3.csv")
CALIBRATION_NAME = "hai-train4.csv"
VALIDATION_NAME = "hai-test1.csv"
VALIDATION_LABEL_NAME = "label-test1.csv"
SEALED_NAMES = ("hai-test2.csv", "label-test2.csv")
ATTACK_IDS = tuple(f"A{100 + index}" for index in range(1, 15))


@dataclass(frozen=True)
class SignalData:
    values: np.ndarray
    timestamp: np.ndarray
    source: str


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_sealed(cache: Path) -> None:
    present = [name for name in SEALED_NAMES if (cache / name).exists()]
    if present:
        raise RuntimeError(f"final test must remain sealed during selection: {present}")


def signal_columns(path: Path) -> tuple[str, ...]:
    columns = tuple(pd.read_csv(path, nrows=0).columns)
    if not columns or columns[0] != "timestamp" or len(columns) != 87:
        raise ValueError(f"expected timestamp plus 86 HAI signals in {path.name}")
    return columns[1:]


def read_signals(path: Path, columns: tuple[str, ...]) -> SignalData:
    frame = pd.read_csv(path, usecols=("timestamp", *columns))
    timestamp = pd.to_datetime(frame.pop("timestamp"), errors="raise").to_numpy(
        dtype="datetime64[s]"
    )
    if len(timestamp) > 1 and not np.all(
        np.diff(timestamp).astype("timedelta64[s]").astype(int) == 1
    ):
        raise ValueError(f"non-contiguous HAI trace: {path.name}")
    values = frame.loc[:, columns].to_numpy(dtype=np.float32)
    if not np.isfinite(values).all():
        raise ValueError(f"non-finite HAI values: {path.name}")
    return SignalData(values, timestamp, path.name)


def fit_signal_normalizer(traces: list[SignalData]) -> tuple[np.ndarray, np.ndarray]:
    values = np.concatenate([trace.values for trace in traces], axis=0)
    center = np.median(values, axis=0)
    lower, upper = np.quantile(values, (0.005, 0.995), axis=0)
    scale = np.maximum(upper - lower, 1e-5)
    return center.astype(np.float32), scale.astype(np.float32)


def normalize(values: np.ndarray, center: np.ndarray, scale: np.ndarray) -> np.ndarray:
    return np.clip((values - center) / scale, -5.0, 5.0).astype(np.float32)


def signal_examples(
    values: np.ndarray, window: int = 5
) -> tuple[np.ndarray, np.ndarray]:
    current = values[window:-1]
    previous = values[window - 1 : -2]
    lagged = values[: -window - 1]
    features = np.concatenate(
        (current, current - previous, (current - lagged) / window), axis=1
    )
    target_delta = values[window + 1 :] - current
    return features.astype(np.float32), target_delta.astype(np.float32)


def ridge_fit(features: np.ndarray, targets: np.ndarray, penalty: float) -> np.ndarray:
    design = np.concatenate(
        (features.astype(np.float32), np.ones((len(features), 1), dtype=np.float32)),
        axis=1,
    )
    gram = (design.T @ design).astype(np.float64)
    cross = (design.T @ targets.astype(np.float32)).astype(np.float64)
    regularizer = np.eye(gram.shape[0], dtype=np.float64) * penalty
    regularizer[-1, -1] = 0.0
    return np.linalg.solve(gram + regularizer, cross).astype(np.float32)


def ridge_predict(features: np.ndarray, coefficients: np.ndarray) -> np.ndarray:
    return features @ coefficients[:-1] + coefficients[-1]


def fit_signal_ridge(
    traces: list[SignalData], center: np.ndarray, scale: np.ndarray
) -> dict:
    features = []
    targets = []
    for trace in traces:
        x, y = signal_examples(normalize(trace.values, center, scale))
        features.append(x[::3])
        targets.append(y[::3])
    x = np.concatenate(features)
    y = np.concatenate(targets)
    return {
        "name": "multivariate_temporal_ridge",
        "kind": "ridge",
        "coefficients": ridge_fit(x, y, 0.01),
        "fit_examples": len(x),
    }


def fit_signal_jepa(
    traces: list[SignalData],
    center: np.ndarray,
    scale: np.ndarray,
    latent_size: int,
    hidden_size: int,
    seed: int,
    epochs: int,
) -> dict:
    import torch
    from torch import nn

    print(
        f"training temporal JEPA latent={latent_size} hidden={hidden_size} seed={seed}",
        flush=True,
    )
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    contexts = []
    targets = []
    for trace in traces:
        x, y = signal_examples(normalize(trace.values, center, scale))
        contexts.append(x[::3])
        targets.append(y[::3])
    x = np.concatenate(contexts)
    y = np.concatenate(targets)
    order = np.arange(len(x))
    validation = order % 10 == 0
    train_x = torch.from_numpy(x[~validation])
    train_y = torch.from_numpy(y[~validation])
    val_x = torch.from_numpy(x[validation]).to(device)
    val_y = torch.from_numpy(y[validation]).to(device)
    signal_size = y.shape[1]

    class Encoder(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.layers = nn.Sequential(
                nn.Linear(signal_size, hidden_size),
                nn.GELU(approximate="tanh"),
                nn.Linear(hidden_size, latent_size),
                nn.LayerNorm(latent_size),
            )

        def forward(self, values):
            return self.layers(values)

    class Predictor(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.layers = nn.Sequential(
                nn.Linear(latent_size + signal_size * 2, hidden_size),
                nn.GELU(approximate="tanh"),
                nn.Linear(hidden_size, latent_size),
            )

        def forward(self, values):
            return self.layers(values)

    class DeltaHead(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.layers = nn.Sequential(
                nn.Linear(latent_size + signal_size * 2, hidden_size),
                nn.GELU(approximate="tanh"),
                nn.Linear(hidden_size, signal_size),
            )

        def forward(self, values):
            return self.layers(values)

    encoder = Encoder().to(device)
    target_encoder = copy.deepcopy(encoder).to(device)
    target_encoder.requires_grad_(False)
    predictor = Predictor().to(device)
    delta_head = DeltaHead().to(device)
    optimizer = torch.optim.AdamW(
        list(encoder.parameters())
        + list(predictor.parameters())
        + list(delta_head.parameters()),
        lr=1e-3,
        weight_decay=1e-5,
    )
    generator = torch.Generator().manual_seed(seed)
    best = None
    best_loss = float("inf")
    patience = 0
    batch_size = 4096
    for epoch in range(epochs):
        permutation = torch.randperm(len(train_x), generator=generator)
        encoder.train()
        predictor.train()
        delta_head.train()
        for start in range(0, len(permutation), batch_size):
            indices = permutation[start : start + batch_size]
            context = train_x[indices].to(device)
            target_delta = train_y[indices].to(device)
            current = context[:, :signal_size]
            temporal = context[:, signal_size:]
            online = encoder(current)
            joined = torch.cat((online, temporal), dim=1)
            predicted_latent = predictor(joined)
            predicted_delta = delta_head(joined)
            with torch.no_grad():
                target_latent = target_encoder(current + target_delta)
            latent_loss = torch.mean((predicted_latent - target_latent) ** 2)
            delta_loss = torch.mean((predicted_delta - target_delta) ** 2)
            standard_deviation = torch.sqrt(
                predicted_latent.var(dim=0, unbiased=False) + 1e-4
            )
            variance_loss = torch.mean(torch.relu(0.25 - standard_deviation))
            loss = latent_loss + 10.0 * delta_loss + 0.1 * variance_loss
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            with torch.no_grad():
                for target_parameter, parameter in zip(
                    target_encoder.parameters(), encoder.parameters(), strict=True
                ):
                    target_parameter.mul_(0.996).add_(parameter, alpha=0.004)

        encoder.eval()
        predictor.eval()
        delta_head.eval()
        with torch.no_grad():
            current = val_x[:, :signal_size]
            temporal = val_x[:, signal_size:]
            online = encoder(current)
            joined = torch.cat((online, temporal), dim=1)
            predicted_latent = predictor(joined)
            predicted_delta = delta_head(joined)
            target_latent = target_encoder(current + val_y)
            validation_loss = float(
                torch.mean((predicted_latent - target_latent) ** 2)
                + 10.0 * torch.mean((predicted_delta - val_y) ** 2)
            )
        if validation_loss < best_loss - 1e-7:
            best_loss = validation_loss
            best = {
                "encoder": copy.deepcopy(encoder.state_dict()),
                "target_encoder": copy.deepcopy(target_encoder.state_dict()),
                "predictor": copy.deepcopy(predictor.state_dict()),
                "delta_head": copy.deepcopy(delta_head.state_dict()),
                "epoch": epoch + 1,
            }
            patience = 0
        else:
            patience += 1
            if patience >= 6:
                break
        if epoch == 0 or (epoch + 1) % 5 == 0:
            print(
                f"  epoch={epoch + 1} validation_objective={validation_loss:.8f} "
                f"best={best_loss:.8f}",
                flush=True,
            )
    if best is None:
        raise RuntimeError("JEPA training did not produce a checkpoint")

    def numpy_state(state: dict) -> dict[str, np.ndarray]:
        return {key: value.detach().cpu().numpy() for key, value in state.items()}

    return {
        "name": f"temporal_jepa_l{latent_size}_h{hidden_size}_seed{seed}",
        "kind": "jepa",
        "latent_size": latent_size,
        "hidden_size": hidden_size,
        "seed": seed,
        "epochs": best["epoch"],
        "validation_objective": best_loss,
        "encoder": numpy_state(best["encoder"]),
        "target_encoder": numpy_state(best["target_encoder"]),
        "predictor": numpy_state(best["predictor"]),
        "delta_head": numpy_state(best["delta_head"]),
        "fit_examples": len(x),
    }


def torch_linear(values: np.ndarray, state: dict, prefix: str) -> np.ndarray:
    weight = state[f"{prefix}.weight"]
    bias = state[f"{prefix}.bias"]
    return values @ weight.T + bias


def torch_gelu(values: np.ndarray) -> np.ndarray:
    return (
        0.5
        * values
        * (1.0 + np.tanh(np.sqrt(2.0 / np.pi) * (values + 0.044715 * values**3)))
    )


def layer_norm(values: np.ndarray, state: dict, prefix: str) -> np.ndarray:
    centered = values - np.mean(values, axis=1, keepdims=True)
    normalized = centered / np.sqrt(np.var(values, axis=1, keepdims=True) + 1e-5)
    return normalized * state[f"{prefix}.weight"] + state[f"{prefix}.bias"]


def jepa_signal_predict(model: dict, features: np.ndarray) -> np.ndarray:
    signal_size = features.shape[1] // 3
    current = features[:, :signal_size]
    temporal = features[:, signal_size:]
    encoded = torch_gelu(torch_linear(current, model["encoder"], "layers.0"))
    encoded = torch_linear(encoded, model["encoder"], "layers.2")
    encoded = layer_norm(encoded, model["encoder"], "layers.3")
    joined = np.concatenate((encoded, temporal), axis=1)
    hidden = torch_gelu(torch_linear(joined, model["delta_head"], "layers.0"))
    return torch_linear(hidden, model["delta_head"], "layers.2").astype(np.float32)


def signal_residuals(
    model: dict, trace: SignalData, center: np.ndarray, scale: np.ndarray
) -> np.ndarray:
    features, target = signal_examples(normalize(trace.values, center, scale))
    if model["kind"] == "ridge":
        predicted = ridge_predict(features, model["coefficients"])
    elif model["kind"] == "jepa":
        predicted = jepa_signal_predict(model, features)
    else:
        raise ValueError(model["kind"])
    return np.abs(target - predicted).astype(np.float32)


def state_features(trace: hai.Trace, window: int = 5) -> tuple[np.ndarray, np.ndarray]:
    current = trace.state[window:]
    previous = trace.state[window - 1 : -1]
    lagged = trace.state[:-window]
    rolling = np.stack(
        [
            trace.state[window - offset : len(trace.state) - offset]
            for offset in range(window)
        ],
        axis=0,
    ).mean(axis=0)
    actions = hai.action_matrix(trace.action[window:], trace.action_features[window:])
    features = np.concatenate(
        (
            current[:, hai.MASK],
            (current - previous)[:, hai.MASK],
            ((current - lagged) / window)[:, hai.MASK],
            (rolling - current)[:, hai.MASK],
            actions,
        ),
        axis=1,
    )
    target = (trace.next_state[window:] - current)[:, hai.MASK]
    return features.astype(np.float32), target.astype(np.float32)


def fit_state_predictor(traces: list[hai.Trace]) -> dict:
    gram = None
    cross = None
    examples = 0
    for trace in traces:
        features, target = state_features(trace)
        design = np.concatenate(
            (features, np.ones((len(features), 1), dtype=np.float32)), axis=1
        )
        current_gram = (design.T @ design).astype(np.float64)
        current_cross = (design.T @ target).astype(np.float64)
        gram = current_gram if gram is None else gram + current_gram
        cross = current_cross if cross is None else cross + current_cross
        examples += len(features)
    regularizer = np.eye(gram.shape[0], dtype=np.float64) * 0.001
    regularizer[-1, -1] = 0.0
    return {
        "coefficients": np.linalg.solve(gram + regularizer, cross).astype(np.float32),
        "window": 5,
        "fit_examples": examples,
    }


def action_mean(traces: list[hai.Trace]) -> np.ndarray:
    totals = np.zeros((hai.ACTION_COUNT, hai.STATE_SIZE), dtype=np.float64)
    counts = np.zeros(hai.ACTION_COUNT, dtype=np.int64)
    for trace in traces:
        delta = trace.next_state - trace.state
        for action in range(hai.ACTION_COUNT):
            selected = delta[trace.action == action]
            totals[action] += selected.sum(axis=0)
            counts[action] += len(selected)
    nonzero = counts > 0
    totals[nonzero] /= counts[nonzero, None]
    return totals.astype(np.float32)


def state_model_delta(
    model: dict,
    sequence: list[np.ndarray],
    action: np.ndarray,
    action_features: np.ndarray,
) -> np.ndarray:
    window = model["window"]
    current = sequence[-1]
    previous = sequence[-2]
    lagged = sequence[-1 - window]
    rolling = np.stack(sequence[-window:], axis=0).mean(axis=0)
    features = np.concatenate(
        (
            current[:, hai.MASK],
            (current - previous)[:, hai.MASK],
            ((current - lagged) / window)[:, hai.MASK],
            (rolling - current)[:, hai.MASK],
            hai.action_matrix(action, action_features),
        ),
        axis=1,
    )
    masked = ridge_predict(features, model["coefficients"])
    result = np.zeros_like(current)
    result[:, hai.MASK] = masked
    return result


def rollout_error(
    trace: hai.Trace,
    horizon: int,
    kind: str,
    state_model: dict | None = None,
    mean: np.ndarray | None = None,
) -> float:
    window = 5
    count = len(trace.state) - window - horizon + 1
    starts = np.arange(window, window + count)
    sequence = [trace.state[starts - offset].copy() for offset in range(window, -1, -1)]
    for offset in range(horizon):
        current = sequence[-1]
        if kind == "persistence":
            delta = np.zeros_like(current)
        elif kind == "action_mean":
            delta = mean[trace.action[starts + offset]]
        elif kind == "temporal_ridge":
            delta = state_model_delta(
                state_model,
                sequence,
                trace.action[starts + offset],
                trace.action_features[starts + offset],
            )
        else:
            raise ValueError(kind)
        predicted = current + delta
        predicted[:, :2] = np.clip(predicted[:, :2], -1.25, 1.25)
        predicted[:, 2:] = np.clip(predicted[:, 2:], 0.0, 1.0)
        sequence.append(predicted)
    actual = trace.next_state[starts + horizon - 1]
    return float(np.mean(np.abs(sequence[-1][:, hai.MASK] - actual[:, hai.MASK])))


def transition_evaluation(
    trace: hai.Trace, kind: str, state_model: dict | None = None, mean=None
) -> dict:
    rollout = {
        f"h{horizon}_normalized_mae": rollout_error(
            trace, horizon, kind, state_model, mean
        )
        for horizon in (1, 3, 5)
    }
    return {
        "rollout": rollout,
        "geometric_h1_h3_h5_error": math.prod(rollout.values()) ** (1.0 / 3.0),
    }


def rolling_alerts(scores: np.ndarray, threshold: float) -> np.ndarray:
    exceed = scores > threshold
    count = np.convolve(exceed.astype(np.int8), np.ones(5, dtype=np.int8), mode="full")[
        : len(exceed)
    ]
    return count >= 3


def event_starts(alerts: np.ndarray, cooldown: int = 30) -> list[int]:
    starts = []
    previous = False
    next_allowed = 0
    for index, value in enumerate(alerts):
        if value and not previous and index >= next_allowed:
            starts.append(index)
            next_allowed = index + cooldown
        previous = bool(value)
    return starts


def attack_windows(labels: np.ndarray) -> list[tuple[int, int]]:
    changes = np.diff(np.pad(labels.astype(np.int8), (1, 1)))
    return list(
        zip(
            np.flatnonzero(changes == 1).tolist(),
            np.flatnonzero(changes == -1).tolist(),
            strict=True,
        )
    )


def detection_metrics(scores, labels, threshold, duration_hours) -> dict:
    alerts = rolling_alerts(scores, threshold)
    labels = labels.astype(bool)
    tp = int(np.sum(alerts & labels))
    fp = int(np.sum(alerts & ~labels))
    tn = int(np.sum(~alerts & ~labels))
    fn = int(np.sum(~alerts & labels))
    windows = attack_windows(labels)
    detected_mask = [bool(np.any(alerts[start:end])) for start, end in windows]
    detected_ids = [
        ATTACK_IDS[index] for index, value in enumerate(detected_mask) if value
    ]
    missed_ids = [
        ATTACK_IDS[index] for index, value in enumerate(detected_mask) if not value
    ]
    false_starts = sum(not labels[index] for index in event_starts(alerts))
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
        "attack_windows": len(windows),
        "detected_attack_windows": sum(detected_mask),
        "attack_window_recall": sum(detected_mask) / max(1, len(windows)),
        "detected_attack_ids": detected_ids,
        "missed_attack_ids": missed_ids,
        "false_alert_events": false_starts,
        "false_alerts_per_hour": false_starts / max(duration_hours, 1e-9),
        "false_alert_seconds_per_hour": fp / max(duration_hours, 1e-9),
    }


def calibrate_threshold(scores: np.ndarray) -> tuple[float, dict]:
    duration_hours = len(scores) / 3600.0
    labels = np.zeros(len(scores), dtype=np.int8)
    grid = np.unique(
        np.concatenate(
            (np.linspace(0.90, 0.999, 100), np.linspace(0.9991, 0.99999, 90))
        )
    )
    for quantile in grid:
        threshold = float(np.quantile(scores, quantile))
        metrics = detection_metrics(scores, labels, threshold, duration_hours)
        if metrics["false_alerts_per_hour"] <= 2.0:
            return threshold, {**metrics, "quantile": float(quantile)}
    threshold = float(np.max(scores))
    return threshold, {
        **detection_metrics(scores, labels, threshold, duration_hours),
        "quantile": 1.0,
    }


def ewma(values: np.ndarray, span: int) -> np.ndarray:
    if span == 1:
        return values.copy()
    alpha = 2.0 / (span + 1.0)
    result = np.empty_like(values)
    result[0] = values[0]
    for index in range(1, len(values)):
        result[index] = alpha * values[index] + (1.0 - alpha) * result[index - 1]
    return result


def aggregate_residuals(standardized: np.ndarray, top_k: int, span: int) -> np.ndarray:
    largest = np.partition(standardized, -top_k, axis=1)[:, -top_k:]
    return ewma(np.mean(largest, axis=1), span)


def select_score(
    calibration_residual: np.ndarray,
    validation_residual: np.ndarray,
    labels: np.ndarray,
) -> tuple[dict | None, list[dict], np.ndarray, np.ndarray]:
    median = np.median(calibration_residual, axis=0)
    mad = np.maximum(np.median(np.abs(calibration_residual - median), axis=0), 1e-5)
    calibration = np.abs(calibration_residual - median) / mad
    validation = np.abs(validation_residual - median) / mad
    evaluations = []
    for top_k in (1, 3, 5, 10, 20):
        for span in (1, 3, 5, 15, 30, 60, 120):
            calibration_scores = aggregate_residuals(calibration, top_k, span)
            validation_scores = aggregate_residuals(validation, top_k, span)
            threshold, normal = calibrate_threshold(calibration_scores)
            detection = detection_metrics(
                validation_scores, labels, threshold, len(validation_scores) / 3600.0
            )
            eligible = (
                detection["attack_window_recall"] >= 0.70
                and detection["false_alerts_per_hour"] <= 2.0
                and detection["balanced_accuracy"] >= 0.60
            )
            evaluations.append(
                {
                    "top_k": top_k,
                    "ewma_span_seconds": span,
                    "threshold": threshold,
                    "normal_calibration": normal,
                    "validation_detection": detection,
                    "eligible_detection": eligible,
                }
            )
    eligible = [item for item in evaluations if item["eligible_detection"]]
    eligible.sort(
        key=lambda item: (
            -item["validation_detection"]["attack_window_recall"],
            -item["validation_detection"]["balanced_accuracy"],
            item["validation_detection"]["false_alerts_per_hour"],
            item["ewma_span_seconds"],
            item["top_k"],
        )
    )
    return (eligible[0] if eligible else None), evaluations, median, mad


def signal_latency(model: dict, sample: SignalData, center, scale) -> dict:
    features, _ = signal_examples(normalize(sample.values[:1030], center, scale))
    samples = []
    for _ in range(25):
        start = time.perf_counter_ns()
        if model["kind"] == "ridge":
            ridge_predict(features, model["coefficients"])
        else:
            jepa_signal_predict(model, features)
        samples.append((time.perf_counter_ns() - start) / len(features) / 1000.0)
    return {
        "median_microseconds_per_row": float(np.median(samples)),
        "p99_microseconds_per_row": float(np.quantile(samples, 0.99)),
    }


def serializable_model_metadata(model: dict) -> dict:
    return {
        key: value
        for key, value in model.items()
        if not isinstance(value, (np.ndarray, dict))
    }


def save_artifact(
    path: Path,
    selected: dict,
    state_model: dict,
    columns: tuple[str, ...],
    center: np.ndarray,
    scale: np.ndarray,
    residual_median: np.ndarray,
    residual_mad: np.ndarray,
    report_sha256: str,
) -> None:
    signal_model = selected["model"]
    arrays = {
        "signal_center": center,
        "signal_scale": scale,
        "residual_median": residual_median,
        "residual_mad": residual_mad,
        "state_coefficients": state_model["coefficients"],
    }
    if signal_model["kind"] == "ridge":
        arrays["signal_coefficients"] = signal_model["coefficients"]
    else:
        for group in ("encoder", "target_encoder", "predictor", "delta_head"):
            for key, value in signal_model[group].items():
                arrays[f"{group}.{key}"] = value
    metadata = {
        "schema": "FERRUM_HAI_TEMPORAL_V1",
        "signal_columns": list(columns),
        "signal_model": serializable_model_metadata(signal_model),
        "score": selected["score"],
        "state_window_seconds": state_model["window"],
        "selection_report_sha256_before_artifact": report_sha256,
        "authority": "advisory diagnostic only; no permit, block, approval, adapter or actuation authority",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, metadata=json.dumps(metadata, sort_keys=True), **arrays)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=hai.DEFAULT_CACHE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--skip-jepa", action="store_true")
    args = parser.parse_args()
    require_sealed(args.cache)

    amendment = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    columns = signal_columns(args.cache / FIT_NAMES[0])
    signal_fit = [read_signals(args.cache / name, columns) for name in FIT_NAMES]
    signal_calibration = read_signals(args.cache / CALIBRATION_NAME, columns)
    signal_validation = read_signals(args.cache / VALIDATION_NAME, columns)
    center, scale = fit_signal_normalizer(signal_fit)

    protocol = hai.load_protocol()
    fit_paths = [
        args.cache / item["name"] for item in protocol["dataset"]["train_files"]
    ]
    projection = hai.fit_projection(fit_paths)
    state_fit = [hai.project_trace(path, projection) for path in fit_paths]
    state_validation = hai.project_trace(
        args.cache / VALIDATION_NAME, projection, args.cache / VALIDATION_LABEL_NAME
    )
    labels = pd.read_csv(args.cache / VALIDATION_LABEL_NAME)["label"].to_numpy(
        dtype=np.int8
    )[6:]
    if len(labels) != len(signal_validation.values) - 6:
        raise ValueError(
            "validation labels do not align with the five-second signal context"
        )

    state_model = fit_state_predictor(state_fit)
    mean = action_mean(state_fit)
    persistence = transition_evaluation(state_validation, "persistence")
    action_baseline = transition_evaluation(state_validation, "action_mean", mean=mean)
    temporal = transition_evaluation(
        state_validation, "temporal_ridge", state_model=state_model
    )
    validation_state_features, actual_delta = state_features(state_validation)
    predicted_delta = ridge_predict(
        validation_state_features, state_model["coefficients"]
    )
    variance_ratio = float(
        np.var(predicted_delta) / max(float(np.var(actual_delta)), 1e-12)
    )
    transition_requirements = {
        "all_predictions_finite": bool(np.isfinite(predicted_delta).all()),
        "beats_persistence_geometric_error_relative": temporal[
            "geometric_h1_h3_h5_error"
        ]
        <= persistence["geometric_h1_h3_h5_error"] * 0.95,
        "beats_per_action_mean_geometric_error_relative": temporal[
            "geometric_h1_h3_h5_error"
        ]
        <= action_baseline["geometric_h1_h3_h5_error"] * 0.98,
        "anti_collapse_variance_ratio": variance_ratio >= 0.10,
    }

    models = [fit_signal_ridge(signal_fit, center, scale)]
    if not args.skip_jepa:
        for item in amendment["all_signal_predictor"]["jepa_grid"]:
            models.append(
                fit_signal_jepa(
                    signal_fit,
                    center,
                    scale,
                    item["latent_size"],
                    item["hidden_size"],
                    item["seed"],
                    amendment["all_signal_predictor"]["jepa_epochs_max"],
                )
            )

    evaluations = []
    candidates = []
    for model in models:
        calibration_residual = signal_residuals(
            model, signal_calibration, center, scale
        )
        validation_residual = signal_residuals(model, signal_validation, center, scale)
        score, grid, residual_median, residual_mad = select_score(
            calibration_residual, validation_residual, labels
        )
        evaluation = {
            "model": serializable_model_metadata(model),
            "selected_score": score,
            "score_grid": grid,
            "latency": signal_latency(model, signal_validation, center, scale),
            "transition_requirements": transition_requirements,
            "eligible": score is not None and all(transition_requirements.values()),
        }
        evaluations.append(evaluation)
        if evaluation["eligible"]:
            candidates.append(
                {
                    "model": model,
                    "score": score,
                    "residual_median": residual_median,
                    "residual_mad": residual_mad,
                    "latency": evaluation["latency"],
                }
            )
        detection = None if score is None else score["validation_detection"]
        print(
            f"{model['name']}: "
            + (
                "no eligible detection score"
                if detection is None
                else f"windows={detection['detected_attack_windows']}/14 "
                f"balanced={detection['balanced_accuracy']:.4f} "
                f"false_alerts/h={detection['false_alerts_per_hour']:.3f}"
            )
        )

    candidates.sort(
        key=lambda item: (
            -item["score"]["validation_detection"]["attack_window_recall"],
            -item["score"]["validation_detection"]["balanced_accuracy"],
            item["score"]["validation_detection"]["false_alerts_per_hour"],
            item["score"]["ewma_span_seconds"],
            item["score"]["top_k"],
            item["model"]["name"],
        )
    )
    selected = candidates[0] if candidates else None
    report = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "amendment_id": amendment["amendment_id"],
        "amendment_sha256": sha256(AMENDMENT),
        "registered_final_test_open_count": 0,
        "rows": {
            "fit_seconds": int(sum(len(trace.values) for trace in signal_fit)),
            "fit_signal_examples": int(
                sum((len(trace.values) - 6) // 3 for trace in signal_fit)
            ),
            "normal_calibration_seconds": len(signal_calibration.values),
            "validation_seconds": len(signal_validation.values),
            "validation_attack_seconds": int(labels.sum()),
            "validation_attack_windows": len(attack_windows(labels)),
        },
        "signals": {"count": len(columns), "columns": list(columns)},
        "masked_transition": {
            "persistence": persistence,
            "per_proxy_action_mean": action_baseline,
            "temporal_ridge": temporal,
            "anti_collapse_variance_ratio": variance_ratio,
            "requirements": transition_requirements,
        },
        "signal_model_evaluations": evaluations,
        "selected_model": None if selected is None else selected["model"]["name"],
        "selected_score": None if selected is None else selected["score"],
        "all_validation_gates_pass": selected is not None,
        "final_test_opened": False,
        "claim_boundary": [
            "HAI test1 labels informed amendment2 and selected the model and score; these are validation results.",
            "HAI test2 remained unopened and may be evaluated exactly once after this selection is committed.",
            "HAI is external recorded HIL/testbed evidence, not a field incident or Ferrum hardware trial.",
            "The selected model has advisory diagnostic authority only and is not a safety certification.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if selected is None:
        print(
            "No candidate passed every unchanged validation gate; test2 remains sealed."
        )
        return 2
    report_hash = sha256(args.report)
    save_artifact(
        args.artifact,
        selected,
        state_model,
        columns,
        center,
        scale,
        selected["residual_median"],
        selected["residual_mad"],
        report_hash,
    )
    report["selected_artifact"] = str(
        args.artifact.resolve().relative_to(ROOT)
    ).replace("\\", "/")
    report["selected_artifact_sha256"] = sha256(args.artifact)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"selected {selected['model']['name']} -> {args.artifact}; final test remains sealed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
