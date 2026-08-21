#!/usr/bin/env python3
"""Reproduce original and incident-challenge physical JEPA false negatives."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import evaluate_physical_jepa_robustness as robustness
import physical_incident_scenarios as incidents
import promote_physical_incident_evidence as evidence
import select_physical_incident_jepa as selector
import train_physical_jepa as jepa
import train_physical_world_model as simulator

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs/research/physical_jepa_false_negative_analysis.json",
    )
    args = parser.parse_args()
    base_rows = simulator.generate(
        selector.DATA_EPISODES, selector.DATA_STEPS, selector.DATA_SEED
    )
    _, _, _, _, base_test = jepa.split_rows(
        base_rows, selector.DATA_EPISODES, selector.DATA_SEED
    )
    incident_test, incident_metadata = incidents.generate_partition(
        "test",
        selector.INCIDENT_TEST_EPISODES_PER_SOURCE,
        selector.DATA_STEPS,
        selector.DATA_SEED,
    )
    weights = robustness.load_artifact(ARTIFACT)
    base_misses = evidence.misses(base_test, weights)
    incident_misses = evidence.misses(incident_test, weights, incident_metadata)
    result = {
        "schema_version": 2,
        "scope": "incident-augmented checkpoint on original and source-family-disjoint held-out simulator episodes",
        "artifact_sha256": hashlib.sha256(ARTIFACT.read_bytes()).hexdigest(),
        "test_transitions": len(base_test),
        "dangerous_test_transitions": sum(bool(row[6]) for row in base_test),
        "combined_false_negative_count": len(base_misses),
        "clusters": dict(
            sorted(Counter("+".join(item["hazards"]) for item in base_misses).items())
        ),
        "misses": base_misses,
        "incident_challenge": {
            "test_transitions": len(incident_test),
            "dangerous_test_transitions": sum(bool(row[6]) for row in incident_test),
            "combined_false_negative_count": len(incident_misses),
            "clusters": dict(
                sorted(
                    Counter(
                        "+".join(item["hazards"]) for item in incident_misses
                    ).items()
                )
            ),
            "source_family_counts": dict(
                sorted(
                    Counter(item["source_family"] for item in incident_misses).items()
                )
            ),
            "misses": incident_misses,
        },
        "interpretation": "Every miss remains a blocker for learned physical gating; deterministic rules remain authoritative and the JEPA remains shadow-only.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
