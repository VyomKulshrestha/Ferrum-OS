#!/usr/bin/env python3
"""Verify deterministic, valid, split-disjoint physical stress trajectories."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_stress_scenarios as stress  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS\t{message}")


def main() -> None:
    partitions = {
        name: stress.generate_partition(name, 120, 8, 20_260_826)
        for name in ("train", "validation", "test")
    }
    ids = {name: set(metadata) for name, (_, metadata) in partitions.items()}
    require(
        not (
            ids["train"] & ids["validation"]
            or ids["train"] & ids["test"]
            or ids["validation"] & ids["test"]
        ),
        "stress episode identifiers are split-disjoint",
    )
    for name, (rows, metadata) in partitions.items():
        require(
            len(rows) == 960 and len(metadata) == 120,
            f"{name} has eight transitions per episode",
        )
        require(
            {item["case"] for item in metadata.values()} == set(stress.CASES),
            f"{name} covers all twelve stress families",
        )
        require(
            {row[3] for row in rows} == set(range(simulator.ACTION_COUNT)),
            f"{name} covers every physical action",
        )
        require(
            all(robustness.observation_consistent(row[2]) for row in rows),
            f"{name} contains only semantically valid observations",
        )
        require(
            all(np.isfinite(row[5]).all() for row in rows),
            f"{name} next states remain finite",
        )
    train_again = stress.generate_partition("train", 120, 8, 20_260_826)[0]
    require(
        all(
            np.array_equal(left[2], right[2]) and np.array_equal(left[5], right[5])
            for left, right in zip(partitions["train"][0], train_again, strict=True)
        ),
        "stress generation is deterministic",
    )
    print("\nPhysical stress-scenario verification passed: 17/17 checks.")


if __name__ == "__main__":
    main()
