#!/usr/bin/env python3
"""Validate the preregistered OS-JEPA v3.4 policy without opening its final catalog."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_world_model_safety import Encoder, TransitionModel  # noqa: E402
from select_world_model_jepa_v3_1 import compact, enrich_legacy_cases, sha256  # noqa: E402
import world_model_incident_scenarios as incidents  # noqa: E402


RESEARCH = ROOT / "docs" / "research"
PROTOCOL = RESEARCH / "world_model_jepa_v3_4_protocol.json"
V3_FINAL = RESEARCH / "world_model_incident_v3_final_catalog.json"
LEGACY_FIXTURE = RESEARCH / "world_model_safety_scenarios.json"
NEW_FINAL_SOURCES = RESEARCH / "world_model_incident_final_sources_v3_1.json"
NEW_FINAL_SCENARIOS = RESEARCH / "world_model_incident_v3_4_final_catalog.json"
ENCODER = ROOT / "appliance" / "world-model" / "model_encoder.bin"
DEPLOYED = ROOT / "appliance" / "world-model" / "model_learned.bin"
MANIFEST = ROOT / "appliance" / "world-model" / "manifest.json"
CANDIDATE = ROOT / "target" / "world-model-v3-work" / "world_model_jepa_v3_candidate.bin"
RESULT = RESEARCH / "world_model_jepa_v3_4_validation.json"


def install_final_guard() -> dict:
    protected = {NEW_FINAL_SOURCES.resolve(), NEW_FINAL_SCENARIOS.resolve()}
    state = {"attempted": False, "paths": []}

    def audit(event: str, arguments: tuple) -> None:
        if event != "open" or not arguments or not isinstance(arguments[0], (str, bytes)):
            return
        try:
            opened = Path(os.fsdecode(arguments[0])).resolve()
        except (OSError, TypeError, ValueError):
            return
        if opened in protected:
            state["attempted"] = True
            state["paths"].append(str(opened))
            raise PermissionError("v3.4 final catalog access is forbidden during policy validation")

    sys.addaudithook(audit)
    return state


def main() -> int:
    guard = install_final_guard()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    lineage = protocol["frozen_lineage"]
    if not protocol["registered_before_policy_validation"] or protocol["final_scenario_open_count"] != 0:
        raise AssertionError("v3.4 policy protocol is not cleanly preregistered")
    if sha256(CANDIDATE) != lineage["v3_candidate_sha256"]:
        raise AssertionError("frozen v3 candidate drifted")
    if sha256(V3_FINAL) != lineage["v3_final_scenario_sha256"]:
        raise AssertionError("opened v3 development catalog drifted")
    if sha256(DEPLOYED) != lineage["deployed_transition_sha256"]:
        raise AssertionError("deployed runtime-v2 transition drifted")

    deployed_before = {path.name: sha256(path) for path in (ENCODER, DEPLOYED, MANIFEST)}
    encoder = Encoder(ENCODER)
    models = {"baseline": TransitionModel(DEPLOYED), "candidate": TransitionModel(CANDIDATE)}
    v3_cases = json.loads(V3_FINAL.read_text(encoding="utf-8"))["cases"]
    legacy_cases = enrich_legacy_cases(json.loads(LEGACY_FIXTURE.read_text(encoding="utf-8")))
    v3 = incidents.evaluate_conditions(v3_cases, encoder, models)
    legacy = incidents.evaluate_conditions(legacy_cases, encoder, models)
    v3_metrics = v3["rules_v3_4_plus_jepa_candidate"]["metrics"]
    legacy_metrics = legacy["rules_v3_4_plus_jepa_candidate"]["metrics"]
    gates = {
        "v3_final_false_negative_zero": v3_metrics["confusion"]["false_negative"] == 0,
        "v3_final_false_positive_below_40": v3_metrics["confusion"]["false_positive"] < 40,
        "legacy_false_negative_below_50": legacy_metrics["confusion"]["false_negative"] < 50,
        "legacy_false_positive_at_most_41": legacy_metrics["confusion"]["false_positive"] <= 41,
        "legacy_balanced_accuracy_above_0_818": legacy_metrics["balanced_accuracy"] > 0.818,
    }
    deployed_after = {path.name: sha256(path) for path in (ENCODER, DEPLOYED, MANIFEST)}
    if deployed_after != deployed_before:
        raise AssertionError("deployed files changed during v3.4 validation")
    passed = all(gates.values()) and not guard["attempted"]
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "candidate_sha256": sha256(CANDIDATE),
        "development": {
            "v3_final_scenario_sha256": sha256(V3_FINAL),
            "legacy_fixture_sha256": sha256(LEGACY_FIXTURE),
            "v3_final_is_opened_development_for_v3_4": True,
        },
        "conditions": {
            "v3_opened_development": {
                "rules_v3_4": compact(v3["rules_v3_4"]["metrics"]),
                "rules_v3_4_plus_jepa_candidate": compact(v3_metrics),
            },
            "legacy_regression": {
                "rules_v3_4": compact(legacy["rules_v3_4"]["metrics"]),
                "rules_v3_4_plus_jepa_candidate": compact(legacy_metrics),
            },
        },
        "gates": gates,
        "validation_passed": passed,
        "new_final_catalog_access": {"opened": guard["attempted"], "attempted_paths": guard["paths"]},
        "deployment": {
            "attempted": False,
            "sha256_before": deployed_before,
            "sha256_after": deployed_after,
            "unchanged": True,
        },
        "claim_boundary": protocol["claim_boundary"],
    }
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "validation_passed": passed,
        "v3_opened_development": compact(v3_metrics),
        "legacy_regression": compact(legacy_metrics),
        "new_final_catalog_opened": guard["attempted"],
        "deployment_unchanged": True,
    }, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
