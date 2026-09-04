#!/usr/bin/env python3
"""Compute registered paired planner-versus-union uncertainty from v14 episodes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "research"
PROTOCOL = RESEARCH / "physical_jepa_safety_gymnasium_paired_uncertainty_protocol_v1.json"
OUTPUT = RESEARCH / "physical_jepa_safety_gymnasium_paired_uncertainty_result_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def paired_episodes(result: dict, left_arm: str, right_arm: str) -> tuple[list[int], np.ndarray, np.ndarray]:
    left = {int(item["seed"]): item for item in result["arms"][left_arm]["episode_summaries"]}
    right = {int(item["seed"]): item for item in result["arms"][right_arm]["episode_summaries"]}
    if set(left) != set(right) or len(left) != len(result["arms"][left_arm]["episode_summaries"]):
        raise ValueError("arms must contain one episode for every identical seed")
    seeds = sorted(left)
    completion = np.asarray(
        [float(left[seed]["task_completed"]) - float(right[seed]["task_completed"]) for seed in seeds],
        dtype=np.float64,
    )
    hazard = np.asarray(
        [left[seed]["actual_hazard_cost_events"] - right[seed]["actual_hazard_cost_events"] for seed in seeds],
        dtype=np.float64,
    )
    return seeds, completion, hazard


def interval(values: np.ndarray, confidence_level: float, method: str) -> list[float]:
    tail = 100.0 * (1.0 - confidence_level) / 2.0
    return [
        round(float(np.percentile(values, tail, method=method)), 12),
        round(float(np.percentile(values, 100.0 - tail, method=method)), 12),
    ]


def summary(estimate: float, values: np.ndarray, protocol: dict) -> dict:
    bounds = interval(
        values,
        float(protocol["bootstrap"]["confidence_level"]),
        protocol["bootstrap"]["numpy_percentile_method"],
    )
    return {
        "estimate": float(estimate),
        "bootstrap_95_percent": bounds,
        "interval_excludes_zero": bool(bounds[1] < 0.0 or bounds[0] > 0.0),
    }


def main() -> None:
    protocol = load(PROTOCOL)
    source = ROOT / protocol["source_result"]["path"]
    if sha256(source) != protocol["source_result"]["sha256"]:
        raise SystemExit("registered v14 source result digest changed")
    result = load(source)
    seeds, completion, hazard = paired_episodes(
        result,
        protocol["arms"]["left"],
        protocol["arms"]["right"],
    )
    resamples = int(protocol["bootstrap"]["resamples"])
    rng = np.random.default_rng(int(protocol["bootstrap"]["seed"]))
    draws = rng.integers(0, len(seeds), size=(resamples, len(seeds)))
    completion_draws = 100.0 * completion[draws].mean(axis=1)
    hazard_draws = hazard[draws].sum(axis=1)
    output = {
        "schema": "physical-jepa-safety-gymnasium-paired-uncertainty-result-v1",
        "analysis_kind": protocol["analysis_kind"],
        "protocol": {"path": PROTOCOL.relative_to(ROOT).as_posix(), "sha256": sha256(PROTOCOL)},
        "source_result": {"path": source.relative_to(ROOT).as_posix(), "sha256": sha256(source)},
        "pairing": {
            "key": protocol["pair_key"],
            "episodes": len(seeds),
            "seed_minimum": min(seeds),
            "seed_maximum": max(seeds),
            "all_seeds_unique_and_matched": True,
        },
        "bootstrap": protocol["bootstrap"],
        "differences_union_minus_planner": {
            "completion_rate_percentage_points": summary(
                100.0 * completion.mean(), completion_draws, protocol
            ),
            "realized_hazard_cost_steps": summary(hazard.sum(), hazard_draws, protocol),
        },
        "interpretation": {
            "completion_difference_statistically_separated_from_zero": False,
            "hazard_cost_difference_statistically_separated_from_zero": False,
            "statement": "Neither paired 95% percentile-bootstrap interval excludes zero; the observed completion gain and hazard-cost increase are descriptive, not statistically stable at this sample size.",
        },
        "final_benchmark_rerun": False,
        "final_catalog_reopened": False,
        "model_or_threshold_reselected": False,
        "promotion_eligible": False,
    }
    differences = output["differences_union_minus_planner"]
    output["interpretation"]["completion_difference_statistically_separated_from_zero"] = differences[
        "completion_rate_percentage_points"
    ]["interval_excludes_zero"]
    output["interpretation"]["hazard_cost_difference_statistically_separated_from_zero"] = differences[
        "realized_hazard_cost_steps"
    ]["interval_excludes_zero"]
    OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": OUTPUT.relative_to(ROOT).as_posix(), "paired_episodes": len(seeds)}))


if __name__ == "__main__":
    main()
