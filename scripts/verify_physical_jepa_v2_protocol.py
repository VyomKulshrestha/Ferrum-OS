#!/usr/bin/env python3
"""Verify the pre-registered large-corpus physical-JEPA protocol."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_v2_protocol.json"
ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS\t{message}")


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    digest = hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()
    base = protocol["base_dataset"]
    incident = protocol["incident_dataset"]
    ood = protocol["registered_ood"]
    candidates = protocol["candidates"]

    require(protocol["registered_before_test_open"] is True, "protocol is registered before the test open")
    require(digest == protocol["baseline_artifact_sha256"], "protocol binds the deployed baseline checkpoint")
    require(base == {"episodes": 10_000, "steps": 8, "seed": 20_260_822}, "base corpus size, horizon, and seed are fixed")
    require(base["episodes"] * base["steps"] == 80_000, "base corpus contains 80,000 generated transitions")
    require(incident["source_families_disjoint"] is True, "incident source families remain split-disjoint")
    require(incident["validation_episodes_per_source"] == 240 and incident["test_episodes_per_source"] == 240, "incident validation and test sizes are fixed")
    require(ood == {"rows": 2_048, "seed": 20_260_823}, "larger registered OOD fixture is fixed")
    require(len(candidates) == 6, "six candidates are pre-registered")
    require(len({(item["latent"], item["hidden"], item["training_seed"], item["incident_train_episodes_per_source"]) for item in candidates}) == len(candidates), "candidate configurations are unique")
    require({item["training_seed"] for item in candidates} == {17, 42, 91}, "candidate sweep covers three training seeds")
    require(max(item["latent"] for item in candidates) == 128 and max(item["hidden"] for item in candidates) == 256, "candidate sweep tests expanded runtime capacity")
    require(set(protocol["selection"]["excludes"]) == {"base_test", "incident_test", "registered_ood"}, "selection excludes every registered test partition")
    require(protocol["selection"]["test_open_count"] == 1, "protocol permits one frozen-candidate test open")
    print("\nPhysical-JEPA v2 protocol verification passed: 13/13 checks.")


if __name__ == "__main__":
    main()
