#!/usr/bin/env python3
"""Verify the complete OS-JEPA v3-v3.4 research lineage and non-promotion boundary."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_world_model_safety import TransitionModel  # noqa: E402
from select_world_model_jepa_v3_1 import sha256  # noqa: E402


RESEARCH = ROOT / "docs" / "research"
ARTIFACT = RESEARCH / "artifacts" / "world-model-v3.4"
PROTOCOL = RESEARCH / "world_model_jepa_v3_4_protocol.json"
VALIDATION = RESEARCH / "world_model_jepa_v3_4_validation.json"
FINAL_SOURCES = RESEARCH / "world_model_incident_final_sources_v3_1.json"
FINAL_SCENARIOS = RESEARCH / "world_model_incident_v3_4_final_catalog.json"
FINAL_RESULT = RESEARCH / "world_model_jepa_v3_4_final_result.json"
MANIFEST = ARTIFACT / "manifest.json"
MODEL = ARTIFACT / "model_candidate.bin"
DEPLOYED = ROOT / "appliance" / "world-model" / "model_learned.bin"
DEPLOYED_MANIFEST = ROOT / "appliance" / "world-model" / "manifest.json"
DEFAULT_RESULT = RESEARCH / "world_model_jepa_v3_4_verification.json"


def require(condition: bool, message: str, checks: dict) -> None:
    checks[message] = bool(condition)
    if not condition:
        raise AssertionError(message)
    print(f"PASS\t{message}")


def verify_url(url: str) -> int:
    request = Request(url, headers={"User-Agent": "FerrumOS-research-verifier/1.0"})
    try:
        with urlopen(request, timeout=25, context=ssl.create_default_context()) as response:
            return int(response.status)
    except HTTPError as error:
        return int(error.code)
    except URLError as error:
        raise AssertionError(f"source URL unavailable: {url}: {error.reason}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    final = json.loads(FINAL_RESULT.read_text(encoding="utf-8"))
    sources = json.loads(FINAL_SOURCES.read_text(encoding="utf-8"))["sources"]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    checks: dict[str, bool] = {}

    require(validation["validation_passed"], "registered development validation passed", checks)
    require(not validation["new_final_catalog_access"]["opened"], "v3.4 final stayed unopened during validation", checks)
    require(final["offline_gates_passed"], "all frozen offline final gates passed", checks)
    require(all(final["gates"].values()), "every recorded offline gate is true", checks)
    require(final["final_open_count"] == 1, "final scenario generation is recorded once", checks)
    require(final["protocol_sha256"] == sha256(PROTOCOL), "final result binds the frozen v3.4 protocol", checks)
    require(final["validation_sha256"] == sha256(VALIDATION), "final result binds the passing validation", checks)
    require(final["final_source_catalog_sha256"] == sha256(FINAL_SOURCES), "final result binds the held-out sources", checks)
    require(final["final_scenario_catalog_sha256"] == sha256(FINAL_SCENARIOS), "final result binds the generated cases", checks)
    require(final["candidate_sha256"] == sha256(MODEL), "archived candidate matches the evaluated weights", checks)
    require(manifest["model"]["sha256"] == sha256(MODEL), "candidate manifest digest matches", checks)
    require(manifest["final_result"]["sha256"] == sha256(FINAL_RESULT), "candidate manifest binds the final result", checks)
    require(manifest["final_scenario_catalog"]["sha256"] == sha256(FINAL_SCENARIOS), "candidate manifest binds the final cases", checks)
    TransitionModel(MODEL)
    require(True, "archived FWM2 candidate parses with the runtime-compatible evaluator", checks)

    baseline = final["final_conditions"]["rules_plus_jepa"]
    rules = final["final_conditions"]["rules_v3_4"]
    combined = final["final_conditions"]["rules_v3_4_plus_jepa_candidate"]
    require(combined["balanced_accuracy"] == 1.0, "source-held-out balanced accuracy is 1.0", checks)
    require(combined["confusion"] == rules["confusion"], "final safety outcome is attributed entirely to deterministic rules", checks)
    require(combined["confusion"]["false_negative"] == 0, "no final simulated hazards were missed", checks)
    require(combined["confusion"]["false_positive"] == 0, "no final simulated safe controls were blocked", checks)
    require(combined["balanced_accuracy"] > baseline["balanced_accuracy"], "v3.4 policy exceeds runtime-v2 on the held-out simulator", checks)
    rollout = final["published_corpus_untouched_test"]["candidate_to_runtime_v2"]
    require(all(value < 1.0 for value in rollout["ratios"].values()), "candidate improves H1 H3 and H5 on untouched published rows", checks)
    require(rollout["geometric_ratio"] < 1.0, "candidate improves untouched-corpus geometric rollout error", checks)

    deployed_manifest = json.loads(DEPLOYED_MANIFEST.read_text(encoding="utf-8"))
    require(sha256(DEPLOYED) == protocol["frozen_lineage"]["deployed_transition_sha256"], "deployed runtime-v2 transition remains unchanged", checks)
    require(deployed_manifest["runtime_revision"] == 2, "deployed manifest remains runtime-v2", checks)
    require(not final["promotion_eligible"], "final result does not claim promotion eligibility", checks)
    require(final["runtime_and_authority_gates_pending"], "runtime and authority gates remain explicitly pending", checks)
    require(not manifest["deployment"]["attempted"], "archived candidate records no deployment attempt", checks)

    statuses = {}
    if args.online:
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda item: verify_url(item["url"]), sources))
        statuses = {item["id"]: status for item, status in zip(sources, values)}
        require(
            all(200 <= status < 400 or status in {403, 429} for status in statuses.values()),
            "all held-out primary-source URLs resolve or explicitly restrict automation",
            checks,
        )

    output = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "online_status": statuses,
        "research_result_verified": all(checks.values()),
        "promotion_eligible": False,
        "deployment_unchanged": True,
        "runtime_authority_status": "pending; authored simulator resource effects are not empirical runtime effects",
    }
    args.result.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "checks": f"{output['checks_passed']}/{output['checks_total']}",
        "research_result_verified": output["research_result_verified"],
        "promotion_eligible": False,
        "deployment_unchanged": True,
    }, indent=2))


if __name__ == "__main__":
    main()
