#!/usr/bin/env python3
"""Run the registered actuator-disabled Physical JEPA v5 sensor replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_hai_data as hai  # noqa: E402
import select_physical_jepa_v5 as selector  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402


PROTOCOL = ROOT / "docs/research/physical_jepa_recorded_hil_replay_protocol_v1.json"
AMENDMENT1 = (
    ROOT / "docs/research/physical_jepa_recorded_hil_replay_protocol_v1_amendment1.json"
)
AMENDMENT2 = (
    ROOT / "docs/research/physical_jepa_recorded_hil_replay_protocol_v1_amendment2.json"
)
PROJECTION = ROOT / "docs/research/physical_hai_v1_selection.json"
DEFAULT_OUTPUT = ROOT / "docs/research/physical_jepa_recorded_hil_replay_result_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def repository_path(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def attach_registered_positional_labels(
    trace: hai.Trace, data_path: Path, label_path: Path
) -> hai.Trace:
    data_frame = pd.read_csv(data_path, usecols=["timestamp"])
    label_frame = pd.read_csv(label_path, usecols=["timestamp", "label"])
    if len(data_frame) != len(label_frame):
        raise ValueError(f"data/label row-count mismatch: {data_path.name}")
    data_timestamps = pd.to_datetime(data_frame["timestamp"], errors="raise").to_numpy(
        dtype="datetime64[s]"
    )
    label_timestamps = pd.to_datetime(
        label_frame["timestamp"], errors="raise"
    ).to_numpy(dtype="datetime64[s]")
    if data_path.name == "hai-test2.csv":
        expected = data_timestamps.astype("datetime64[m]").astype("datetime64[s]")
    else:
        expected = data_timestamps
    if not np.array_equal(expected, label_timestamps):
        raise ValueError(f"registered positional timestamps do not align: {data_path}")
    continuous = np.diff(data_timestamps).astype("timedelta64[s]").astype(np.int64) == 1
    projected_timestamps = data_timestamps[1:][continuous]
    if not np.array_equal(projected_timestamps, trace.timestamp):
        raise ValueError(f"projection continuity mismatch: {data_path}")
    aligned = label_frame["label"].to_numpy(dtype=np.int8)[1:][continuous]
    if len(aligned) != len(trace.state):
        raise ValueError(f"projected label length mismatch: {data_path}")
    return hai.Trace(
        state=trace.state,
        next_state=trace.next_state,
        action=trace.action,
        action_features=trace.action_features,
        timestamp=trace.timestamp,
        label=aligned,
        source_file=trace.source_file,
    )


def rank_auc(labels: np.ndarray, scores: np.ndarray) -> float | None:
    positives = int(labels.sum())
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=np.float64)
    sorted_scores = scores[order]
    start = 0
    while start < len(scores):
        end = start + 1
        while end < len(scores) and sorted_scores[end] == sorted_scores[start]:
            end += 1
        ranks[order[start:end]] = 0.5 * (start + 1 + end)
        start = end
    positive_rank_sum = float(ranks[labels].sum())
    return (positive_rank_sum - positives * (positives + 1) / 2) / (
        positives * negatives
    )


def average_precision(labels: np.ndarray, scores: np.ndarray) -> float | None:
    positives = int(labels.sum())
    if positives == 0:
        return None
    order = np.argsort(-scores, kind="mergesort")
    ordered = labels[order]
    cumulative = np.cumsum(ordered)
    precision = cumulative / np.arange(1, len(ordered) + 1)
    return float(precision[ordered].sum() / positives)


def event_metrics(labels: np.ndarray, alerts: np.ndarray) -> dict:
    starts = np.flatnonzero(labels & ~np.r_[False, labels[:-1]])
    ends = np.flatnonzero(labels & ~np.r_[labels[1:], False]) + 1
    detected = sum(bool(alerts[start:end].any()) for start, end in zip(starts, ends))
    normal_alerts = alerts & ~labels
    false_starts = np.flatnonzero(normal_alerts & ~np.r_[False, normal_alerts[:-1]])
    return {
        "attack_events": int(len(starts)),
        "detected_attack_events": int(detected),
        "attack_event_recall": detected / len(starts) if len(starts) else None,
        "false_alert_events": int(len(false_starts)),
        "false_alerts_per_hour": float(len(false_starts) / (len(labels) / 3600.0)),
    }


def confusion(labels: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    alerts = scores > threshold
    tp = int(np.sum(alerts & labels))
    fp = int(np.sum(alerts & ~labels))
    tn = int(np.sum(~alerts & ~labels))
    fn = int(np.sum(~alerts & labels))
    return {
        "threshold": threshold,
        "threshold_source": "post-hoc pooled clean non-attack 99th percentile",
        "descriptive_only": True,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "true_positive_rate": tp / max(1, tp + fn),
        "false_positive_rate": fp / max(1, fp + tn),
        **event_metrics(labels, alerts),
    }


def hold_last(values: np.ndarray, dropout: np.ndarray) -> np.ndarray:
    result = values.copy()
    rows = np.arange(len(values))
    for column in range(values.shape[1]):
        valid = np.where(~dropout[:, column], rows, -1)
        valid[0] = 0
        source = np.maximum.accumulate(valid)
        result[:, column] = values[source, column]
    return result


def perturb(
    state: np.ndarray,
    features: np.ndarray,
    condition: dict,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, dict]:
    rows = np.arange(len(state))
    jitter_bound = int(condition["jitter_seconds"])
    jitter = (
        rng.integers(0, jitter_bound + 1, len(state), dtype=np.int64)
        if jitter_bound
        else np.zeros(len(state), dtype=np.int64)
    )
    delay = int(condition["sensor_delay_seconds"]) + jitter
    source = np.maximum(rows - delay, 0)
    observed = state[source].copy()
    available = np.asarray(hai.MASK, dtype=np.int64)
    dropout_probability = float(condition["dropout_probability"])
    dropout_count = 0
    if dropout_probability:
        mask = rng.random((len(state), len(available))) < dropout_probability
        dropout_count = int(mask.sum())
        observed[:, available] = hold_last(observed[:, available], mask)
    noise_standard_deviation = float(condition["noise_standard_deviation"])
    if noise_standard_deviation:
        observed[:, available] += rng.normal(
            0.0, noise_standard_deviation, (len(state), len(available))
        ).astype(np.float32)
    observed[:, available] = np.clip(observed[:, available], -1.25, 1.25)
    clipped_features = np.clip(
        features,
        -float(condition["command_feature_clip"]),
        float(condition["command_feature_clip"]),
    ).astype(np.float32)
    return (
        observed,
        clipped_features,
        {
            "mean_effective_delay_seconds": float(np.mean(delay)),
            "maximum_effective_delay_seconds": int(np.max(delay)),
            "dropped_sensor_values": dropout_count,
            "clipped_command_feature_values": int(np.sum(clipped_features != features)),
        },
    )


def predict_batched(
    weights: dict,
    state: np.ndarray,
    action: np.ndarray,
    features: np.ndarray,
    batch_size: int,
) -> tuple[np.ndarray, list[float]]:
    output = np.empty_like(state)
    timings = []
    for start in range(0, len(state), batch_size):
        end = min(start + batch_size, len(state))
        began = time.perf_counter_ns()
        output[start:end] = selector.batch_prediction(
            weights, state[start:end], action[start:end], features[start:end]
        )
        elapsed = time.perf_counter_ns() - began
        timings.append(elapsed / 1000.0 / (end - start))
    return output, timings


def row_error(predicted: np.ndarray, actual: np.ndarray) -> np.ndarray:
    mask = np.asarray(hai.MASK, dtype=np.int64)
    return np.mean(
        np.abs(predicted[:, mask] - actual[:, mask]) / simulator.STATE_RANGES[mask],
        axis=1,
    ).astype(np.float64)


def condition_metrics(
    name: str,
    errors: np.ndarray,
    labels: np.ndarray,
    metadata: dict,
    clean_mean: float,
    threshold: float,
) -> dict:
    return {
        "name": name,
        "rows": int(len(errors)),
        "masked_normalized_h1_mae": float(np.mean(errors)),
        "p95_row_error": float(np.percentile(errors, 95)),
        "p99_row_error": float(np.percentile(errors, 99)),
        "mean_error_delta_from_clean": float(np.mean(errors) - clean_mean),
        "attack_label_auroc": rank_auc(labels, errors),
        "attack_label_average_precision": average_precision(labels, errors),
        "post_hoc_detection": confusion(labels, errors, threshold),
        "perturbation_accounting": metadata,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    protocol = load(PROTOCOL)
    amendment1 = load(AMENDMENT1)
    amendment2 = load(AMENDMENT2)
    if amendment1["parent_protocol_sha256"] != sha256(PROTOCOL):
        raise ValueError("replay amendment 1 parent digest mismatch")
    if amendment2["parent_amendment_sha256"] != sha256(AMENDMENT1):
        raise ValueError("replay amendment 2 parent digest mismatch")
    projection_record = load(PROJECTION)
    statistics = projection_record["projection"]
    artifact = ROOT / protocol["frozen_artifact"]["path"]
    artifact_before = sha256(artifact)
    if artifact_before != protocol["frozen_artifact"]["sha256"]:
        raise ValueError("frozen Physical JEPA v5 artifact digest mismatch")
    weights = robustness.load_artifact(artifact)

    traces = []
    input_files = []
    for item in protocol["replay_files"]:
        data_path = ROOT / item["data"]
        label_path = ROOT / item["labels"]
        if sha256(data_path) != item["data_sha256"]:
            raise ValueError(f"data digest mismatch: {data_path}")
        if sha256(label_path) != item["labels_sha256"]:
            raise ValueError(f"label digest mismatch: {label_path}")
        trace = hai.project_trace(data_path, statistics)
        traces.append(attach_registered_positional_labels(trace, data_path, label_path))
        input_files.append(
            {
                "data": item["data"],
                "data_sha256": sha256(data_path),
                "labels": item["labels"],
                "labels_sha256": sha256(label_path),
            }
        )

    batch_size = int(protocol["timing"]["batch_size"])
    warmup = traces[0]
    for _ in range(int(protocol["timing"]["warmup_batches"])):
        selector.batch_prediction(
            weights,
            warmup.state[:batch_size],
            warmup.action[:batch_size],
            warmup.action_features[:batch_size],
        )

    conditions = []
    errors_by_condition: dict[str, np.ndarray] = {}
    labels = np.concatenate([trace.label.astype(bool) for trace in traces])
    all_timings = []
    raw_condition_data = {}
    metadata_by_condition = {}
    for condition_index, condition in enumerate(protocol["conditions"]):
        condition_errors = []
        condition_metadata = {
            "mean_effective_delay_seconds": [],
            "maximum_effective_delay_seconds": 0,
            "dropped_sensor_values": 0,
            "clipped_command_feature_values": 0,
        }
        per_trace = []
        for trace_index, trace in enumerate(traces):
            rng = np.random.default_rng(
                int(protocol["random_seed"]) + condition_index * 1009 + trace_index
            )
            observed, features, metadata = perturb(
                trace.state, trace.action_features, condition, rng
            )
            predicted, timings = predict_batched(
                weights, observed, trace.action, features, batch_size
            )
            errors = row_error(predicted, trace.next_state)
            condition_errors.append(errors)
            all_timings.extend(timings)
            condition_metadata["mean_effective_delay_seconds"].append(
                metadata["mean_effective_delay_seconds"]
            )
            condition_metadata["maximum_effective_delay_seconds"] = max(
                condition_metadata["maximum_effective_delay_seconds"],
                metadata["maximum_effective_delay_seconds"],
            )
            condition_metadata["dropped_sensor_values"] += metadata[
                "dropped_sensor_values"
            ]
            condition_metadata["clipped_command_feature_values"] += metadata[
                "clipped_command_feature_values"
            ]
            per_trace.append((observed, features, errors))
        condition_metadata["mean_effective_delay_seconds"] = float(
            np.mean(condition_metadata["mean_effective_delay_seconds"])
        )
        combined_errors = np.concatenate(condition_errors)
        errors_by_condition[condition["name"]] = combined_errors
        if condition["name"] in {"clean", "combined"}:
            raw_condition_data[condition["name"]] = per_trace
        metadata_by_condition[condition["name"]] = condition_metadata

    clean_errors = errors_by_condition["clean"]
    normal_threshold = float(np.quantile(clean_errors[~labels], 0.99))
    clean_mean = float(np.mean(clean_errors))
    for condition in protocol["conditions"]:
        conditions.append(
            condition_metrics(
                condition["name"],
                errors_by_condition[condition["name"]],
                labels,
                metadata_by_condition[condition["name"]],
                clean_mean,
                normal_threshold,
            )
        )

    recovery_times = []
    censored = 0
    total_windows = 0
    clean_p95 = float(np.percentile(clean_errors, 95))
    for trace_index, trace in enumerate(traces):
        clean_observed, clean_features, _ = raw_condition_data["clean"][trace_index]
        combined_observed, combined_features, _ = raw_condition_data["combined"][
            trace_index
        ]
        hybrid_observed = clean_observed.copy()
        hybrid_features = clean_features.copy()
        period = int(protocol["fault_recovery"]["window_period_seconds"])
        duration = int(protocol["fault_recovery"]["fault_duration_seconds"])
        maximum = int(protocol["fault_recovery"]["maximum_observation_seconds"])
        starts = np.arange(period, max(period, len(trace.state) - maximum), period)
        for start in starts:
            hybrid_observed[start : start + duration] = combined_observed[
                start : start + duration
            ]
            hybrid_features[start : start + duration] = combined_features[
                start : start + duration
            ]
        predicted, timings = predict_batched(
            weights, hybrid_observed, trace.action, hybrid_features, batch_size
        )
        all_timings.extend(timings)
        hybrid_error = row_error(predicted, trace.next_state)
        for start in starts:
            total_windows += 1
            recovery_start = start + duration
            recovery_end = min(len(trace.state), recovery_start + maximum + 1)
            candidates = np.flatnonzero(
                hybrid_error[recovery_start:recovery_end] <= 1.25 * clean_p95
            )
            if len(candidates):
                recovery_times.append(int(candidates[0]))
            else:
                censored += 1

    timing = np.asarray(all_timings, dtype=np.float64)
    artifact_after = sha256(artifact)
    all_finite = (
        all(np.isfinite(errors).all() for errors in errors_by_condition.values())
        and np.isfinite(timing).all()
    )
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "amendments": [
            {
                "id": amendment1["amendment_id"],
                "sha256": sha256(AMENDMENT1),
                "status": "superseded_before_evaluation",
            },
            {
                "id": amendment2["amendment_id"],
                "sha256": sha256(AMENDMENT2),
                "status": "applied",
            },
        ],
        "evidence_class": protocol["evidence_class"],
        "artifact": {
            "path": repository_path(artifact),
            "sha256_before": artifact_before,
            "sha256_after": artifact_after,
            "unchanged": artifact_before == artifact_after,
            "gating_flag": protocol["frozen_artifact"]["gating_flag"],
        },
        "projection": {
            "source": repository_path(PROJECTION),
            "source_sha256": sha256(PROJECTION),
            "fit_rows": statistics["fit_rows"],
            "available_state_indices": hai.MASK.tolist(),
        },
        "inputs": input_files,
        "replay": {
            "files": len(traces),
            "rows": int(sum(len(trace.state) for trace in traces)),
            "recorded_seconds": int(sum(len(trace.state) for trace in traces)),
            "attack_label_seconds": int(labels.sum()),
            "conditions": conditions,
        },
        "inference_timing": {
            "environment": "Python/NumPy host replay; not physical control-loop timing",
            "batch_size": batch_size,
            "measured_batches": int(len(timing)),
            "median_microseconds_per_row": float(np.median(timing)),
            "p95_microseconds_per_row": float(np.percentile(timing, 95)),
            "p99_microseconds_per_row": float(np.percentile(timing, 99)),
        },
        "fault_recovery": {
            "definition": "first post-window row at or below 1.25 times pooled clean p95 row error",
            "clean_p95_row_error": clean_p95,
            "windows": total_windows,
            "recovered_within_120_seconds": len(recovery_times),
            "censored_windows": censored,
            "recovery_fraction": len(recovery_times) / max(1, total_windows),
            "median_recovery_seconds": (
                float(np.median(recovery_times)) if recovery_times else None
            ),
            "p95_recovery_seconds": (
                float(np.percentile(recovery_times, 95)) if recovery_times else None
            ),
            "contact_recovery_measured": False,
        },
        "authority": {
            "mode": "actuator-disabled sensor replay",
            "actuator_delivery_attempts": 0,
            "actuator_deliveries": 0,
            "may_grant_permits": False,
            "may_issue_approvals": False,
            "may_actuate_hardware": False,
        },
        "checks": {
            "all_predictions_and_metrics_finite": bool(all_finite),
            "all_inputs_match_registered_digests": True,
            "all_registered_conditions_reported": [item["name"] for item in conditions]
            == [item["name"] for item in protocol["conditions"]],
            "both_replay_files_reported": len(input_files) == 2,
            "zero_actuator_delivery_attempts": True,
            "zero_actuator_deliveries": True,
            "artifact_unchanged": artifact_before == artifact_after,
            "claim_boundary_preserved": True,
        },
        "acceptance_gates_passed": artifact_before == artifact_after,
        "promotion_eligible": False,
        "claim_boundary": protocol["interpretation"],
        "unsupported_gaps": protocol["not_claimed"],
    }
    if not all(result["checks"].values()):
        result["acceptance_gates_passed"] = False
    if not math.isfinite(float(result["inference_timing"]["p99_microseconds_per_row"])):
        result["checks"]["all_predictions_and_metrics_finite"] = False
        result["acceptance_gates_passed"] = False
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": result["replay"]["rows"],
                "conditions": len(conditions),
                "acceptance_gates_passed": result["acceptance_gates_passed"],
            },
            indent=2,
        )
    )
    return 0 if result["acceptance_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
