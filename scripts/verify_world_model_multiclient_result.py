#!/usr/bin/env python3
"""Verify the frozen FerrumOS multi-client contention result."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/world_model_multiclient_contention_protocol_v1.json"
DEFAULT_RESULT = ROOT / "docs/research/world_model_multiclient_contention_result_v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/world_model_multiclient_contention_verification_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    result = json.loads(args.result.read_text(encoding="utf-8"))
    checks = {
        "protocol_identity": result["protocol_id"] == protocol["protocol_id"] and result["protocol_sha256"] == sha256(PROTOCOL),
        "client_count": result["clients"] == protocol["clients"] == len(result["per_client"]) == 4,
        "request_count": result["requests_per_client"] == protocol["requests_per_client"] == 32 and result["timed_responses"] == 128,
        "per_client_completion": all(item["responses"] == 32 for item in result["per_client"]),
        "no_leakage": all(not item["unexpected_response_ids"] for item in result["per_client"]),
        "fairness": result["jain_throughput_fairness"] >= 0.95,
        "authority_rejected": result["authority"]["additional_clients_scope"] == "world_model_preview only"
        and result["authority"]["execution_probe_error_code"] == -32601,
        "zero_execution": result["authority"]["execution_dataset_records_added"] == 0,
        "zero_physical_delivery": result["authority"]["physical_delivery_attempts"] == 0
        and result["authority"]["physical_deliveries"] == 0,
        "disconnect_probe": all(result["failure_probe"].values()),
        "source_disk_unchanged": result["packaged_source_disk"]["unchanged"] is True
        and result["packaged_source_disk"]["sha256_before"] == result["packaged_source_disk"]["sha256_after"],
        "runtime_checks": all(result["checks"].values()),
        "result_gates": result["acceptance_gates_passed"] is True,
        "no_promotion": result["promotion_eligible"] is False,
    }
    verification = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "result": {"path": str(args.result.resolve().relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(args.result)},
        "checks": checks,
        "verification_passed": all(checks.values()),
        "promotion_eligible": False,
        "claim_boundary": protocol["claim_boundary"],
    }
    args.output.write_text(json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "verification_passed": verification["verification_passed"]}, indent=2))
    return 0 if verification["verification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
