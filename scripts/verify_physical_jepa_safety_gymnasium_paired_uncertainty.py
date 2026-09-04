#!/usr/bin/env python3
"""Independently verify the registered v14 paired uncertainty analysis."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "research"
PROTOCOL = RESEARCH / "physical_jepa_safety_gymnasium_paired_uncertainty_protocol_v1.json"
RESULT = RESEARCH / "physical_jepa_safety_gymnasium_paired_uncertainty_result_v1.json"
OUTPUT = RESEARCH / "physical_jepa_safety_gymnasium_paired_uncertainty_verification_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def close(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)


def main() -> None:
    protocol = load(PROTOCOL)
    recorded = load(RESULT)
    source_path = ROOT / protocol["source_result"]["path"]
    source = load(source_path)
    left_name = protocol["arms"]["left"]
    right_name = protocol["arms"]["right"]
    left_rows = source["arms"][left_name]["episode_summaries"]
    right_rows = source["arms"][right_name]["episode_summaries"]
    left = {int(item["seed"]): item for item in left_rows}
    right = {int(item["seed"]): item for item in right_rows}
    seeds = sorted(set(left) & set(right))
    completion = np.asarray(
        [100.0 * (int(left[seed]["task_completed"]) - int(right[seed]["task_completed"])) for seed in seeds],
        dtype=np.float64,
    )
    hazard = np.asarray(
        [left[seed]["actual_hazard_cost_events"] - right[seed]["actual_hazard_cost_events"] for seed in seeds],
        dtype=np.float64,
    )
    rng = np.random.default_rng(int(protocol["bootstrap"]["seed"]))
    draws = rng.integers(0, len(seeds), size=(int(protocol["bootstrap"]["resamples"]), len(seeds)))
    confidence = float(protocol["bootstrap"]["confidence_level"])
    tail = 100.0 * (1.0 - confidence) / 2.0
    method = protocol["bootstrap"]["numpy_percentile_method"]
    recomputed = {
        "completion_rate_percentage_points": {
            "estimate": float(completion.mean()),
            "bootstrap_95_percent": [
                round(float(np.percentile(completion[draws].mean(axis=1), tail, method=method)), 12),
                round(float(np.percentile(completion[draws].mean(axis=1), 100.0 - tail, method=method)), 12),
            ],
        },
        "realized_hazard_cost_steps": {
            "estimate": float(hazard.sum()),
            "bootstrap_95_percent": [
                round(float(np.percentile(hazard[draws].sum(axis=1), tail, method=method)), 12),
                round(float(np.percentile(hazard[draws].sum(axis=1), 100.0 - tail, method=method)), 12),
            ],
        },
    }
    observed = recorded["differences_union_minus_planner"]
    checks = {
        "protocol_and_source_hashes_exact": recorded["protocol"]["sha256"] == sha256(PROTOCOL)
        and recorded["source_result"]["sha256"] == sha256(source_path)
        and sha256(source_path) == protocol["source_result"]["sha256"],
        "all_128_seeds_unique_and_matched": len(left_rows) == len(right_rows) == len(left) == len(right) == len(seeds) == 128
        and set(left) == set(right)
        and seeds == list(range(6000, 6128)),
        "completion_point_matches_123_minus_121": close(recomputed["completion_rate_percentage_points"]["estimate"], 100.0 * (123 - 121) / 128),
        "hazard_point_matches_84_minus_70": close(recomputed["realized_hazard_cost_steps"]["estimate"], 84 - 70),
        "completion_interval_recomputes": all(
            close(left_value, right_value)
            for left_value, right_value in zip(
                recomputed["completion_rate_percentage_points"]["bootstrap_95_percent"],
                observed["completion_rate_percentage_points"]["bootstrap_95_percent"],
            )
        ),
        "hazard_interval_recomputes": all(
            close(left_value, right_value)
            for left_value, right_value in zip(
                recomputed["realized_hazard_cost_steps"]["bootstrap_95_percent"],
                observed["realized_hazard_cost_steps"]["bootstrap_95_percent"],
            )
        ),
        "neither_interval_excludes_zero": observed["completion_rate_percentage_points"]["interval_excludes_zero"] is False
        and observed["realized_hazard_cost_steps"]["interval_excludes_zero"] is False,
        "no_rerun_reselection_or_promotion_claimed": recorded["final_benchmark_rerun"] is False
        and recorded["final_catalog_reopened"] is False
        and recorded["model_or_threshold_reselected"] is False
        and recorded["promotion_eligible"] is False,
    }
    output = {
        "schema": "physical-jepa-safety-gymnasium-paired-uncertainty-verification-v1",
        "overall_pass": all(checks.values()),
        "checks": checks,
        "recomputed": recomputed,
        "artifacts": {
            "protocol_sha256": sha256(PROTOCOL),
            "result_sha256": sha256(RESULT),
            "source_result_sha256": sha256(source_path),
        },
        "promotion_eligible": False,
    }
    OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"overall_pass": output["overall_pass"], "output": OUTPUT.relative_to(ROOT).as_posix()}))
    if not output["overall_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
