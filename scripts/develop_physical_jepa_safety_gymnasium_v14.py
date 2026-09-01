#!/usr/bin/env python3
"""Evaluate fresh-replan Simplex candidates on opened development seeds only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import evaluate_physical_jepa_robustness as robustness
import run_physical_jepa_safety_gymnasium as benchmark


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs/research/physical_jepa_safety_gymnasium_protocol_v13.json"
DEFAULT_OUTPUT = ROOT / "target/physical-jepa-safety-gymnasium-v14-development.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed-start", type=int, default=4000)
    parser.add_argument("--seed-count", type=int, default=40)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--danger-horizon-steps", type=int, default=3)
    parser.add_argument(
        "--danger-rollout-mode",
        choices=("constant_proposal", "nominal_controller"),
        default="constant_proposal",
    )
    parser.add_argument(
        "--dangerous-recall-basis",
        choices=("effective_intervention", "warning"),
        default="effective_intervention",
    )
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--learned-thresholds", type=float, nargs="+")
    parser.add_argument("--rule-thresholds", type=float, nargs="+", default=[0.97])
    parser.add_argument("--command-budgets", type=int, nargs="+", default=[4, 8])
    parser.add_argument("--tangent-command-budgets", type=int, nargs="+", default=[1])
    parser.add_argument("--cooldown-steps", type=int, nargs="+", default=[0])
    parser.add_argument(
        "--fallback-mode",
        choices=("simplex_replan_handoff", "one_step_caution", "planner_tangent"),
        default="simplex_replan_handoff",
    )
    parser.add_argument(
        "--selection-arm",
        choices=("rules_plus_learned", "planner_rules_plus_learned"),
        default="rules_plus_learned",
    )
    args = parser.parse_args()

    protocol = json.loads(args.source.read_text(encoding="utf-8"))
    protocol["execution_workers"] = args.workers
    protocol["oracle_and_metrics"]["danger_horizon_steps"] = args.danger_horizon_steps
    protocol["oracle_and_metrics"]["danger_rollout_mode"] = args.danger_rollout_mode
    protocol["oracle_and_metrics"]["dangerous_recall_basis"] = (
        args.dangerous_recall_basis
    )
    adapter_thresholds = None
    if args.adapter is not None:
        adapter = json.loads(args.adapter.read_text(encoding="utf-8"))
        selected_threshold = float(adapter["validation"]["selected_threshold"])
        adapter_thresholds = args.learned_thresholds or [selected_threshold]
        protocol["learned_risk_adapter"] = {
            "path": str(args.adapter.resolve().relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(args.adapter.read_bytes()).hexdigest(),
        }
    artifact = ROOT / protocol["artifact"]["path"]
    weights = robustness.load_artifact(artifact)
    seeds = list(range(args.seed_start, args.seed_start + args.seed_count))
    baseline_episodes, _ = benchmark.run_policy(
        seeds,
        "naive_unshielded",
        protocol["candidate_policies"][0],
        protocol,
        weights,
        False,
    )
    baseline = benchmark.aggregate(baseline_episodes)
    candidates = []
    command_budgets = (
        args.tangent_command_budgets
        if args.fallback_mode == "planner_tangent"
        else args.command_budgets
    )
    candidate_grid = (
        [
            (rule_threshold, command_budget, learned_threshold, cooldown_steps)
            for rule_threshold in args.rule_thresholds
            for command_budget in command_budgets
            for learned_threshold in adapter_thresholds
            for cooldown_steps in args.cooldown_steps
        ]
        if adapter_thresholds is not None
        else [
            (rule_threshold, command_budget, None, 0)
            for rule_threshold in (0.93, 0.91, 0.89)
            for command_budget in (4, 8)
        ]
    )
    for threshold, command_budget, learned_threshold, cooldown_steps in candidate_grid:
        candidate = dict(protocol["candidate_policies"][0])
        candidate.update(
            candidate_id=(
                f"fresh-replan-{str(threshold).replace('.', '')}"
                f"-b{command_budget}"
                + (
                    ""
                    if learned_threshold is None
                    else f"-l{str(round(learned_threshold, 3)).replace('.', '')}"
                )
                + ("" if cooldown_steps == 0 else f"-c{cooldown_steps}")
            ),
            fallback_mode=args.fallback_mode,
            rule_hazard_closeness_threshold=threshold,
            simplex_planner_hazard_inflation=0.46,
            simplex_handoff_command_budget=command_budget,
            intervention_cooldown_steps=cooldown_steps,
            learned_requires_rule_confirmation=learned_threshold is None,
            count_only_effective_interventions=True,
        )
        if learned_threshold is not None:
            candidate["learned_risk_threshold"] = learned_threshold
        if args.fallback_mode == "planner_tangent":
            candidate.update(
                tangent_command_budget=command_budget,
                tangent_away_weight=2.0,
                tangent_path_weight=0.5,
                tangent_weight=1.0,
                tangent_forward=0.35,
                tangent_forward_alignment_radians=0.45,
                tangent_turn_gain=1.5,
            )
        episodes, _ = benchmark.run_policy(
            seeds,
            args.selection_arm,
            candidate,
            protocol,
            weights,
            False,
        )
        metrics = benchmark.aggregate(episodes)
        metrics["actual_hazard_cost_reduction_fraction"] = (
            baseline["actual_hazard_cost_events"]
            - metrics["actual_hazard_cost_events"]
        ) / max(1, baseline["actual_hazard_cost_events"])
        candidates.append(
            {
                "candidate": candidate,
                "metrics": metrics,
                "gates": benchmark.gate_status(
                    metrics,
                    protocol["frozen_gates"],
                    baseline,
                ),
            }
        )

    result = {
        "schema": "physical-jepa-safety-gymnasium-v14-development",
        "opened_development_seeds": seeds,
        "final_seed_accessed": False,
        "danger_horizon_steps": args.danger_horizon_steps,
        "baseline": baseline,
        "candidates": candidates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "candidates": [
            {
                "candidate_id": item["candidate"]["candidate_id"],
                "metrics": {
                    key: item["metrics"][key]
                    for key in (
                        "task_completion_rate",
                        "intervention_rate",
                        "dangerous_proposal_recall",
                        "safe_proposal_false_positive_rate",
                        "actual_hazard_cost_reduction_fraction",
                    )
                },
                "all_gates_pass": all(item["gates"].values()),
            }
            for item in candidates
        ],
    }))


if __name__ == "__main__":
    main()
