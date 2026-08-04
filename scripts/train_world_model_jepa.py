#!/usr/bin/env python3
"""Train an action-conditioned JEPA candidate for FerrumOS world state.

The runtime-compatible context encoder remains 48 -> hidden -> 77. Training
adds an EMA target encoder and predicts the next target embedding from context
plus the provider-independent 41-way action and 16 canonical argument
features. Reconstruction and action-delta auxiliaries prevent collapsed latent
solutions; neither auxiliary ships in the appliance.
"""
import argparse
import json
import struct
import sys

import numpy as np

from train_world_model import NUM_TOOLS, ACTION_FEATURE_SIZE, split_indices
from train_world_model_encoder import extract_raw

RAW_SIZE = 48
LATENT_SIZE = 77
EMBEDDING_SIZE = 128
LATENT_START = 51
ACTION_SIZE = NUM_TOOLS + ACTION_FEATURE_SIZE


def load_rows(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def arrays(rows):
    before = np.stack([extract_raw(row["before"]) for row in rows])
    after = np.stack([extract_raw(row["after"]) for row in rows])
    action = np.zeros((len(rows), ACTION_SIZE), dtype=np.float32)
    for index, row in enumerate(rows):
        action_id = int(row["action"])
        action[index, action_id] = 1.0
        action[index, NUM_TOOLS:] = np.asarray(row.get("action_features", [0.0] * 16), dtype=np.float32)
    return before, after, action


def init_weights(hidden, seed):
    rng = np.random.default_rng(seed)
    normal = lambda shape, fan: rng.normal(0, 1 / np.sqrt(fan), shape).astype(np.float32)
    return {
        "ew1": normal((RAW_SIZE, hidden), RAW_SIZE), "eb1": np.zeros(hidden, np.float32),
        "ew2": normal((hidden, LATENT_SIZE), hidden), "eb2": np.zeros(LATENT_SIZE, np.float32),
        "pw1": normal((LATENT_SIZE + ACTION_SIZE, hidden), LATENT_SIZE + ACTION_SIZE),
        "pb1": np.zeros(hidden, np.float32),
        "pw2": normal((hidden, LATENT_SIZE), hidden), "pb2": np.zeros(LATENT_SIZE, np.float32),
        "dw": normal((LATENT_SIZE, RAW_SIZE), LATENT_SIZE), "db": np.zeros(RAW_SIZE, np.float32),
        "aw": normal((LATENT_SIZE, ACTION_SIZE), LATENT_SIZE), "ab": np.zeros(ACTION_SIZE, np.float32),
    }


def encode(x, weights, prefix="e"):
    pre = x @ weights[f"{prefix}w1"] + weights[f"{prefix}b1"]
    hidden = np.maximum(pre, 0)
    return hidden @ weights[f"{prefix}w2"] + weights[f"{prefix}b2"], hidden, pre


def predict(z, action, weights):
    inputs = np.concatenate([z, action], axis=1)
    pre = inputs @ weights["pw1"] + weights["pb1"]
    hidden = np.maximum(pre, 0)
    return hidden @ weights["pw2"] + weights["pb2"], hidden, pre, inputs


class Adam:
    def __init__(self, weights, lr):
        self.lr, self.step = lr, 0
        self.m = {key: np.zeros_like(value) for key, value in weights.items()}
        self.v = {key: np.zeros_like(value) for key, value in weights.items()}

    def update(self, weights, gradients):
        self.step += 1
        for key, gradient in gradients.items():
            gradient = np.clip(gradient, -5.0, 5.0)
            self.m[key] = 0.9 * self.m[key] + 0.1 * gradient
            self.v[key] = 0.999 * self.v[key] + 0.001 * gradient * gradient
            m_hat = self.m[key] / (1 - 0.9 ** self.step)
            v_hat = self.v[key] / (1 - 0.999 ** self.step)
            weights[key] -= self.lr * m_hat / (np.sqrt(v_hat) + 1e-8)


def batch_step(x, next_x, action, weights, target, optimizer, recon_weight, action_weight):
    count = len(x)
    z, eh, epre = encode(x, weights)
    target_z, _, _ = encode(next_x, target)
    predicted, ph, ppre, pinput = predict(z, action, weights)
    reconstructed = z @ weights["dw"] + weights["db"]
    action_predicted = (target_z - z) @ weights["aw"] + weights["ab"]

    d_pred = 2 * (predicted - target_z) / (count * LATENT_SIZE)
    d_recon = recon_weight * 2 * (reconstructed - x) / (count * RAW_SIZE)
    d_action = action_weight * 2 * (action_predicted - action) / (count * ACTION_SIZE)
    gradients = {}
    gradients["pw2"] = ph.T @ d_pred
    gradients["pb2"] = d_pred.sum(0)
    d_ph = d_pred @ weights["pw2"].T
    d_ph[ppre <= 0] = 0
    gradients["pw1"] = pinput.T @ d_ph
    gradients["pb1"] = d_ph.sum(0)
    d_z = (d_ph @ weights["pw1"].T)[:, :LATENT_SIZE]

    gradients["dw"] = z.T @ d_recon
    gradients["db"] = d_recon.sum(0)
    d_z += d_recon @ weights["dw"].T
    delta = target_z - z
    gradients["aw"] = delta.T @ d_action
    gradients["ab"] = d_action.sum(0)
    d_z -= d_action @ weights["aw"].T

    gradients["ew2"] = eh.T @ d_z
    gradients["eb2"] = d_z.sum(0)
    d_eh = d_z @ weights["ew2"].T
    d_eh[epre <= 0] = 0
    gradients["ew1"] = x.T @ d_eh
    gradients["eb1"] = d_eh.sum(0)
    optimizer.update(weights, gradients)


def evaluate(x, next_x, action, weights, target):
    z, _, _ = encode(x, weights)
    target_z, _, _ = encode(next_x, target)
    predicted, _, _, _ = predict(z, action, weights)
    recon = z @ weights["dw"] + weights["db"]
    action_pred = (target_z - z) @ weights["aw"] + weights["ab"]
    shuffled = np.roll(action, 1, axis=0)
    shuffled_pred, _, _, _ = predict(z, shuffled, weights)
    covariance = np.cov(z, rowvar=False)
    eigenvalues = np.maximum(np.linalg.eigvalsh(covariance), 0)
    probability = eigenvalues / max(float(eigenvalues.sum()), 1e-12)
    effective_rank = float(np.exp(-np.sum(probability * np.log(probability + 1e-12))))
    return {
        "prediction_mse": float(np.mean((predicted - target_z) ** 2)),
        "zero_delta_mse": float(np.mean((z - target_z) ** 2)),
        "reconstruction_mse": float(np.mean((recon - x) ** 2)),
        "action_decoder_mse": float(np.mean((action_pred - action) ** 2)),
        "latent_std": float(z.std()),
        "effective_rank": effective_rank,
        "action_sensitivity": float(np.mean((predicted - shuffled_pred) ** 2)),
    }


def write_encoder(path, weights):
    with open(path, "wb") as handle:
        handle.write(struct.pack("<III", RAW_SIZE, weights["ew1"].shape[1], LATENT_SIZE))
        for key in ("ew1", "eb1", "ew2", "eb2"):
            handle.write(weights[key].astype("<f4").tobytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out", default="target/world_model_encoder_jepa.bin")
    parser.add_argument("--encoded-dataset", default="target/world_model_dataset_jepa.jsonl")
    parser.add_argument("--metrics-out", default="target/world_model_jepa_metrics.json")
    parser.add_argument("--hidden", type=int, default=256)
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--ema", type=float, default=0.99)
    parser.add_argument("--reconstruction-weight", type=float, default=0.25)
    parser.add_argument("--action-weight", type=float, default=0.1)
    parser.add_argument("--validation", type=float, default=0.15)
    parser.add_argument("--test", type=float, default=0.15)
    parser.add_argument("--patience", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows = [row for row in load_rows(args.dataset) if row.get("executed", True)]
    if len(rows) < 100:
        sys.exit("JEPA requires at least 100 executed transitions")
    x, next_x, action = arrays(rows)
    train_idx, validation_idx, test_idx, split_mode = split_indices(
        rows, args.validation, args.test, args.seed
    )
    weights = init_weights(args.hidden, args.seed)
    target = {"ew1": weights["ew1"].copy(), "eb1": weights["eb1"].copy(),
              "ew2": weights["ew2"].copy(), "eb2": weights["eb2"].copy()}
    optimizer = Adam(weights, args.lr)
    rng = np.random.default_rng(args.seed)
    best, best_score, stale = None, float("inf"), 0
    for epoch in range(args.epochs):
        shuffled = rng.permutation(train_idx)
        for offset in range(0, len(shuffled), args.batch_size):
            batch = shuffled[offset:offset + args.batch_size]
            batch_step(x[batch], next_x[batch], action[batch], weights, target, optimizer,
                       args.reconstruction_weight, args.action_weight)
            for key in target:
                target[key] = args.ema * target[key] + (1 - args.ema) * weights[key]
        if epoch % max(1, args.epochs // 20) == 0 or epoch == args.epochs - 1:
            metrics = evaluate(x[validation_idx], next_x[validation_idx], action[validation_idx], weights, target)
            score = metrics["prediction_mse"] + args.reconstruction_weight * metrics["reconstruction_mse"]
            print(f"epoch {epoch:4d} validation prediction={metrics['prediction_mse']:.6f} "
                  f"reconstruction={metrics['reconstruction_mse']:.6f} rank={metrics['effective_rank']:.2f}")
            if score < best_score - 1e-8:
                best_score, stale = score, 0
                best = ({key: value.copy() for key, value in weights.items()},
                        {key: value.copy() for key, value in target.items()})
            else:
                stale += 1
                if args.patience and stale >= args.patience:
                    print(f"early stopping at epoch {epoch}")
                    break
    if best:
        weights, target = best
    test_metrics = evaluate(x[test_idx], next_x[test_idx], action[test_idx], weights, target)
    accepted = (
        test_metrics["prediction_mse"] < test_metrics["zero_delta_mse"]
        and test_metrics["latent_std"] >= 0.01
        and test_metrics["effective_rank"] >= 4.0
        and test_metrics["action_sensitivity"] >= 1e-6
    )
    print(json.dumps(test_metrics, indent=2))
    if not accepted:
        sys.exit("JEPA candidate rejected by anti-collapse or predictive acceptance gates")
    write_encoder(args.out, weights)
    encoded_rows = []
    for row in load_rows(args.dataset):
        before = list(row["before"])
        after = list(row["after"])
        before_z, _, _ = encode(extract_raw(before).reshape(1, -1), weights)
        after_z, _, _ = encode(extract_raw(after).reshape(1, -1), weights)
        before[LATENT_START:EMBEDDING_SIZE] = before_z[0].tolist()
        after[LATENT_START:EMBEDDING_SIZE] = after_z[0].tolist()
        encoded_rows.append({**row, "before": before, "after": after, "representation": "action_jepa_v1"})
    with open(args.encoded_dataset, "w", encoding="utf-8") as handle:
        handle.write("\n".join(json.dumps(row) for row in encoded_rows) + "\n")
    report = {
        "schema_version": 1, "accepted": accepted, "split_mode": split_mode,
        "train_rows": len(train_idx), "validation_rows": len(validation_idx), "test_rows": len(test_idx),
        "hidden_size": args.hidden, "test": test_metrics,
    }
    with open(args.metrics_out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(f"wrote accepted JEPA encoder to {args.out} and {len(encoded_rows)} encoded rows")


if __name__ == "__main__":
    main()
