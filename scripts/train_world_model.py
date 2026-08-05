#!/usr/bin/env python3
"""
Trains the world model's Phase 2 transition model: a small MLP predicting
the *delta* a tool call produces on the 128-float state embedding
(cognitive/world_model/encoder.rs), given the current embedding, a
one-hot action id, and canonical provider-independent argument features.
Predicting a delta rather than the absolute next state
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
import hashlib
import json
import struct
import sys

import numpy as np

EMBEDDING_SIZE = 128
NUM_TOOLS = 41
ACTION_FEATURE_SIZE = 16
INPUT_SIZE = EMBEDDING_SIZE + NUM_TOOLS + ACTION_FEATURE_SIZE
OUTPUT_SIZE = EMBEDDING_SIZE
LATENT_START = 51
V2_MAGIC = b"FWM2"
V2_VERSION = 2
POLICY_ONLY_ACTIONS = frozenset({28})  # trigger_kernel_upgrade

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
        features = row.get("action_features", [0.0] * ACTION_FEATURE_SIZE)
        if len(features) != ACTION_FEATURE_SIZE:
            raise ValueError(
                f"row {i} has {len(features)} action features; expected {ACTION_FEATURE_SIZE}"
            )
        X[i, EMBEDDING_SIZE + NUM_TOOLS:] = np.asarray(features, dtype=np.float32)
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


def train_mlp(
    X,
    Y,
    hidden_size,
    epochs,
    lr,
    validation=None,
    patience=0,
    seed=0,
    sample_weights=None,
):
    rng = np.random.default_rng(seed)
    n_in, n_out = X.shape[1], Y.shape[1]
    w1 = rng.normal(0, 1.0 / np.sqrt(n_in), size=(n_in, hidden_size)).astype(np.float32)
    inactive_inputs = np.all(X == 0.0, axis=0)
    # A missing legacy feature (or an unseen tool one-hot) never receives a
    # gradient. Zero its row up front so runtime nonzero values cannot activate
    # random initialization; trained-tool coverage still handles whole actions.
    w1[inactive_inputs] = 0.0
    if inactive_inputs.any():
        print(f"  zeroed {int(inactive_inputs.sum())} inactive input columns")
    b1 = np.zeros(hidden_size, dtype=np.float32)
    w2 = rng.normal(0, 1.0 / np.sqrt(hidden_size), size=(hidden_size, n_out)).astype(np.float32)
    b2 = np.zeros(n_out, dtype=np.float32)

    n = X.shape[0]
    if sample_weights is None:
        sample_weights = np.ones(n, dtype=np.float32)
    sample_weights = np.asarray(sample_weights, dtype=np.float32)
    if sample_weights.shape != (n,) or np.any(sample_weights <= 0):
        raise ValueError("sample_weights must contain one positive value per training row")
    sample_weights = sample_weights / float(sample_weights.mean())
    report_every = max(1, epochs // 10)
    best_validation = float("inf")
    best_weights = None
    stale_checks = 0
    for epoch in range(epochs):
        h_pre = X @ w1 + b1
        h = np.maximum(h_pre, 0.0)
        pred = h @ w2 + b2

        err = pred - Y
        loss = float(np.sum(sample_weights[:, None] * err ** 2) / (sample_weights.sum() * n_out))

        d_pred = (2.0 / n) * sample_weights[:, None] * err
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

        if epoch % report_every == 0 or epoch == epochs - 1:
            message = f"  epoch {epoch:5d}  train MSE={loss:.6f}"
            if validation is not None:
                X_validation, Y_validation = validation
                validation_pred = predict_mlp(X_validation, w1, b1, w2, b2)
                validation_loss = float(np.mean((validation_pred - Y_validation) ** 2))
                message += f" validation MSE={validation_loss:.6f}"
                if validation_loss < best_validation - 1e-9:
                    best_validation = validation_loss
                    best_weights = tuple(value.copy() for value in (w1, b1, w2, b2))
                    stale_checks = 0
                else:
                    stale_checks += 1
            print(message)
            if patience > 0 and stale_checks >= patience:
                print(
                    f"  early stopping after {epoch + 1} epochs; "
                    f"restoring best validation checkpoint ({best_validation:.6f})"
                )
                break

    if best_weights is not None:
        return best_weights
    return w1, b1, w2, b2


def predict_mlp(X, w1, b1, w2, b2):
    h = np.maximum(X @ w1 + b1, 0.0)
    return h @ w2 + b2


def split_indices(rows, validation_fraction=0.15, test_fraction=0.15, seed=42):
    """Return disjoint train/validation/test indices without episode leakage."""
    if validation_fraction <= 0 or test_fraction <= 0:
        raise ValueError("validation and test fractions must both be greater than zero")
    if validation_fraction + test_fraction >= 0.8:
        raise ValueError("validation + test fractions must leave at least 20% for training")
    rng = np.random.default_rng(seed)
    episode_ids = [row.get("episode_id") for row in rows]
    if all(episode_id is not None for episode_id in episode_ids):
        unique_episodes = np.array(sorted(set(episode_ids)), dtype=object)
        if len(unique_episodes) < 3:
            raise ValueError("episode-aware train/validation/test splitting needs at least 3 episodes")
        shuffled = rng.permutation(unique_episodes)
        n_test = max(1, int(len(unique_episodes) * test_fraction))
        n_validation = max(1, int(len(unique_episodes) * validation_fraction))
        if n_test + n_validation >= len(unique_episodes):
            n_validation = 1
            n_test = 1
        test_episodes = set(shuffled[:n_test].tolist())
        validation_episodes = set(shuffled[n_test:n_test + n_validation].tolist())
        train_idx = np.array([
            i for i, episode_id in enumerate(episode_ids)
            if episode_id not in test_episodes and episode_id not in validation_episodes
        ], dtype=np.int64)
        validation_idx = np.array([
            i for i, episode_id in enumerate(episode_ids) if episode_id in validation_episodes
        ], dtype=np.int64)
        test_idx = np.array([
            i for i, episode_id in enumerate(episode_ids) if episode_id in test_episodes
        ], dtype=np.int64)
        mode = "episode"
    else:
        if len(rows) < 3:
            raise ValueError("train/validation/test splitting needs at least 3 rows")
        shuffled = rng.permutation(len(rows))
        n_test = max(1, int(len(rows) * test_fraction))
        n_validation = max(1, int(len(rows) * validation_fraction))
        test_idx = shuffled[:n_test]
        validation_idx = shuffled[n_test:n_test + n_validation]
        train_idx = shuffled[n_test + n_validation:]
        mode = "row"
    if min(len(train_idx), len(validation_idx), len(test_idx)) == 0:
        raise ValueError("train/validation/test split produced an empty partition")
    return train_idx, validation_idx, test_idx, mode


def coverage_from_training_rows(rows, train_idx, minimum_samples):
    counts = np.zeros(NUM_TOOLS, dtype=np.int64)
    for index in train_idx:
        action_id = int(rows[int(index)]["action"])
        if 0 <= action_id < NUM_TOOLS:
            counts[action_id] += 1
    coverage = 0
    for action_id, count in enumerate(counts):
        if count >= minimum_samples:
            coverage |= 1 << action_id
    return coverage, counts


def transition_eligible(row):
    """Only real, non-quarantined actions may influence learned weights."""
    try:
        action_id = int(row.get("action", -1))
    except (TypeError, ValueError):
        return False
    return row.get("executed", True) and action_id not in POLICY_ONLY_ACTIONS


def dataset_fingerprint(rows):
    """Hash row identity while deliberately excluding representation latents.

    AE and JEPA replace only indices 51..127.  The ordered episode/action
    identity, argument features, outcomes, and unchanged OS-state prefix must
    still be byte-for-byte equivalent before their metrics are comparable.
    """
    digest = hashlib.sha256()
    for row in rows:
        identity = {
            "episode_id": row.get("episode_id"),
            "step": row.get("step"),
            "transition_in_step": row.get("transition_in_step"),
            "action": row.get("action"),
            "action_features": row.get("action_features"),
            "executed": row.get("executed", True),
            "success": row.get("success"),
            "ram_mb": row.get("ram_mb"),
            "observation_schema": row.get("observation_schema"),
            "before_prefix": row.get("before", [])[:LATENT_START],
            "after_prefix": row.get("after", [])[:LATENT_START],
        }
        encoded = json.dumps(
            identity, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        digest.update(encoded)
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def metric_summary(prediction, target, actions):
    learned_mse = float(np.mean((prediction - target) ** 2))
    zero_mse = float(np.mean(target ** 2))
    core_mse = float(np.mean((prediction[:, :7] - target[:, :7]) ** 2))
    core_zero_mse = float(np.mean(target[:, :7] ** 2))
    changed_dimensions = np.any(np.abs(target) > 1e-7, axis=0)
    dynamic_mse = (
        float(np.mean((prediction[:, changed_dimensions] - target[:, changed_dimensions]) ** 2))
        if changed_dimensions.any() else 0.0
    )
    per_action = {}
    action_mses = []
    action_zero_mses = []
    for action_id in sorted(set(actions.tolist())):
        mask = actions == action_id
        action_mse = float(np.mean((prediction[mask] - target[mask]) ** 2))
        action_zero_mse = float(np.mean(target[mask] ** 2))
        core_action_mse = float(np.mean((prediction[mask, :7] - target[mask, :7]) ** 2))
        core_action_zero_mse = float(np.mean(target[mask, :7] ** 2))
        name = TOOL_NAMES[action_id] if 0 <= action_id < NUM_TOOLS else str(action_id)
        per_action[name] = {
            "samples": int(mask.sum()),
            "mse": action_mse,
            "zero_mse": action_zero_mse,
            "normalized_mse": action_mse / max(action_zero_mse, 1e-12),
            "core_mse": core_action_mse,
            "core_zero_mse": core_action_zero_mse,
            "normalized_core_mse": core_action_mse / max(core_action_zero_mse, 1e-12),
        }
        action_mses.append(action_mse)
        action_zero_mses.append(action_zero_mse)
    return {
        "mse": learned_mse,
        "zero_mse": zero_mse,
        "normalized_mse": learned_mse / max(zero_mse, 1e-12),
        "core_mse": core_mse,
        "core_zero_mse": core_zero_mse,
        "normalized_core_mse": core_mse / max(core_zero_mse, 1e-12),
        "dynamic_mse": dynamic_mse,
        "macro_tool_mse": float(np.mean(action_mses)) if action_mses else 0.0,
        "normalized_macro_tool_mse": (
            float(np.mean(action_mses)) / max(float(np.mean(action_zero_mses)), 1e-12)
            if action_mses else 0.0
        ),
        "changed_dimensions": np.flatnonzero(changed_dimensions).tolist(),
        "per_action": per_action,
    }


def runtime_clamp(states):
    states[..., :LATENT_START] = np.clip(states[..., :LATENT_START], 0.0, 1.0)
    states[..., LATENT_START:] = np.clip(states[..., LATENT_START:], -1.0, 1.0)
    return states


def rollout_metrics(rows, test_idx, weights, max_horizon=5):
    """Open-loop evaluation using subsequent real actions from held-out episodes."""
    w1, b1, w2, b2 = weights
    by_episode = {}
    for index in test_idx:
        row = rows[int(index)]
        episode_id = str(row.get("episode_id", f"legacy-{int(index)}"))
        by_episode.setdefault(episode_id, []).append((int(index), row))
    for episode_rows in by_episode.values():
        episode_rows.sort(key=lambda item: (
            int(item[1].get("step", item[0])),
            int(item[1].get("transition_in_step", 0)),
            item[0],
        ))

    squared_errors = {horizon: [] for horizon in range(1, max_horizon + 1)}
    core_squared_errors = {horizon: [] for horizon in range(1, max_horizon + 1)}
    zero_squared_errors = {horizon: [] for horizon in range(1, max_horizon + 1)}
    core_zero_squared_errors = {horizon: [] for horizon in range(1, max_horizon + 1)}
    for episode_rows in by_episode.values():
        for start in range(len(episode_rows)):
            state = np.asarray(episode_rows[start][1]["before"], dtype=np.float32).copy()
            zero_state = state.copy()
            for offset in range(max_horizon):
                position = start + offset
                if position >= len(episode_rows):
                    break
                row = episode_rows[position][1]
                action_id = int(row["action"])
                model_input = np.zeros((1, INPUT_SIZE), dtype=np.float32)
                model_input[0, :EMBEDDING_SIZE] = state
                model_input[0, EMBEDDING_SIZE + action_id] = 1.0
                model_input[0, EMBEDDING_SIZE + NUM_TOOLS:] = np.asarray(
                    row.get("action_features", [0.0] * ACTION_FEATURE_SIZE), dtype=np.float32
                )
                state = runtime_clamp(state + predict_mlp(model_input, w1, b1, w2, b2)[0])
                target = np.asarray(row["after"], dtype=np.float32)
                horizon = offset + 1
                squared_errors[horizon].append(float(np.mean((state - target) ** 2)))
                core_squared_errors[horizon].append(float(np.mean((state[:7] - target[:7]) ** 2)))
                zero_squared_errors[horizon].append(float(np.mean((zero_state - target) ** 2)))
                core_zero_squared_errors[horizon].append(
                    float(np.mean((zero_state[:7] - target[:7]) ** 2))
                )
    return {
        str(horizon): {
            "samples": len(squared_errors[horizon]),
            "mse": float(np.mean(squared_errors[horizon])) if squared_errors[horizon] else None,
            "zero_mse": (
                float(np.mean(zero_squared_errors[horizon]))
                if zero_squared_errors[horizon] else None
            ),
            "normalized_mse": (
                float(np.mean(squared_errors[horizon]))
                / max(float(np.mean(zero_squared_errors[horizon])), 1e-12)
                if squared_errors[horizon] else None
            ),
            "core_mse": float(np.mean(core_squared_errors[horizon])) if core_squared_errors[horizon] else None,
            "core_zero_mse": (
                float(np.mean(core_zero_squared_errors[horizon]))
                if core_zero_squared_errors[horizon] else None
            ),
            "normalized_core_mse": (
                float(np.mean(core_squared_errors[horizon]))
                / max(float(np.mean(core_zero_squared_errors[horizon])), 1e-12)
                if core_squared_errors[horizon] else None
            ),
        }
        for horizon in range(1, max_horizon + 1)
    }


def write_weights(path, w1, b1, w2, b2, coverage):
    """
    Flat binary format cognitive/world_model/learned.rs parses directly:
      v2 header: magic "FWM2", version, input/hidden/output sizes,
      action-feature size, and a 64-bit trained-tool coverage mask
      then f32 LE arrays in order: w1 (input*hidden), b1 (hidden),
      w2 (hidden*output), b2 (output) - row-major, matching numpy's
      default C-contiguous layout so a straight byte copy is correct.
    """
    input_size, hidden_size = w1.shape
    output_size = w2.shape[1]
    with open(path, "wb") as f:
        f.write(V2_MAGIC)
        f.write(struct.pack(
            "<IIIIIQ",
            V2_VERSION,
            input_size,
            hidden_size,
            output_size,
            ACTION_FEATURE_SIZE,
            coverage,
        ))
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
    parser.add_argument("--validation", type=float, default=0.15)
    parser.add_argument("--test", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--split-seed",
        type=int,
        default=42,
        help="fixed data-partition seed, independent of weight-initialization --seed",
    )
    parser.add_argument(
        "--patience",
        type=int,
        default=0,
        help="stop after N validation checks without improvement and restore the best checkpoint (0 disables)",
    )
    parser.add_argument(
        "--min-train-per-tool",
        type=int,
        default=32,
        help="minimum executed training examples required before learned inference is enabled for a tool",
    )
    parser.add_argument(
        "--require-covered-tools",
        type=int,
        default=1,
        help="fail unless this many tools meet --min-train-per-tool",
    )
    parser.add_argument("--max-rollout-horizon", type=int, default=5)
    parser.add_argument("--metrics-out", default="target/world_model_metrics.json")
    parser.add_argument(
        "--no-balance-tools",
        action="store_true",
        help="disable inverse-frequency training weights across canonical tools",
    )
    args = parser.parse_args()

    corpus_rows = load_dataset(args.dataset)
    excluded_unexecuted = sum(not row.get("executed", True) for row in corpus_rows)
    excluded_policy = sum(
        row.get("executed", True) and int(row.get("action", -1)) in POLICY_ONLY_ACTIONS
        for row in corpus_rows
    )
    rows = [row for row in corpus_rows if transition_eligible(row)]
    if excluded_unexecuted:
        print(
            f"excluded {excluded_unexecuted} blocked/confirmation-only rows from transition fitting "
            "(retained in the source corpus for policy analysis)"
        )
    if excluded_policy:
        print(
            f"excluded {excluded_policy} executed historical policy-only rows from transition fitting"
        )
    if len(rows) < 20:
        print(f"error: only {len(rows)} examples in {args.dataset} - collect more with scripts/collect_world_model_dataset.mjs first", file=sys.stderr)
        sys.exit(1)
    print(f"loaded {len(rows)} executed examples from {args.dataset}")

    X, Y, baseline_delta = build_arrays(rows)

    try:
        train_idx, validation_idx, test_idx, split_mode = split_indices(
            rows, args.validation, args.test, args.split_seed
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
    X_train, Y_train = X[train_idx], Y[train_idx]
    X_validation, Y_validation = X[validation_idx], Y[validation_idx]
    X_test, Y_test = X[test_idx], Y[test_idx]
    baseline_test = baseline_delta[test_idx]
    print(
        f"{split_mode}-aware train/validation/test split: "
        f"{len(train_idx)}/{len(validation_idx)}/{len(test_idx)}"
    )

    baseline_mse = float(np.mean((baseline_test - Y_test) ** 2))
    zero_mse = float(np.mean(Y_test ** 2))
    print(f"baseline (Phase 1 rule table) untouched-test MSE: {baseline_mse:.6f}")
    print(f"trivial (always predict zero delta) untouched-test MSE: {zero_mse:.6f}")

    print(f"training MLP (input={X.shape[1]}, hidden={args.hidden}, output={Y.shape[1]}, epochs={args.epochs})...")
    training_actions = np.asarray([rows[int(i)]["action"] for i in train_idx], dtype=np.int32)
    sample_weights = None
    if not args.no_balance_tools:
        counts = np.bincount(training_actions, minlength=NUM_TOOLS)
        sample_weights = np.asarray([
            1.0 / counts[action] if 0 <= action < NUM_TOOLS and counts[action] > 0 else 1.0
            for action in training_actions
        ], dtype=np.float32)
        sample_weights /= sample_weights.mean()
        active_counts = counts[counts > 0]
        print(
            f"balanced {len(active_counts)} observed tools during fitting "
            f"(training counts {active_counts.min()}..{active_counts.max()})"
        )
    w1, b1, w2, b2 = train_mlp(
        X_train,
        Y_train,
        args.hidden,
        args.epochs,
        args.lr,
        validation=(X_validation, Y_validation),
        patience=max(0, args.patience),
        seed=args.seed,
        sample_weights=sample_weights,
    )

    pred_test = predict_mlp(X_test, w1, b1, w2, b2)
    pred_validation = predict_mlp(X_validation, w1, b1, w2, b2)
    test_actions = np.asarray([rows[int(i)]["action"] for i in test_idx], dtype=np.int32)
    validation_actions = np.asarray([rows[int(i)]["action"] for i in validation_idx], dtype=np.int32)
    evaluation = metric_summary(pred_test, Y_test, test_actions)
    validation_evaluation = metric_summary(pred_validation, Y_validation, validation_actions)
    learned_mse = evaluation["mse"]
    core_mse = evaluation["core_mse"]
    print(f"learned MLP untouched-test MSE: {learned_mse:.6f}")
    print(f"learned MLP relative-to-zero untouched-test error: {evaluation['normalized_mse']:.6f}")
    print(f"learned MLP core-feature untouched-test MSE: {core_mse:.6f}")
    print(f"learned MLP macro-per-tool untouched-test MSE: {evaluation['macro_tool_mse']:.6f}")
    print(
        "learned MLP normalized macro-per-tool untouched-test error: "
        f"{evaluation['normalized_macro_tool_mse']:.6f}"
    )
    for name, action_metrics in evaluation["per_action"].items():
        print(
            f"  {name:24s} n={action_metrics['samples']:4d} "
            f"mse={action_metrics['mse']:.6f} core={action_metrics['core_mse']:.6f}"
        )

    rollouts = rollout_metrics(
        rows,
        test_idx,
        (w1, b1, w2, b2),
        max(1, args.max_rollout_horizon),
    )
    validation_rollouts = rollout_metrics(
        rows,
        validation_idx,
        (w1, b1, w2, b2),
        max(1, args.max_rollout_horizon),
    )
    for horizon, result in rollouts.items():
        if result["mse"] is not None:
            print(
                f"  rollout H={horizon} n={result['samples']:4d} "
                f"mse={result['mse']:.6f} relative={result['normalized_mse']:.6f} "
                f"core={result['core_mse']:.6f}"
            )

    acceptance_reference = min(baseline_mse, zero_mse)
    if learned_mse < acceptance_reference:
        print(
            "PASS: learned model beats both the rule-table and zero-delta "
            f"untouched-test baselines ({learned_mse:.6f} < {acceptance_reference:.6f})"
        )
    else:
        print(
            "FAIL: learned model does not beat the strongest untouched-test baseline "
            f"({learned_mse:.6f} >= {acceptance_reference:.6f})"
        )
        sys.exit(1)

    coverage, training_counts = coverage_from_training_rows(
        rows, train_idx, max(1, args.min_train_per_tool)
    )
    covered_count = int(coverage.bit_count())
    if covered_count < args.require_covered_tools:
        print(
            f"FAIL: only {covered_count} tools have at least {args.min_train_per_tool} "
            f"training rows; required {args.require_covered_tools}",
            file=sys.stderr,
        )
        sys.exit(1)
    write_weights(args.out, w1, b1, w2, b2, coverage)
    weight_bytes = w1.nbytes + b1.nbytes + w2.nbytes + b2.nbytes + 32
    print(f"wrote weights to {args.out} ({weight_bytes} bytes, coverage=0x{coverage:x})")

    metrics = {
        "schema_version": 4,
        "corpus_rows": len(corpus_rows),
        "excluded_unexecuted_rows": excluded_unexecuted,
        "excluded_policy_rows": excluded_policy,
        "rows": len(rows),
        "dataset_fingerprint": dataset_fingerprint(rows),
        "train_rows": len(train_idx),
        "validation_rows": len(validation_idx),
        "test_rows": len(test_idx),
        "split_mode": split_mode,
        "seed": args.seed,
        "split_seed": args.split_seed,
        "input_size": INPUT_SIZE,
        "hidden_size": args.hidden,
        "tool_balanced_training": not args.no_balance_tools,
        "min_train_per_tool": args.min_train_per_tool,
        "coverage_mask": f"0x{coverage:x}",
        "covered_tools": [TOOL_NAMES[i] for i in range(NUM_TOOLS) if coverage & (1 << i)],
        "training_samples_per_tool": {
            TOOL_NAMES[i]: int(training_counts[i]) for i in range(NUM_TOOLS)
        },
        "baseline_mse": baseline_mse,
        "zero_mse": zero_mse,
        "learned_mse": learned_mse,
        "normalized_mse": evaluation["normalized_mse"],
        "core_feature_mse": core_mse,
        "core_zero_mse": evaluation["core_zero_mse"],
        "normalized_core_mse": evaluation["normalized_core_mse"],
        "dynamic_feature_mse": evaluation["dynamic_mse"],
        "macro_tool_mse": evaluation["macro_tool_mse"],
        "normalized_macro_tool_mse": evaluation["normalized_macro_tool_mse"],
        "changed_dimensions": evaluation["changed_dimensions"],
        "per_action": evaluation["per_action"],
        "rollout": rollouts,
        "validation": validation_evaluation,
        "validation_rollout": validation_rollouts,
    }
    with open(args.metrics_out, "w") as f:
        json.dump(metrics, f, indent=2)
        f.write("\n")
    print(f"wrote metrics to {args.metrics_out}")


if __name__ == "__main__":
    main()
