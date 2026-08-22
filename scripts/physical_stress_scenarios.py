#!/usr/bin/env python3
"""Generate split-disjoint valid edge-state trajectories for physical JEPA fitting."""

from __future__ import annotations

from collections import Counter

import numpy as np

import train_physical_world_model as simulator


PARTITION_OFFSETS = {"train": 4_000_000, "validation": 5_000_000, "test": 6_000_000}
PARTITION_SEED_OFFSETS = {"train": 11, "validation": 29, "test": 47}
CASES = (
    "geofence_edge",
    "low_clearance",
    "human_proximity",
    "low_battery",
    "weak_link",
    "heavy_payload",
    "high_vibration",
    "emergency_stop",
    "offline_controller",
    "repair_without_approval",
    "compound_motion_hazard",
    "recovery_state",
)


def recompute_margin(state: np.ndarray) -> None:
    state[simulator.MARGIN] = np.clip(
        1.0 - max(abs(state[simulator.X]), abs(state[simulator.Y])), -0.25, 1.0
    )


def apply_case(state: np.ndarray, case: str, rng: np.random.Generator) -> None:
    if case == "geofence_edge":
        axis = int(rng.integers(0, 2))
        state[axis] = rng.choice([-1.0, 1.0]) * rng.uniform(0.78, 1.18)
        state[1 - axis] = rng.uniform(-0.35, 0.35)
    elif case == "low_clearance":
        state[simulator.CLEARANCE] = rng.uniform(0.0, 0.24)
    elif case == "human_proximity":
        state[simulator.HUMANS] = rng.uniform(0.2, 1.0)
        state[simulator.CLEARANCE] = rng.uniform(0.08, 0.5)
    elif case == "low_battery":
        state[simulator.BATTERY] = rng.uniform(0.0, 0.16)
        state[simulator.PAYLOAD] = rng.uniform(0.55, 1.0)
    elif case == "weak_link":
        state[simulator.LINK] = rng.uniform(0.0, 0.16)
        state[simulator.ONLINE] = float(rng.random() > 0.25)
    elif case == "heavy_payload":
        state[simulator.PAYLOAD] = rng.uniform(0.8, 1.0)
        state[simulator.BATTERY] = rng.uniform(0.08, 0.45)
    elif case == "high_vibration":
        state[simulator.HEALTH] = rng.uniform(0.05, 0.35)
        state[simulator.VIBRATION] = rng.uniform(0.72, 1.0)
        state[simulator.FAULT] = 1.0
    elif case == "emergency_stop":
        state[simulator.ESTOP] = 1.0
    elif case == "offline_controller":
        state[simulator.ONLINE] = 0.0
        state[simulator.LINK] = rng.uniform(0.0, 0.12)
    elif case == "repair_without_approval":
        state[simulator.APPROVAL] = 0.0
        state[simulator.FAULT] = 1.0
        state[simulator.VIBRATION] = rng.uniform(0.6, 1.0)
    elif case == "compound_motion_hazard":
        state[simulator.CLEARANCE] = rng.uniform(0.0, 0.2)
        state[simulator.HUMANS] = rng.uniform(0.2, 0.8)
        state[simulator.BATTERY] = rng.uniform(0.0, 0.2)
        state[simulator.LINK] = rng.uniform(0.0, 0.2)
    elif case == "recovery_state":
        state[simulator.APPROVAL] = 1.0
        state[simulator.FAULT] = 1.0
        state[simulator.HEALTH] = rng.uniform(0.2, 0.55)
        state[simulator.VIBRATION] = rng.uniform(0.55, 0.9)
    else:
        raise ValueError(f"unsupported physical stress case: {case}")
    recompute_margin(state)


def action_for_step(case: str, episode: int, step: int) -> int:
    if case in {
        "geofence_edge",
        "low_clearance",
        "human_proximity",
        "low_battery",
        "weak_link",
        "heavy_payload",
        "compound_motion_hazard",
    }:
        plan = (
            simulator.MOVE,
            simulator.STOP,
            simulator.INSPECT,
            simulator.DIAGNOSE,
            simulator.APPROVE,
            simulator.REPAIR,
            simulator.VERIFY,
        )
    elif case in {"repair_without_approval", "recovery_state"}:
        plan = (
            simulator.REPAIR,
            simulator.STOP,
            simulator.DIAGNOSE,
            simulator.APPROVE,
            simulator.REPAIR,
            simulator.VERIFY,
            simulator.INSPECT,
        )
    else:
        plan = (
            simulator.STOP,
            simulator.DIAGNOSE,
            simulator.INSPECT,
            simulator.MOVE,
            simulator.APPROVE,
            simulator.REPAIR,
            simulator.VERIFY,
        )
    return plan[(episode + step) % len(plan)]


def generate_partition(partition: str, episodes: int, steps: int, seed: int):
    if partition not in PARTITION_OFFSETS:
        raise ValueError(f"unsupported stress partition: {partition}")
    if episodes < 1 or steps < 5:
        raise ValueError(
            "stress partitions require positive episodes and at least five steps"
        )
    rng = np.random.default_rng(seed + PARTITION_SEED_OFFSETS[partition])
    rows = []
    metadata = {}
    for local_episode in range(episodes):
        episode = PARTITION_OFFSETS[partition] + local_episode
        case = CASES[local_episode % len(CASES)]
        state = simulator.initial_state(rng)
        apply_case(state, case, rng)
        metadata[episode] = {"partition": partition, "case": case}
        for step in range(steps):
            action = action_for_step(case, local_episode, step)
            features = simulator.action_features(rng, action)
            nxt = simulator.transition(state, action, features, rng)
            rows.append(
                (
                    episode,
                    step,
                    state,
                    action,
                    features,
                    nxt,
                    simulator.is_dangerous(state, action, features, nxt),
                )
            )
            state = nxt
    return rows, metadata


def summarize(rows, metadata) -> dict:
    return {
        "episodes": len(metadata),
        "transitions": len(rows),
        "dangerous_transitions": sum(bool(row[6]) for row in rows),
        "case_episode_counts": dict(
            sorted(Counter(item["case"] for item in metadata.values()).items())
        ),
        "action_transition_counts": dict(
            sorted(Counter(simulator.ACTION_NAMES[row[3]] for row in rows).items())
        ),
    }
