#!/usr/bin/env python3
"""Fast host-side checks for leakage, coverage, and runtime rollout bounds."""
import importlib.util
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("train_world_model.py")
SPEC = importlib.util.spec_from_file_location("train_world_model", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


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

print("PASS\tepisode-aware train/validation/test partitions are disjoint")
print("PASS\tlearned-tool coverage is derived only from sufficiently sampled training rows")
print("PASS\toffline rollout clamping matches signed runtime latent bounds")
print("3/3 checks passed")
