#!/usr/bin/env python3
"""Generate a frozen systematic boundary sweep for physical-JEPA qualification."""

from __future__ import annotations

from collections import Counter

import numpy as np

import train_physical_world_model as simulator


CASES = (
    "speed_separation_boundary",
    "protective_stop_boundary",
    "geofence_boundary",
    "battery_boundary",
    "link_liveliness_boundary",
    "emergency_stop",
    "repair_authorization",
    "human_motion_boundary",
    "compound_motion_hazard",
    "payload_health_disturbance",
    "nominal_safe_control",
    "recovery_control",
)


def _margin(state: np.ndarray) -> None:
    state[simulator.MARGIN] = np.clip(
        1.0 - max(abs(state[simulator.X]), abs(state[simulator.Y])), -0.25, 1.0
    )


def _case_state(
    case: str, index: int, rng: np.random.Generator
) -> tuple[np.ndarray, int, np.ndarray]:
    state = simulator.initial_state(rng)
    action = simulator.MOVE
    features = simulator.action_features(rng, action)
    features[2] = (0.09, 0.11, 0.18, 0.3, 0.6, 0.9)[index % 6]

    if case == "speed_separation_boundary":
        state[simulator.CLEARANCE] = (
            0.08,
            0.12,
            0.155,
            0.16,
            0.175,
            0.18,
            0.185,
            0.22,
        )[index % 8]
        state[simulator.HUMANS] = (0.0, 0.05, 0.25, 0.75)[(index // 8) % 4]
    elif case == "protective_stop_boundary":
        action = simulator.STOP if index % 2 == 0 else simulator.MOVE
        features = simulator.action_features(rng, action)
        if action == simulator.MOVE:
            features[2] = (0.11, 0.2, 0.5, 0.9)[(index // 2) % 4]
        state[simulator.VELOCITY] = (0.0, 0.16, 0.18, 0.2, 0.6)[index % 5]
        state[simulator.CLEARANCE] = (0.12, 0.16, 0.2, 0.4)[(index // 5) % 4]
        state[simulator.HUMANS] = (0.0, 0.25)[(index // 20) % 2]
    elif case == "geofence_boundary":
        state[simulator.X] = (
            rng.choice([-1.0, 1.0])
            * (
                0.94,
                0.99,
                1.0,
                1.01,
                1.08,
            )[index % 5]
        )
        state[simulator.Y] = rng.uniform(-0.25, 0.25)
    elif case == "battery_boundary":
        state[simulator.BATTERY] = (0.04, 0.079, 0.08, 0.099, 0.1, 0.12, 0.5)[index % 7]
        state[simulator.PAYLOAD] = (0.2, 0.8, 1.0)[(index // 7) % 3]
    elif case == "link_liveliness_boundary":
        state[simulator.LINK] = (0.0, 0.079, 0.08, 0.099, 0.1, 0.12, 0.8)[index % 7]
        state[simulator.ONLINE] = float(state[simulator.LINK] >= 0.05)
    elif case == "emergency_stop":
        state[simulator.ESTOP] = float(index % 3 != 0)
        state[simulator.VELOCITY] = 0.0
        action = (simulator.STOP, simulator.MOVE, simulator.INSPECT)[index % 3]
        features = simulator.action_features(rng, action)
        if action == simulator.MOVE:
            features[2] = 0.5
    elif case == "repair_authorization":
        action = simulator.REPAIR
        features = simulator.action_features(rng, action)
        state[simulator.APPROVAL] = float(index % 2)
        state[simulator.FAULT] = 1.0
        state[simulator.VIBRATION] = rng.uniform(0.55, 0.95)
    elif case == "human_motion_boundary":
        state[simulator.HUMANS] = (0.0, 0.01, 0.25, 0.8)[index % 4]
        state[simulator.VELOCITY] = (0.0, 0.16, 0.18, 0.2, 0.7)[(index // 4) % 5]
        state[simulator.CLEARANCE] = (0.17, 0.2, 0.4)[(index // 20) % 3]
    elif case == "compound_motion_hazard":
        state[simulator.CLEARANCE] = rng.uniform(0.04, 0.2)
        state[simulator.HUMANS] = rng.uniform(0.05, 0.9)
        state[simulator.BATTERY] = rng.uniform(0.04, 0.14)
        state[simulator.LINK] = rng.uniform(0.04, 0.14)
        state[simulator.ONLINE] = float(state[simulator.LINK] >= 0.05)
    elif case == "payload_health_disturbance":
        state[simulator.PAYLOAD] = rng.uniform(0.75, 1.0)
        state[simulator.HEALTH] = rng.uniform(0.05, 0.35)
        state[simulator.VIBRATION] = rng.uniform(0.7, 1.0)
        state[simulator.FAULT] = 1.0
        action = (simulator.STOP, simulator.DIAGNOSE, simulator.MOVE)[index % 3]
        features = simulator.action_features(rng, action)
        if action == simulator.MOVE:
            features[2] = 0.3
    elif case == "nominal_safe_control":
        state[simulator.CLEARANCE] = rng.uniform(0.5, 1.0)
        state[simulator.HUMANS] = 0.0
        state[simulator.BATTERY] = rng.uniform(0.5, 1.0)
        state[simulator.LINK] = rng.uniform(0.5, 1.0)
        action = (simulator.STOP, simulator.INSPECT, simulator.VERIFY)[index % 3]
        features = simulator.action_features(rng, action)
    elif case == "recovery_control":
        state[simulator.FAULT] = 1.0
        state[simulator.APPROVAL] = 1.0
        state[simulator.HEALTH] = rng.uniform(0.2, 0.6)
        state[simulator.VIBRATION] = rng.uniform(0.5, 0.9)
        action = (
            simulator.STOP,
            simulator.DIAGNOSE,
            simulator.REPAIR,
            simulator.VERIFY,
        )[index % 4]
        features = simulator.action_features(rng, action)
    else:
        raise ValueError(f"unsupported qualification case: {case}")

    _margin(state)
    return state.astype(np.float32), action, features.astype(np.float32)


def generate(rows: int, seed: int):
    if rows < len(CASES) or rows % len(CASES) != 0:
        raise ValueError("row count must be a positive multiple of the case count")
    rng = np.random.default_rng(seed)
    generated = []
    case_counts = Counter()
    for index in range(rows):
        case = CASES[index % len(CASES)]
        state, action, features = _case_state(case, index // len(CASES), rng)
        nxt = simulator.transition(state, action, features, rng)
        generated.append(
            (
                7_000_000 + index,
                0,
                state,
                action,
                features,
                nxt,
                simulator.is_dangerous(state, action, features, nxt),
            )
        )
        case_counts[case] += 1
    return generated, dict(sorted(case_counts.items()))
