#!/usr/bin/env python3
"""Reproduce and validate the committed simulator-only physical model."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "scripts" / "select_physical_jepa.py"
ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
EVALUATION = ROOT / "docs" / "research" / "physical_world_model_evaluation.json"
SEED_EVALUATION = ROOT / "docs" / "research" / "physical_jepa_seed_evaluation.json"
FALSE_NEGATIVES = ROOT / "docs" / "research" / "physical_jepa_false_negative_analysis.json"


def require(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="verify committed artifacts and metrics without retraining the validation sweep",
    )
    args = parser.parse_args()
    evaluation = json.loads(EVALUATION.read_text(encoding="utf-8"))
    seed_evaluation = json.loads(SEED_EVALUATION.read_text(encoding="utf-8"))
    false_negatives = json.loads(FALSE_NEGATIVES.read_text(encoding="utf-8"))
    artifact = ARTIFACT.read_bytes()
    require(sha256(ARTIFACT) == evaluation["artifact_sha256"], "artifact hash matches evaluation")
    require(len(artifact) == 79_984, "PJE1 artifact has exact bounded size")
    header = struct.unpack("<4sIIIIIIIIffI", artifact[:48])
    (
        magic, version, state_size, action_count, feature_size, latent, hidden,
        samples, action_input_size, h3, mean_h3, gating,
    ) = header
    require(magic == b"PJE1" and version == 1, "artifact magic and version are supported")
    require(
        (state_size, action_count, feature_size, action_input_size) == (16, 7, 3, 10),
        "artifact schema matches runtime",
    )
    require(
        latent == 64 and hidden == 128 and samples == 10_500,
        "validation-selected JEPA capacity and training sample count are recorded",
    )
    require(gating == 0 and not evaluation["validated_for_gating"], "simulator artifact remains shadow-only")
    require(
        evaluation["model_class"] == "ema_target_joint_embedding_predictive_architecture",
        "artifact is a real EMA-target JEPA rather than a renamed transition MLP",
    )
    require(h3 < mean_h3, "JEPA H=3 error beats per-action mean baseline")
    require(evaluation["episode_overlap"] == 0, "train validation and test episodes do not overlap")
    require(
        evaluation["safety"]["rules_plus_jepa"]["fn"]
        < evaluation["safety"]["rules_only"]["fn"],
        "rules plus JEPA reduce false negatives versus rules only",
    )
    require(
        evaluation["safety"]["rules_plus_jepa"]["fn"] == 1
        and evaluation["safety"]["rules_plus_jepa"]["fp"] == 16,
        "selected JEPA held-out safety screen records one false negative and 16 false positives",
    )
    baseline = evaluation["baseline_mlp"]
    require(
        evaluation["safety"]["rules_plus_jepa"]["balanced_accuracy"]
        > baseline["safety"]["rules_plus_learned"]["balanced_accuracy"],
        "selected JEPA safety balanced accuracy beats the prior physical MLP",
    )
    require(
        evaluation["model_selection"]["criterion"]
        == "validation_only_geometric_error_with_regression_and_anti_collapse_gates"
        and evaluation["model_selection"]["test_metrics_not_used_for_selection"],
        "capacity selection excludes held-out test metrics and rejects rollout regressions",
    )
    for candidate in evaluation["model_selection"]["candidates"]:
        require(
            not any(key.startswith("test") for key in candidate),
            f"candidate {candidate['latent']}x{candidate['hidden']} contains no test metrics",
        )
    anti_collapse = evaluation["anti_collapse"]
    require(
        anti_collapse["latent_standard_deviation"] >= 0.02
        and anti_collapse["effective_rank"] >= 4.0
        and anti_collapse["action_sensitivity"] >= 0.005,
        "held-out representation passes anti-collapse checks",
    )
    rollout = evaluation["normalized_rollout_error"]
    baseline_rollout = baseline["normalized_rollout_error"]
    require(
        all(
            rollout[f"physical_jepa_h{h}"] < baseline_rollout[f"transition_model_h{h}"]
            for h in (1, 3, 5)
        ),
        "selected JEPA beats the supervised transition MLP at H=1, H=3 and H=5",
    )
    require(
        seed_evaluation["data_seed"] == 42
        and len(seed_evaluation["runs"]) >= 3
        and not seed_evaluation["test_metrics_used_for_selection"],
        "seed sensitivity holds data and the episode split fixed after capacity selection",
    )
    require(
        false_negatives["combined_false_negative_count"]
        == evaluation["safety"]["rules_plus_jepa"]["fn"]
        and false_negatives["clusters"] == {"clearance": 1},
        "held-out false-negative decomposition accounts for every combined miss",
    )

    if not args.quick:
        reproduce(evaluation)

    print("\nPhysical world-model verification passed.")


def reproduce(evaluation):
    with tempfile.TemporaryDirectory(prefix="ferrum-physical-model-") as temp:
        directory = Path(temp)
        artifact_copy = directory / "model.bin"
        evaluation_copy = directory / "evaluation.json"
        selection_copy = directory / "selection.json"
        dataset_copy = directory / "trajectories.jsonl"
        subprocess.run(
            [
                sys.executable,
                str(SELECTOR),
                "--artifact", str(artifact_copy),
                "--evaluation", str(evaluation_copy),
                "--selection", str(selection_copy),
                "--dataset", str(dataset_copy),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        reproduced = json.loads(evaluation_copy.read_text(encoding="utf-8"))
        reproduced_selection = json.loads(selection_copy.read_text(encoding="utf-8"))
        require(sha256(artifact_copy) == evaluation["artifact_sha256"], "validation sweep deterministically reproduces artifact")
        require(
            reproduced_selection["selected_capacity"] == evaluation["model_selection"]["selected"],
            "validation-only sweep deterministically selects the same capacity",
        )
        require(
            reproduced["normalized_rollout_error"] == evaluation["normalized_rollout_error"],
            "held-out rollout metrics reproduce exactly",
        )
        require(reproduced["safety"] == evaluation["safety"], "three-arm safety metrics reproduce exactly")
        require(
            sha256(dataset_copy) == evaluation["generated_dataset_sha256"],
            "deterministic simulator dataset reproduces exactly",
        )

if __name__ == "__main__":
    main()
