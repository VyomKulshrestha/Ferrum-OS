#!/usr/bin/env python3
"""Verify or fully reproduce the promoted physical-JEPA v3 checkpoint."""

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
RESEARCH = ROOT / "docs" / "research"
SELECTOR = ROOT / "scripts" / "select_physical_incident_jepa.py"
PROMOTER = ROOT / "scripts" / "promote_physical_jepa_v3.py"
ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
BASELINE_ARTIFACT = (
    RESEARCH
    / "artifacts"
    / "physical-jepa-stress-v3"
    / "incident-v1-baseline.bin"
)
PROTOCOL = RESEARCH / "physical_jepa_v3_protocol.json"
SELECTION = RESEARCH / "physical_jepa_v3_selection.json"
BASELINES = RESEARCH / "physical_jepa_v3_baselines.json"
EVALUATION = RESEARCH / "physical_jepa_v3_evaluation.json"
FALSE_NEGATIVES = RESEARCH / "physical_jepa_v3_false_negative_analysis.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_committed() -> tuple[dict, dict, dict, dict, dict]:
    protocol = load(PROTOCOL)
    selection = load(SELECTION)
    baselines = load(BASELINES)
    evaluation = load(EVALUATION)
    false_negatives = load(FALSE_NEGATIVES)
    digest = sha256(ARTIFACT)

    require(
        protocol["registered_before_test_open"]
        and protocol["protocol_id"] == "physical-jepa-stress-curriculum-v3",
        "v3 protocol was registered before the test partitions were opened",
    )
    require(
        digest
        == selection["candidate_artifact_sha256"]
        == baselines["artifact_sha256"]
        == evaluation["artifact_sha256"]
        == false_negatives["artifact_sha256"],
        "deployed artifact digest matches every v3 evidence report",
    )
    require(
        sha256(BASELINE_ARTIFACT) == protocol["baseline_artifact_sha256"],
        "immutable incident-v1 checkpoint anchors the registered comparison",
    )

    artifact = ARTIFACT.read_bytes()
    require(
        len(artifact) == evaluation["artifact_bytes"] == 290_928,
        "PJE1 artifact size is recorded exactly",
    )
    header = struct.unpack("<4sIIIIIIIIffI", artifact[:48])
    magic, version, state, actions, features, latent, hidden, samples, action_input, h3, mean_h3, gating = header
    require(
        (magic, version, state, actions, features, action_input)
        == (b"PJE1", 1, 16, 7, 3, 10),
        "artifact schema matches the bounded Rust loader",
    )
    require(
        (latent, hidden, samples) == (128, 256, 123_200),
        "deployed model records the selected capacity and training count",
    )
    require(
        gating == 0 and not evaluation["validated_for_gating"],
        "model bytes cannot self-promote or mint physical authority",
    )
    require(h3 < mean_h3, "JEPA H=3 error beats the fitted per-action mean")

    require(
        selection["test_metrics_used_for_selection"] is False
        and selection["selection_protocol"]
        == "validation_only_then_single_untouched_test_open",
        "candidate choice excludes every frozen test partition",
    )
    selected = selection["selected_candidate"]
    require(
        selection["selected_candidate_index"] == 3
        and selected["latent"] == 128
        and selected["hidden"] == 256
        and selected["training_seed"] == 91
        and selected["training_transitions"] == 123_200,
        "validation sweep selected the registered 128 by 256 seed-91 candidate",
    )
    require(
        selection["promotion"]["passed"]
        and len(selection["promotion"]["checks"]) == 11
        and all(selection["promotion"]["checks"].values()),
        "all 11 frozen promotion gates pass",
    )
    require(
        evaluation["episodes"] == 23_680
        and evaluation["transitions"] == 189_440
        and evaluation["transition_split"]
        == {"train": 123_200, "validation": 28_160, "test": 38_080}
        and evaluation["episode_overlap"] == 0,
        "23,680 episodes remain disjoint across train, validation, and test",
    )

    tests = evaluation["test_metrics"]
    require(
        tests["original_test"]["rollout"]["h3"]
        < evaluation["deployed_baseline_test_metrics"]["original_test"]["rollout"]["h3"]
        and tests["incident_test"]["rollout"]["h3"]
        < evaluation["deployed_baseline_test_metrics"]["incident_test"]["rollout"]["h3"]
        and tests["stress_test"]["rollout"]["h3"]
        < evaluation["deployed_baseline_test_metrics"]["stress_test"]["rollout"]["h3"],
        "H=3 error improves on ordinary, incident, and stress tests",
    )
    require(
        tests["ood_test"]["invalid_observations_rejected"] == 682
        and tests["ood_test"]["rules_plus_jepa"]["fn"] == 0,
        "registered OOD test rejects malformed observations and records zero false negatives",
    )
    require(
        false_negatives["ordinary"]["false_negatives"] == 8
        and false_negatives["incident"]["false_negatives"] == 1
        and false_negatives["stress"]["false_negatives"] == 1
        and false_negatives["registered_ood"]["rules_plus_jepa"]["fn"] == 0,
        "remaining false negatives are explicitly decomposed instead of hidden",
    )

    comparisons = baselines["comparisons"]
    require(
        all(
            comparisons[split]["jepa"]["rollout"]["h3"]
            < comparisons[split]["matched_autoencoder"]["rollout"]["h3"]
            < comparisons[split]["per_action_mean"]["rollout"]["h3"]
            for split in ("original", "incident", "stress")
        ),
        "matched-capacity JEPA beats autoencoder and mean-delta H=3 rollout error",
    )
    require(
        evaluation["runtime_horizon"] == 3
        and "H=5 has higher compounding error" in evaluation["horizon_decision"],
        "runtime retains H=3 because H=5 is less accurate on every test split",
    )
    return protocol, selection, baselines, evaluation, false_negatives


def reproduce(protocol: dict, selection: dict) -> None:
    base = protocol["base_dataset"]
    incident = protocol["incident_dataset"]
    stress = protocol["stress_curriculum"]
    ood = protocol["registered_ood"]
    with tempfile.TemporaryDirectory(prefix="ferrum-physical-v3-") as temp:
        directory = Path(temp)
        artifact = directory / "model.bin"
        report = directory / "selection.json"
        dataset = directory / "dataset.jsonl"
        command = [
            sys.executable,
            str(SELECTOR),
            "--current-artifact", str(BASELINE_ARTIFACT),
            "--artifact", str(artifact),
            "--report", str(report),
            "--dataset", str(dataset),
            "--base-episodes", str(base["episodes"]),
            "--steps", str(base["steps"]),
            "--data-seed", str(base["seed"]),
            "--incident-validation-per-source", str(incident["validation_episodes_per_source"]),
            "--incident-test-per-source", str(incident["test_episodes_per_source"]),
            "--candidate-config", str(PROTOCOL),
            "--ood-count", str(ood["rows"]),
            "--ood-seed", str(ood["seed"]),
            "--ood-protocol", str(ood["protocol"]),
            "--stress-train-episodes", str(stress["train_episodes"]),
            "--stress-validation-episodes", str(stress["validation_episodes"]),
            "--stress-test-episodes", str(stress["test_episodes"]),
            "--stress-seed", str(stress["seed"]),
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        reproduced = load(report)
        require(sha256(artifact) == sha256(ARTIFACT), "full sweep reproduces the deployed checkpoint")
        require(
            reproduced["selected_candidate_index"] == selection["selected_candidate_index"]
            and reproduced["promotion"] == selection["promotion"],
            "full sweep reproduces selection and all promotion decisions",
        )
        require(
            sha256(dataset) == selection["dataset_sha256"],
            "training trajectory corpus reproduces byte-for-byte",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="verify committed artifacts and metrics without retraining the sweep",
    )
    args = parser.parse_args()
    protocol, selection, _, _, _ = verify_committed()
    if not args.quick:
        reproduce(protocol, selection)
    print("\nPhysical-JEPA v3 verification passed.")


if __name__ == "__main__":
    main()
