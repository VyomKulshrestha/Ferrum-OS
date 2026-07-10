#!/usr/bin/env python3
"""
Trains the world model's Phase 2 transition model: a small MLP predicting
the *delta* a tool call produces on the 128-float state embedding
(cognitive/world_model/encoder.rs), given the current embedding and a
one-hot action id. Predicting a delta rather than the absolute next state
matches how Phase 1's rule table already works (fixed per-action nudges
to a handful of fields) and is far easier to fit than the identity-heavy
absolute target (most of the 128 dims never change per call).

Pure numpy, no PyTorch/candle - same pragmatic scoping as
scripts/convert_model_v2.py. Reads scripts/collect_world_model_dataset.mjs's
output (target/world_model_dataset.jsonl), trains, and writes a flat f32
binary weights file cognitive/world_model/learned.rs loads at daemon boot.

Usage:
    python scripts/train_world_model.py [--dataset PATH] [--out PATH] [--hidden N] [--epochs N]
"""
import argparse
import json
import struct
import sys

import numpy as np

EMBEDDING_SIZE = 128
NUM_TOOLS = 41
INPUT_SIZE = EMBEDDING_SIZE + NUM_TOOLS  # state + one-hot action
OUTPUT_SIZE = EMBEDDING_SIZE

# Mirrors cognitive/world_model/transition.rs's rule table, for the
# specific fields it actually touches (encoder.rs's IDX_PROC_COUNT=0,
# IDX_HEAP_FRACTION=1, IDX_FS_FILE_COUNT=2, IDX_DISK_USAGE=3) - used only
# to compute a baseline MSE the learned model should beat, not shipped
# anywhere. TOOL_NAMES order must match world_model/mod.rs's array
# exactly since action ids are positional.
TOOL_NAMES = [
    "ipc_send", "audit_write", "yield_cpu", "camera_capture", "gesture_status",
    "report_status", "capability_check", "read_file", "read_dir", "query_memory",
    "get_config", "system_info", "list_processes", "net_connect", "net_send",
    "net_recv", "http_get", "write_file", "create_directory", "save_memory",
    "load_memory", "set_goal", "sleep", "service_start", "service_stop",
    "exec_process", "delete_file", "local_inference", "trigger_kernel_upgrade",
    "hud_update", "hit_test", "read_screen", "add_subtask", "record_audio",
    "play_audio", "set_volume", "keyboard_type", "mouse_click", "mouse_move",
    "browse_url", "poll_input",
]


def rule_table_delta(action_name):
    delta = np.zeros(EMBEDDING_SIZE, dtype=np.float32)
    if action_name == "write_file":
        delta[3] = 0.02
        delta[2] = 0.01
    elif action_name == "delete_file":
        delta[2] = -0.01
    elif action_name == "create_directory":
        delta[3] = 0.005
    elif action_name == "exec_process":
        delta[0] = 1.0 / 64.0
    elif action_name == "service_start":
        delta[0] = 1.0 / 64.0
    elif action_name == "service_stop":
        delta[0] = -1.0 / 64.0
    elif action_name == "trigger_kernel_upgrade":
        delta[1] = 1.0  # forced to max, not a small nudge - handled specially below
    return delta


def load_dataset(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def build_arrays(rows):
    n = len(rows)
    X = np.zeros((n, INPUT_SIZE), dtype=np.float32)
    Y = np.zeros((n, OUTPUT_SIZE), dtype=np.float32)
    baseline = np.zeros((n, OUTPUT_SIZE), dtype=np.float32)
    for i, row in enumerate(rows):
        before = np.array(row["before"], dtype=np.float32)
        after = np.array(row["after"], dtype=np.float32)
        action_id = row["action"]
        X[i, :EMBEDDING_SIZE] = before
        if 0 <= action_id < NUM_TOOLS:
            X[i, EMBEDDING_SIZE + action_id] = 1.0
        Y[i] = after - before
        action_name = TOOL_NAMES[action_id] if 0 <= action_id < NUM_TOOLS else ""
        if action_name == "trigger_kernel_upgrade":
            # transition.rs forces heap_fraction to 1.0 outright, not a
            # relative nudge - the baseline "delta" here is (1.0 - before[1]).
            baseline[i] = rule_table_delta(action_name)
            baseline[i, 1] = 1.0 - before[1]
        else:
            baseline[i] = rule_table_delta(action_name)
    return X, Y, baseline


def train_mlp(X, Y, hidden_size, epochs, lr, seed=0):
    rng = np.random.default_rng(seed)
    n_in, n_out = X.shape[1], Y.shape[1]
    w1 = rng.normal(0, 1.0 / np.sqrt(n_in), size=(n_in, hidden_size)).astype(np.float32)
    b1 = np.zeros(hidden_size, dtype=np.float32)
    w2 = rng.normal(0, 1.0 / np.sqrt(hidden_size), size=(hidden_size, n_out)).astype(np.float32)
    b2 = np.zeros(n_out, dtype=np.float32)

    n = X.shape[0]
    for epoch in range(epochs):
        h_pre = X @ w1 + b1
        h = np.maximum(h_pre, 0.0)
        pred = h @ w2 + b2

        err = pred - Y
        loss = float(np.mean(err ** 2))

        d_pred = (2.0 / n) * err
        grad_w2 = h.T @ d_pred
        grad_b2 = d_pred.sum(axis=0)
        d_h = d_pred @ w2.T
        d_h[h_pre <= 0] = 0.0
        grad_w1 = X.T @ d_h
        grad_b1 = d_h.sum(axis=0)

        w2 -= lr * grad_w2
        b2 -= lr * grad_b2
        w1 -= lr * grad_w1
        b1 -= lr * grad_b1

        if epoch % max(1, epochs // 10) == 0 or epoch == epochs - 1:
            print(f"  epoch {epoch:5d}  train MSE={loss:.6f}")

    return w1, b1, w2, b2


def predict_mlp(X, w1, b1, w2, b2):
    h = np.maximum(X @ w1 + b1, 0.0)
    return h @ w2 + b2


def write_weights(path, w1, b1, w2, b2):
    """
    Flat binary format cognitive/world_model/learned.rs parses directly:
      header: 3 x u32 LE = input_size, hidden_size, output_size
      then f32 LE arrays in order: w1 (input*hidden), b1 (hidden),
      w2 (hidden*output), b2 (output) - row-major, matching numpy's
      default C-contiguous layout so a straight byte copy is correct.
    """
    input_size, hidden_size = w1.shape
    output_size = w2.shape[1]
    with open(path, "wb") as f:
        f.write(struct.pack("<III", input_size, hidden_size, output_size))
        f.write(w1.astype("<f4").tobytes())
        f.write(b1.astype("<f4").tobytes())
        f.write(w2.astype("<f4").tobytes())
        f.write(b2.astype("<f4").tobytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="target/world_model_dataset.jsonl")
    parser.add_argument("--out", default="target/world_model_learned.bin")
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=2000)
    parser.add_argument("--lr", type=float, default=0.05)
    parser.add_argument("--holdout", type=float, default=0.15)
    args = parser.parse_args()

    rows = load_dataset(args.dataset)
    if len(rows) < 20:
        print(f"error: only {len(rows)} examples in {args.dataset} - collect more with scripts/collect_world_model_dataset.mjs first", file=sys.stderr)
        sys.exit(1)
    print(f"loaded {len(rows)} examples from {args.dataset}")

    X, Y, baseline_delta = build_arrays(rows)

    rng = np.random.default_rng(42)
    idx = rng.permutation(len(rows))
    n_holdout = max(1, int(len(rows) * args.holdout))
    holdout_idx, train_idx = idx[:n_holdout], idx[n_holdout:]

    X_train, Y_train = X[train_idx], Y[train_idx]
    X_holdout, Y_holdout, baseline_holdout = X[holdout_idx], Y[holdout_idx], baseline_delta[holdout_idx]

    print(f"train/holdout split: {len(train_idx)}/{len(holdout_idx)}")

    baseline_mse = float(np.mean((baseline_holdout - Y_holdout) ** 2))
    zero_mse = float(np.mean(Y_holdout ** 2))
    print(f"baseline (Phase 1 rule table) holdout MSE: {baseline_mse:.6f}")
    print(f"trivial (always predict zero delta) holdout MSE: {zero_mse:.6f}")

    print(f"training MLP (input={X.shape[1]}, hidden={args.hidden}, output={Y.shape[1]}, epochs={args.epochs})...")
    w1, b1, w2, b2 = train_mlp(X_train, Y_train, args.hidden, args.epochs, args.lr)

    pred_holdout = predict_mlp(X_holdout, w1, b1, w2, b2)
    learned_mse = float(np.mean((pred_holdout - Y_holdout) ** 2))
    print(f"learned MLP holdout MSE: {learned_mse:.6f}")

    if learned_mse < baseline_mse:
        print(f"PASS: learned model beats the Phase 1 rule table baseline ({learned_mse:.6f} < {baseline_mse:.6f})")
    else:
        print(f"FAIL: learned model does not beat the Phase 1 rule table baseline ({learned_mse:.6f} >= {baseline_mse:.6f})")
        sys.exit(1)

    write_weights(args.out, w1, b1, w2, b2)
    print(f"wrote weights to {args.out} ({w1.nbytes + b1.nbytes + w2.nbytes + b2.nbytes + 12} bytes)")


if __name__ == "__main__":
    main()
