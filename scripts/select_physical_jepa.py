#!/usr/bin/env python3
"""Run a validation-only physical JEPA capacity sweep and deploy the winner."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAINER = ROOT / "scripts" / "train_physical_jepa.py"
BASELINE_TRAINER = ROOT / "scripts" / "train_physical_world_model.py"
DATASET = ROOT / "target" / "physical_world_model" / "trajectories.jsonl"
CANDIDATES = (
    {"latent": 24, "hidden": 64, "epochs": 2400},
    {"latent": 32, "hidden": 96, "epochs": 4000},
    {"latent": 48, "hidden": 128, "epochs": 4000},
    {"latent": 64, "hidden": 128, "epochs": 5000},
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved).replace("\\", "/")


def run(command):
    subprocess.run(
        [sys.executable, *map(str, command)],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def accepted_against_baseline(result, baseline):
    tolerance = 1.02
    checks = {
        "delta_mse": result["validation_mse"] <= baseline["validation_mse"] * tolerance,
        "rollout_h1": result["validation_rollout_error"]["physical_jepa_h1"]
        <= baseline["validation_rollout_error"]["transition_model_h1"] * tolerance,
        "rollout_h3": result["validation_rollout_error"]["physical_jepa_h3"]
        <= baseline["validation_rollout_error"]["transition_model_h3"] * tolerance,
        "rollout_h5": result["validation_rollout_error"]["physical_jepa_h5"]
        <= baseline["validation_rollout_error"]["transition_model_h5"] * tolerance,
        "latent_std": result["validation_anti_collapse"]["latent_standard_deviation"] >= 0.05,
        "effective_rank": result["validation_anti_collapse"]["effective_rank"] >= 2.0,
        "action_sensitivity": result["validation_anti_collapse"]["action_sensitivity"] >= 0.01,
    }
    ratios = [
        result["validation_mse"] / baseline["validation_mse"],
        result["validation_rollout_error"]["physical_jepa_h1"]
        / baseline["validation_rollout_error"]["transition_model_h1"],
        result["validation_rollout_error"]["physical_jepa_h3"]
        / baseline["validation_rollout_error"]["transition_model_h3"],
        result["validation_rollout_error"]["physical_jepa_h5"]
        / baseline["validation_rollout_error"]["transition_model_h5"],
    ]
    geometric_ratio = math.exp(sum(math.log(max(value, 1e-12)) for value in ratios) / len(ratios))
    return checks, geometric_ratio


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact",
        type=Path,
        default=ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin",
    )
    parser.add_argument(
        "--evaluation",
        type=Path,
        default=ROOT / "docs" / "research" / "physical_world_model_evaluation.json",
    )
    parser.add_argument(
        "--selection",
        type=Path,
        default=ROOT / "docs" / "research" / "physical_jepa_selection.json",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DATASET,
    )
    args = parser.parse_args()

    summaries = []
    with tempfile.TemporaryDirectory(prefix="ferrum-physical-jepa-") as temp:
        directory = Path(temp)
        baseline_selection_artifact = directory / "baseline-selection.bin"
        baseline_selection_evaluation = directory / "baseline-selection.json"
        run([
            BASELINE_TRAINER,
            "--selection-only",
            "--artifact", baseline_selection_artifact,
            "--evaluation", baseline_selection_evaluation,
            "--dataset", directory / "selection-trajectories.jsonl",
        ])
        baseline_selection = json.loads(
            baseline_selection_evaluation.read_text(encoding="utf-8")
        )
        if baseline_selection["test_split_opened"]:
            raise RuntimeError("baseline selection unexpectedly opened the test split")

        for index, candidate in enumerate(CANDIDATES):
            artifact = directory / f"candidate-{index}.bin"
            evaluation = directory / f"candidate-{index}.json"
            run([
                TRAINER,
                "--selection-only",
                "--latent", candidate["latent"],
                "--hidden", candidate["hidden"],
                "--epochs", candidate["epochs"],
                "--artifact", artifact,
                "--evaluation", evaluation,
            ])
            result = json.loads(evaluation.read_text(encoding="utf-8"))
            if result["test_split_opened"]:
                raise RuntimeError("candidate selection unexpectedly opened the test split")
            checks, geometric_ratio = accepted_against_baseline(result, baseline_selection)
            summaries.append({
                **candidate,
                "evaluation": result,
                "validation_mse": result["validation_mse"],
                "acceptance_checks": checks,
                "accepted": all(checks.values()),
                "geometric_error_ratio": geometric_ratio,
            })

        # Every decision above uses only the fixed validation split. The test
        # split is opened below only after the accepted capacity is frozen.
        accepted = [item for item in summaries if item["accepted"]]
        if not accepted:
            raise RuntimeError("no physical JEPA candidate passed validation regression and anti-collapse gates")
        selected = min(
            accepted,
            key=lambda item: (
                item["geometric_error_ratio"],
                item["latent"],
                item["hidden"],
            ),
        )

        final_candidate_evaluation = directory / "selected-final.json"
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        run([
            TRAINER,
            "--latent", selected["latent"],
            "--hidden", selected["hidden"],
            "--epochs", selected["epochs"],
            "--artifact", args.artifact,
            "--evaluation", final_candidate_evaluation,
        ])
        final = json.loads(final_candidate_evaluation.read_text(encoding="utf-8"))
        if not final["test_split_opened"]:
            raise RuntimeError("selected final evaluation did not open the held-out test split")

        baseline_artifact = directory / "baseline-final.bin"
        baseline_evaluation = directory / "baseline-final.json"
        baseline_dataset = directory / "trajectories.jsonl"
        run([
            BASELINE_TRAINER,
            "--artifact", baseline_artifact,
            "--evaluation", baseline_evaluation,
            "--dataset", baseline_dataset,
        ])
        baseline = json.loads(baseline_evaluation.read_text(encoding="utf-8"))

        final["artifact"] = repository_path(args.artifact)
        final["artifact_sha256"] = digest(args.artifact)
        final["deployed"] = True
        final["model_selection"] = {
            "criterion": "validation_only_geometric_error_with_regression_and_anti_collapse_gates",
            "test_metrics_not_used_for_selection": True,
            "regression_tolerance": 0.02,
            "selected": {
                "latent": selected["latent"],
                "hidden": selected["hidden"],
                "epochs_requested": selected["epochs"],
            },
            "candidates": [
                {
                    "latent": item["latent"],
                    "hidden": item["hidden"],
                    "epochs_requested": item["epochs"],
                    "epochs_completed": item["evaluation"]["epochs_completed"],
                    "validation_mse": item["validation_mse"],
                    "validation_rollout_error": item["evaluation"]["validation_rollout_error"],
                    "validation_anti_collapse": item["evaluation"]["validation_anti_collapse"],
                    "acceptance_checks": item["acceptance_checks"],
                    "accepted": item["accepted"],
                    "geometric_error_ratio": item["geometric_error_ratio"],
                }
                for item in summaries
            ],
        }
        final["baseline_mlp"] = {
            "model_class": baseline["model_class"],
            "artifact_format": baseline["artifact_format"],
            "artifact_sha256": baseline["artifact_sha256"],
            "validation_mse": baseline["validation_mse"],
            "validation_rollout_error": baseline["validation_rollout_error"],
            "normalized_rollout_error": baseline["normalized_rollout_error"],
            "safety": baseline["safety"],
        }
        args.dataset.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(baseline_dataset, args.dataset)
        final["generated_dataset"] = repository_path(args.dataset)
        final["generated_dataset_sha256"] = baseline["generated_dataset_sha256"]
        args.evaluation.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")

        selection = {
            "selection_criterion": final["model_selection"]["criterion"],
            "test_metrics_not_used_for_selection": True,
            "baseline_validation": {
                "validation_mse": baseline_selection["validation_mse"],
                "validation_rollout_error": baseline_selection["validation_rollout_error"],
            },
            "selected_capacity": final["model_selection"]["selected"],
            "selected_artifact_sha256": final["artifact_sha256"],
            "candidates": [
                {
                    "latent": item["latent"],
                    "hidden": item["hidden"],
                    "epochs_requested": item["epochs"],
                    "epochs_completed": item["evaluation"]["epochs_completed"],
                    "validation_mse": item["validation_mse"],
                    "validation_rollout_error": item["evaluation"]["validation_rollout_error"],
                    "validation_anti_collapse": item["evaluation"]["validation_anti_collapse"],
                    "acceptance_checks": item["acceptance_checks"],
                    "accepted": item["accepted"],
                    "geometric_error_ratio": item["geometric_error_ratio"],
                }
                for item in summaries
            ],
            "selected_held_out_test": {
                "normalized_rollout_error": final["normalized_rollout_error"],
                "anti_collapse": final["anti_collapse"],
                "safety": final["safety"],
            },
        }
        args.selection.parent.mkdir(parents=True, exist_ok=True)
        args.selection.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(selection, indent=2))


if __name__ == "__main__":
    main()
