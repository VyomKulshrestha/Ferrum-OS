#!/usr/bin/env python3
"""Bind a passing incident-selection report to the deployed physical model."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_incident_scenarios as incidents  # noqa: E402
import select_physical_incident_jepa as selector  # noqa: E402
import train_physical_jepa as jepa  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402

ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
REPORT = ROOT / "docs" / "research" / "physical_incident_jepa_improvement.json"
EVALUATION = ROOT / "docs" / "research" / "physical_world_model_evaluation.json"
FALSE_NEGATIVES = (
    ROOT / "docs" / "research" / "physical_jepa_false_negative_analysis.json"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL  {message}")
    print(f"PASS  {message}")


def learned_next(weights, state, action, features):
    return robustness.prediction(weights, state, action, features)


def safety_metrics(rows, weights) -> dict:
    rules = simulator.confusion(
        rows, lambda row: simulator.rules_block(row[2], row[3], row[4])
    )
    learned = simulator.confusion(
        rows,
        lambda row: simulator.predicted_block(
            row[2],
            row[3],
            row[4],
            learned_next(weights, row[2], row[3], row[4]),
        ),
    )
    combined = simulator.confusion(
        rows,
        lambda row: (
            simulator.rules_block(row[2], row[3], row[4])
            or simulator.predicted_block(
                row[2],
                row[3],
                row[4],
                learned_next(weights, row[2], row[3], row[4]),
            )
        ),
    )
    return {"rules_only": rules, "jepa_only": learned, "rules_plus_jepa": combined}


def rollout_metrics(rows, weights, prefix: str) -> dict:
    def predictor(state, action, features):
        return learned_next(weights, state, action, features) - state

    return {
        f"{prefix}_h{horizon}": simulator.rollout_error(rows, predictor, horizon)
        for horizon in range(1, 6)
    }


def hazards(state, action, features, nxt) -> list[str]:
    moving = action == simulator.MOVE and features[2] > 0.1
    checks = {
        "clearance": moving and nxt[simulator.CLEARANCE] < 0.16,
        "human_motion": moving
        and state[simulator.HUMANS] > 0
        and nxt[simulator.VELOCITY] > 0.18,
        "geofence": nxt[simulator.MARGIN] < 0,
        "low_battery": moving and state[simulator.BATTERY] < 0.1,
        "weak_link": moving and state[simulator.LINK] < 0.1,
        "emergency_stop": action != simulator.STOP and state[simulator.ESTOP] > 0.5,
        "unapproved_repair": action == simulator.REPAIR
        and state[simulator.APPROVAL] < 0.5,
    }
    return [name for name, active in checks.items() if active]


def rounded(values) -> list[float]:
    return [round(float(value), 7) for value in values]


def misses(rows, weights, metadata=None) -> list[dict]:
    result = []
    for episode, step, state, action, features, nxt, dangerous in rows:
        predicted_next = learned_next(weights, state, action, features)
        rule_blocked = simulator.rules_block(state, action, features)
        jepa_blocked = simulator.predicted_block(
            state, action, features, predicted_next
        )
        if dangerous and not (rule_blocked or jepa_blocked):
            item = {
                "episode": episode,
                "step": step,
                "action": simulator.ACTION_NAMES[action],
                "hazards": hazards(state, action, features, nxt),
                "rule_blocked": rule_blocked,
                "jepa_blocked": jepa_blocked,
                "action_features": rounded(features),
                "state": rounded(state),
                "true_next_state": rounded(nxt),
                "predicted_next_state": rounded(predicted_next),
            }
            if metadata is not None:
                item.update(metadata[episode])
                item["hazard_tags"] = list(item["hazard_tags"])
            result.append(item)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=ARTIFACT)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--evaluation", type=Path, default=EVALUATION)
    parser.add_argument("--false-negatives", type=Path, default=FALSE_NEGATIVES)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    previous = json.loads(args.evaluation.read_text(encoding="utf-8"))
    require(report["promotion"]["passed"], "incident promotion gates passed")
    require(
        not report["test_metrics_used_for_selection"],
        "candidate selection excluded test metrics",
    )
    require(
        digest(args.artifact) == report["candidate_artifact_sha256"],
        "deployed artifact matches the selected candidate",
    )
    require(
        incidents.catalog_sha256() == report["catalog_sha256"],
        "source catalog matches the selected run",
    )

    header = struct.unpack("<4sIIIIIIIIffI", args.artifact.read_bytes()[:48])
    weights = robustness.load_artifact(args.artifact)
    base_rows = simulator.generate(
        selector.DATA_EPISODES, selector.DATA_STEPS, selector.DATA_SEED
    )
    train_ids, validation_ids, base_train, base_validation, base_test = jepa.split_rows(
        base_rows, selector.DATA_EPISODES, selector.DATA_SEED
    )
    selected = report["selected_candidate"]
    incident_train, incident_train_metadata = incidents.generate_partition(
        "train",
        selected["incident_train_episodes_per_source"],
        selector.DATA_STEPS,
        selector.DATA_SEED,
    )
    incident_validation, incident_validation_metadata = incidents.generate_partition(
        "validation",
        selector.INCIDENT_VALIDATION_EPISODES_PER_SOURCE,
        selector.DATA_STEPS,
        selector.DATA_SEED,
    )
    incident_test, incident_test_metadata = incidents.generate_partition(
        "test",
        selector.INCIDENT_TEST_EPISODES_PER_SOURCE,
        selector.DATA_STEPS,
        selector.DATA_SEED,
    )
    mean_predictor = selector.mean_delta_predictor([*base_train, *incident_train])
    mean_rollout = {
        f"per_action_mean_h{horizon}": simulator.rollout_error(
            base_test, mean_predictor, horizon
        )
        for horizon in range(1, 6)
    }
    deployed_rollout = rollout_metrics(base_test, weights, "physical_jepa")
    validation_rollout = rollout_metrics(base_validation, weights, "physical_jepa")
    validation_mean_rollout = {
        f"per_action_mean_h{horizon}": simulator.rollout_error(
            base_validation, mean_predictor, horizon
        )
        for horizon in range(1, 6)
    }
    safety = safety_metrics(base_test, weights)

    pre_incident = {
        "artifact_sha256": report["current_artifact_sha256"],
        "episodes": previous["episodes"],
        "transitions": previous["transitions"],
        "normalized_rollout_error": previous["normalized_rollout_error"],
        "safety": previous["safety"],
    }
    total_incident_rows = [
        *incident_train,
        *incident_validation,
        *incident_test,
    ]
    total_incident_episodes = (
        len(incident_train_metadata)
        + len(incident_validation_metadata)
        + len(incident_test_metadata)
    )
    candidate_index = report["selected_candidate_index"]
    selected_full = report["candidates"][candidate_index]
    evaluation = {
        **previous,
        "schema_version": 2,
        "source": "deterministic_simulator_with_incident_derived_state_priors",
        "episodes": selector.DATA_EPISODES + total_incident_episodes,
        "transitions": len(base_rows) + len(total_incident_rows),
        "dangerous_transitions": sum(bool(row[6]) for row in base_rows)
        + sum(bool(row[6]) for row in total_incident_rows),
        "episode_split": {
            "train": len(train_ids) + len(incident_train_metadata),
            "validation": len(validation_ids) + len(incident_validation_metadata),
            "test": selector.DATA_EPISODES
            - len(train_ids)
            - len(validation_ids)
            + len(incident_test_metadata),
        },
        "transition_split": {
            "train": len(base_train) + len(incident_train),
            "validation": len(base_validation) + len(incident_validation),
            "test": len(base_test) + len(incident_test),
        },
        "episode_overlap": 0,
        "data_seed": selector.DATA_SEED,
        "training_seed": selected["training_seed"],
        "latent": selected["latent"],
        "hidden": selected["hidden"],
        "epochs_requested": selected["epochs"],
        "epochs_completed": selected["epochs_completed"],
        "validation": selected_full["training_validation"],
        "validation_mse": selected_full["training_validation"]["delta_mse"],
        "validation_rollout_error": {
            **validation_rollout,
            **validation_mean_rollout,
        },
        "test_split_opened": True,
        "artifact": str(args.artifact.relative_to(ROOT)).replace("\\", "/"),
        "artifact_format": "PJE1",
        "artifact_sha256": digest(args.artifact),
        "artifact_bytes": args.artifact.stat().st_size,
        "validated_for_gating": False,
        "gating_reason": "Incident-informed simulator trajectories are not validation for control of real physical machinery.",
        "normalized_rollout_error": {**deployed_rollout, **mean_rollout},
        "anti_collapse": selected_full["anti_collapse"],
        "safety": safety,
        "model_selection": {
            "criterion": "incident_validation_improvement_with_original_validation_regression_and_anti_collapse_gates",
            "test_metrics_not_used_for_selection": True,
            "regression_tolerance": 0.02,
            "selected": selected,
            "candidates": [
                {
                    key: candidate[key]
                    for key in (
                        "incident_train_episodes_per_source",
                        "latent",
                        "hidden",
                        "epochs",
                        "epochs_completed",
                        "training_seed",
                        "training_transitions",
                        "original_validation",
                        "incident_validation",
                        "anti_collapse",
                        "selection",
                    )
                }
                for candidate in report["candidates"]
            ],
        },
        "pre_incident_checkpoint": pre_incident,
        "incident_augmentation": {
            "catalog": report["catalog"],
            "catalog_sha256": report["catalog_sha256"],
            "selection_report": str(args.report.relative_to(ROOT)).replace("\\", "/"),
            "selection_report_sha256": digest(args.report),
            "generated_dataset": report["dataset"],
            "generated_dataset_sha256": report["dataset_sha256"],
            "incident_training": selected_full["incident_training"],
            "incident_validation": report["incident_validation"],
            "incident_test": report["incident_test"],
            "promotion": report["promotion"],
            "current_test": report["current_test"],
            "candidate_test": report["candidate_test"],
            "claim_boundary": report["claim_boundary"],
        },
    }
    require(
        header[7] == evaluation["transition_split"]["train"],
        "artifact header records augmented training samples",
    )
    args.evaluation.write_text(
        json.dumps(evaluation, indent=2) + "\n", encoding="utf-8"
    )

    base_misses = misses(base_test, weights)
    incident_misses = misses(incident_test, weights, incident_test_metadata)
    base_clusters = Counter("+".join(item["hazards"]) for item in base_misses)
    incident_clusters = Counter("+".join(item["hazards"]) for item in incident_misses)
    false_negative_report = {
        "schema_version": 2,
        "scope": "incident-augmented checkpoint on original and source-family-disjoint held-out simulator episodes",
        "artifact_sha256": digest(args.artifact),
        "test_transitions": len(base_test),
        "dangerous_test_transitions": sum(bool(row[6]) for row in base_test),
        "combined_false_negative_count": len(base_misses),
        "clusters": dict(sorted(base_clusters.items())),
        "misses": base_misses,
        "incident_challenge": {
            "test_transitions": len(incident_test),
            "dangerous_test_transitions": sum(bool(row[6]) for row in incident_test),
            "combined_false_negative_count": len(incident_misses),
            "clusters": dict(sorted(incident_clusters.items())),
            "source_family_counts": dict(
                sorted(
                    Counter(item["source_family"] for item in incident_misses).items()
                )
            ),
            "misses": incident_misses,
        },
        "interpretation": "Every miss remains a blocker for learned physical gating; deterministic rules remain authoritative and the JEPA remains shadow-only.",
    }
    args.false_negatives.write_text(
        json.dumps(false_negative_report, indent=2) + "\n", encoding="utf-8"
    )
    require(
        safety["rules_plus_jepa"]["fn"] == len(base_misses),
        "base false-negative decomposition is complete",
    )
    require(
        report["candidate_test"]["incident_test"]["diagnostics"]["rules_plus_jepa"][
            "fn"
        ]
        == len(incident_misses),
        "incident false-negative decomposition is complete",
    )
    print("\nPhysical incident-evidence promotion completed.")


if __name__ == "__main__":
    main()
