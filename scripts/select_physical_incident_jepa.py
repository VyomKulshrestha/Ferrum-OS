#!/usr/bin/env python3
"""Select an incident-augmented physical JEPA without test-set tuning.

Candidate choice uses only the original validation split and incident-family
validation split. Original, incident-family, and registered OOD tests are
opened only after a candidate configuration is frozen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_incident_scenarios as incidents  # noqa: E402
import train_physical_jepa as jepa  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402

CURRENT_ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
DEFAULT_ARTIFACT = ROOT / "target" / "physical_world_model" / "incident_candidate.bin"
DEFAULT_REPORT = (
    ROOT / "target" / "physical_world_model" / "incident_candidate_selection.json"
)
DEFAULT_DATASET = (
    ROOT / "target" / "physical_world_model" / "incident_trajectories.jsonl"
)
DATA_EPISODES = 2_500
DATA_STEPS = 6
DATA_SEED = 42
INCIDENT_VALIDATION_EPISODES_PER_SOURCE = 120
INCIDENT_TEST_EPISODES_PER_SOURCE = 120
CANDIDATES = (
    {"incident_train_episodes_per_source": 150, "epochs": 4_000, "training_seed": 42},
    {"incident_train_episodes_per_source": 250, "epochs": 5_000, "training_seed": 42},
    {"incident_train_episodes_per_source": 350, "epochs": 6_000, "training_seed": 42},
    {"incident_train_episodes_per_source": 250, "epochs": 5_000, "training_seed": 17},
    {"incident_train_episodes_per_source": 350, "epochs": 6_000, "training_seed": 17},
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rollout_metrics(rows, weights) -> dict:
    def predictor(state, action, features):
        if "reconstruction_w" in weights:
            return jepa.predict_delta(state, action, features, weights)
        return robustness.prediction(weights, state, action, features) - state

    return {
        f"h{horizon}": simulator.rollout_error(rows, predictor, horizon)
        for horizon in range(1, 6)
    }


def evaluation(rows, weights) -> dict:
    return {
        "rollout": rollout_metrics(rows, weights),
        "diagnostics": robustness.diagnostics(rows, weights),
    }


def geometric(values) -> float:
    return math.exp(sum(math.log(max(value, 1e-12)) for value in values) / len(values))


def validation_decision(candidate, current_original, current_incident) -> dict:
    original_ratios = {
        horizon: candidate["original_validation"]["rollout"][horizon]
        / current_original["rollout"][horizon]
        for horizon in ("h1", "h3", "h5")
    }
    incident_ratios = {
        horizon: candidate["incident_validation"]["rollout"][horizon]
        / current_incident["rollout"][horizon]
        for horizon in ("h1", "h3", "h5")
    }
    anti = candidate["anti_collapse"]
    checks = {
        "original_validation_no_regression_over_2_percent": all(
            ratio <= 1.02 for ratio in original_ratios.values()
        ),
        "incident_validation_geometric_improvement_at_least_5_percent": geometric(
            list(incident_ratios.values())
        )
        <= 0.95,
        "incident_validation_no_horizon_regression": all(
            ratio <= 1.0 for ratio in incident_ratios.values()
        ),
        "latent_standard_deviation": anti["latent_standard_deviation"] >= 0.02,
        "effective_rank": anti["effective_rank"] >= 4.0,
        "action_sensitivity": anti["action_sensitivity"] >= 0.005,
    }
    return {
        "checks": checks,
        "accepted": all(checks.values()),
        "original_ratios": original_ratios,
        "incident_ratios": incident_ratios,
        "selection_score": geometric(
            [
                *incident_ratios.values(),
                *incident_ratios.values(),
                *original_ratios.values(),
            ]
        ),
    }


def promotion_decision(candidate, current) -> dict:
    base_ratios = {
        horizon: candidate["original_test"]["rollout"][horizon]
        / current["original_test"]["rollout"][horizon]
        for horizon in ("h1", "h3", "h5")
    }
    incident_ratios = {
        horizon: candidate["incident_test"]["rollout"][horizon]
        / current["incident_test"]["rollout"][horizon]
        for horizon in ("h1", "h3", "h5")
    }
    candidate_incident = candidate["incident_test"]["diagnostics"]["rules_plus_jepa"]
    current_incident = current["incident_test"]["diagnostics"]["rules_plus_jepa"]
    candidate_ood = candidate["ood_test"]["rules_plus_jepa"]
    current_ood = current["ood_test"]["rules_plus_jepa"]
    checks = {
        "original_test_no_regression_over_2_percent": all(
            ratio <= 1.02 for ratio in base_ratios.values()
        ),
        "incident_test_geometric_improvement_at_least_10_percent": geometric(
            list(incident_ratios.values())
        )
        <= 0.90,
        "incident_test_no_horizon_regression": all(
            ratio <= 1.0 for ratio in incident_ratios.values()
        ),
        "incident_test_false_negatives_not_increased": candidate_incident["fn"]
        <= current_incident["fn"],
        "incident_test_false_positive_rate_within_2_points": candidate_incident[
            "false_positive_rate"
        ]
        <= current_incident["false_positive_rate"] + 0.02,
        "ood_one_step_error_improves_at_least_5_percent": candidate["ood_test"][
            "normalized_one_step_error"
        ]
        <= current["ood_test"]["normalized_one_step_error"] * 0.95,
        "ood_false_negatives_not_increased": candidate_ood["fn"] <= current_ood["fn"],
        "ood_false_positive_rate_within_2_points": candidate_ood["false_positive_rate"]
        <= current_ood["false_positive_rate"] + 0.02,
        "all_predictions_finite": candidate["original_test"]["diagnostics"][
            "all_predictions_finite"
        ]
        and candidate["incident_test"]["diagnostics"]["all_predictions_finite"]
        and candidate["ood_test"]["all_predictions_finite"],
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "original_test_ratios": base_ratios,
        "incident_test_ratios": incident_ratios,
    }


def mean_delta_predictor(rows):
    values = np.zeros((simulator.ACTION_COUNT, simulator.STATE_SIZE), dtype=np.float32)
    for action in range(simulator.ACTION_COUNT):
        selected = [row[5] - row[2] for row in rows if row[3] == action]
        values[action] = np.mean(selected, axis=0)

    def predictor(_state, action, _features):
        return values[action]

    return predictor


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-artifact", type=Path, default=CURRENT_ARTIFACT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()

    current_artifact_sha256 = digest(args.current_artifact)
    base_rows = simulator.generate(DATA_EPISODES, DATA_STEPS, DATA_SEED)
    _, _, base_train, base_validation, base_test = jepa.split_rows(
        base_rows, DATA_EPISODES, DATA_SEED
    )
    incident_validation, incident_validation_metadata = incidents.generate_partition(
        "validation",
        INCIDENT_VALIDATION_EPISODES_PER_SOURCE,
        DATA_STEPS,
        DATA_SEED,
    )
    current_weights = robustness.load_artifact(args.current_artifact)
    current_original_validation = evaluation(base_validation, current_weights)
    current_incident_validation = evaluation(incident_validation, current_weights)

    candidates = []
    candidate_weights = []
    for config in CANDIDATES:
        incident_train, incident_train_metadata = incidents.generate_partition(
            "train",
            config["incident_train_episodes_per_source"],
            DATA_STEPS,
            DATA_SEED,
        )
        train_rows = [*base_train, *incident_train]
        validation_rows = [*base_validation, *incident_validation]
        weights, training_validation, epochs_completed = jepa.train(
            train_rows,
            validation_rows,
            latent=64,
            hidden=128,
            epochs=config["epochs"],
            seed=config["training_seed"],
        )
        result = {
            **config,
            "latent": 64,
            "hidden": 128,
            "epochs_completed": epochs_completed,
            "training_transitions": len(train_rows),
            "incident_training": incidents.summarize(
                incident_train, incident_train_metadata
            ),
            "training_validation": training_validation,
            "original_validation": evaluation(base_validation, weights),
            "incident_validation": evaluation(incident_validation, weights),
            "anti_collapse": jepa.representation_metrics(validation_rows, weights),
        }
        result["selection"] = validation_decision(
            result, current_original_validation, current_incident_validation
        )
        candidates.append(result)
        candidate_weights.append(weights)

    accepted_indices = [
        index
        for index, candidate in enumerate(candidates)
        if candidate["selection"]["accepted"]
    ]
    if not accepted_indices:
        selected_index = min(
            range(len(candidates)),
            key=lambda index: candidates[index]["selection"]["selection_score"],
        )
    else:
        selected_index = min(
            accepted_indices,
            key=lambda index: candidates[index]["selection"]["selection_score"],
        )
    selected = candidates[selected_index]
    selected_weights = candidate_weights[selected_index]

    # Test partitions are generated only after the candidate index is frozen.
    incident_test, incident_test_metadata = incidents.generate_partition(
        "test", INCIDENT_TEST_EPISODES_PER_SOURCE, DATA_STEPS, DATA_SEED
    )
    ood_test = robustness.ood_rows()
    current_test = {
        "original_test": evaluation(base_test, current_weights),
        "incident_test": evaluation(incident_test, current_weights),
        "ood_test": robustness.diagnostics(ood_test, current_weights),
    }
    candidate_test = {
        "original_test": evaluation(base_test, selected_weights),
        "incident_test": evaluation(incident_test, selected_weights),
        "ood_test": robustness.diagnostics(ood_test, selected_weights),
    }
    promotion = promotion_decision(candidate_test, current_test)

    selected_incident_train, selected_train_metadata = incidents.generate_partition(
        "train",
        selected["incident_train_episodes_per_source"],
        DATA_STEPS,
        DATA_SEED,
    )
    selected_train_rows = [*base_train, *selected_incident_train]
    mean_predictor = mean_delta_predictor(selected_train_rows)
    mean_h3 = simulator.rollout_error(base_test, mean_predictor, 3)
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    jepa.write_artifact(
        args.artifact,
        selected_weights,
        len(selected_train_rows),
        candidate_test["original_test"]["rollout"]["h3"],
        mean_h3,
        64,
        128,
    )

    all_incident_rows = [
        *selected_incident_train,
        *incident_validation,
        *incident_test,
    ]
    all_incident_metadata = {
        **selected_train_metadata,
        **incident_validation_metadata,
        **incident_test_metadata,
    }
    incidents.write_jsonl(args.dataset, all_incident_rows, all_incident_metadata)
    report = {
        "schema_version": 1,
        "selection_protocol": "validation_only_then_single_untouched_test_open",
        "test_metrics_used_for_selection": False,
        "current_artifact": str(args.current_artifact).replace("\\", "/"),
        "current_artifact_sha256": current_artifact_sha256,
        "candidate_artifact": str(args.artifact).replace("\\", "/"),
        "candidate_artifact_sha256": digest(args.artifact),
        "candidate_artifact_bytes": args.artifact.stat().st_size,
        "catalog": str(incidents.DEFAULT_CATALOG.relative_to(ROOT)).replace("\\", "/"),
        "catalog_sha256": incidents.catalog_sha256(),
        "dataset": str(args.dataset).replace("\\", "/"),
        "dataset_sha256": digest(args.dataset),
        "base_dataset": {
            "episodes": DATA_EPISODES,
            "steps": DATA_STEPS,
            "seed": DATA_SEED,
            "train_transitions": len(base_train),
            "validation_transitions": len(base_validation),
            "test_transitions": len(base_test),
        },
        "incident_validation": incidents.summarize(
            incident_validation, incident_validation_metadata
        ),
        "incident_test": incidents.summarize(incident_test, incident_test_metadata),
        "current_validation": {
            "original": current_original_validation,
            "incident": current_incident_validation,
        },
        "candidates": candidates,
        "selected_candidate_index": selected_index,
        "selected_candidate": {
            key: selected[key]
            for key in (
                "incident_train_episodes_per_source",
                "latent",
                "hidden",
                "epochs",
                "epochs_completed",
                "training_seed",
                "training_transitions",
                "selection",
            )
        },
        "current_test": current_test,
        "candidate_test": candidate_test,
        "promotion": promotion,
        "validated_for_gating": False,
        "claim_boundary": [
            "Incident sources provide defensive state-distribution priors, not measured Ferrum trajectories.",
            "Every transition and danger label is generated by the deterministic Ferrum simulator.",
            "The test partitions were not used to select a candidate.",
            "The artifact remains shadow-only and cannot control physical equipment.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "report": str(args.report),
                "candidate_artifact": str(args.artifact),
                "selected_candidate_index": selected_index,
                "accepted_on_validation": selected["selection"]["accepted"],
                "promotion_passed": promotion["passed"],
                "promotion_checks": promotion["checks"],
            },
            indent=2,
        )
    )
    return 0 if selected["selection"]["accepted"] and promotion["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
