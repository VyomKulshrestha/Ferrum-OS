#!/usr/bin/env python3
"""Verify authority-disabled in-guest shadow evidence for OS-JEPA v3.4."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/world_model_jepa_v3_4_protocol.json"
ARCHITECTURE_PROTOCOL = (
    ROOT / "docs/research/cross_domain_world_model_improvement_protocol_v1.json"
)
DEFAULT_RUNTIME = ROOT / "docs/research/world_model_v3_4_shadow_runtime_v1.json"
DEFAULT_CONCURRENCY = ROOT / "docs/research/world_model_v3_4_shadow_concurrency_v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/world_model_v3_4_shadow_verification_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value) -> bool:
    if value is None or isinstance(value, (bool, str)):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, list):
        return all(finite(item) for item in value)
    if isinstance(value, dict):
        return all(finite(item) for item in value.values())
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--concurrency", type=Path, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    protocol = load(PROTOCOL)
    architecture = load(ARCHITECTURE_PROTOCOL)
    runtime = load(args.runtime)
    concurrency = load(args.concurrency)
    candidate = ROOT / protocol["frozen_lineage"]["v3_candidate_path"]
    candidate_digest = protocol["frozen_lineage"]["v3_candidate_sha256"]
    protected = {
        name: sha256(ROOT / item["path"]) == item["sha256"]
        for name, item in architecture["protected_deployed_artifacts"].items()
    }
    runtime_checks = {
        "protocol_v3": runtime["protocol"]
        == "in-guest-world-model-runtime-benchmark-v3",
        "authority_disabled": runtime["authority_disabled"] is True,
        "candidate_digest": runtime["transition"]["sha256"]
        == candidate_digest
        == sha256(candidate),
        "disposable_role": "disposable" in runtime["transition"]["role"],
        "source_disk_unchanged": runtime["packaged_source_disk"]["unchanged"] is True,
        "horizons": [item["horizon"] for item in runtime["horizons"]]
        == [1, 2, 3, 4, 5],
        "p99_ordered": all(
            item["median_cycles"]
            <= item["p95_cycles"]
            <= item["p99_cycles"]
            <= item["max_cycles"]
            and item["median_microseconds"]
            <= item["p95_microseconds"]
            <= item["p99_microseconds"]
            <= item["max_microseconds"]
            for item in runtime["horizons"]
        ),
        "models_loaded": runtime["memory"]["encoder_loaded"]
        and runtime["memory"]["transition_loaded"],
        "no_heap_growth": runtime["memory"]["heap_growth_bytes"] == 0,
        "finite": finite(runtime),
    }
    concurrency_checks = {
        "authority_disabled": concurrency["authority_disabled"] is True,
        "candidate_digest": concurrency["transition"]["sha256"] == candidate_digest,
        "source_disk_unchanged": concurrency["packaged_source_disk"]["unchanged"]
        is True,
        "all_responses": concurrency["responses_received"]
        == concurrency["outstanding_requests"],
        "deterministic": concurrency["identical_requests_deterministic"] is True,
        "no_execution_records": concurrency["execution_dataset_records_added"] == 0,
        "models_loaded": concurrency["learned_encoder_loaded"]
        and concurrency["learned_transition_loaded"],
        "guest_fault_free": concurrency["guest_fault_free"] is True,
        "finite": finite(concurrency),
    }
    checks = {
        "candidate_exists": candidate.is_file(),
        "protected_deployed_artifacts_unchanged": all(protected.values()),
        "runtime_verified": all(runtime_checks.values()),
        "concurrency_verified": all(concurrency_checks.values()),
    }
    result = {
        "schema_version": 1,
        "protocol_id": "ferrumos-os-jepa-v3.4-authority-disabled-shadow-v1",
        "candidate_sha256": candidate_digest,
        "runtime_report": {
            "path": str(args.runtime.resolve().relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256(args.runtime),
        },
        "concurrency_report": {
            "path": str(args.concurrency.resolve().relative_to(ROOT)).replace(
                "\\", "/"
            ),
            "sha256": sha256(args.concurrency),
        },
        "runtime_checks": runtime_checks,
        "concurrency_checks": concurrency_checks,
        "protected_deployed_artifacts": protected,
        "checks": checks,
        "verification_passed": all(checks.values()),
        "promotion_eligible": False,
        "evidence_class": "QEMU/WHPX or QEMU/TCG in-guest authority-disabled shadow preview; no action dispatch",
        "claim_boundary": [
            "The frozen v3.4 candidate was injected only into disposable run-disk copies.",
            "The packaged source disk and deployed research artifacts remained byte-identical.",
            "This is emulator runtime, timing, load, memory, and concurrent-preview evidence; it is not production deployment or natural-use outcome evidence.",
        ],
    }
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "verification_passed": result["verification_passed"],
            },
            indent=2,
        )
    )
    return 0 if result["verification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
