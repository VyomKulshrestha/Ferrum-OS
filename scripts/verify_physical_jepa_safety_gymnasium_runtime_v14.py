#!/usr/bin/env python3
"""Verify the v14 mirrored-horizon and fail-closed adapter runtime changes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import evaluate_physical_jepa_robustness as robustness
import run_physical_jepa_safety_gymnasium as benchmark


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PROTOCOL = ROOT / "docs/research/physical_jepa_safety_gymnasium_protocol_v13.json"
RUNNER = ROOT / "scripts/run_physical_jepa_safety_gymnasium.py"
DEFAULT_OUTPUT = ROOT / "docs/research/physical_jepa_safety_gymnasium_runtime_verification_v14.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    protocol = json.loads(SOURCE_PROTOCOL.read_text(encoding="utf-8"))
    weights = robustness.load_artifact(ROOT / protocol["artifact"]["path"])
    candidate = protocol["candidate_policies"][0]
    horizons = (1, 3, 10, 20)
    danger_steps = {}
    cost_counts = {}
    protocol["oracle_and_metrics"]["danger_rollout_mode"] = "nominal_controller"
    for horizon in horizons:
        protocol["oracle_and_metrics"]["danger_horizon_steps"] = horizon
        episode, cases = benchmark.run_episode(
            4006,
            "naive_unshielded",
            candidate,
            protocol,
            weights,
            None,
            True,
        )
        danger_steps[str(horizon)] = [
            int(case["step"]) for case in cases if case["dangerous_proposal"]
        ]
        cost_counts[str(horizon)] = {
            "hazard": episode["actual_hazard_cost_events"],
            "total": episode["actual_total_cost_events"],
            "vase": episode["actual_vase_cost_events"],
        }

    nested = all(
        set(danger_steps[str(left)]) <= set(danger_steps[str(right)])
        for left, right in zip(horizons, horizons[1:])
    )
    controller_rollout_counts = {}
    for mode in ("constant_proposal", "nominal_controller"):
        protocol["oracle_and_metrics"]["danger_horizon_steps"] = 20
        protocol["oracle_and_metrics"]["danger_rollout_mode"] = mode
        _, cases = benchmark.run_episode(
            4108,
            "planner_unshielded",
            candidate,
            protocol,
            weights,
            None,
            True,
        )
        controller_rollout_counts[mode] = sum(
            item["dangerous_proposal"] for item in cases
        )
    synthetic = {
        "feature_transform": "identity",
        "feature_mean": [0.0] * 25,
        "feature_scale": [1.0] * 25,
        "weights": [0.0] * 25,
        "bias": float("nan"),
    }
    nonfinite_adapter_score = benchmark.risk_adapter_score(
        np.zeros(25, dtype=np.float64),
        synthetic,
    )
    nonfinite_input_score = benchmark.risk_adapter_score(
        np.full(25, float("nan"), dtype=np.float64),
        {
            **synthetic,
            "bias": 0.0,
        },
    )
    stopped = np.zeros(25, dtype=np.float64)
    residual_velocity = stopped.copy()
    residual_velocity[3] = 0.1
    checks = {
        "opened_development_seed_only": 4006 < 5000,
        "danger_sets_monotone_with_horizon": nested,
        "horizon_adds_earlier_warning": min(danger_steps["20"]) < min(danger_steps["1"]),
        "nominal_controller_oracle_avoids_repeated_command_artifact": (
            controller_rollout_counts["nominal_controller"]
            < controller_rollout_counts["constant_proposal"]
        ),
        "main_trajectory_cost_invariant_to_oracle_horizon": len(
            {json.dumps(item, sort_keys=True) for item in cost_counts.values()}
        )
        == 1,
        "registered_hazard_cost_is_cost_hazards_only": all(
            item["hazard"] == item["total"] and item["vase"] == 0
            for item in cost_counts.values()
        ),
        "nonfinite_adapter_fails_to_caution": nonfinite_adapter_score == 1.0,
        "nonfinite_input_fails_to_caution": nonfinite_input_score == 1.0,
        "rotation_counts_as_motion_for_learned_caution": benchmark.proposal_has_motion(
            stopped,
            np.asarray([0.0, 0.2], dtype=np.float64),
        ),
        "residual_velocity_counts_as_motion_for_learned_caution": benchmark.proposal_has_motion(
            residual_velocity,
            np.asarray([0.0, 0.0], dtype=np.float64),
        ),
        "stationary_zero_command_is_not_motion": not benchmark.proposal_has_motion(
            stopped,
            np.asarray([0.0, 0.0], dtype=np.float64),
        ),
    }
    output = {
        "schema": "physical-jepa-safety-gymnasium-runtime-verification-v14",
        "verification_passed": all(checks.values()),
        "checks": checks,
        "development_seed": 4006,
        "danger_steps": danger_steps,
        "cost_counts": cost_counts,
        "controller_rollout_danger_counts": controller_rollout_counts,
        "artifacts": {
            "source_protocol": {
                "path": SOURCE_PROTOCOL.relative_to(ROOT).as_posix(),
                "sha256": sha256(SOURCE_PROTOCOL),
            },
            "runner": {
                "path": RUNNER.relative_to(ROOT).as_posix(),
                "sha256": sha256(RUNNER),
            },
            "physical_jepa_v5": {
                "path": protocol["artifact"]["path"],
                "sha256": protocol["artifact"]["sha256"],
            },
        },
        "authority": {
            "physical_actuator_attempts": 0,
            "physical_actuator_deliveries": 0,
            "promotion_eligible": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"verification_passed": output["verification_passed"], "output": str(args.output)}))
    if not output["verification_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
