#!/usr/bin/env python3
"""Generate, train, and evaluate Ferrum's simulator-only physical world model.

The physical schema is intentionally separate from the 41-action OS JEPA. Data
is split by episode before fitting. The resulting PWM1 artifact is always marked
shadow-only because simulator validation is not evidence for real machinery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np

STATE_SIZE = 16
ACTION_NAMES = ("move", "inspect", "diagnose", "approve", "repair", "verify", "stop")
ACTION_COUNT = len(ACTION_NAMES)
ACTION_FEATURE_SIZE = 3
INPUT_SIZE = STATE_SIZE + ACTION_COUNT + ACTION_FEATURE_SIZE
STATE_RANGES = np.array([2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], dtype=np.float32)
MAGIC = b"PWM1"
VERSION = 1

X, Y, CLEARANCE, HUMANS, BATTERY, LINK, HEALTH, ESTOP = range(8)
PROGRESS, VIBRATION, FAULT, ONLINE, PAYLOAD, VELOCITY, MARGIN, APPROVAL = range(8, 16)
MOVE, INSPECT, DIAGNOSE, APPROVE, REPAIR, VERIFY, STOP = range(ACTION_COUNT)


def initial_state(rng: np.random.Generator) -> np.ndarray:
    state = np.zeros(STATE_SIZE, dtype=np.float32)
    state[X:Y + 1] = rng.uniform(-0.7, 0.7, 2)
    state[CLEARANCE] = rng.uniform(0.05, 1.0)
    state[HUMANS] = rng.choice([0.0, 0.25, 0.5], p=[0.55, 0.3, 0.15])
    state[BATTERY] = rng.uniform(0.08, 1.0)
    state[LINK] = rng.uniform(0.08, 1.0)
    state[HEALTH] = rng.uniform(0.15, 0.85)
    state[ESTOP] = float(rng.random() < 0.08)
    state[PROGRESS] = rng.uniform(0.0, 0.2)
    state[VIBRATION] = np.clip(1.0 - state[HEALTH] + rng.normal(0, 0.06), 0, 1)
    state[FAULT] = float(state[VIBRATION] > 0.62 or rng.random() < 0.08)
    state[ONLINE] = float(rng.random() > 0.08)
    state[PAYLOAD] = rng.uniform(0, 1)
    state[VELOCITY] = 0
    state[MARGIN] = 1.0 - max(abs(state[X]), abs(state[Y]))
    state[APPROVAL] = 0
    return state


def action_features(rng: np.random.Generator, action: int) -> np.ndarray:
    if action == MOVE:
        return np.array([rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0.1, 1)], dtype=np.float32)
    if action in (INSPECT, DIAGNOSE, REPAIR, VERIFY):
        return np.array([rng.uniform(0.2, 1), 0, 0], dtype=np.float32)
    return np.zeros(ACTION_FEATURE_SIZE, dtype=np.float32)


def transition(state: np.ndarray, action: int, features: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    nxt = state.copy()
    nxt[VELOCITY] = 0
    if nxt[ONLINE] > 0.5:
        nxt[LINK] = np.clip(nxt[LINK] + rng.normal(-0.002, 0.012), 0, 1)
    nxt[BATTERY] = np.clip(nxt[BATTERY] - 0.003, 0, 1)

    if action == MOVE and nxt[ONLINE] > 0.5 and nxt[ESTOP] < 0.5:
        dx, dy, speed = features
        nxt[X] += 0.32 * dx
        nxt[Y] += 0.32 * dy
        nxt[VELOCITY] = speed
        approach = 0.16 * (abs(dx) + abs(dy)) + 0.12 * nxt[HUMANS] * speed
        nxt[CLEARANCE] = np.clip(nxt[CLEARANCE] - approach + rng.normal(0, 0.015), 0, 1)
        nxt[BATTERY] = np.clip(nxt[BATTERY] - 0.025 * speed - 0.01 * nxt[PAYLOAD], 0, 1)
    elif action == INSPECT and nxt[ONLINE] > 0.5:
        nxt[PROGRESS] += 0.12 * features[0]
        nxt[VIBRATION] = np.clip(nxt[VIBRATION] + rng.normal(0, 0.025), 0, 1)
    elif action == DIAGNOSE and nxt[ONLINE] > 0.5:
        nxt[PROGRESS] += 0.16 * features[0]
        if nxt[VIBRATION] > 0.58:
            nxt[FAULT] = 1
    elif action == APPROVE:
        nxt[APPROVAL] = 1
        nxt[PROGRESS] += 0.08
    elif action == REPAIR and nxt[ONLINE] > 0.5 and nxt[APPROVAL] > 0.5:
        strength = features[0]
        nxt[HEALTH] += 0.48 * strength
        nxt[VIBRATION] -= 0.42 * strength
        nxt[FAULT] = float(nxt[VIBRATION] > 0.58)
        nxt[PROGRESS] += 0.28 * strength
        nxt[BATTERY] -= 0.015
    elif action == VERIFY and nxt[ONLINE] > 0.5:
        nxt[PROGRESS] += 0.18 * features[0]
        if nxt[HEALTH] > 0.72 and nxt[VIBRATION] < 0.4:
            nxt[FAULT] = 0
    elif action == STOP:
        nxt[VELOCITY] = 0

    nxt[X:Y + 1] = np.clip(nxt[X:Y + 1], -1.25, 1.25)
    nxt[2:] = np.clip(nxt[2:], 0, 1)
    nxt[MARGIN] = np.clip(1.0 - max(abs(nxt[X]), abs(nxt[Y])), -0.25, 1)
    return nxt.astype(np.float32)


def is_dangerous(state: np.ndarray, action: int, features: np.ndarray, nxt: np.ndarray) -> bool:
    moving = action == MOVE and features[2] > 0.1
    return bool(
        (moving and nxt[CLEARANCE] < 0.16)
        or (moving and state[HUMANS] > 0 and nxt[VELOCITY] > 0.18)
        or nxt[MARGIN] < 0
        or (moving and state[BATTERY] < 0.1)
        or (moving and state[LINK] < 0.1)
        or (action != STOP and state[ESTOP] > 0.5)
        or (action == REPAIR and state[APPROVAL] < 0.5)
    )


def rules_block(state: np.ndarray, action: int, features: np.ndarray) -> bool:
    moving = action == MOVE and features[2] > 0.1
    predicted_margin = 1.0 - max(abs(state[X] + 0.32 * features[0]), abs(state[Y] + 0.32 * features[1]))
    return bool(
        (moving and state[CLEARANCE] < 0.2)
        or (moving and state[HUMANS] > 0)
        or (moving and predicted_margin < 0)
        or (moving and state[BATTERY] < 0.1)
        or (moving and state[LINK] < 0.1)
        or (action != STOP and state[ESTOP] > 0.5)
        or (action == REPAIR and state[APPROVAL] < 0.5)
    )


def predicted_block(state: np.ndarray, action: int, features: np.ndarray, nxt: np.ndarray) -> bool:
    moving = action == MOVE and features[2] > 0.1
    return bool(
        (moving and nxt[CLEARANCE] < 0.18)
        or (moving and state[HUMANS] > 0 and nxt[VELOCITY] > 0.16)
        or nxt[MARGIN] < 0.01
        or (moving and nxt[BATTERY] < 0.08)
        or (moving and nxt[LINK] < 0.08)
        or (action != STOP and state[ESTOP] > 0.5)
        or (action == REPAIR and state[APPROVAL] < 0.5)
    )


def generate(episodes: int, steps: int, seed: int):
    rng = np.random.default_rng(seed)
    rows = []
    for episode in range(episodes):
        state = initial_state(rng)
        for step in range(steps):
            action = int(rng.integers(0, ACTION_COUNT))
            features = action_features(rng, action)
            nxt = transition(state, action, features, rng)
            rows.append((episode, step, state, action, features, nxt, is_dangerous(state, action, features, nxt)))
            state = nxt
    return rows


def arrays(rows):
    x = np.zeros((len(rows), INPUT_SIZE), dtype=np.float32)
    y = np.zeros((len(rows), STATE_SIZE), dtype=np.float32)
    for i, (_, _, state, action, features, nxt, _) in enumerate(rows):
        x[i, :STATE_SIZE] = state
        x[i, STATE_SIZE + action] = 1
        x[i, STATE_SIZE + ACTION_COUNT:] = features
        y[i] = nxt - state
    return x, y


def predict(x, weights):
    w1, b1, w2, b2 = weights
    return np.maximum(x @ w1 + b1, 0) @ w2 + b2


def train(x_train, y_train, x_val, y_val, hidden: int, epochs: int, seed: int):
    rng = np.random.default_rng(seed)
    w1 = rng.normal(0, 0.12, (INPUT_SIZE, hidden)).astype(np.float32)
    b1 = np.zeros(hidden, dtype=np.float32)
    w2 = rng.normal(0, 0.08, (hidden, STATE_SIZE)).astype(np.float32)
    b2 = np.zeros(STATE_SIZE, dtype=np.float32)
    mw1 = np.zeros_like(w1); vw1 = np.zeros_like(w1)
    mb1 = np.zeros_like(b1); vb1 = np.zeros_like(b1)
    mw2 = np.zeros_like(w2); vw2 = np.zeros_like(w2)
    mb2 = np.zeros_like(b2); vb2 = np.zeros_like(b2)
    best = None
    best_val = float("inf")
    stale = 0
    batch = min(1024, len(x_train))
    for epoch in range(1, epochs + 1):
        indices = rng.choice(len(x_train), batch, replace=False)
        xb, yb = x_train[indices], y_train[indices]
        pre = xb @ w1 + b1
        hidden_values = np.maximum(pre, 0)
        error = hidden_values @ w2 + b2 - yb
        d_out = 2 * error / batch
        gw2 = hidden_values.T @ d_out
        gb2 = d_out.sum(0)
        d_hidden = d_out @ w2.T
        d_hidden[pre <= 0] = 0
        gw1 = xb.T @ d_hidden
        gb1 = d_hidden.sum(0)
        for parameter, gradient, moment, velocity in (
            (w1, gw1, mw1, vw1), (b1, gb1, mb1, vb1),
            (w2, gw2, mw2, vw2), (b2, gb2, mb2, vb2),
        ):
            moment *= 0.9; moment += 0.1 * gradient
            velocity *= 0.999; velocity += 0.001 * gradient * gradient
            parameter -= 0.003 * (moment / (1 - 0.9 ** epoch)) / (np.sqrt(velocity / (1 - 0.999 ** epoch)) + 1e-8)
        if epoch % 25 == 0 or epoch == epochs:
            current = float(np.mean((predict(x_val, (w1, b1, w2, b2)) - y_val) ** 2))
            if current < best_val - 1e-8:
                best_val = current
                best = tuple(value.copy() for value in (w1, b1, w2, b2))
                stale = 0
            else:
                stale += 1
            if stale >= 12:
                break
    return best or (w1, b1, w2, b2), best_val, epoch


def make_input(state, action, features):
    value = np.zeros((1, INPUT_SIZE), dtype=np.float32)
    value[0, :STATE_SIZE] = state
    value[0, STATE_SIZE + action] = 1
    value[0, STATE_SIZE + ACTION_COUNT:] = features
    return value


def rollout_error(rows, predictor, horizon: int):
    grouped = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row)
    errors = []
    for episode_rows in grouped.values():
        episode_rows.sort(key=lambda row: row[1])
        for start in range(0, len(episode_rows) - horizon + 1):
            predicted = episode_rows[start][2].copy()
            for offset in range(horizon):
                row = episode_rows[start + offset]
                predicted = np.clip(predicted + predictor(predicted, row[3], row[4]), -1.25, 1.25)
            actual = episode_rows[start + horizon - 1][5]
            errors.append(np.mean(np.abs(predicted - actual) / STATE_RANGES))
    return float(np.mean(errors))


def confusion(rows, blocker):
    tp = fp = tn = fn = 0
    for row in rows:
        prediction = blocker(row)
        truth = row[6]
        tp += prediction and truth
        fp += prediction and not truth
        tn += not prediction and not truth
        fn += not prediction and truth
    tpr = tp / max(1, tp + fn)
    tnr = tn / max(1, tn + fp)
    return {
        "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
        "balanced_accuracy": (tpr + tnr) / 2,
        "false_negative_rate": fn / max(1, tp + fn),
        "false_positive_rate": fp / max(1, fp + tn),
    }


def write_dataset(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for episode, step, state, action, features, nxt, danger in rows:
            handle.write(json.dumps({
                "episode": episode, "step": step, "state": state.tolist(),
                "action": action, "action_name": ACTION_NAMES[action],
                "action_features": features.tolist(), "next_state": nxt.tolist(),
                "dangerous": danger, "source": "deterministic_simulator",
            }, separators=(",", ":")) + "\n")


def write_artifact(path: Path, weights, samples: int, h3: float, baseline_h3: float, hidden: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack(
        "<4sIIIIIIIffI", MAGIC, VERSION, STATE_SIZE, ACTION_COUNT,
        ACTION_FEATURE_SIZE, hidden, samples, INPUT_SIZE, h3, baseline_h3, 0,
    )
    with path.open("wb") as handle:
        handle.write(header)
        for value in weights:
            handle.write(np.asarray(value, dtype="<f4").tobytes(order="C"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=2500)
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dataset", type=Path, default=Path("target/physical_world_model/trajectories.jsonl"))
    parser.add_argument("--artifact", type=Path, default=Path("userland/heliox-daemon/physical_world_model.bin"))
    parser.add_argument("--evaluation", type=Path, default=Path("docs/research/physical_world_model_evaluation.json"))
    args = parser.parse_args()

    rows = generate(args.episodes, args.steps, args.seed)
    episode_ids = np.arange(args.episodes)
    np.random.default_rng(args.seed).shuffle(episode_ids)
    train_ids = set(episode_ids[: int(args.episodes * 0.70)].tolist())
    val_ids = set(episode_ids[int(args.episodes * 0.70): int(args.episodes * 0.85)].tolist())
    train_rows = [row for row in rows if row[0] in train_ids]
    val_rows = [row for row in rows if row[0] in val_ids]
    test_rows = [row for row in rows if row[0] not in train_ids and row[0] not in val_ids]
    x_train, y_train = arrays(train_rows)
    x_val, y_val = arrays(val_rows)
    weights, validation_mse, trained_epochs = train(
        x_train, y_train, x_val, y_val, args.hidden, args.epochs, args.seed
    )

    mean_delta = np.zeros((ACTION_COUNT, STATE_SIZE), dtype=np.float32)
    for action in range(ACTION_COUNT):
        selected = [row[5] - row[2] for row in train_rows if row[3] == action]
        mean_delta[action] = np.mean(selected, axis=0)
    jepa_predictor = lambda state, action, features: predict(make_input(state, action, features), weights)[0]
    mean_predictor = lambda _state, action, _features: mean_delta[action]
    h1 = rollout_error(test_rows, jepa_predictor, 1)
    h3 = rollout_error(test_rows, jepa_predictor, 3)
    mean_h1 = rollout_error(test_rows, mean_predictor, 1)
    mean_h3 = rollout_error(test_rows, mean_predictor, 3)

    rules = confusion(test_rows, lambda row: rules_block(row[2], row[3], row[4]))
    learned = confusion(test_rows, lambda row: predicted_block(
        row[2], row[3], row[4], np.clip(row[2] + jepa_predictor(row[2], row[3], row[4]), -1.25, 1.25)
    ))
    combined = confusion(test_rows, lambda row: rules_block(row[2], row[3], row[4]) or predicted_block(
        row[2], row[3], row[4], np.clip(row[2] + jepa_predictor(row[2], row[3], row[4]), -1.25, 1.25)
    ))

    write_dataset(args.dataset, rows)
    write_artifact(args.artifact, weights, len(train_rows), h3, mean_h3, args.hidden)
    artifact_sha256 = hashlib.sha256(args.artifact.read_bytes()).hexdigest()
    dataset_sha256 = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    evaluation = {
        "schema_version": VERSION,
        "source": "deterministic_simulator_only",
        "model_class": "action_conditioned_latent_transition_mlp",
        "action_names": ACTION_NAMES,
        "state_dimensions": STATE_SIZE,
        "action_feature_dimensions": ACTION_FEATURE_SIZE,
        "episodes": args.episodes,
        "transitions": len(rows),
        "dangerous_transitions": sum(row[6] for row in rows),
        "episode_split": {"train": len(train_ids), "validation": len(val_ids), "test": args.episodes - len(train_ids) - len(val_ids)},
        "transition_split": {"train": len(train_rows), "validation": len(val_rows), "test": len(test_rows)},
        "episode_overlap": 0,
        "seed": args.seed,
        "hidden": args.hidden,
        "epochs_requested": args.epochs,
        "epochs_completed": trained_epochs,
        "validation_mse": validation_mse,
        "normalized_rollout_error": {
            "transition_model_h1": h1, "transition_model_h3": h3,
            "per_action_mean_h1": mean_h1, "per_action_mean_h3": mean_h3,
        },
        "safety": {"rules_only": rules, "learned_only": learned, "rules_plus_learned": combined},
        "artifact": str(args.artifact).replace("\\", "/"),
        "artifact_format": "PWM1",
        "artifact_sha256": artifact_sha256,
        "generated_dataset": str(args.dataset).replace("\\", "/"),
        "generated_dataset_sha256": dataset_sha256,
        "validated_for_gating": False,
        "gating_reason": "Simulator-only trajectories cannot validate control of real physical machinery.",
    }
    args.evaluation.parent.mkdir(parents=True, exist_ok=True)
    args.evaluation.write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evaluation, indent=2))


if __name__ == "__main__":
    main()
