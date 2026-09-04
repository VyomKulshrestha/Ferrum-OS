#!/usr/bin/env python3
"""Verify the registered Safety-Gymnasium risk-source attribution evidence."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess

import run_physical_jepa_safety_gymnasium as benchmark


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_protocol_v2.json"
RESULT_PATH = ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_result_v2.json"
VERIFICATION_PATH = ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_verification_v2.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def close(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)


def main() -> None:
    protocol = load_json(PROTOCOL_PATH)
    result = load_json(RESULT_PATH)
    boundary = protocol["prospective_boundary"]["final_seed_range_unopened_at_registration"]
    expected_seeds = list(range(boundary["start"], boundary["start"] + boundary["count"]))
    checks: dict[str, bool] = {
        "result_protocol_digest_matches": result["protocol"]["sha256"] == sha256(PROTOCOL_PATH),
        "registration_commit_recorded": bool(result["protocol"]["registered_commit"]),
        "single_final_access": result["final_seed_access_count"] == 1,
        "final_seed_range_matches": result["final_seed_range"] == boundary,
        "runtime_versions_match": result["runtime"]["versions_match"],
        "runtime_source_matches": result["runtime"]["source_matches"],
        "physical_actuator_attempts_zero": result["authority"]["physical_actuator_attempts"] == 0,
        "physical_actuator_deliveries_zero": result["authority"]["physical_actuator_deliveries"] == 0,
        "protected_deployed_artifact_unchanged": result["authority"]["protected_deployed_artifact_unchanged"],
        "promotion_ineligible": result["authority"]["promotion_eligible"] is False,
    }
    registered_blob = subprocess.check_output(
        ["git", "show", f"{result['protocol']['registered_commit']}:{str(PROTOCOL_PATH.relative_to(ROOT)).replace(chr(92), '/')}"],
        cwd=ROOT,
    )
    checks["protocol_matches_registered_commit"] = (
        hashlib.sha256(registered_blob).hexdigest() == sha256(PROTOCOL_PATH)
    )
    expected_variants = [item["id"] for item in protocol["risk_source_variants"]]
    checks["variant_set_exact"] = list(result["variants"]) == expected_variants

    for registered in protocol["risk_source_variants"]:
        name = registered["id"]
        record = result["variants"][name]
        episodes = record["episode_summaries"]
        checks[f"{name}_adapter_digest"] = sha256(ROOT / registered["path"]) == registered["sha256"]
        checks[f"{name}_threshold"] = close(
            record["learned_risk_threshold"], registered["learned_risk_threshold"]
        )
        checks[f"{name}_seed_set"] = sorted(int(item["seed"]) for item in episodes) == expected_seeds
        recomputed = benchmark.aggregate(episodes)
        stored = record["aggregate"]
        aggregate_ok = True
        for key, value in recomputed.items():
            if isinstance(value, list):
                aggregate_ok = aggregate_ok and all(
                    close(left, right) for left, right in zip(value, stored[key])
                )
            elif isinstance(value, (float, int)):
                aggregate_ok = aggregate_ok and close(value, stored[key])
            else:
                aggregate_ok = aggregate_ok and value == stored[key]
        checks[f"{name}_aggregate_recomputes"] = aggregate_ok
        expected_precision = stored["true_positive_interventions"] / max(1, stored["interventions"])
        checks[f"{name}_intervention_precision"] = close(
            stored["intervention_precision"], expected_precision
        )
        catalog = ROOT / record["case_catalog"]["path"]
        checks[f"{name}_case_digest"] = sha256(catalog) == record["case_catalog"]["sha256"]
        rows = 0
        seeds = set()
        with gzip.open(catalog, "rt", encoding="utf-8") as handle:
            for line in handle:
                case = json.loads(line)
                rows += 1
                seeds.add(int(case["seed"]))
        checks[f"{name}_case_rows"] = rows == record["case_catalog"]["rows"] == stored["proposals"]
        checks[f"{name}_case_seed_set"] = sorted(seeds) == expected_seeds
        checks[f"{name}_paired_resamples"] = (
            record["versus_planner_paired_bootstrap"]["resamples"] == 10000
            and record["versus_full_adapter_paired_bootstrap"]["resamples"] == 10000
        )

    all_checks_pass = all(checks.values())
    verification = {
        "schema": "physical-jepa-safety-gymnasium-risk-source-attribution-verification-v2",
        "protocol": {"path": str(PROTOCOL_PATH.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(PROTOCOL_PATH)},
        "result": {"path": str(RESULT_PATH.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(RESULT_PATH)},
        "checks": checks,
        "all_checks_pass": all_checks_pass,
        "promotion_eligible": False,
    }
    VERIFICATION_PATH.write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(verification, indent=2, sort_keys=True))
    if not all_checks_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
