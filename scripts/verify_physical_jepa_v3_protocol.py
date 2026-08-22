#!/usr/bin/env python3
"""Verify the pre-registered stress-curriculum physical-JEPA protocol."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_v3_protocol.json"
ARTIFACT = (
    ROOT
    / "docs"
    / "research"
    / "artifacts"
    / "physical-jepa-stress-v3"
    / "incident-v1-baseline.bin"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS\t{message}")


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    digest = hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()
    base = protocol["base_dataset"]
    stress = protocol["stress_curriculum"]
    candidates = protocol["candidates"]
    require(
        protocol["registered_before_test_open"] is True,
        "v3 protocol is registered before test open",
    )
    require(
        digest == protocol["baseline_artifact_sha256"],
        "v3 protocol binds the frozen incident-v1 baseline",
    )
    require(
        base == {"episodes": 12_000, "steps": 8, "seed": 20_260_824},
        "new base corpus and split seed are fixed",
    )
    require(
        stress["train_episodes"] == 3_000
        and stress["validation_episodes"] == 1_000
        and stress["test_episodes"] == 2_000,
        "stress curriculum sizes are fixed",
    )
    require(
        stress["valid_edge_state_families"] == 12,
        "stress curriculum covers twelve valid edge-state families",
    )
    require(
        protocol["registered_ood"]
        == {
            "protocol": "v2",
            "rows": 4_096,
            "seed": 20_260_825,
            "invalid_observations_fail_closed": True,
            "invalid_rows_excluded_from_transition_error": True,
        },
        "new OOD fixture and invalid-state accounting are fixed",
    )
    require(
        len(candidates) == 4
        and {item["training_seed"] for item in candidates} == {17, 42, 91},
        "four candidates cover three seeds",
    )
    require(
        all(item["stress_train_episodes"] == 3_000 for item in candidates),
        "every candidate fits the stress curriculum",
    )
    require(
        max(item["latent"] for item in candidates) == 128
        and max(item["hidden"] for item in candidates) == 256,
        "expanded capacity remains registered",
    )
    require(
        set(protocol["selection"]["excludes"])
        == {"base_test", "incident_test", "stress_test", "registered_ood"},
        "selection excludes all four test partitions",
    )
    require(
        protocol["selection"]["test_open_count"] == 1,
        "v3 permits one frozen-candidate test open",
    )
    print("\nPhysical-JEPA v3 protocol verification passed: 11/11 checks.")


if __name__ == "__main__":
    main()
