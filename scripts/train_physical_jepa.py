#!/usr/bin/env python3
"""Train an EMA-target physical JEPA on deterministic simulator episodes.

The predictor learns in an abstract latent space. Reconstruction and action
auxiliaries keep the online representation informative, while an auxiliary
state-delta head provides the compact forecast needed by the runtime safety
scorer. Simulator evidence is always serialized shadow-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np

import train_physical_world_model as simulator

MAGIC = b"PJE1"
VERSION = 1
EMA_DECAY = np.float32(0.995)
LATENT_LOSS_WEIGHT = np.float32(0.25)
RECONSTRUCTION_LOSS_WEIGHT = np.float32(0.10)
ACTION_LOSS_WEIGHT = np.float32(0.02)


def split_rows(rows, episodes: int, seed: int):
    episode_ids = np.arange(episodes)
    np.random.default_rng(seed).shuffle(episode_ids)
    train_ids = set(episode_ids[: int(episodes * 0.70)].tolist())
    validation_ids = set(episode_ids[int(episodes * 0.70): int(episodes * 0.85)].tolist())
    train = [row for row in rows if row[0] in train_ids]
    validation = [row for row in rows if row[0] in validation_ids]
    test = [row for row in rows if row[0] not in train_ids and row[0] not in validation_ids]
    return train_ids, validation_ids, train, validation, test


def action_matrix(rows) -> np.ndarray:
    values = np.zeros((len(rows), simulator.ACTION_COUNT + simulator.ACTION_FEATURE_SIZE), dtype=np.float32)
    for index, row in enumerate(rows):
        values[index, row[3]] = 1.0
        values[index, simulator.ACTION_COUNT:] = row[4]
    return values


def state_arrays(rows):
    state = np.asarray([row[2] for row in rows], dtype=np.float32)
    next_state = np.asarray([row[5] for row in rows], dtype=np.float32)
    return state, action_matrix(rows), next_state - state, next_state


def initialize(latent: int, hidden: int, seed: int):
    rng = np.random.default_rng(seed)
    action_width = simulator.ACTION_COUNT + simulator.ACTION_FEATURE_SIZE
    weights = {
        "encoder_w": rng.normal(0, 0.16, (simulator.STATE_SIZE, latent)).astype(np.float32),
        "encoder_b": np.zeros(latent, dtype=np.float32),
        "predictor_w1": rng.normal(0, 0.12, (latent + action_width, hidden)).astype(np.float32),
        "predictor_b1": np.zeros(hidden, dtype=np.float32),
        "predictor_w2": rng.normal(0, 0.10, (hidden, latent)).astype(np.float32),
        "predictor_b2": np.zeros(latent, dtype=np.float32),
        "state_w": rng.normal(0, 0.08, (latent, simulator.STATE_SIZE)).astype(np.float32),
        "state_b": np.zeros(simulator.STATE_SIZE, dtype=np.float32),
        "reconstruction_w": rng.normal(0, 0.08, (latent, simulator.STATE_SIZE)).astype(np.float32),
        "reconstruction_b": np.zeros(simulator.STATE_SIZE, dtype=np.float32),
        "action_w": rng.normal(0, 0.08, (latent, simulator.ACTION_COUNT)).astype(np.float32),
        "action_b": np.zeros(simulator.ACTION_COUNT, dtype=np.float32),
    }
    target = {
        "encoder_w": weights["encoder_w"].copy(),
        "encoder_b": weights["encoder_b"].copy(),
    }
    return rng, weights, target


def forward(state, actions, weights):
    encoder_pre = state @ weights["encoder_w"] + weights["encoder_b"]
    latent = np.tanh(encoder_pre)
    predictor_input = np.concatenate((latent, actions), axis=1)
    hidden_pre = predictor_input @ weights["predictor_w1"] + weights["predictor_b1"]
    hidden = np.maximum(hidden_pre, 0)
    predicted_latent = hidden @ weights["predictor_w2"] + weights["predictor_b2"]
    reconstructed_state = latent @ weights["reconstruction_w"] + weights["reconstruction_b"]
    action_context = predicted_latent - latent
    action_logits = action_context @ weights["action_w"] + weights["action_b"]
    delta = predicted_latent @ weights["state_w"] + weights["state_b"]
    return (
        encoder_pre,
        latent,
        predictor_input,
        hidden_pre,
        hidden,
        predicted_latent,
        reconstructed_state,
        action_context,
        action_logits,
        delta,
    )


def predict_delta(state, action, features, weights):
    actions = np.zeros((1, simulator.ACTION_COUNT + simulator.ACTION_FEATURE_SIZE), dtype=np.float32)
    actions[0, action] = 1.0
    actions[0, simulator.ACTION_COUNT:] = features
    return forward(state.reshape(1, -1), actions, weights)[-1][0]


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    values = np.exp(shifted)
    return values / values.sum(axis=1, keepdims=True)


def validation_metrics(state, actions, delta, next_state, weights, target):
    outputs = forward(state, actions, weights)
    latent = outputs[1]
    predicted_latent = outputs[5]
    reconstructed_state = outputs[6]
    action_logits = outputs[8]
    predicted_delta = outputs[9]
    target_latent = np.tanh(next_state @ target["encoder_w"] + target["encoder_b"])
    probabilities = np.clip(softmax(action_logits), 1e-8, 1.0)
    action_targets = actions[:, : simulator.ACTION_COUNT]
    delta_mse = float(np.mean((predicted_delta - delta) ** 2))
    latent_mse = float(np.mean((predicted_latent - target_latent) ** 2))
    reconstruction_mse = float(np.mean((reconstructed_state - state) ** 2))
    action_cross_entropy = float(-np.mean(np.sum(action_targets * np.log(probabilities), axis=1)))
    objective = (
        delta_mse
        + 0.25 * latent_mse
        + 0.10 * reconstruction_mse
        + 0.0001 * action_cross_entropy
    )
    return {
        "objective": objective,
        "delta_mse": delta_mse,
        "latent_prediction_mse": latent_mse,
        "reconstruction_mse": reconstruction_mse,
        "action_cross_entropy": action_cross_entropy,
    }


def representation_metrics(rows, weights):
    state, actions, _, _ = state_arrays(rows)
    outputs = forward(state, actions, weights)
    latent = outputs[1]
    action_context = outputs[7]
    centered = latent - latent.mean(axis=0, keepdims=True)
    singular = np.linalg.svd(centered, full_matrices=False, compute_uv=False)
    mass = singular / max(float(singular.sum()), 1e-12)
    effective_rank = float(np.exp(-np.sum(mass[mass > 0] * np.log(mass[mass > 0]))))
    action_means = []
    for action in range(simulator.ACTION_COUNT):
        mask = actions[:, action] > 0.5
        action_means.append(action_context[mask].mean(axis=0))
    return {
        "latent_standard_deviation": float(np.std(latent)),
        "effective_rank": effective_rank,
        "action_sensitivity": float(np.std(np.asarray(action_means, dtype=np.float32))),
    }


def train(train_rows, validation_rows, latent: int, hidden: int, epochs: int, seed: int):
    train_state, train_actions, train_delta, train_next = state_arrays(train_rows)
    val_state, val_actions, val_delta, val_next = state_arrays(validation_rows)
    rng, weights, target = initialize(latent, hidden, seed)
    moments = {name: np.zeros_like(value) for name, value in weights.items()}
    velocities = {name: np.zeros_like(value) for name, value in weights.items()}
    best = None
    best_validation = float("inf")
    stale = 0
    batch_size = min(1024, len(train_rows))

    for epoch in range(1, epochs + 1):
        indices = rng.choice(len(train_rows), batch_size, replace=False)
        state = train_state[indices]
        actions = train_actions[indices]
        actual_delta = train_delta[indices]
        actual_next = train_next[indices]
        (
            encoder_pre,
            latent_values,
            predictor_input,
            hidden_pre,
            hidden_values,
            predicted_latent,
            reconstructed_state,
            action_context,
            action_logits,
            predicted_delta,
        ) = forward(state, actions, weights)
        target_latent = np.tanh(actual_next @ target["encoder_w"] + target["encoder_b"])

        delta_gradient = np.float32(2.0) * (predicted_delta - actual_delta) / np.float32(batch_size * simulator.STATE_SIZE)
        latent_gradient = (
            np.float32(2.0) * LATENT_LOSS_WEIGHT * (predicted_latent - target_latent)
            / np.float32(batch_size * latent)
        )
        reconstruction_gradient = (
            np.float32(2.0)
            * RECONSTRUCTION_LOSS_WEIGHT
            * (reconstructed_state - state)
            / np.float32(batch_size * simulator.STATE_SIZE)
        )
        action_targets = actions[:, : simulator.ACTION_COUNT]
        action_gradient = ACTION_LOSS_WEIGHT * (softmax(action_logits) - action_targets) / np.float32(batch_size)
        gradients = {}
        gradients["state_w"] = predicted_latent.T @ delta_gradient
        gradients["state_b"] = delta_gradient.sum(axis=0)
        gradients["reconstruction_w"] = latent_values.T @ reconstruction_gradient
        gradients["reconstruction_b"] = reconstruction_gradient.sum(axis=0)
        gradients["action_w"] = action_context.T @ action_gradient
        gradients["action_b"] = action_gradient.sum(axis=0)
        action_context_gradient = action_gradient @ weights["action_w"].T
        predicted_latent_gradient = (
            latent_gradient
            + delta_gradient @ weights["state_w"].T
            + action_context_gradient
        )
        gradients["predictor_w2"] = hidden_values.T @ predicted_latent_gradient
        gradients["predictor_b2"] = predicted_latent_gradient.sum(axis=0)
        hidden_gradient = predicted_latent_gradient @ weights["predictor_w2"].T
        hidden_gradient[hidden_pre <= 0] = 0
        gradients["predictor_w1"] = predictor_input.T @ hidden_gradient
        gradients["predictor_b1"] = hidden_gradient.sum(axis=0)
        predictor_input_gradient = hidden_gradient @ weights["predictor_w1"].T
        latent_gradient_online = (
            predictor_input_gradient[:, :latent]
            + reconstruction_gradient @ weights["reconstruction_w"].T
            - action_context_gradient
        )
        encoder_gradient = latent_gradient_online * (np.float32(1.0) - np.tanh(encoder_pre) ** 2)
        gradients["encoder_w"] = state.T @ encoder_gradient
        gradients["encoder_b"] = encoder_gradient.sum(axis=0)

        for name, parameter in weights.items():
            gradient = np.clip(gradients[name], -1.0, 1.0)
            moments[name] *= 0.9
            moments[name] += 0.1 * gradient
            velocities[name] *= 0.999
            velocities[name] += 0.001 * gradient * gradient
            corrected_moment = moments[name] / (1 - 0.9**epoch)
            corrected_velocity = velocities[name] / (1 - 0.999**epoch)
            parameter -= np.float32(0.002) * corrected_moment / (np.sqrt(corrected_velocity) + 1e-8)

        target["encoder_w"] *= EMA_DECAY
        target["encoder_w"] += (np.float32(1.0) - EMA_DECAY) * weights["encoder_w"]
        target["encoder_b"] *= EMA_DECAY
        target["encoder_b"] += (np.float32(1.0) - EMA_DECAY) * weights["encoder_b"]

        if epoch % 25 == 0 or epoch == epochs:
            metrics = validation_metrics(
                val_state, val_actions, val_delta, val_next, weights, target
            )
            current = metrics["objective"]
            if current < best_validation - 1e-9:
                best_validation = current
                best = {name: value.copy() for name, value in weights.items()}
                best_metrics = metrics
                stale = 0
            else:
                stale += 1
            if stale >= 16:
                break
    if best is None:
        best = weights
        best_metrics = validation_metrics(
            val_state, val_actions, val_delta, val_next, weights, target
        )
    return best, best_metrics, epoch


def write_artifact(path: Path, weights, samples: int, h3: float, mean_h3: float, latent: int, hidden: int):
    header = struct.pack(
        "<4sIIIIIIIIffI",
        MAGIC,
        VERSION,
        simulator.STATE_SIZE,
        simulator.ACTION_COUNT,
        simulator.ACTION_FEATURE_SIZE,
        latent,
        hidden,
        samples,
        simulator.ACTION_COUNT + simulator.ACTION_FEATURE_SIZE,
        h3,
        mean_h3,
        0,
    )
    body = b"".join(
        np.asarray(weights[name], dtype="<f4").tobytes(order="C")
        for name in (
            "encoder_w", "encoder_b", "predictor_w1", "predictor_b1",
            "predictor_w2", "predictor_b2", "state_w", "state_b",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=Path("target/physical_jepa_candidate.bin"))
    parser.add_argument("--evaluation", type=Path, default=Path("target/physical_jepa_candidate.json"))
    parser.add_argument("--episodes", type=int, default=2500)
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument("--latent", type=int, default=24)
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=2400)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--training-seed",
        type=int,
        help="model initialization/minibatch seed; defaults to the dataset seed",
    )
    parser.add_argument(
        "--selection-only",
        action="store_true",
        help="report validation evidence without opening the held-out test split",
    )
    args = parser.parse_args()
    if args.steps < 5:
        parser.error("--steps must be at least 5 for registered H=1..5 evaluation")
    if args.episodes < 20:
        parser.error("--episodes must be at least 20 for episode-disjoint splits")

    training_seed = args.seed if args.training_seed is None else args.training_seed
    rows = simulator.generate(args.episodes, args.steps, args.seed)
    train_ids, validation_ids, train_rows, validation_rows, test_rows = split_rows(rows, args.episodes, args.seed)
    weights, validation, trained_epochs = train(
        train_rows, validation_rows, args.latent, args.hidden, args.epochs, training_seed
    )
    mean_delta = np.zeros((simulator.ACTION_COUNT, simulator.STATE_SIZE), dtype=np.float32)
    for action in range(simulator.ACTION_COUNT):
        selected = [row[5] - row[2] for row in train_rows if row[3] == action]
        mean_delta[action] = np.mean(selected, axis=0)
    predictor = lambda state, action, features: predict_delta(state, action, features, weights)
    mean_predictor = lambda _state, action, _features: mean_delta[action]
    validation_rollout = {}
    for horizon in range(1, 6):
        validation_rollout[f"physical_jepa_h{horizon}"] = simulator.rollout_error(
            validation_rows, predictor, horizon
        )
        validation_rollout[f"per_action_mean_h{horizon}"] = simulator.rollout_error(
            validation_rows, mean_predictor, horizon
        )
    validation_representation = representation_metrics(validation_rows, weights)

    test_rollout = None
    safety = None
    test_representation = None
    if not args.selection_only:
        test_rollout = {}
        for horizon in range(1, 6):
            test_rollout[f"physical_jepa_h{horizon}"] = simulator.rollout_error(
                test_rows, predictor, horizon
            )
            test_rollout[f"per_action_mean_h{horizon}"] = simulator.rollout_error(
                test_rows, mean_predictor, horizon
            )
        rules = simulator.confusion(
            test_rows, lambda row: simulator.rules_block(row[2], row[3], row[4])
        )
        learned = simulator.confusion(test_rows, lambda row: simulator.predicted_block(
            row[2], row[3], row[4], np.clip(row[2] + predictor(row[2], row[3], row[4]), -1.25, 1.25)
        ))
        combined = simulator.confusion(test_rows, lambda row: simulator.rules_block(row[2], row[3], row[4]) or simulator.predicted_block(
            row[2], row[3], row[4], np.clip(row[2] + predictor(row[2], row[3], row[4]), -1.25, 1.25)
        ))
        safety = {
            "rules_only": rules,
            "jepa_only": learned,
            "rules_plus_jepa": combined,
        }
        test_representation = representation_metrics(test_rows, weights)
    artifact_rollout = test_rollout or validation_rollout
    write_artifact(
        args.artifact,
        weights,
        len(train_rows),
        artifact_rollout["physical_jepa_h3"],
        artifact_rollout["per_action_mean_h3"],
        args.latent,
        args.hidden,
    )
    evaluation = {
        "schema_version": VERSION,
        "source": "deterministic_simulator_only",
        "model_class": "ema_target_joint_embedding_predictive_architecture",
        "objective": "ema_target_latent_prediction_with_reconstruction_action_and_state_delta_auxiliaries",
        "action_names": simulator.ACTION_NAMES,
        "state_dimensions": simulator.STATE_SIZE,
        "action_feature_dimensions": simulator.ACTION_FEATURE_SIZE,
        "episodes": args.episodes,
        "transitions": len(rows),
        "dangerous_transitions": sum(row[6] for row in rows),
        "episode_split": {
            "train": len(train_ids), "validation": len(validation_ids),
            "test": args.episodes - len(train_ids) - len(validation_ids),
        },
        "transition_split": {"train": len(train_rows), "validation": len(validation_rows), "test": len(test_rows)},
        "episode_overlap": 0,
        "data_seed": args.seed,
        "training_seed": training_seed,
        "latent": args.latent,
        "hidden": args.hidden,
        "epochs_requested": args.epochs,
        "epochs_completed": trained_epochs,
        "validation": validation,
        "validation_mse": validation["delta_mse"],
        "validation_rollout_error": validation_rollout,
        "validation_anti_collapse": validation_representation,
        "training_objective": {
            "ema_decay": float(EMA_DECAY),
            "latent_loss_weight": float(LATENT_LOSS_WEIGHT),
            "reconstruction_loss_weight": float(RECONSTRUCTION_LOSS_WEIGHT),
            "action_loss_weight": float(ACTION_LOSS_WEIGHT),
        },
        "test_split_opened": not args.selection_only,
        "artifact": str(args.artifact).replace("\\", "/"),
        "artifact_format": "PJE1",
        "artifact_sha256": hashlib.sha256(args.artifact.read_bytes()).hexdigest(),
        "artifact_bytes": args.artifact.stat().st_size,
        "validated_for_gating": False,
        "gating_reason": "Simulator-only trajectories cannot validate control of real physical machinery.",
    }
    if test_rollout is not None:
        evaluation["normalized_rollout_error"] = test_rollout
        evaluation["anti_collapse"] = test_representation
        evaluation["safety"] = safety
    args.evaluation.parent.mkdir(parents=True, exist_ok=True)
    args.evaluation.write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evaluation, indent=2))


if __name__ == "__main__":
    main()
