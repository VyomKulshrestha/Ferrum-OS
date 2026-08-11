#!/usr/bin/env python3
"""Measure physical JEPA sensitivity while holding simulator data fixed."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAINER = ROOT / "scripts" / "train_physical_jepa.py"


def summary(values):
    return {
        "mean": statistics.fmean(values),
        "sample_standard_deviation": statistics.stdev(values) if len(values) > 1 else 0.0,
        "minimum": min(values),
        "maximum": max(values),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", default="17,42,91")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs/research/physical_jepa_seed_evaluation.json",
    )
    args = parser.parse_args()
    seeds = [int(value) for value in args.seeds.split(",")]
    if len(set(seeds)) < 3:
        parser.error("at least three distinct seeds are required")

    runs = []
    with tempfile.TemporaryDirectory(prefix="ferrum-physical-seeds-") as temp:
        directory = Path(temp)
        for seed in seeds:
            evaluation = directory / f"seed-{seed}.json"
            subprocess.run(
                [
                    sys.executable,
                    str(TRAINER),
                    "--artifact", str(directory / f"seed-{seed}.bin"),
                    "--evaluation", str(evaluation),
                    "--latent", "64",
                    "--hidden", "128",
                    "--epochs", "5000",
                    "--seed", "42",
                    "--training-seed", str(seed),
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            report = json.loads(evaluation.read_text(encoding="utf-8"))
            runs.append({
                "training_seed": seed,
                "validation_h3": report["validation_rollout_error"]["physical_jepa_h3"],
                "test_h1": report["normalized_rollout_error"]["physical_jepa_h1"],
                "test_h3": report["normalized_rollout_error"]["physical_jepa_h3"],
                "test_h5": report["normalized_rollout_error"]["physical_jepa_h5"],
                "combined_false_negatives": report["safety"]["rules_plus_jepa"]["fn"],
                "combined_false_positives": report["safety"]["rules_plus_jepa"]["fp"],
                "latent_standard_deviation": report["anti_collapse"]["latent_standard_deviation"],
                "effective_rank": report["anti_collapse"]["effective_rank"],
                "action_sensitivity": report["anti_collapse"]["action_sensitivity"],
            })

    result = {
        "schema_version": 1,
        "scope": "deterministic_simulator_only",
        "data_seed": 42,
        "split_policy": "fixed episode-disjoint split; only training seed varies",
        "checkpoint_selection": "capacity frozen by the validation-only sweep before this audit",
        "test_metrics_used_for_selection": False,
        "runs": runs,
        "aggregate": {
            key: summary([run[key] for run in runs])
            for key in (
                "test_h1", "test_h3", "test_h5", "combined_false_negatives",
                "combined_false_positives", "latent_standard_deviation",
                "effective_rank", "action_sensitivity",
            )
        },
        "claim_boundary": "Seed stability on authored simulator trajectories is not evidence of real-hardware safety.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
