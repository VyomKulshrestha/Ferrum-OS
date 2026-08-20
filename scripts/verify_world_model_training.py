#!/usr/bin/env python3
"""Fast host-side checks for leakage, coverage, and runtime rollout bounds."""
import importlib.util
import tempfile
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("train_world_model.py")
SPEC = importlib.util.spec_from_file_location("train_world_model", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SELECTOR_SCRIPT = Path(__file__).with_name("select_world_model_candidate.py")
SELECTOR_SPEC = importlib.util.spec_from_file_location(
    "select_world_model_candidate", SELECTOR_SCRIPT
)
SELECTOR = importlib.util.module_from_spec(SELECTOR_SPEC)
SELECTOR_SPEC.loader.exec_module(SELECTOR)


rows = []
for episode in range(20):
    for step in range(3):
        rows.append({
            "episode_id": f"episode-{episode:02d}",
            "step": step,
            "action": episode % MODULE.NUM_TOOLS,
            "action_features": [step / 10.0] + [0.0] * 15,
            "before": [0.0] * MODULE.EMBEDDING_SIZE,
            "after": [0.0] * MODULE.EMBEDDING_SIZE,
        })

train, validation, test, mode = MODULE.split_indices(rows, 0.2, 0.2, seed=7)
partitions = [set(train.tolist()), set(validation.tolist()), set(test.tolist())]
assert mode == "episode"
assert not partitions[0].intersection(partitions[1])
assert not partitions[0].intersection(partitions[2])
assert not partitions[1].intersection(partitions[2])
for episode in {row["episode_id"] for row in rows}:
    memberships = {
        part for part, indices in enumerate(partitions)
        if any(rows[index]["episode_id"] == episode for index in indices)
    }
    assert len(memberships) == 1, f"episode leaked across partitions: {episode}"

coverage, counts = MODULE.coverage_from_training_rows(rows, train, minimum_samples=3)
for action_id, count in enumerate(counts):
    assert bool(coverage & (1 << action_id)) == (count >= 3)
assert MODULE.transition_eligible({"action": 0, "executed": True})
assert not MODULE.transition_eligible({"action": 0, "executed": False})
assert not MODULE.transition_eligible({"action": 28, "executed": True})

states = np.zeros((2, MODULE.EMBEDDING_SIZE), dtype=np.float32)
states[:, :MODULE.LATENT_START] = [-0.5]
states[:, MODULE.LATENT_START:] = [-2.0]
states[1, :MODULE.LATENT_START] = 1.5
states[1, MODULE.LATENT_START:] = 2.0
clamped = MODULE.runtime_clamp(states)
assert np.all(clamped[:, :MODULE.LATENT_START] >= 0.0)
assert np.all(clamped[:, :MODULE.LATENT_START] <= 1.0)
assert np.all(clamped[:, MODULE.LATENT_START:] >= -1.0)
assert np.all(clamped[:, MODULE.LATENT_START:] <= 1.0)
assert clamped[0, MODULE.LATENT_START] == -1.0

rng = np.random.default_rng(11)
conditioning_w1 = rng.normal(size=(MODULE.INPUT_SIZE, 7)).astype(np.float32)
conditioning_b1 = rng.normal(size=7).astype(np.float32)
conditioning_w2 = rng.normal(size=(7, MODULE.OUTPUT_SIZE)).astype(np.float32)
conditioning_b2 = rng.normal(size=MODULE.OUTPUT_SIZE).astype(np.float32)

# Warm starts must round-trip the exact FWM2 format used by the Rust loader.
with tempfile.TemporaryDirectory() as temporary_directory:
    warm_start_path = Path(temporary_directory) / "warm-start.bin"
    MODULE.write_weights(
        warm_start_path,
        conditioning_w1,
        conditioning_b1,
        conditioning_w2,
        conditioning_b2,
        coverage=0x123,
    )
    loaded_weights, loaded_coverage = MODULE.read_weights(warm_start_path)
assert loaded_coverage == 0x123
for expected, loaded in zip(
    (conditioning_w1, conditioning_b1, conditioning_w2, conditioning_b2),
    loaded_weights,
):
    assert np.array_equal(expected, loaded)

# An all-ones feature objective must preserve the historical training path.
compatibility_x = rng.normal(size=(5, MODULE.INPUT_SIZE)).astype(np.float32)
compatibility_y = rng.normal(size=(5, MODULE.OUTPUT_SIZE)).astype(np.float32)
default_fit = MODULE.train_mlp(
    compatibility_x, compatibility_y, hidden_size=3, epochs=1, lr=0.001, seed=19
)
explicit_fit = MODULE.train_mlp(
    compatibility_x,
    compatibility_y,
    hidden_size=3,
    epochs=1,
    lr=0.001,
    seed=19,
    output_weights=np.ones(MODULE.OUTPUT_SIZE, dtype=np.float32),
)
for default_value, explicit_value in zip(default_fit, explicit_fit):
    assert np.array_equal(default_value, explicit_value)

# A candidate whose latent space is scaled down 10x has 100x smaller raw MSE,
# but exactly the same error relative to its own zero-delta baseline.  The
# promotion gate must see a tie, never a fake accuracy gain.
baseline_report = {
    "schema_version": 4,
    "normalized_mse": 0.1,
    "normalized_core_mse": 0.2,
    "normalized_macro_tool_mse": 0.3,
    "rollout": {
        "3": {"normalized_mse": 0.4},
        "5": {"normalized_mse": 0.5},
    },
}
scaled_report = {
    **baseline_report,
    "learned_mse": 0.001,
    "zero_mse": 0.01,
}
assert SELECTOR.metric_values(baseline_report) == SELECTOR.metric_values(scaled_report)
metric_actions = np.array([0], dtype=np.int32)
unit_target = np.ones((1, MODULE.EMBEDDING_SIZE), dtype=np.float32)
unit_prediction = unit_target * 0.5
unit_summary = MODULE.metric_summary(unit_prediction, unit_target, metric_actions)
scaled_summary = MODULE.metric_summary(unit_prediction * 0.1, unit_target * 0.1, metric_actions)
assert abs(unit_summary["normalized_mse"] - 0.25) < 1e-7
assert abs(unit_summary["normalized_mse"] - scaled_summary["normalized_mse"]) < 1e-7
assert abs(
    unit_summary["normalized_macro_tool_mse"]
    - scaled_summary["normalized_macro_tool_mse"]
) < 1e-7

# A legitimately no-op action can have an almost-zero per-tool baseline.
# Macro normalization must weight tools equally without averaging an
# unbounded error/baseline ratio for that one action.
mixed_actions = np.array([0, 1], dtype=np.int32)
mixed_target = np.vstack([
    np.zeros((1, MODULE.EMBEDDING_SIZE), dtype=np.float32),
    np.ones((1, MODULE.EMBEDDING_SIZE), dtype=np.float32),
])
mixed_prediction = np.vstack([
    np.full((1, MODULE.EMBEDDING_SIZE), 0.01, dtype=np.float32),
    np.full((1, MODULE.EMBEDDING_SIZE), 0.5, dtype=np.float32),
])
mixed_summary = MODULE.metric_summary(mixed_prediction, mixed_target, mixed_actions)
assert mixed_summary["per_action"][MODULE.TOOL_NAMES[0]]["normalized_mse"] > 1e6
assert mixed_summary["normalized_macro_tool_mse"] < 1.0

fingerprint_rows = [{
    "episode_id": "fingerprint-1",
    "step": 0,
    "action": 3,
    "action_features": [0.0] * MODULE.ACTION_FEATURE_SIZE,
    "before": [0.25] * MODULE.EMBEDDING_SIZE,
    "after": [0.5] * MODULE.EMBEDDING_SIZE,
}]
latent_variant = [{
    **fingerprint_rows[0],
    "before": fingerprint_rows[0]["before"][:MODULE.LATENT_START]
        + [-0.75] * (MODULE.EMBEDDING_SIZE - MODULE.LATENT_START),
    "after": fingerprint_rows[0]["after"][:MODULE.LATENT_START]
        + [0.75] * (MODULE.EMBEDDING_SIZE - MODULE.LATENT_START),
}]
different_action = [{**fingerprint_rows[0], "action": 4}]
assert MODULE.dataset_fingerprint(fingerprint_rows) == MODULE.dataset_fingerprint(latent_variant)
assert MODULE.dataset_fingerprint(fingerprint_rows) != MODULE.dataset_fingerprint(different_action)

candidate_identity = {
    "rows": 100, "test_rows": 15, "split_mode": "episode", "split_seed": 42,
    "dataset_fingerprint": MODULE.dataset_fingerprint(fingerprint_rows),
}
representation_identity = {**candidate_identity, "accepted": True}
assert SELECTOR.representation_mismatches(candidate_identity, representation_identity) == []
assert SELECTOR.representation_mismatches(
    candidate_identity, {**representation_identity, "dataset_fingerprint": "sha256:stale"}
) == ["dataset_fingerprint"]

print("PASS\tepisode-aware train/validation/test partitions are disjoint")
print("PASS\tlearned-tool coverage is derived only from sufficiently sampled training rows")
print("PASS\tpolicy-only kernel upgrades can never enter learned weights")
print("PASS\toffline rollout clamping matches signed runtime latent bounds")
print("PASS\tFWM2 warm-start weights round-trip exactly")
print("PASS\tdefault output weighting preserves the historical fitting path")
print("PASS\tJEPA promotion metrics are invariant to latent scale alone")
print("PASS\tmacro tool normalization remains finite for legitimate no-op actions")
print("PASS\tdataset fingerprints ignore representation latents but bind row identity")
print("PASS\tJEPA acceptance reports are bound to their transition dataset and split")
print("10/10 checks passed")
