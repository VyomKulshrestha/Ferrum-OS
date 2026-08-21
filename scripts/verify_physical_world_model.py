#!/usr/bin/env python3
"""Reproduce and validate the incident-augmented shadow-only physical JEPA."""

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
SELECTOR = ROOT / "scripts" / "select_physical_incident_jepa.py"
ANALYZER = ROOT / "scripts" / "analyze_physical_jepa_false_negatives.py"
ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
PRE_INCIDENT = (
    ROOT
    / "docs"
    / "research"
    / "artifacts"
    / "physical-jepa-incident-v1"
    / "pre-incident-physical-world-model.bin"
)
EVALUATION = ROOT / "docs" / "research" / "physical_world_model_evaluation.json"
IMPROVEMENT = ROOT / "docs" / "research" / "physical_incident_jepa_improvement.json"
ROBUSTNESS = ROOT / "docs" / "research" / "physical_jepa_robustness.json"
FALSE_NEGATIVES = (
    ROOT / "docs" / "research" / "physical_jepa_false_negative_analysis.json"
)
CATALOG = ROOT / "docs" / "research" / "physical_incident_sources.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="verify committed artifacts and metrics without retraining the sweep",
    )
    args = parser.parse_args()
    evaluation = json.loads(EVALUATION.read_text(encoding="utf-8"))
    improvement = json.loads(IMPROVEMENT.read_text(encoding="utf-8"))
    robustness = json.loads(ROBUSTNESS.read_text(encoding="utf-8"))
    false_negatives = json.loads(FALSE_NEGATIVES.read_text(encoding="utf-8"))

    artifact = ARTIFACT.read_bytes()
    require(
        sha256(ARTIFACT)
        == evaluation["artifact_sha256"]
        == improvement["candidate_artifact_sha256"]
        == robustness["artifact_sha256"],
        "artifact hash matches evaluation, selection, and robustness evidence",
    )
    require(
        sha256(PRE_INCIDENT)
        == improvement["current_artifact_sha256"]
        == evaluation["pre_incident_checkpoint"]["artifact_sha256"],
        "immutable pre-incident checkpoint anchors the comparison",
    )
    require(
        sha256(CATALOG) == improvement["catalog_sha256"],
        "incident source catalog matches training evidence",
    )
    require(len(artifact) == 79_984, "PJE1 artifact retains its bounded size")
    header = struct.unpack("<4sIIIIIIIIffI", artifact[:48])
    (
        magic,
        version,
        state_size,
        action_count,
        feature_size,
        latent,
        hidden,
        samples,
        action_input_size,
        h3,
        mean_h3,
        gating,
    ) = header
    require(
        magic == b"PJE1" and version == 1,
        "artifact magic and runtime version are supported",
    )
    require(
        (state_size, action_count, feature_size, action_input_size) == (16, 7, 3, 10),
        "artifact schema matches the runtime loader",
    )
    require(
        latent == 64
        and hidden == 128
        and samples == evaluation["transition_split"]["train"] == 18_900,
        "artifact records the selected capacity and augmented training count",
    )
    require(
        gating == 0
        and not evaluation["validated_for_gating"]
        and not improvement["validated_for_gating"],
        "incident-informed simulator artifact remains shadow-only",
    )
    require(h3 < mean_h3, "JEPA H=3 error remains below the per-action mean")
    require(
        evaluation["schema_version"] == 2
        and evaluation["source"]
        == "deterministic_simulator_with_incident_derived_state_priors",
        "evaluation identifies incident-derived priors without claiming telemetry",
    )
    require(
        evaluation["episodes"] == 4_740
        and evaluation["transitions"] == 28_440
        and evaluation["episode_overlap"] == 0,
        "augmented evidence count and disjoint episode split are recorded",
    )

    selection = evaluation["model_selection"]
    require(
        selection["test_metrics_not_used_for_selection"]
        and not improvement["test_metrics_used_for_selection"]
        and improvement["selection_protocol"]
        == "validation_only_then_single_untouched_test_open",
        "candidate selection excludes original, incident, and OOD tests",
    )
    require(
        all(
            not any("test" in key for key in candidate)
            for candidate in selection["candidates"]
        ),
        "candidate records contain validation evidence only",
    )
    selected = improvement["selected_candidate"]
    require(
        selected["incident_train_episodes_per_source"] == 350
        and selected["latent"] == 64
        and selected["hidden"] == 128
        and selected["training_seed"] == 42
        and selected["training_transitions"] == 18_900,
        "validation sweep selected the larger incident corpus deterministically",
    )
    require(
        selected["selection"]["accepted"]
        and improvement["promotion"]["passed"]
        and all(improvement["promotion"]["checks"].values()),
        "all registered validation and promotion gates pass",
    )

    previous_test = improvement["current_test"]
    candidate_test = improvement["candidate_test"]
    require(
        all(
            candidate_test["original_test"]["rollout"][horizon]
            < previous_test["original_test"]["rollout"][horizon]
            for horizon in ("h1", "h3", "h5")
        ),
        "original held-out H=1, H=3, and H=5 all improve",
    )
    require(
        all(
            candidate_test["incident_test"]["rollout"][horizon]
            <= previous_test["incident_test"]["rollout"][horizon] * 0.90
            for horizon in ("h1", "h3", "h5")
        ),
        "source-family-disjoint incident H=1, H=3, and H=5 improve by at least 10 percent",
    )
    require(
        candidate_test["incident_test"]["diagnostics"]["rules_plus_jepa"]["fn"]
        == 1
        < previous_test["incident_test"]["diagnostics"]["rules_plus_jepa"]["fn"]
        == 11,
        "incident challenge false negatives fall from 11 to 1",
    )
    require(
        candidate_test["ood_test"]["normalized_one_step_error"]
        < previous_test["ood_test"]["normalized_one_step_error"]
        and candidate_test["ood_test"]["rules_plus_jepa"]["fn"]
        == 41
        < previous_test["ood_test"]["rules_plus_jepa"]["fn"]
        == 42
        and candidate_test["ood_test"]["rules_plus_jepa"]["fp"]
        == previous_test["ood_test"]["rules_plus_jepa"]["fp"]
        == 4,
        "registered OOD error and false negatives improve without added false positives",
    )
    require(
        robustness["out_of_distribution"]["normalized_one_step_error"]
        == candidate_test["ood_test"]["normalized_one_step_error"]
        and robustness["out_of_distribution"]["rules_plus_jepa"]
        == candidate_test["ood_test"]["rules_plus_jepa"],
        "independent robustness report matches the promotion test",
    )

    safety = evaluation["safety"]
    require(
        safety["rules_plus_jepa"]["fn"] == 0
        and safety["rules_plus_jepa"]["fp"] == 16
        and safety["rules_plus_jepa"]["balanced_accuracy"]
        > safety["rules_only"]["balanced_accuracy"],
        "original held-out combined screen records zero false negatives",
    )
    anti = evaluation["anti_collapse"]
    require(
        anti["latent_standard_deviation"] >= 0.02
        and anti["effective_rank"] >= 4.0
        and anti["action_sensitivity"] >= 0.005,
        "selected representation passes anti-collapse gates",
    )
    require(
        false_negatives["artifact_sha256"] == sha256(ARTIFACT)
        and false_negatives["combined_false_negative_count"] == 0
        and false_negatives["incident_challenge"]["combined_false_negative_count"] == 1
        and false_negatives["incident_challenge"]["clusters"] == {"clearance": 1},
        "false-negative decomposition covers original and incident tests",
    )
    require(
        all(robustness["gates"].values()) and robustness["passed"],
        "registered physical-JEPA robustness gates pass",
    )

    if not args.quick:
        reproduce(improvement, false_negatives)
    print("\nIncident-augmented physical world-model verification passed.")


def reproduce(improvement: dict, false_negatives: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="ferrum-physical-incident-") as temp:
        directory = Path(temp)
        artifact_copy = directory / "model.bin"
        report_copy = directory / "selection.json"
        dataset_copy = directory / "incident.jsonl"
        subprocess.run(
            [
                sys.executable,
                str(SELECTOR),
                "--current-artifact",
                str(PRE_INCIDENT),
                "--artifact",
                str(artifact_copy),
                "--report",
                str(report_copy),
                "--dataset",
                str(dataset_copy),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        reproduced = json.loads(report_copy.read_text(encoding="utf-8"))
        require(
            sha256(artifact_copy) == improvement["candidate_artifact_sha256"],
            "validation sweep deterministically reproduces the deployed artifact",
        )
        require(
            reproduced["selected_candidate_index"]
            == improvement["selected_candidate_index"]
            and reproduced["selected_candidate"] == improvement["selected_candidate"],
            "validation-only sweep deterministically selects the same candidate",
        )
        require(
            reproduced["candidate_test"] == improvement["candidate_test"]
            and reproduced["promotion"] == improvement["promotion"],
            "untouched test metrics and promotion gates reproduce exactly",
        )
        require(
            sha256(dataset_copy) == improvement["dataset_sha256"],
            "incident-derived trajectory dataset reproduces byte-for-byte",
        )
        false_negative_copy = directory / "false-negatives.json"
        subprocess.run(
            [
                sys.executable,
                str(ANALYZER),
                "--out",
                str(false_negative_copy),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        require(
            json.loads(false_negative_copy.read_text(encoding="utf-8"))
            == false_negatives,
            "false-negative decomposition reproduces exactly",
        )


if __name__ == "__main__":
    main()
