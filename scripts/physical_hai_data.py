#!/usr/bin/env python3
"""Load HAI 23.05 and project documented signals into a masked Ferrum state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "research" / "physical_hai_transfer_protocol_v1.json"
DEFAULT_CACHE = ROOT / "target" / "external-data" / "hai-23.05"

STATE_SIZE = 16
MASK = np.array([6, 8, 9, 10, 11, 12, 13, 14], dtype=np.int64)
MOVE, INSPECT, STOP = 0, 1, 6
ACTION_COUNT = 7
ACTION_FEATURE_SIZE = 3

PROCESS_CHANNELS = (
    "P1_FT01Z",
    "P1_FT02Z",
    "P1_FT03Z",
    "P1_LIT01",
    "P1_PIT01",
    "P1_PIT02",
    "P1_TIT01",
    "P1_TIT02",
    "P1_TIT03",
    "P2_SIT01",
    "P2_VIBTR01",
    "P2_VIBTR02",
    "P2_VIBTR03",
    "P2_VIBTR04",
    "P3_FIT01",
    "P3_LIT01",
    "P3_PIT01",
    "P4_LD",
    "P4_ST_LD",
)
CONTROL_CHANNELS = (
    "P1_FCV01D",
    "P1_FCV02D",
    "P1_FCV03D",
    "P1_LCV01D",
    "P1_PCV01D",
    "P1_PCV02D",
    "P1_PP01AD",
    "P1_PP01BD",
    "P1_PP02D",
    "P1_PP04D",
    "P1_PP04SP",
    "P2_AutoSD",
    "P2_ManualSD",
    "P2_OnOff",
    "P2_RTR",
    "P2_SCO",
    "P3_LCP01D",
    "P3_LCV01D",
    "P4_ST_GOV",
)
AUX_CHANNELS = (
    "P2_Emerg",
    "P2_TripEx",
    "P2_VTR01",
    "P2_VTR02",
    "P2_VTR03",
    "P2_VTR04",
)
READ_COLUMNS = ("timestamp", *PROCESS_CHANNELS, *CONTROL_CHANNELS, *AUX_CHANNELS)
ACTIVITY_CHANNELS = (
    "P1_FT01Z",
    "P1_FT02Z",
    "P1_FT03Z",
    "P3_FIT01",
    "P4_LD",
    "P4_ST_LD",
)
VIBRATION_CHANNELS = (
    "P2_VIBTR01",
    "P2_VIBTR02",
    "P2_VIBTR03",
    "P2_VIBTR04",
)
VIBRATION_LIMIT_CHANNELS = ("P2_VTR01", "P2_VTR02", "P2_VTR03", "P2_VTR04")


@dataclass(frozen=True)
class Trace:
    state: np.ndarray
    next_state: np.ndarray
    action: np.ndarray
    action_features: np.ndarray
    timestamp: np.ndarray
    label: np.ndarray | None
    source_file: str


def load_protocol() -> dict:
    return json.loads(PROTOCOL.read_text(encoding="utf-8"))


def read_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=READ_COLUMNS)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    return frame


def fit_projection(paths: list[Path]) -> dict:
    frames = [read_frame(path) for path in paths]
    values = pd.concat(
        [frame.loc[:, PROCESS_CHANNELS] for frame in frames], ignore_index=True
    ).to_numpy(dtype=np.float64)
    controls = pd.concat(
        [frame.loc[:, CONTROL_CHANNELS] for frame in frames], ignore_index=True
    ).to_numpy(dtype=np.float64)
    lower, upper = np.quantile(values, [0.005, 0.995], axis=0)
    median = np.median(values, axis=0)
    q25, q75 = np.quantile(values, [0.25, 0.75], axis=0)
    iqr = np.maximum(q75 - q25, 1e-6)
    control_lower, control_upper = np.quantile(controls, [0.005, 0.995], axis=0)
    control_scale = np.maximum(control_upper - control_lower, 1e-6)

    aggregates = []
    for frame in frames:
        raw = frame.loc[:, CONTROL_CHANNELS].to_numpy(dtype=np.float64)
        delta = np.diff(raw, axis=0) / control_scale
        aggregates.append(np.mean(np.abs(np.clip(delta, -1.0, 1.0)), axis=1))
    aggregate = np.concatenate(aggregates)
    material_threshold = max(1e-4, float(np.quantile(aggregate, 0.90)))
    return {
        "process_channels": list(PROCESS_CHANNELS),
        "control_channels": list(CONTROL_CHANNELS),
        "lower": lower.tolist(),
        "upper": upper.tolist(),
        "median": median.tolist(),
        "iqr": iqr.tolist(),
        "control_lower": control_lower.tolist(),
        "control_upper": control_upper.tolist(),
        "control_scale": control_scale.tolist(),
        "material_control_delta_threshold": material_threshold,
        "fit_rows": int(sum(len(frame) for frame in frames)),
        "fit_files": [path.name for path in paths],
    }


def _indices(names: tuple[str, ...], selected: tuple[str, ...]) -> list[int]:
    return [names.index(name) for name in selected]


def project_states(frame: pd.DataFrame, statistics: dict) -> np.ndarray:
    values = frame.loc[:, PROCESS_CHANNELS].to_numpy(dtype=np.float64)
    lower = np.asarray(statistics["lower"], dtype=np.float64)
    upper = np.asarray(statistics["upper"], dtype=np.float64)
    median = np.asarray(statistics["median"], dtype=np.float64)
    iqr = np.asarray(statistics["iqr"], dtype=np.float64)
    normalized = np.clip((values - lower) / np.maximum(upper - lower, 1e-6), 0, 1)
    robust_deviation = np.abs(values - median) / iqr

    state = np.zeros((len(frame), STATE_SIZE), dtype=np.float32)
    state[:, 2] = 1.0
    state[:, 4] = 1.0
    state[:, 5] = 1.0
    state[:, 11] = 1.0

    largest = np.partition(robust_deviation, -4, axis=1)[:, -4:]
    state[:, 6] = np.exp(-np.mean(largest, axis=1) / 3.0)
    activity_indices = _indices(PROCESS_CHANNELS, ACTIVITY_CHANNELS)
    state[:, 8] = np.mean(normalized[:, activity_indices], axis=1)

    vibration = np.abs(frame.loc[:, VIBRATION_CHANNELS].to_numpy(dtype=np.float64))
    vibration_limit = np.maximum(
        np.abs(frame.loc[:, VIBRATION_LIMIT_CHANNELS].to_numpy(dtype=np.float64)),
        1e-6,
    )
    state[:, 9] = np.clip(np.max(vibration / vibration_limit, axis=1), 0, 1)
    state[:, 10] = (np.max(robust_deviation, axis=1) > 6.0).astype(np.float32)

    finite = np.isfinite(values).all(axis=1)
    timestamp = frame["timestamp"].to_numpy(dtype="datetime64[s]")
    continuous = np.ones(len(frame), dtype=bool)
    if len(frame) > 1:
        continuous[1:] = np.diff(timestamp).astype("timedelta64[s]").astype(int) == 1
    state[:, 11] = (finite & continuous).astype(np.float32)

    load_indices = _indices(PROCESS_CHANNELS, ("P4_LD", "P4_ST_LD"))
    state[:, 12] = np.mean(normalized[:, load_indices], axis=1)
    state[:, 13] = np.clip(frame["P2_SIT01"].to_numpy(dtype=np.float64) / 3200.0, 0, 1)
    state[:, 14] = np.clip(1.0 - np.max(robust_deviation, axis=1) / 6.0, 0, 1)
    return state


def project_trace(
    path: Path,
    statistics: dict,
    label_path: Path | None = None,
) -> Trace:
    frame = read_frame(path)
    state = project_states(frame, statistics)
    timestamp = frame["timestamp"].to_numpy(dtype="datetime64[s]")
    continuous = np.diff(timestamp).astype("timedelta64[s]").astype(int) == 1

    controls = frame.loc[:, CONTROL_CHANNELS].to_numpy(dtype=np.float64)
    scale = np.asarray(statistics["control_scale"], dtype=np.float64)
    delta = np.clip(np.diff(controls, axis=0) / scale, -1.0, 1.0)
    order = np.argsort(np.abs(delta), axis=1)
    row = np.arange(len(delta))
    largest = delta[row, order[:, -1]]
    second = delta[row, order[:, -2]]
    aggregate = np.mean(np.abs(delta), axis=1)
    features = np.column_stack((largest, second, aggregate)).astype(np.float32)

    action = np.full(len(delta), INSPECT, dtype=np.int64)
    action[aggregate > statistics["material_control_delta_threshold"]] = MOVE
    emergency = frame["P2_Emerg"].to_numpy(dtype=np.float64)[1:] > 0.5
    trip = frame["P2_TripEx"].to_numpy(dtype=np.float64)[1:] < 0.5
    onoff = frame["P2_OnOff"].to_numpy(dtype=np.float64)
    demand = frame["P2_AutoSD"].to_numpy(dtype=np.float64)
    demand_to_zero = ((onoff[:-1] > 0.5) & (onoff[1:] < 0.5)) | (
        (demand[:-1] > 1.0) & (demand[1:] <= 1.0)
    )
    action[emergency | trip | demand_to_zero] = STOP

    label = None
    if label_path is not None:
        labels = pd.read_csv(label_path)
        label_timestamp = pd.to_datetime(labels["timestamp"], errors="raise").to_numpy(
            dtype="datetime64[s]"
        )
        if not np.array_equal(label_timestamp, timestamp):
            raise ValueError(f"label timestamps do not align with {path.name}")
        label = labels["label"].to_numpy(dtype=np.int8)[1:][continuous]

    return Trace(
        state=state[:-1][continuous],
        next_state=state[1:][continuous],
        action=action[continuous],
        action_features=features[continuous],
        timestamp=timestamp[1:][continuous],
        label=label,
        source_file=path.name,
    )


def concatenate(traces: list[Trace]) -> Trace:
    labels = None
    if all(trace.label is not None for trace in traces):
        labels = np.concatenate([trace.label for trace in traces])
    elif any(trace.label is not None for trace in traces):
        raise ValueError("cannot concatenate labelled and unlabelled traces")
    return Trace(
        state=np.concatenate([trace.state for trace in traces]),
        next_state=np.concatenate([trace.next_state for trace in traces]),
        action=np.concatenate([trace.action for trace in traces]),
        action_features=np.concatenate([trace.action_features for trace in traces]),
        timestamp=np.concatenate([trace.timestamp for trace in traces]),
        label=labels,
        source_file="+".join(trace.source_file for trace in traces),
    )


def action_matrix(action: np.ndarray, features: np.ndarray) -> np.ndarray:
    result = np.zeros((len(action), ACTION_COUNT + ACTION_FEATURE_SIZE), dtype=np.float32)
    result[np.arange(len(action)), action] = 1.0
    result[:, ACTION_COUNT:] = features
    return result


def make_input(trace: Trace) -> tuple[np.ndarray, np.ndarray]:
    inputs = np.concatenate(
        (trace.state, action_matrix(trace.action, trace.action_features)), axis=1
    ).astype(np.float32)
    return inputs, (trace.next_state - trace.state).astype(np.float32)
