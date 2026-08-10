#!/usr/bin/env python3
"""Reproduce and validate the committed simulator-only physical model."""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAINER = ROOT / "scripts" / "train_physical_world_model.py"
ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
EVALUATION = ROOT / "docs" / "research" / "physical_world_model_evaluation.json"


def require(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    evaluation = json.loads(EVALUATION.read_text(encoding="utf-8"))
    artifact = ARTIFACT.read_bytes()
    require(sha256(ARTIFACT) == evaluation["artifact_sha256"], "artifact hash matches evaluation")
    require(len(artifact) == 11_116, "PWM1 artifact has exact bounded size")
    header = struct.unpack("<4sIIIIIIIffI", artifact[:44])
    magic, version, state_size, action_count, feature_size, hidden, samples, input_size, h3, mean_h3, gating = header
    require(magic == b"PWM1" and version == 1, "artifact magic and version are supported")
    require((state_size, action_count, feature_size, input_size) == (16, 7, 3, 26), "artifact schema matches runtime")
    require(hidden == 64 and samples == 10_500, "artifact capacity and training sample count are recorded")
    require(gating == 0 and not evaluation["validated_for_gating"], "simulator artifact remains shadow-only")
    require(h3 < mean_h3, "artifact H=3 error beats per-action mean baseline")
    require(evaluation["episode_overlap"] == 0, "train validation and test episodes do not overlap")
    require(
        evaluation["safety"]["rules_plus_learned"]["fn"]
        < evaluation["safety"]["rules_only"]["fn"],
        "combined simulator screen reduces false negatives versus rules only",
    )

    with tempfile.TemporaryDirectory(prefix="ferrum-physical-model-") as temp:
        directory = Path(temp)
        dataset = directory / "trajectories.jsonl"
        artifact_copy = directory / "model.bin"
        evaluation_copy = directory / "evaluation.json"
        subprocess.run(
            [
                sys.executable,
                str(TRAINER),
                "--dataset", str(dataset),
                "--artifact", str(artifact_copy),
                "--evaluation", str(evaluation_copy),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        reproduced = json.loads(evaluation_copy.read_text(encoding="utf-8"))
        require(sha256(artifact_copy) == evaluation["artifact_sha256"], "training deterministically reproduces artifact")
        require(sha256(dataset) == evaluation["generated_dataset_sha256"], "generator deterministically reproduces 15,000 transitions")
        require(
            reproduced["normalized_rollout_error"] == evaluation["normalized_rollout_error"],
            "held-out rollout metrics reproduce exactly",
        )
        require(reproduced["safety"] == evaluation["safety"], "three-arm safety metrics reproduce exactly")

    print("\nPhysical world-model verification passed.")


if __name__ == "__main__":
    main()
