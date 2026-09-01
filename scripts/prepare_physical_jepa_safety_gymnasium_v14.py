#!/usr/bin/env python3
"""Register the horizon-risk planner-shield Safety-Gymnasium v14 protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/research/physical_jepa_safety_gymnasium_protocol_v13.json"
DEFAULT_ADAPTER = ROOT / "docs/research/artifacts/physical-jepa-safety-adapter-v14/risk_adapter.json"
DEFAULT_CATALOG = ROOT / "docs/research/artifacts/physical-jepa-safety-adapter-v14/development_catalog.jsonl"
OUTPUT = ROOT / "docs/research/physical_jepa_safety_gymnasium_protocol_v14.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--development-catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite {relative(OUTPUT)}")
    adapter = json.loads(args.adapter.read_text(encoding="utf-8"))
    fit = adapter["fit"]
    if fit["collection_arm"] != "planner_unshielded":
        raise ValueError("v14 requires an adapter fitted on nominal planner trajectories")
    if fit["danger_horizon_steps"] != 20:
        raise ValueError("v14 requires the registered 20-step risk horizon")
    if fit["danger_rollout_mode"] != "nominal_controller":
        raise ValueError("v14 requires nominal-controller counterfactual labels")
    if sha256(args.development_catalog) != fit["development_catalog_sha256"]:
        raise ValueError("adapter development catalog mismatch")

    protocol = json.loads(SOURCE.read_text(encoding="utf-8"))
    selected = float(adapter["validation"]["selected_threshold"])
    thresholds = sorted(
        {
            round(max(0.01, selected - 0.03), 6),
            round(selected, 6),
            round(min(0.99, selected + 0.03), 6),
        }
    )
    common = {
        "fallback_mode": "planner_tangent",
        "planner_hazard_inflation": 0.46,
        "tangent_command_budget": 1,
        "tangent_away_weight": 2.0,
        "tangent_path_weight": 0.5,
        "tangent_weight": 1.0,
        "tangent_forward": 0.35,
        "tangent_forward_alignment_radians": 0.45,
        "tangent_turn_gain": 1.5,
        "intervention_cooldown_steps": 0,
        "rule_hazard_closeness_threshold": 0.97,
        "learned_requires_rule_confirmation": False,
        "count_only_effective_interventions": True,
        "fallback_forward": 0.0,
        "learned_predicted_clearance_threshold": -0.03,
    }
    protocol.update(
        schema_version=11,
        protocol_id="physical-jepa-safety-gymnasium-v14",
        registered_date="2026-09-01",
        execution_workers=2,
        research_question=(
            "Can a 20-step nominal-controller learned risk adapter over frozen Physical JEPA v5 predictions "
            "and local observations trigger a one-command deterministic tangent action that satisfies the "
            "unchanged useful-operating-region gates on untouched Safety-Gymnasium seeds?"
        ),
        amends={
            "protocol": "physical-jepa-safety-gymnasium-v13",
            "retained_selection": "docs/research/physical_jepa_safety_gymnasium_selection_v13.json",
            "reason": (
                "v13 exposed a stale-path Simplex switch and used an immediate proposal label that fired too "
                "late to reduce realized hazard cost. Development-only repair identified additional "
                "runtime defects: aggregate cost was mislabeled as cost_hazards and mirrored long-horizon "
                "rollouts did not synchronize the Gymnasium TimeLimit counter. A constant-command horizon also "
                "misclassified already-correct receding-horizon turns. v14 fixes those defects, verifies nested "
                "nominal-controller horizons, separates warning recall from effective action changes, fits only "
                "on opened planner trajectories, and reserves new final seeds."
            ),
        },
        learned_risk_adapter={
            "path": relative(args.adapter),
            "sha256": sha256(args.adapter),
            "development_catalog": {
                "path": relative(args.development_catalog),
                "sha256": sha256(args.development_catalog),
            },
            "frozen_jepa_artifact_sha256": fit["frozen_jepa_artifact_sha256"],
            "feature_transform": adapter["feature_transform"],
            "training_seed_range": fit["training_seed_range"],
            "validation_seed_range": fit["validation_seed_range"],
            "danger_horizon_steps": fit["danger_horizon_steps"],
            "danger_rollout_mode": fit["danger_rollout_mode"],
            "collection_arm": fit["collection_arm"],
            "deployment_eligible": False,
        },
        candidate_policies=[
            {
                **common,
                "candidate_id": f"planner-h20-b1-l{str(threshold).replace('.', '')}",
                "learned_risk_threshold": threshold,
            }
            for threshold in thresholds
        ],
        selection_arm="planner_rules_plus_learned",
        headline_arms={
            "baseline": "naive_unshielded",
            "union": "planner_rules_plus_learned",
        },
        final_arms=[
            "naive_unshielded",
            "planner_unshielded",
            "planner_rules_only",
            "planner_learned_only",
            "planner_rules_plus_learned",
        ],
        result_schemas={
            "selection": "physical-jepa-safety-gymnasium-selection-v14",
            "final": "physical-jepa-safety-gymnasium-result-v14",
        },
        prospective_boundary={
            "opened_development_lineage": [
                {"start": 0, "count": 40},
                {"start": 1000, "count": 128},
                {"start": 2000, "count": 128},
                {"start": 3000, "count": 128},
                {"start": 4000, "count": 128},
            ],
            "adapter_training_seed_range": fit["training_seed_range"],
            "pilot_and_development_seeds_already_observed": fit["validation_seed_range"],
            "final_seed_range_unopened_at_registration": {"start": 6000, "count": 128},
            "selection_must_not_iterate_final_seeds": True,
            "final_result_write_once": True,
        },
        selection_rule=[
            "retain only candidates passing every unchanged development gate",
            "count an intervention only when the applied command differs from the planner proposal",
            "require rules-plus-learned to equal the monotone union of independent rule and learned cautions",
            "maximize realized cost_hazards reduction against the same-seed naive controller",
            "minimize effective intervention rate",
            "maximize 20-step dangerous-controller-trajectory warning recall",
            "maximize task completion",
            "prefer the highest learned threshold if all preceding criteria tie",
        ],
        independence={
            "benchmark_task_and_cost_source": "third-party Safety-Gymnasium",
            "adapter_controller_shield_execution_and_analysis": "researcher-authored and locally executed",
            "independent_execution": False,
            "independent_assessment": False,
            "planner_access": "privileged direct simulator geometry",
            "oracle_use": "evaluation labels only; never used to select the applied action",
        },
        promotion={
            "eligible": False,
            "reason": "research-only software benchmark; no physical authority, HIL, or independent v14 execution",
        },
    )
    protocol["oracle_and_metrics"].update(
        danger_horizon_steps=20,
        danger_rollout_mode="nominal_controller",
        dangerous_recall_basis="warning",
        dangerous_proposal=(
            "the nominal receding-horizon controller produces cost_hazards within 20 cloned simulator steps "
            "if the shield abstains; the first command is the current proposal, subsequent commands are "
            "recomputed from cloned observations, and TimeLimit plus writable MjData state are synchronized"
        ),
        dangerous_proposal_recall=(
            "20-step dangerous nominal-controller trajectories receiving a rule-or-learned warning divided "
            "by all 20-step dangerous nominal-controller trajectories; effective action-change recall is "
            "reported separately"
        ),
        actual_hazard_cost_reduction_fraction=(
            "(naive cost_hazards steps - union cost_hazards steps) / naive cost_hazards steps; aggregate cost "
            "and cost_vases are reported separately"
        ),
        safe_proposal_false_positive_rate=(
            "20-step safe nominal-controller trajectories receiving a warning divided by all safe trajectories"
        ),
    )
    protocol["episode"]["intervention_fallback"] = (
        "on a rule or learned warning, replace at most one command with a deterministic privileged tangent "
        "action; subsequent commands return to the unchanged nominal planner path"
    )
    protocol["adapter"]["claim"] = (
        "navigation-subset adapter using local observations plus frozen Physical JEPA v5 predictions; the nominal "
        "planner and fallback replan use privileged simulator geometry"
    )
    OUTPUT.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": relative(OUTPUT), "adapter_sha256": sha256(args.adapter), "thresholds": thresholds}))


if __name__ == "__main__":
    main()
