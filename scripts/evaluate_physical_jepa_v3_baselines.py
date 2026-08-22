#!/usr/bin/env python3
"""Evaluate v3 JEPA against matched autoencoder, mean-delta, and zero baselines."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_incident_scenarios as incidents  # noqa: E402
import physical_stress_scenarios as stress  # noqa: E402
import select_physical_incident_jepa as selector  # noqa: E402
import train_physical_jepa as jepa  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rollout(rows, predictor) -> dict:
    return {
        f"h{horizon}": simulator.rollout_error(rows, predictor, horizon)
        for horizon in range(1, 6)
    }


def learned_predictor(weights):
    return lambda state, action, features: robustness.prediction(
        weights, state, action, features
    ) - state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-report", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.selection_report.read_text(encoding="utf-8"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    selected = report["selected_candidate"]
    if not report["promotion"]["passed"]:
        raise SystemExit("selection report did not pass promotion gates")
    if digest(args.artifact) != report["candidate_artifact_sha256"]:
        raise SystemExit("candidate artifact does not match selection report")

    base = protocol["base_dataset"]
    base_rows = simulator.generate(base["episodes"], base["steps"], base["seed"])
    _, _, base_train, base_validation, base_test = jepa.split_rows(
        base_rows, base["episodes"], base["seed"]
    )
    incident_train, _ = incidents.generate_partition(
        "train", selected["incident_train_episodes_per_source"], base["steps"], base["seed"]
    )
    incident_validation, _ = incidents.generate_partition(
        "validation", protocol["incident_dataset"]["validation_episodes_per_source"], base["steps"], base["seed"]
    )
    incident_test, _ = incidents.generate_partition(
        "test", protocol["incident_dataset"]["test_episodes_per_source"], base["steps"], base["seed"]
    )
    stress_spec = protocol["stress_curriculum"]
    stress_train, _ = stress.generate_partition(
        "train", stress_spec["train_episodes"], base["steps"], stress_spec["seed"]
    )
    stress_validation, _ = stress.generate_partition(
        "validation", stress_spec["validation_episodes"], base["steps"], stress_spec["seed"]
    )
    stress_test, _ = stress.generate_partition(
        "test", stress_spec["test_episodes"], base["steps"], stress_spec["seed"]
    )
    train_rows = [*base_train, *incident_train, *stress_train]
    validation_rows = [*base_validation, *incident_validation, *stress_validation]

    autoencoder, autoencoder_validation, completed = jepa.train(
        train_rows,
        validation_rows,
        latent=selected["latent"],
        hidden=selected["hidden"],
        epochs=selected["epochs"],
        seed=selected["training_seed"],
        latent_loss_weight=np.float32(0.0),
        validation_latent_weight=0.0,
    )
    mean = selector.mean_delta_predictor(train_rows)
    zero = lambda _state, _action, _features: np.zeros(
        simulator.STATE_SIZE, dtype=np.float32
    )
    candidate = robustness.load_artifact(args.artifact)
    test_sets = {
        "original": base_test,
        "incident": incident_test,
        "stress": stress_test,
    }
    comparisons = {}
    for name, rows in test_sets.items():
        comparisons[name] = {
            "rows": len(rows),
            "jepa": {
                "rollout": rollout(rows, learned_predictor(candidate)),
                "safety": robustness.diagnostics(rows, candidate)["rules_plus_jepa"],
            },
            "matched_autoencoder": {
                "rollout": rollout(rows, learned_predictor(autoencoder)),
                "safety": robustness.diagnostics(rows, autoencoder)["rules_plus_jepa"],
            },
            "per_action_mean": {"rollout": rollout(rows, mean)},
            "zero_delta": {"rollout": rollout(rows, zero)},
        }

    ood_spec = protocol["registered_ood"]
    ood = robustness.ood_v2_rows(ood_spec["rows"], ood_spec["seed"])
    output = {
        "schema_version": 1,
        "protocol_id": "physical-jepa-v3-post-selection-baselines",
        "selection_report": str(args.selection_report).replace("\\", "/"),
        "selection_report_sha256": digest(args.selection_report),
        "artifact": str(args.artifact).replace("\\", "/"),
        "artifact_sha256": digest(args.artifact),
        "test_metrics_used_for_selection": False,
        "training_transitions": len(train_rows),
        "capacity": {"latent": selected["latent"], "hidden": selected["hidden"]},
        "matched_autoencoder": {
            "epochs_requested": selected["epochs"],
            "epochs_completed": completed,
            "validation": autoencoder_validation,
            "latent_target_prediction_loss": False,
        },
        "comparisons": comparisons,
        "registered_ood": {
            "jepa": robustness.diagnostics(ood, candidate, fail_closed_invalid=True),
            "matched_autoencoder": robustness.diagnostics(
                ood, autoencoder, fail_closed_invalid=True
            ),
        },
        "claim_boundary": "Baselines are trained after candidate selection and do not alter promotion. All results are deterministic simulator evidence.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "training_transitions": len(train_rows), "autoencoder_epochs_completed": completed}, indent=2))


if __name__ == "__main__":
    main()
