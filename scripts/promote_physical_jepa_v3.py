#!/usr/bin/env python3
"""Verify and publish the passing v3 physical-JEPA evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_incident_scenarios as incidents  # noqa: E402
import physical_stress_scenarios as stress  # noqa: E402
import promote_physical_incident_evidence as prior_promotion  # noqa: E402
import train_physical_jepa as jepa  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL  {message}")
    print(f"PASS  {message}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--selection-report", type=Path, required=True)
    parser.add_argument("--baselines", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--false-negatives", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.selection_report.read_text(encoding="utf-8"))
    baselines = json.loads(args.baselines.read_text(encoding="utf-8"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    require(report["promotion"]["passed"], "all registered v3 promotion gates passed")
    require(report["test_metrics_used_for_selection"] is False, "candidate selection excluded every test partition")
    require(digest(args.artifact) == report["candidate_artifact_sha256"], "artifact matches the frozen selected candidate")
    require(digest(args.artifact) == baselines["artifact_sha256"], "baseline comparison uses the same candidate bytes")
    require(report["protocol_id"] == protocol["protocol_id"], "selection report matches the registered protocol")

    selected = report["selected_candidate"]
    header = struct.unpack("<4sIIIIIIIIffI", args.artifact.read_bytes()[:48])
    require(header[:7] == (b"PJE1", 1, 16, 7, 3, selected["latent"], selected["hidden"]), "artifact header records the selected v3 schema and capacity")
    require(header[7] == selected["training_transitions"], "artifact header records all fitting transitions")
    require(header[-1] == 0, "artifact bytes cannot self-promote")

    base = protocol["base_dataset"]
    base_rows = simulator.generate(base["episodes"], base["steps"], base["seed"])
    train_ids, validation_ids, base_train, base_validation, base_test = jepa.split_rows(
        base_rows, base["episodes"], base["seed"]
    )
    incident_train, incident_train_metadata = incidents.generate_partition(
        "train", selected["incident_train_episodes_per_source"], base["steps"], base["seed"]
    )
    incident_validation, incident_validation_metadata = incidents.generate_partition(
        "validation", protocol["incident_dataset"]["validation_episodes_per_source"], base["steps"], base["seed"]
    )
    incident_test, incident_test_metadata = incidents.generate_partition(
        "test", protocol["incident_dataset"]["test_episodes_per_source"], base["steps"], base["seed"]
    )
    stress_spec = protocol["stress_curriculum"]
    stress_train, stress_train_metadata = stress.generate_partition(
        "train", stress_spec["train_episodes"], base["steps"], stress_spec["seed"]
    )
    stress_validation, stress_validation_metadata = stress.generate_partition(
        "validation", stress_spec["validation_episodes"], base["steps"], stress_spec["seed"]
    )
    stress_test, stress_test_metadata = stress.generate_partition(
        "test", stress_spec["test_episodes"], base["steps"], stress_spec["seed"]
    )
    weights = robustness.load_artifact(args.artifact)
    base_misses = prior_promotion.misses(base_test, weights)
    incident_misses = prior_promotion.misses(incident_test, weights, incident_test_metadata)
    stress_misses = prior_promotion.misses(stress_test, weights)
    require(len(base_misses) == report["candidate_test"]["original_test"]["diagnostics"]["rules_plus_jepa"]["fn"], "ordinary false-negative decomposition is complete")
    require(len(incident_misses) == report["candidate_test"]["incident_test"]["diagnostics"]["rules_plus_jepa"]["fn"], "incident false-negative decomposition is complete")
    require(len(stress_misses) == report["candidate_test"]["stress_test"]["diagnostics"]["rules_plus_jepa"]["fn"], "stress false-negative decomposition is complete")

    total_rows = [
        *base_rows,
        *incident_train,
        *incident_validation,
        *incident_test,
        *stress_train,
        *stress_validation,
        *stress_test,
    ]
    evaluation = {
        "schema_version": 3,
        "protocol_id": protocol["protocol_id"],
        "artifact": str(args.artifact).replace("\\", "/"),
        "artifact_sha256": digest(args.artifact),
        "artifact_bytes": args.artifact.stat().st_size,
        "artifact_format": "PJE1",
        "validated_for_gating": False,
        "runtime_authority": "digest_bound_simulation_caution_only",
        "permit_authority": "deterministic_supervisor",
        "episodes": base["episodes"] + len(incident_train_metadata) + len(incident_validation_metadata) + len(incident_test_metadata) + len(stress_train_metadata) + len(stress_validation_metadata) + len(stress_test_metadata),
        "transitions": len(total_rows),
        "dangerous_transitions": sum(bool(row[6]) for row in total_rows),
        "episode_split": {
            "train": len(train_ids) + len(incident_train_metadata) + len(stress_train_metadata),
            "validation": len(validation_ids) + len(incident_validation_metadata) + len(stress_validation_metadata),
            "test": base["episodes"] - len(train_ids) - len(validation_ids) + len(incident_test_metadata) + len(stress_test_metadata),
        },
        "transition_split": {
            "train": len(base_train) + len(incident_train) + len(stress_train),
            "validation": len(base_validation) + len(incident_validation) + len(stress_validation),
            "test": len(base_test) + len(incident_test) + len(stress_test),
        },
        "episode_overlap": 0,
        "selected_candidate": selected,
        "selection_report_sha256": digest(args.selection_report),
        "baseline_report_sha256": digest(args.baselines),
        "promotion": report["promotion"],
        "test_metrics": report["candidate_test"],
        "deployed_baseline_test_metrics": report["current_test"],
        "baselines": baselines,
        "runtime_horizon": 3,
        "horizon_decision": "H=3 remains the runtime horizon because H=5 has higher compounding error on every registered test split and no separately registered incremental safety catch.",
        "claim_boundary": protocol["claim_boundary"],
    }
    false_negatives = {
        "schema_version": 3,
        "protocol_id": protocol["protocol_id"],
        "artifact_sha256": digest(args.artifact),
        "ordinary": {
            "rows": len(base_test),
            "dangerous": sum(bool(row[6]) for row in base_test),
            "false_negatives": len(base_misses),
            "clusters": dict(sorted(Counter("+".join(item["hazards"]) for item in base_misses).items())),
            "misses": base_misses,
        },
        "incident": {
            "rows": len(incident_test),
            "dangerous": sum(bool(row[6]) for row in incident_test),
            "false_negatives": len(incident_misses),
            "clusters": dict(sorted(Counter("+".join(item["hazards"]) for item in incident_misses).items())),
            "misses": incident_misses,
        },
        "stress": {
            "rows": len(stress_test),
            "dangerous": sum(bool(row[6]) for row in stress_test),
            "false_negatives": len(stress_misses),
            "clusters": dict(sorted(Counter("+".join(item["hazards"]) for item in stress_misses).items())),
            "misses": stress_misses,
        },
        "registered_ood": report["candidate_test"]["ood_test"],
        "interpretation": "Remaining simulator misses stay visible; deterministic rules and the runtime permit boundary remain independent.",
    }
    args.evaluation.parent.mkdir(parents=True, exist_ok=True)
    args.evaluation.write_text(json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.false_negatives.write_text(json.dumps(false_negatives, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("\nPhysical-JEPA v3 promotion evidence generated.")


if __name__ == "__main__":
    main()
