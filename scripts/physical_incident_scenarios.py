#!/usr/bin/env python3
"""Generate defensive incident-derived priors in Ferrum's physical simulator.

Public sources choose rare observable state distributions; they never provide
transition targets. Every next state and danger label is produced by the same
deterministic simulator used by the physical JEPA baseline.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

import train_physical_world_model as simulator

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "docs" / "research" / "physical_incident_sources.json"
PARTITION_OFFSETS = {"train": 1_000_000, "validation": 2_000_000, "test": 3_000_000}

ACTION_PLANS = {
    "availability_loss": (
        simulator.STOP,
        simulator.DIAGNOSE,
        simulator.VERIFY,
        simulator.APPROVE,
        simulator.REPAIR,
        simulator.STOP,
    ),
    "logic_or_configuration_tamper": (
        simulator.DIAGNOSE,
        simulator.VERIFY,
        simulator.MOVE,
        simulator.STOP,
        simulator.APPROVE,
        simulator.REPAIR,
    ),
    "loss_of_control": (
        simulator.MOVE,
        simulator.DIAGNOSE,
        simulator.STOP,
        simulator.VERIFY,
        simulator.APPROVE,
        simulator.REPAIR,
    ),
    "loss_of_view": (
        simulator.INSPECT,
        simulator.DIAGNOSE,
        simulator.MOVE,
        simulator.STOP,
        simulator.VERIFY,
        simulator.APPROVE,
    ),
    "manual_fallback": (
        simulator.STOP,
        simulator.DIAGNOSE,
        simulator.APPROVE,
        simulator.REPAIR,
        simulator.VERIFY,
        simulator.STOP,
    ),
    "process_divergence": (
        simulator.INSPECT,
        simulator.DIAGNOSE,
        simulator.MOVE,
        simulator.STOP,
        simulator.APPROVE,
        simulator.VERIFY,
    ),
    "recovery_inhibition": (
        simulator.REPAIR,
        simulator.VERIFY,
        simulator.STOP,
        simulator.DIAGNOSE,
        simulator.APPROVE,
        simulator.REPAIR,
    ),
    "safety_interlock_compromise": (
        simulator.MOVE,
        simulator.INSPECT,
        simulator.REPAIR,
        simulator.STOP,
        simulator.DIAGNOSE,
        simulator.VERIFY,
    ),
    "sensor_or_view_deception": (
        simulator.INSPECT,
        simulator.DIAGNOSE,
        simulator.MOVE,
        simulator.STOP,
        simulator.VERIFY,
        simulator.APPROVE,
    ),
    "unauthorized_actuation": (
        simulator.MOVE,
        simulator.REPAIR,
        simulator.MOVE,
        simulator.STOP,
        simulator.APPROVE,
        simulator.VERIFY,
    ),
    "unsafe_command_sequence": (
        simulator.MOVE,
        simulator.MOVE,
        simulator.REPAIR,
        simulator.STOP,
        simulator.DIAGNOSE,
        simulator.VERIFY,
    ),
}


def load_catalog(path: Path = DEFAULT_CATALOG) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    base_name = payload.get("extends")
    if base_name is None:
        return payload
    base = load_catalog(path.parent / base_name)
    return {
        **base,
        **payload,
        "allowed_hazard_tags": base["allowed_hazard_tags"],
        "sources": [*base["sources"], *payload["additional_sources"]],
    }


def catalog_sha256(path: Path = DEFAULT_CATALOG) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "extends" not in payload:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    resolved = json.dumps(
        load_catalog(path), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(resolved).hexdigest()


def source_seed(source_id: str, seed: int) -> int:
    digest = hashlib.sha256(f"{seed}:{source_id}".encode()).digest()
    return int.from_bytes(digest[:8], "little", signed=False)


def apply_prior(state: np.ndarray, tag: str, rng: np.random.Generator) -> None:
    """Apply a coarse, defensive, observable prior without changing dynamics."""

    if tag == "availability_loss":
        state[simulator.ONLINE] = 0.0
        state[simulator.LINK] = rng.uniform(0.0, 0.08)
        state[simulator.VELOCITY] = 0.0
    elif tag == "logic_or_configuration_tamper":
        state[simulator.FAULT] = 1.0
        state[simulator.LINK] = rng.uniform(0.08, 0.45)
        state[simulator.APPROVAL] = 0.0
    elif tag == "loss_of_control":
        state[simulator.ONLINE] = float(rng.random() > 0.65)
        state[simulator.LINK] = rng.uniform(0.0, 0.09)
        state[simulator.FAULT] = float(rng.random() < 0.7)
    elif tag == "loss_of_view":
        state[simulator.LINK] = rng.uniform(0.0, 0.06)
        state[simulator.ONLINE] = float(rng.random() > 0.5)
    elif tag == "manual_fallback":
        state[simulator.ONLINE] = 0.0
        state[simulator.LINK] = rng.uniform(0.0, 0.12)
        state[simulator.VELOCITY] = 0.0
    elif tag == "process_divergence":
        state[simulator.HEALTH] = rng.uniform(0.05, 0.35)
        state[simulator.VIBRATION] = rng.uniform(0.72, 1.0)
        state[simulator.FAULT] = 1.0
    elif tag == "recovery_inhibition":
        state[simulator.ONLINE] = 0.0
        state[simulator.LINK] = rng.uniform(0.0, 0.05)
        state[simulator.APPROVAL] = 0.0
    elif tag == "safety_interlock_compromise":
        state[simulator.ESTOP] = 1.0
        state[simulator.HEALTH] = rng.uniform(0.08, 0.45)
        state[simulator.VIBRATION] = rng.uniform(0.58, 1.0)
        state[simulator.FAULT] = 1.0
    elif tag == "sensor_or_view_deception":
        state[simulator.HEALTH] = rng.uniform(0.08, 0.35)
        state[simulator.VIBRATION] = rng.uniform(0.72, 1.0)
        state[simulator.FAULT] = float(rng.random() < 0.25)
        state[simulator.LINK] = rng.uniform(0.12, 0.55)
    elif tag == "unauthorized_actuation":
        state[simulator.APPROVAL] = 0.0
        state[simulator.HUMANS] = rng.choice([0.25, 0.5, 0.9])
        state[simulator.CLEARANCE] = rng.uniform(0.04, 0.24)
    elif tag == "unsafe_command_sequence":
        axis = int(rng.integers(0, 2))
        state[axis] = rng.choice([-1.0, 1.0]) * rng.uniform(0.82, 1.18)
        state[simulator.CLEARANCE] = rng.uniform(0.0, 0.2)
        state[simulator.BATTERY] = rng.uniform(0.0, 0.16)
        state[simulator.HUMANS] = rng.choice([0.0, 0.25, 0.5])
    else:
        raise ValueError(f"unsupported incident hazard tag: {tag}")


def choose_tags(tags: list[str], episode_index: int) -> tuple[str, ...]:
    primary_index = episode_index % len(tags)
    selected = [tags[primary_index]]
    if len(tags) > 1 and episode_index % 3 == 0:
        selected.append(tags[(primary_index + 1) % len(tags)])
    return tuple(selected)


def action_for_step(
    primary_tag: str,
    step: int,
    episode_index: int,
    rng: np.random.Generator,
) -> int:
    plan = ACTION_PLANS[primary_tag]
    planned = plan[(step + episode_index) % len(plan)]
    if episode_index % 7 == 0 and step == len(plan) - 1:
        return int(rng.integers(0, simulator.ACTION_COUNT))
    return planned


def generate_partition(
    partition: str,
    episodes_per_source: int,
    steps: int,
    seed: int,
    catalog_path: Path = DEFAULT_CATALOG,
):
    if partition not in PARTITION_OFFSETS:
        raise ValueError(f"unsupported incident partition: {partition}")
    if episodes_per_source < 1:
        raise ValueError("episodes_per_source must be positive")
    if steps < 5:
        raise ValueError("steps must be at least 5 for H=1..5 evaluation")

    sources = [
        source
        for source in load_catalog(catalog_path)["sources"]
        if source["use_for_scenario_generation"]
        and source["training_partition"] == partition
    ]
    sources.sort(key=lambda source: source["id"])
    rows = []
    metadata = {}
    episode_cursor = PARTITION_OFFSETS[partition]
    for source in sources:
        rng = np.random.default_rng(source_seed(source["id"], seed))
        tags = list(source["hazard_tags"])
        for local_episode in range(episodes_per_source):
            episode = episode_cursor
            episode_cursor += 1
            selected_tags = choose_tags(tags, local_episode)
            state = simulator.initial_state(rng)
            for tag in selected_tags:
                apply_prior(state, tag, rng)
            state[simulator.MARGIN] = np.clip(
                1.0 - max(abs(state[simulator.X]), abs(state[simulator.Y])),
                -0.25,
                1.0,
            )
            primary = selected_tags[0]
            metadata[episode] = {
                "partition": partition,
                "source_id": source["id"],
                "source_family": source["source_family"],
                "hazard_tags": selected_tags,
            }
            for step in range(steps):
                action = action_for_step(primary, step, local_episode, rng)
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
    action_counts = Counter(simulator.ACTION_NAMES[row[3]] for row in rows)
    source_counts = Counter(item["source_id"] for item in metadata.values())
    family_counts = Counter(item["source_family"] for item in metadata.values())
    tag_counts = Counter(
        tag for item in metadata.values() for tag in item["hazard_tags"]
    )
    return {
        "episodes": len(metadata),
        "transitions": len(rows),
        "dangerous_transitions": sum(bool(row[6]) for row in rows),
        "source_episode_counts": dict(sorted(source_counts.items())),
        "source_family_episode_counts": dict(sorted(family_counts.items())),
        "hazard_tag_episode_counts": dict(sorted(tag_counts.items())),
        "action_transition_counts": dict(sorted(action_counts.items())),
    }


def write_jsonl(path: Path, rows, metadata) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for episode, step, state, action, features, nxt, danger in rows:
            source = metadata[episode]
            record = {
                "episode": episode,
                "step": step,
                "partition": source["partition"],
                "source_id": source["source_id"],
                "source_family": source["source_family"],
                "hazard_tags": list(source["hazard_tags"]),
                "state": state.tolist(),
                "action": action,
                "action_name": simulator.ACTION_NAMES[action],
                "action_features": features.tolist(),
                "next_state": nxt.tolist(),
                "dangerous": bool(danger),
                "transition_source": "deterministic_ferrum_simulator",
                "incident_role": "defensive_state_distribution_prior",
            }
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
