#!/usr/bin/env python3
"""Audit externally authored OS cases and physical telemetry for model use."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlretrieve

import numpy as np
import pyarrow.parquet as parquet


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/world_model_external_case_intake_protocol_v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/world_model_external_case_intake_result_v1.json"
DATA_ROOT = ROOT / "target/external-data/anchor-lab"
PHYSICAL_ARTIFACT = ROOT / "userland/heliox-daemon/physical_world_model.bin"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_path(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def percentile(values: np.ndarray, quantile: float) -> float | None:
    if len(values) == 0:
        return None
    return float(np.percentile(values, quantile))


def field_category(name: str) -> str:
    lowered = name.lower()
    if any(token in lowered for token in ("target", "command", "cmd", "desired", "setpoint")):
        return "command"
    if any(token in lowered for token in ("contact", "collision")):
        return "contact_label"
    if any(token in lowered for token in ("fault", "failure", "emergency", "estop")):
        return "safety_label"
    return "measured_state"


def inspect_file(path: Path, source_path: str) -> dict:
    table = parquet.read_table(path, columns=["time_ns", "experiment", "field", "value"])
    frame = table.to_pandas()
    values = frame["value"].to_numpy(dtype=np.float64)
    timestamps = np.sort(frame["time_ns"].unique().astype(np.int64))
    intervals_ms = np.diff(timestamps).astype(np.float64) / 1_000_000.0
    fields = sorted(str(value) for value in frame["field"].unique())
    categories: dict[str, list[str]] = {}
    for field in fields:
        categories.setdefault(field_category(field), []).append(field)
    return {
        "source_path": source_path,
        "local_path": repository_path(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "rows": len(frame),
        "experiments": sorted(str(value) for value in frame["experiment"].unique()),
        "fields": fields,
        "field_categories": categories,
        "unique_timestamps": int(len(timestamps)),
        "median_sampling_interval_ms": percentile(intervals_ms, 50),
        "p99_sampling_interval_ms": percentile(intervals_ms, 99),
        "nonfinite_values": int(np.sum(~np.isfinite(values))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    args = parser.parse_args()

    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    source = next(item for item in protocol["sources"] if item["source_id"] == "nvidia-anchor-lab")
    args.data_root.mkdir(parents=True, exist_ok=True)
    artifact_before = sha256(PHYSICAL_ARTIFACT)
    inspected = []
    for source_path in source["selected_files"]:
        local = args.data_root / source_path
        local.parent.mkdir(parents=True, exist_ok=True)
        if not local.exists():
            url = f"https://huggingface.co/datasets/nvidia/Anchor-Lab/resolve/{source['revision']}/{source_path}"
            urlretrieve(url, local)
        inspected.append(inspect_file(local, source_path))

    command_files = [item for item in inspected if item["field_categories"].get("command")]
    contact_files = [item for item in inspected if item["field_categories"].get("contact_label")]
    safety_files = [item for item in inspected if item["field_categories"].get("safety_label")]
    all_finite = all(item["nonfinite_values"] == 0 for item in inspected)
    artifact_after = sha256(PHYSICAL_ARTIFACT)
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "sources": {
            "physical": {
                "publisher": source["publisher"],
                "revision": source["revision"],
                "files": inspected,
            },
            "os_case_taxonomy": next(
                item for item in protocol["sources"] if item["source_id"] == "azure-public-vm-noise"
            ),
        },
        "physical_compatibility": {
            "timing_available": all(item["unique_timestamps"] > 1 for item in inspected),
            "measured_state_available": all(item["field_categories"].get("measured_state") for item in inspected),
            "command_or_target_available": bool(command_files),
            "command_or_target_file_count": len(command_files),
            "safety_labels_available": bool(safety_files),
            "contact_labels_available": bool(contact_files),
            "embodiment_specific_dynamics_study_useful": bool(command_files) and all_finite,
            "direct_physical_jepa_v5_replay_valid": False,
            "reason_direct_replay_is_invalid": "Anchor-Lab joint, actuator and temperature fields do not share Physical JEPA v5's 16-state navigation/maintenance semantics or seven-action ontology. A numeric projection would be researcher-invented and would not measure v5 accuracy.",
            "recommended_use": "Train and freeze an embodiment-specific adapter/world model on Anchor-Lab train trials, then evaluate only the publisher-designated heldout SO-101 trials and separated H1 conditions.",
        },
        "authority": {
            "mode": "metadata and telemetry compatibility audit",
            "model_inference_calls": 0,
            "actuator_delivery_attempts": 0,
            "actuator_deliveries": 0,
            "physical_hardware_connected": False,
        },
        "artifact": {
            "path": repository_path(PHYSICAL_ARTIFACT),
            "sha256_before": artifact_before,
            "sha256_after": artifact_after,
            "unchanged": artifact_before == artifact_after,
        },
        "checks": {
            "registered_file_count": len(inspected) == len(source["selected_files"]) == 6,
            "all_external_values_finite": all_finite,
            "all_files_have_timestamps": all(item["unique_timestamps"] > 1 for item in inspected),
            "all_files_digest_recorded": all(len(item["sha256"]) == 64 for item in inspected),
            "heldout_cases_present": sum("heldout" in item["source_path"] for item in inspected) == 3,
            "no_semantic_projection": True,
            "zero_model_inference": True,
            "zero_actuator_attempts": True,
            "zero_actuator_deliveries": True,
            "artifact_unchanged": artifact_before == artifact_after,
        },
        "claim_boundary": protocol["claim_boundary"],
        "promotion_eligible": False,
    }
    result["acceptance_gates_passed"] = all(result["checks"].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "acceptance_gates_passed": result["acceptance_gates_passed"]}, indent=2))
    return 0 if result["acceptance_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
