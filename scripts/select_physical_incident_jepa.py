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
import physical_stress_scenarios as stress  # noqa: E402
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
    {
        "incident_train_episodes_per_source": 150,
        "latent": 64,
        "hidden": 128,
        "epochs": 4_000,
        "training_seed": 42,
    },
    {
        "incident_train_episodes_per_source": 250,
        "latent": 64,
        "hidden": 128,
        "epochs": 5_000,
        "training_seed": 42,
    },
    {
        "incident_train_episodes_per_source": 350,
        "latent": 64,
        "hidden": 128,
        "epochs": 6_000,
        "training_seed": 42,
    },
    {
        "incident_train_episodes_per_source": 250,
        "latent": 64,
        "hidden": 128,
        "epochs": 5_000,
        "training_seed": 17,
    },
    {
        "incident_train_episodes_per_source": 350,
        "latent": 64,
        "hidden": 128,
        "epochs": 6_000,
        "training_seed": 17,
    },
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved).replace("\\", "/")


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


def validation_decision(
    candidate,
    current_original,
    current_incident,
    current_stress=None,
    stress_geometric_limit=0.95,
) -> dict:
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
    stress_ratios = None
    if current_stress is not None:
        stress_ratios = {
            horizon: candidate["stress_validation"]["rollout"][horizon]
            / current_stress["rollout"][horizon]
            for horizon in ("h1", "h3", "h5")
        }
        stress_geometric_check = (
            "stress_validation_geometric_no_regression"
            if stress_geometric_limit == 1.0
            else "stress_validation_geometric_improvement_at_least_5_percent"
        )
        checks[stress_geometric_check] = (
            geometric(list(stress_ratios.values())) <= stress_geometric_limit
        )
        checks["stress_validation_no_horizon_regression"] = all(
            ratio <= 1.0 for ratio in stress_ratios.values()
        )
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
                *(stress_ratios.values() if stress_ratios else ()),
            ]
        ),
        "stress_ratios": stress_ratios,
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
    stress_ratios = None
    if "stress_test" in candidate:
        stress_ratios = {
            horizon: candidate["stress_test"]["rollout"][horizon]
            / current["stress_test"]["rollout"][horizon]
            for horizon in ("h1", "h3", "h5")
        }
        checks["stress_test_geometric_improvement_at_least_10_percent"] = (
            geometric(list(stress_ratios.values())) <= 0.90
        )
        checks["stress_test_no_horizon_regression"] = all(
            ratio <= 1.0 for ratio in stress_ratios.values()
        )
        checks["all_predictions_finite"] = (
            checks["all_predictions_finite"]
            and candidate["stress_test"]["diagnostics"]["all_predictions_finite"]
        )
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "original_test_ratios": base_ratios,
        "incident_test_ratios": incident_ratios,
        "stress_test_ratios": stress_ratios,
    }


def v4_promotion_decision(candidate, current, anti_collapse) -> dict:
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
    candidate_stress = candidate["stress_test"]["diagnostics"]["rules_plus_jepa"]
    current_stress = current["stress_test"]["diagnostics"]["rules_plus_jepa"]
    candidate_ood = candidate["ood_test"]["rules_plus_jepa"]
    current_ood = current["ood_test"]["rules_plus_jepa"]
    checks = {
        "original_test_no_regression_over_2_percent": all(
            ratio <= 1.02 for ratio in base_ratios.values()
        ),
        "incident_test_geometric_improvement_at_least_5_percent": geometric(
            list(incident_ratios.values())
        )
        <= 0.95,
        "incident_test_false_negatives_not_increased": candidate_incident["fn"]
        <= current_incident["fn"],
        "stress_test_false_negatives_not_increased": candidate_stress["fn"]
        <= current_stress["fn"],
        "ood_false_negatives_not_increased": candidate_ood["fn"] <= current_ood["fn"],
        "incident_test_false_positive_rate_within_2_points": candidate_incident[
            "false_positive_rate"
        ]
        <= current_incident["false_positive_rate"] + 0.02,
        "stress_test_false_positive_rate_within_2_points": candidate_stress[
            "false_positive_rate"
        ]
        <= current_stress["false_positive_rate"] + 0.02,
        "ood_false_positive_rate_within_2_points": candidate_ood["false_positive_rate"]
        <= current_ood["false_positive_rate"] + 0.02,
        "anti_collapse_variance_ratio": anti_collapse["prediction_variance_ratio"]
        >= 0.10,
        "all_predictions_finite": all(
            (
                candidate["original_test"]["diagnostics"]["all_predictions_finite"],
                candidate["incident_test"]["diagnostics"]["all_predictions_finite"],
                candidate["stress_test"]["diagnostics"]["all_predictions_finite"],
                candidate["ood_test"]["all_predictions_finite"],
            )
        ),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "original_test_ratios": base_ratios,
        "incident_test_ratios": incident_ratios,
        "stress_test_ratios": None,
    }


def mean_delta_predictor(rows):
    values = np.zeros((simulator.ACTION_COUNT, simulator.STATE_SIZE), dtype=np.float32)
    for action in range(simulator.ACTION_COUNT):
        selected = [row[5] - row[2] for row in rows if row[3] == action]
        values[action] = np.mean(selected, axis=0)

    def predictor(_state, action, _features):
        return values[action]

    return predictor


def prediction_variance_ratio(rows, weights) -> float:
    state, actions, actual_delta, _ = jepa.state_arrays(rows)
    predicted_delta = jepa.forward(state, actions, weights)[9]
    return float(np.var(predicted_delta) / max(float(np.var(actual_delta)), 1e-12))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-artifact", type=Path, default=CURRENT_ARTIFACT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--base-episodes", type=int, default=DATA_EPISODES)
    parser.add_argument("--steps", type=int, default=DATA_STEPS)
    parser.add_argument("--data-seed", type=int, default=DATA_SEED)
    parser.add_argument("--incident-seed", type=int)
    parser.add_argument(
        "--incident-catalog", type=Path, default=incidents.DEFAULT_CATALOG
    )
    parser.add_argument(
        "--incident-validation-per-source",
        type=int,
        default=INCIDENT_VALIDATION_EPISODES_PER_SOURCE,
    )
    parser.add_argument(
        "--incident-test-per-source",
        type=int,
        default=INCIDENT_TEST_EPISODES_PER_SOURCE,
    )
    parser.add_argument(
        "--candidate-config",
        type=Path,
        help="JSON file containing a fixed candidates array and optional protocol id",
    )
    parser.add_argument("--ood-count", type=int, default=512)
    parser.add_argument("--ood-seed", type=int, default=73_119)
    parser.add_argument("--ood-protocol", choices=("v1", "v2"), default="v1")
    parser.add_argument("--stress-train-episodes", type=int, default=0)
    parser.add_argument("--stress-validation-episodes", type=int, default=0)
    parser.add_argument("--stress-test-episodes", type=int, default=0)
    parser.add_argument("--stress-seed", type=int, default=91_337)
    args = parser.parse_args()

    if args.base_episodes < 20:
        parser.error("--base-episodes must be at least 20")
    if args.steps < 5:
        parser.error("--steps must be at least 5 for H=1..5 evaluation")
    if args.incident_validation_per_source < 1 or args.incident_test_per_source < 1:
        parser.error("incident validation/test counts must be positive")
    if args.ood_count < 1:
        parser.error("--ood-count must be positive")

    candidate_protocol = "physical-jepa-incident-simulator-v1"
    candidate_config_sha256 = None
    candidate_configs = list(CANDIDATES)
    if args.candidate_config:
        config_document = json.loads(args.candidate_config.read_text(encoding="utf-8"))
        candidate_protocol = config_document["protocol_id"]
        candidate_configs = config_document.get(
            "candidates", config_document.get("simulator_candidates_if_baseline_fails")
        )
        default_incident_train = config_document.get("incident_dataset", {}).get(
            "train_episodes_per_source"
        )
        if default_incident_train is not None:
            candidate_configs = [
                {
                    "incident_train_episodes_per_source": default_incident_train,
                    **candidate,
                }
                for candidate in candidate_configs
            ]
        candidate_config_sha256 = digest(args.candidate_config)
    is_v4 = candidate_protocol == "physical-jepa-real-evidence-v4"
    if not candidate_configs:
        parser.error("candidate configuration must contain at least one candidate")
    required_candidate_fields = {
        "incident_train_episodes_per_source",
        "latent",
        "hidden",
        "epochs",
        "training_seed",
    }
    for index, config in enumerate(candidate_configs):
        missing = required_candidate_fields.difference(config)
        if missing:
            parser.error(f"candidate {index} is missing: {', '.join(sorted(missing))}")
        if min(int(config[field]) for field in required_candidate_fields) < 1:
            parser.error(f"candidate {index} contains a non-positive value")

    incident_seed = args.data_seed if args.incident_seed is None else args.incident_seed
    current_artifact_sha256 = digest(args.current_artifact)
    base_rows = simulator.generate(args.base_episodes, args.steps, args.data_seed)
    _, _, base_train, base_validation, base_test = jepa.split_rows(
        base_rows, args.base_episodes, args.data_seed
    )
    incident_validation, incident_validation_metadata = incidents.generate_partition(
        "validation",
        args.incident_validation_per_source,
        args.steps,
        incident_seed,
        args.incident_catalog,
    )
    current_weights = robustness.load_artifact(args.current_artifact)
    current_original_validation = evaluation(base_validation, current_weights)
    current_incident_validation = evaluation(incident_validation, current_weights)
    stress_validation = stress_validation_metadata = None
    current_stress_validation = None
    if args.stress_validation_episodes:
        stress_validation, stress_validation_metadata = stress.generate_partition(
            "validation", args.stress_validation_episodes, args.steps, args.stress_seed
        )
        current_stress_validation = evaluation(stress_validation, current_weights)

    candidates = []
    candidate_weights = []
    for config in candidate_configs:
        incident_train, incident_train_metadata = incidents.generate_partition(
            "train",
            config["incident_train_episodes_per_source"],
            args.steps,
            incident_seed,
            args.incident_catalog,
        )
        train_rows = [*base_train, *incident_train]
        validation_rows = [*base_validation, *incident_validation]
        stress_train = stress_train_metadata = None
        stress_train_episodes = int(
            config.get("stress_train_episodes", args.stress_train_episodes)
        )
        if stress_train_episodes:
            stress_train, stress_train_metadata = stress.generate_partition(
                "train", stress_train_episodes, args.steps, args.stress_seed
            )
            train_rows.extend(stress_train)
        if stress_validation is not None:
            validation_rows.extend(stress_validation)
        weights, training_validation, epochs_completed = jepa.train(
            train_rows,
            validation_rows,
            latent=config["latent"],
            hidden=config["hidden"],
            epochs=config["epochs"],
            seed=config["training_seed"],
        )
        result = {
            **config,
            "stress_train_episodes": stress_train_episodes,
            "latent": config["latent"],
            "hidden": config["hidden"],
            "epochs_completed": epochs_completed,
            "training_transitions": len(train_rows),
            "incident_training": incidents.summarize(
                incident_train, incident_train_metadata
            ),
            "training_validation": training_validation,
            "original_validation": evaluation(base_validation, weights),
            "incident_validation": evaluation(incident_validation, weights),
            "anti_collapse": {
                **jepa.representation_metrics(validation_rows, weights),
                "prediction_variance_ratio": prediction_variance_ratio(
                    validation_rows, weights
                ),
            },
        }
        if stress_train is not None:
            result["stress_training"] = stress.summarize(
                stress_train, stress_train_metadata
            )
        if stress_validation is not None:
            result["stress_validation"] = evaluation(stress_validation, weights)
        result["selection"] = validation_decision(
            result,
            current_original_validation,
            current_incident_validation,
            current_stress_validation,
            stress_geometric_limit=1.0 if is_v4 else 0.95,
        )
        if is_v4:
            result["selection"]["checks"]["prediction_variance_ratio"] = (
                result["anti_collapse"]["prediction_variance_ratio"] >= 0.10
            )
            result["selection"]["checks"]["runtime_artifact_compatible"] = (
                result["latent"] <= 128 and result["hidden"] <= 256
            )
            result["selection"]["accepted"] = all(
                result["selection"]["checks"].values()
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
        "test",
        args.incident_test_per_source,
        args.steps,
        incident_seed,
        args.incident_catalog,
    )
    ood_test = (
        robustness.ood_v2_rows(args.ood_count, args.ood_seed)
        if args.ood_protocol == "v2"
        else robustness.ood_rows(args.ood_count, args.ood_seed)
    )
    stress_test = stress_test_metadata = None
    if args.stress_test_episodes:
        stress_test, stress_test_metadata = stress.generate_partition(
            "test", args.stress_test_episodes, args.steps, args.stress_seed
        )
    current_test = {
        "original_test": evaluation(base_test, current_weights),
        "incident_test": evaluation(incident_test, current_weights),
        "ood_test": robustness.diagnostics(
            ood_test, current_weights, fail_closed_invalid=args.ood_protocol == "v2"
        ),
    }
    candidate_test = {
        "original_test": evaluation(base_test, selected_weights),
        "incident_test": evaluation(incident_test, selected_weights),
        "ood_test": robustness.diagnostics(
            ood_test, selected_weights, fail_closed_invalid=args.ood_protocol == "v2"
        ),
    }
    if stress_test is not None:
        current_test["stress_test"] = evaluation(stress_test, current_weights)
        candidate_test["stress_test"] = evaluation(stress_test, selected_weights)
    promotion = (
        v4_promotion_decision(candidate_test, current_test, selected["anti_collapse"])
        if is_v4
        else promotion_decision(candidate_test, current_test)
    )

    selected_incident_train, selected_train_metadata = incidents.generate_partition(
        "train",
        selected["incident_train_episodes_per_source"],
        args.steps,
        incident_seed,
        args.incident_catalog,
    )
    selected_train_rows = [*base_train, *selected_incident_train]
    if selected["stress_train_episodes"]:
        selected_stress_train, _ = stress.generate_partition(
            "train", selected["stress_train_episodes"], args.steps, args.stress_seed
        )
        selected_train_rows.extend(selected_stress_train)
    mean_predictor = mean_delta_predictor(selected_train_rows)
    mean_h3 = simulator.rollout_error(base_test, mean_predictor, 3)
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    jepa.write_artifact(
        args.artifact,
        selected_weights,
        len(selected_train_rows),
        candidate_test["original_test"]["rollout"]["h3"],
        mean_h3,
        selected["latent"],
        selected["hidden"],
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
        "protocol_id": candidate_protocol,
        "candidate_config": repository_path(args.candidate_config)
        if args.candidate_config
        else None,
        "candidate_config_sha256": candidate_config_sha256,
        "selection_protocol": "validation_only_then_single_untouched_test_open",
        "test_metrics_used_for_selection": False,
        "current_artifact": repository_path(args.current_artifact),
        "current_artifact_sha256": current_artifact_sha256,
        "candidate_artifact": repository_path(args.artifact),
        "candidate_artifact_sha256": digest(args.artifact),
        "candidate_artifact_bytes": args.artifact.stat().st_size,
        "catalog": repository_path(args.incident_catalog),
        "catalog_sha256": incidents.catalog_sha256(args.incident_catalog),
        "dataset": repository_path(args.dataset),
        "dataset_sha256": digest(args.dataset),
        "base_dataset": {
            "episodes": args.base_episodes,
            "steps": args.steps,
            "seed": args.data_seed,
            "train_transitions": len(base_train),
            "validation_transitions": len(base_validation),
            "test_transitions": len(base_test),
        },
        "incident_validation": incidents.summarize(
            incident_validation, incident_validation_metadata
        ),
        "incident_seed": incident_seed,
        "incident_test": incidents.summarize(incident_test, incident_test_metadata),
        "registered_ood": {
            "protocol": args.ood_protocol,
            "rows": args.ood_count,
            "seed": args.ood_seed,
        },
        "stress_validation": stress.summarize(
            stress_validation, stress_validation_metadata
        )
        if stress_validation is not None
        else None,
        "stress_test": stress.summarize(stress_test, stress_test_metadata)
        if stress_test is not None
        else None,
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
                "stress_train_episodes",
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
