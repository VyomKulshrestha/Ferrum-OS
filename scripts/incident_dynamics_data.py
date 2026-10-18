"""Causal research-only trajectories. Incident narratives are NOT telemetry."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np

import cross_domain_world_model_models as legacy
import evaluate_cross_domain_world_models as architecture
import evaluate_cross_domain_learned_contribution as temporal
import train_physical_world_model as physical
import train_world_model as os_model


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/research/incident_dynamics_development_plan_v1.json"
SOURCES = ROOT / "docs/research/incident_dynamics_sources_v1.json"
WORK = ROOT / "target/incident-dynamics-v1"


@dataclass
class Windows:
    states: np.ndarray
    actions: np.ndarray
    future_actions: np.ndarray
    targets: np.ndarray
    valid: np.ndarray
    episodes: np.ndarray
    sources: np.ndarray


def windows(rows: list[dict], spec: legacy.DomainSpec, complete: bool = False) -> Windows:
    """No future states enter inputs; pad history, and mask short training tails."""
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["episode"], []).append(row)
    result = [[] for _ in range(7)]
    for episode, sequence in sorted(grouped.items()):
        sequence.sort(key=lambda row: row["step"])
        if len({row["step"] for row in sequence}) != len(sequence):
            raise ValueError(f"duplicate step in {episode}")
        for index, row in enumerate(sequence):
            future = sequence[index:index + 5]
            # Do not invent transitions across missing records.
            for k, item in enumerate(future):
                if item["step"] != row["step"] + k:
                    future = future[:k]
                    break
            if complete and len(future) != 5:
                continue
            history = sequence[max(0, index - spec.history + 1):index + 1]
            while len(history) > 1 and history[0]["step"] != row["step"] - len(history) + 1:
                history = history[1:]
            pad = spec.history - len(history)
            states = [history[0]["state"]] * pad + [item["state"] for item in history]
            actions = [np.zeros(spec.action_size, np.float32)] * pad + [item["action"] for item in history]
            actual = [item["next_state"] for item in future]
            planned = [item["action"] for item in future]
            valid = [1.0] * len(future) + [0.0] * (5 - len(future))
            actual += [actual[-1]] * (5 - len(actual))
            planned += [planned[-1]] * (5 - len(planned))
            for output, value in zip(result, (states, actions, planned, actual, valid, episode, row["source"])):
                output.append(value)
    if not result[0]:
        raise ValueError("no eligible causal windows")
    return Windows(*[np.asarray(value, dtype=np.float32 if i < 5 else str) for i, value in enumerate(result)])


def subset(data: Windows, indices: np.ndarray) -> Windows:
    return Windows(**{key: value[indices] for key, value in vars(data).items()})


def spec_for(domain: str):
    protocol = architecture.load_json(architecture.PROTOCOL)
    return (architecture.os_spec if domain == "ferrumos" else architecture.physical_spec)(protocol)


def incident_rows(domain: str, partition: str, episodes: int, seed: int) -> list[dict]:
    """Local mechanisms, bounded numeric ranges; no network or execution capability.

    Each split has disjoint episode RNGs. Held-out sources combine familiar
    mechanisms; neither equations nor assessment are externally controlled.
    """
    catalog = json.loads(SOURCES.read_text(encoding="utf-8"))
    source_partition = "held_out_source" if partition == "final" else "development"
    sources = [x["id"] for x in catalog["sources"] if x["domain"] == domain and x["partition"] == source_partition]
    spec = spec_for(domain)
    output = []
    for episode in range(episodes):
        source = sources[episode % len(sources)]
        digest = hashlib.sha256(f"{domain}:{partition}:{seed}:{episode}".encode()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
        pressure = episode % 4
        if domain == "ferrumos":
            state = np.zeros(48, np.float32)
            state[[0, 1, 3]] = rng.uniform(0.3, 0.95, 3)
            state[2] = rng.uniform(0, 0.7)
            drift = np.zeros(48, np.float32)
            drift[[0, 1, 3]] = rng.uniform(-0.002, 0.012, 3) * (pressure / 3)
        else:
            state = physical.initial_state(rng)
            state[physical.HUMANS] = 0
            state[physical.ESTOP] = 0
            state[physical.ONLINE] = 1
            state[physical.CLEARANCE] = rng.uniform(0.3, 0.95)
            state[physical.BATTERY] = rng.uniform(0.1, 0.8)
            state[physical.LINK] = rng.uniform(0.15, 0.9)
            drift = np.zeros(16, np.float32)
            drift[physical.LINK] = -rng.uniform(0, 0.018) * (pressure / 3)
            drift[physical.BATTERY] = -rng.uniform(0, 0.008) * (pressure / 3)
        previous_observed = state.copy()
        for step in range(14):
            observed = state.copy()
            # Known observation fault is not furnished as a privileged predictor input.
            stale = pressure == 3 and step % 5 == 3
            if stale:
                indices = [1] if domain == "ferrumos" else [physical.X, physical.Y, physical.CLEARANCE]
                observed[indices] = previous_observed[indices]
            if domain == "ferrumos":
                choices = ["service_start", "service_stop", "local_inference", "http_get", "write_file", "report_status"]
                name = str(rng.choice(choices, p=[.25, .15, .25, .10, .10, .15]))
                action = temporal.action_record(name)
                features = [0.0] * os_model.ACTION_FEATURE_SIZE
                action_vector = legacy.standardize_action(action["id"], features, spec.action_size, os_model.NUM_TOOLS)
                # Held-out composition changes recovery timing, not the shared equation.
                factor = (-0.5 if step >= 9 else 1.0) if partition == "final" else (0.0 if step >= 11 else 1.0)
                nxt = temporal.apply_os(state, action, drift * factor)
                dangerous = temporal.os_harm(nxt)
            else:
                action_id = int(rng.choice([physical.MOVE, physical.INSPECT, physical.DIAGNOSE, physical.STOP], p=[.55, .15, .15, .15]))
                features = physical.action_features(rng, action_id)
                # Coherent moves make delayed approach observable over several steps.
                if action_id == physical.MOVE:
                    features[:2] *= .3
                action_vector = legacy.standardize_action(action_id, features, spec.action_size, physical.ACTION_COUNT)
                nxt = physical.transition(state, action_id, features, rng)
                factor = 1.5 if partition == "final" and step >= 7 else 1.0
                nxt += drift * factor
                nxt[2:] = np.clip(nxt[2:], 0, 1)
                nxt[physical.MARGIN] = np.clip(1 - max(abs(nxt[0]), abs(nxt[1])), -.25, 1)
                dangerous = physical.is_dangerous(state, action_id, features, nxt)
            output.append({"episode": f"new:{domain}:{partition}:{seed}:{episode}", "step": step,
                           "state": observed, "action": action_vector, "next_state": nxt,
                           "source": source, "hazard": f"pressure-{pressure}:stale-{stale}", "dangerous": dangerous})
            previous_observed = observed
            state = nxt
    return output


def save_windows(path: Path, data: Windows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **vars(data))


def load_windows(path: Path) -> Windows:
    with np.load(path, allow_pickle=False) as values:
        return Windows(**{key: values[key] for key in Windows.__dataclass_fields__})


def prepare(domain: str) -> dict:
    protocol = architecture.load_json(architecture.PROTOCOL)
    guard = architecture.install_final_guard(protocol)
    loader = architecture.os_development if domain == "ferrumos" else architecture.physical_development
    spec, train, validation, metadata = loader(protocol)
    train += incident_rows(domain, "train", 1200, 281001)
    validation += incident_rows(domain, "validation", 256, 281002)
    # Partition-specific prefixes also expose accidental episode-name reuse.
    train_ids, val_ids = {x["episode"] for x in train}, {x["episode"] for x in validation}
    if train_ids & val_ids:
        raise AssertionError("training and validation episodes overlap")
    a, b = windows(train, spec), windows(validation, spec, complete=True)
    save_windows(WORK / domain / "train.npz", a)
    save_windows(WORK / domain / "validation.npz", b)
    summary = {"domain": domain, "train_windows": len(a.states), "validation_windows": len(b.states),
               "train_episodes": len(train_ids), "validation_episodes": len(val_ids), "legacy_metadata": metadata,
               "final_access_attempted": guard["attempted"], "train_validation_disjoint": True,
               "train_sha256": legacy.sha256(WORK / domain / "train.npz"),
               "validation_sha256": legacy.sha256(WORK / domain / "validation.npz")}
    architecture.write_json(WORK / domain / "data_manifest.json", summary)
    return summary
