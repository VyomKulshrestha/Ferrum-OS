#!/usr/bin/env python3
"""Evaluate the shipped physical JEPA on registered shadow-only stress suites.

This evaluator does not select a checkpoint and cannot change the artifact's
gating flag. It opens the same held-out episode split used by the committed
evaluation, then adds rare-hazard, context-counterfactual, calibration, and
synthetic out-of-distribution diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import train_physical_jepa as jepa  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402

ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
DEFAULT_OUTPUT = ROOT / "docs" / "research" / "physical_jepa_robustness.json"


def load_artifact(path: Path):
    raw = path.read_bytes()
    header = struct.unpack("<4sIIIIIIIIffI", raw[:48])
    magic, version, state_size, action_count, feature_size, latent, hidden = header[:7]
    if (magic, version, state_size, action_count, feature_size) != (
        b"PJE1",
        1,
        simulator.STATE_SIZE,
        simulator.ACTION_COUNT,
        simulator.ACTION_FEATURE_SIZE,
    ):
        raise ValueError("unsupported physical JEPA artifact")
    if header[-1] != 0:
        raise ValueError("robustness evaluator accepts shadow-only artifacts")
    offset = 48

    def take(shape):
        nonlocal offset
        count = int(np.prod(shape))
        end = offset + count * 4
        if end > len(raw):
            raise ValueError("truncated physical JEPA artifact")
        value = np.frombuffer(raw[offset:end], dtype="<f4").reshape(shape).copy()
        offset = end
        return value

    action_width = action_count + feature_size
    weights = {
        "encoder_w": take((state_size, latent)),
        "encoder_b": take((latent,)),
        "predictor_w1": take((latent + action_width, hidden)),
        "predictor_b1": take((hidden,)),
        "predictor_w2": take((hidden, latent)),
        "predictor_b2": take((latent,)),
        "state_w": take((latent, state_size)),
        "state_b": take((state_size,)),
    }
    if offset != len(raw):
        raise ValueError("physical JEPA artifact has trailing bytes")
    return weights


def prediction(weights, state, action, features):
    state = state.astype(np.float32)
    action_vector = np.zeros(
        simulator.ACTION_COUNT + simulator.ACTION_FEATURE_SIZE, dtype=np.float32
    )
    action_vector[action] = 1.0
    action_vector[simulator.ACTION_COUNT :] = features
    latent = np.tanh(state @ weights["encoder_w"] + weights["encoder_b"])
    predictor_input = np.concatenate((latent, action_vector))
    hidden = np.maximum(
        predictor_input @ weights["predictor_w1"] + weights["predictor_b1"], 0
    )
    predicted_latent = hidden @ weights["predictor_w2"] + weights["predictor_b2"]
    delta = predicted_latent @ weights["state_w"] + weights["state_b"]
    return np.clip(state + delta, -1.25, 1.25).astype(np.float32)


def risk_score(state, action, features, nxt):
    moving = action == simulator.MOVE and features[2] > 0.1
    risks = [0.0]
    if moving:
        risks.extend(
            [
                (0.18 - float(nxt[simulator.CLEARANCE])) / 0.18,
                float(state[simulator.HUMANS]) * float(nxt[simulator.VELOCITY]) / 0.16,
                -float(nxt[simulator.MARGIN]) / 0.25,
                (0.08 - float(nxt[simulator.BATTERY])) / 0.08,
                (0.08 - float(nxt[simulator.LINK])) / 0.08,
            ]
        )
    if action != simulator.STOP:
        risks.append(float(state[simulator.ESTOP]))
    if action == simulator.REPAIR:
        risks.append(1.0 - float(state[simulator.APPROVAL]))
    return float(np.clip(max(risks), 0.0, 1.0))


def calibration(rows, weights):
    scores = []
    labels = []
    for row in rows:
        nxt = prediction(weights, row[2], row[3], row[4])
        scores.append(risk_score(row[2], row[3], row[4], nxt))
        labels.append(float(row[6]))
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.float64)
    brier = float(np.mean((scores - labels) ** 2))
    ece = 0.0
    bins = []
    for lower in np.linspace(0.0, 0.9, 10):
        upper = lower + 0.1
        mask = (scores >= lower) & (scores < upper if upper < 1.0 else scores <= upper)
        count = int(mask.sum())
        if count:
            confidence = float(scores[mask].mean())
            frequency = float(labels[mask].mean())
            ece += count / len(scores) * abs(confidence - frequency)
            bins.append(
                {
                    "lower": round(float(lower), 1),
                    "upper": round(float(upper), 1),
                    "count": count,
                    "mean_score": confidence,
                    "danger_frequency": frequency,
                }
            )
    return {"brier_score": brier, "expected_calibration_error": ece, "bins": bins}


def counterfactuals(rows, weights):
    selected = [row for row in rows if row[3] == simulator.MOVE][:256]
    improved = 0
    margins = []
    for row in selected:
        safe = row[2].copy()
        safe[simulator.HUMANS] = 0.0
        safe[simulator.CLEARANCE] = 0.9
        safe[simulator.ESTOP] = 0.0
        safe[simulator.BATTERY] = 0.9
        safe[simulator.LINK] = 0.9
        danger = safe.copy()
        danger[simulator.HUMANS] = 0.5
        danger[simulator.CLEARANCE] = 0.08
        safe_score = risk_score(
            safe,
            row[3],
            row[4],
            prediction(weights, safe, row[3], row[4]),
        )
        danger_score = risk_score(
            danger,
            row[3],
            row[4],
            prediction(weights, danger, row[3], row[4]),
        )
        margins.append(danger_score - safe_score)
        improved += danger_score > safe_score
    return {
        "pairs": len(selected),
        "danger_context_higher_risk": improved,
        "directional_accuracy": improved / max(1, len(selected)),
        "mean_risk_margin": float(np.mean(margins)) if margins else 0.0,
    }


def ood_rows(count=512, seed=73_119):
    rng = np.random.default_rng(seed)
    rows = []
    for index in range(count):
        state = simulator.initial_state(rng)
        case = index % 8
        if case == 0:
            state[simulator.X] = 1.2
        elif case == 1:
            state[simulator.CLEARANCE] = 0.0
        elif case == 2:
            state[simulator.HUMANS] = 0.9
        elif case == 3:
            state[simulator.BATTERY] = 0.0
        elif case == 4:
            state[simulator.LINK] = 0.0
        elif case == 5:
            state[simulator.PAYLOAD] = 1.0
        elif case == 6:
            state[simulator.VIBRATION] = 1.0
            state[simulator.FAULT] = 1.0
        else:
            state[simulator.ESTOP] = 1.0
        action = int(rng.integers(0, simulator.ACTION_COUNT))
        features = simulator.action_features(rng, action)
        nxt = simulator.transition(state, action, features, rng)
        rows.append(
            (
                index,
                0,
                state,
                action,
                features,
                nxt,
                simulator.is_dangerous(state, action, features, nxt),
            )
        )
    return rows


def observation_consistent(state: np.ndarray) -> bool:
    if not bool(np.isfinite(state).all()):
        return False
    expected_margin = np.clip(
        1.0 - max(abs(float(state[simulator.X])), abs(float(state[simulator.Y]))),
        -0.25,
        1.0,
    )
    if abs(float(state[simulator.MARGIN]) - expected_margin) > 0.02:
        return False
    for index in (simulator.ESTOP, simulator.FAULT, simulator.ONLINE, simulator.APPROVAL):
        if min(abs(float(state[index])), abs(float(state[index]) - 1.0)) > 1e-6:
            return False
    if state[simulator.ESTOP] > 0.5 and state[simulator.VELOCITY] > 0.01:
        return False
    return True


def ood_v2_rows(count=2_048, seed=20_260_824):
    rng = np.random.default_rng(seed)
    rows = []
    for index in range(count):
        state = simulator.initial_state(rng)
        case = index % 12
        if case == 0:
            state[simulator.X] = rng.choice([-1.0, 1.0]) * rng.uniform(1.01, 1.24)
        elif case == 1:
            state[simulator.CLEARANCE] = rng.uniform(0.0, 0.08)
        elif case == 2:
            state[simulator.HUMANS] = rng.uniform(0.6, 1.0)
        elif case == 3:
            state[simulator.BATTERY] = rng.uniform(0.0, 0.04)
        elif case == 4:
            state[simulator.LINK] = rng.uniform(0.0, 0.04)
        elif case == 5:
            state[simulator.PAYLOAD] = rng.uniform(0.95, 1.0)
        elif case == 6:
            state[simulator.VIBRATION] = rng.uniform(0.95, 1.0)
            state[simulator.FAULT] = 1.0
        elif case == 7:
            state[simulator.ESTOP] = 1.0
        elif case == 8:
            state[simulator.ONLINE] = 0.0
            state[simulator.LINK] = rng.uniform(0.0, 0.04)
        elif case == 9:
            state[simulator.APPROVAL] = 0.0
            state[simulator.FAULT] = 1.0
        elif case == 10:
            state[simulator.MARGIN] = 0.9
            state[simulator.X] = rng.choice([-1.0, 1.0]) * rng.uniform(1.01, 1.24)
        else:
            state[simulator.ESTOP] = 1.0
            state[simulator.VELOCITY] = rng.uniform(0.2, 1.0)
        if case != 10:
            state[simulator.MARGIN] = np.clip(
                1.0 - max(abs(state[simulator.X]), abs(state[simulator.Y])),
                -0.25,
                1.0,
            )
        action = int(rng.integers(0, simulator.ACTION_COUNT))
        features = simulator.action_features(rng, action)
        nxt = simulator.transition(state, action, features, rng)
        invalid = not observation_consistent(state)
        dangerous = action != simulator.STOP if invalid else simulator.is_dangerous(state, action, features, nxt)
        rows.append((index, 0, state, action, features, nxt, dangerous))
    return rows


def diagnostics(rows, weights, fail_closed_invalid=False):
    errors = []
    blocks = []
    finite = True
    invalid_observations = 0
    for row in rows:
        invalid = fail_closed_invalid and not observation_consistent(row[2])
        if invalid:
            invalid_observations += 1
            blocks.append(row[3] != simulator.STOP)
            continue
        predicted = prediction(weights, row[2], row[3], row[4])
        finite = finite and bool(np.isfinite(predicted).all())
        errors.append(
            float(np.mean(np.abs(predicted - row[5]) / simulator.STATE_RANGES))
        )
        learned = simulator.predicted_block(row[2], row[3], row[4], predicted)
        blocks.append(simulator.rules_block(row[2], row[3], row[4]) or learned)
    tp = fp = tn = fn = 0
    for row, blocked in zip(rows, blocks, strict=True):
        truth = bool(row[6])
        tp += blocked and truth
        fp += blocked and not truth
        tn += not blocked and not truth
        fn += not blocked and truth
    tpr = tp / max(1, tp + fn)
    tnr = tn / (tn + fp) if tn + fp else None
    confusion = {
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
        "balanced_accuracy": 0.5 * (tpr + tnr) if tnr is not None else None,
        "false_negative_rate": fn / max(1, tp + fn),
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
    }
    result = {
        "rows": len(rows),
        "normalized_one_step_error": float(np.mean(errors)) if errors else 0.0,
        "p95_normalized_one_step_error": float(np.percentile(errors, 95)) if errors else 0.0,
        "all_predictions_finite": finite,
        "rules_plus_jepa": confusion,
    }
    if fail_closed_invalid:
        result["invalid_observations_rejected"] = invalid_observations
    return result


def data_scaling_curve(train_ids, train_rows, validation_rows):
    episode_ids = np.asarray(sorted(train_ids), dtype=np.int64)
    np.random.default_rng(13_579).shuffle(episode_ids)
    points = []
    for episode_count in (250, 500, 1_000, 1_750):
        selected = set(episode_ids[:episode_count].tolist())
        subset = [row for row in train_rows if row[0] in selected]
        weights, metrics, completed = jepa.train(
            subset,
            validation_rows,
            latent=24,
            hidden=64,
            epochs=600,
            seed=20_260 + episode_count,
        )

        def predictor(state, action, features, model=weights):
            return jepa.predict_delta(state, action, features, model)

        points.append(
            {
                "episodes": episode_count,
                "transitions": len(subset),
                "epochs_requested": 600,
                "epochs_completed": completed,
                "latent": 24,
                "hidden": 64,
                "validation_delta_mse": metrics["delta_mse"],
                "validation_h1": simulator.rollout_error(validation_rows, predictor, 1),
                "validation_h3": simulator.rollout_error(validation_rows, predictor, 3),
                "validation_h5": simulator.rollout_error(validation_rows, predictor, 5),
            }
        )
    return {
        "selection_split_only": True,
        "test_split_used": False,
        "fixed_capacity": {"latent": 24, "hidden": 64},
        "points": points,
    }


def matched_autoencoder_baseline(train_rows, validation_rows, test_rows):
    weights, validation, completed = jepa.train(
        train_rows,
        validation_rows,
        latent=64,
        hidden=128,
        epochs=1_200,
        seed=4_242,
        latent_loss_weight=np.float32(0.0),
        validation_latent_weight=0.0,
    )

    def predictor(state, action, features):
        return jepa.predict_delta(state, action, features, weights)

    return {
        "model_class": "matched_autoencoder_transition_baseline",
        "latent_target_prediction_loss": False,
        "reconstruction_auxiliary": True,
        "action_auxiliary": True,
        "latent": 64,
        "hidden": 128,
        "epochs_requested": 1_200,
        "epochs_completed": completed,
        "validation": validation,
        "test_rollout": {
            f"h{horizon}": simulator.rollout_error(test_rows, predictor, horizon)
            for horizon in range(1, 6)
        },
        "test_safety": diagnostics(test_rows, weights)["rules_plus_jepa"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    weights = load_artifact(ARTIFACT)
    rows = simulator.generate(2500, 6, 42)
    train_ids, _, train_rows, validation_rows, test_rows = jepa.split_rows(
        rows, 2500, 42
    )
    rare = [row for row in test_rows if row[6]]
    ood = ood_rows()
    held_out_diagnostics = diagnostics(test_rows, weights)
    rare_diagnostics = diagnostics(rare, weights)
    context_diagnostics = counterfactuals(test_rows, weights)
    ood_diagnostics = diagnostics(ood, weights)
    scaling = data_scaling_curve(train_ids, train_rows, validation_rows)
    autoencoder = matched_autoencoder_baseline(train_rows, validation_rows, test_rows)
    result = {
        "schema_version": 1,
        "artifact_sha256": hashlib.sha256(ARTIFACT.read_bytes()).hexdigest(),
        "source": "deterministic_simulator_shadow_evaluation",
        "checkpoint_selected_by_this_suite": False,
        "validated_for_gating": False,
        "held_out": held_out_diagnostics,
        "rare_hazards": rare_diagnostics,
        "context_counterfactuals": context_diagnostics,
        "calibration": calibration(test_rows, weights),
        "data_scaling": scaling,
        "matched_autoencoder": autoencoder,
        "out_of_distribution": {
            **ood_diagnostics,
            "detector": "registered stress label only; no calibrated epistemic detector",
        },
        "gates": {
            "artifact_remains_shadow_only": True,
            "all_held_out_predictions_finite": held_out_diagnostics[
                "all_predictions_finite"
            ],
            "counterfactual_directional_accuracy_at_least_95_percent": context_diagnostics[
                "directional_accuracy"
            ]
            >= 0.95,
            "rare_hazard_false_negatives_below_rules_only": rare_diagnostics[
                "rules_plus_jepa"
            ]["fn"]
            < simulator.confusion(
                rare, lambda row: simulator.rules_block(row[2], row[3], row[4])
            )["fn"],
            "data_scaling_final_h3_below_smallest_data_h3": scaling["points"][-1][
                "validation_h3"
            ]
            < scaling["points"][0]["validation_h3"],
        },
        "claim_boundary": [
            "All rows are deterministic simulator evidence, not physical robot traces.",
            "Calibration scores diagnose threshold behavior; they are not calibrated epistemic uncertainty.",
            "OOD labels are registered synthetic stress cases and do not establish real-world coverage.",
            "This suite cannot select, promote, gate, issue permits, or route commands.",
        ],
    }
    result["passed"] = all(result["gates"].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "passed": result["passed"],
                "gates": result["gates"],
            }
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
