#!/usr/bin/env python3
"""Select the OS-JEPA v3.2 learned disk threshold without opening its final catalog."""

from __future__ import annotations

import argparse
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
PROTOCOL = RESEARCH / "world_model_jepa_v3_2_protocol.json"
V3_FINAL = RESEARCH / "world_model_incident_v3_final_catalog.json"
LEGACY_FIXTURE = RESEARCH / "world_model_safety_scenarios.json"
NEW_FINAL_SOURCES = RESEARCH / "world_model_incident_final_sources_v3_1.json"
NEW_FINAL_SCENARIOS = RESEARCH / "world_model_incident_v3_2_final_catalog.json"
ENCODER = ROOT / "appliance" / "world-model" / "model_encoder.bin"
DEPLOYED = ROOT / "appliance" / "world-model" / "model_learned.bin"
MANIFEST = ROOT / "appliance" / "world-model" / "manifest.json"
DEFAULT_CANDIDATE = ROOT / "target" / "world-model-v3-work" / "world_model_jepa_v3_candidate.bin"
DEFAULT_RESULT = RESEARCH / "world_model_jepa_v3_2_selection.json"


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
            raise PermissionError("v3.2 final catalog access is forbidden during threshold selection")

    sys.addaudithook(audit)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    args = parser.parse_args()
    guard = install_final_guard()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    lineage = protocol["frozen_lineage"]
    if not protocol["registered_before_threshold_selection"] or protocol["final_scenario_open_count"] != 0:
        raise AssertionError("v3.2 threshold protocol is not cleanly preregistered")
    if sha256(args.candidate) != lineage["v3_candidate_sha256"]:
        raise AssertionError("frozen v3 candidate drifted")
    if sha256(V3_FINAL) != lineage["v3_final_scenario_sha256"]:
        raise AssertionError("opened v3 development catalog drifted")
    if sha256(DEPLOYED) != lineage["deployed_transition_sha256"]:
        raise AssertionError("deployed runtime-v2 transition drifted")

    deployed_before = {path.name: sha256(path) for path in (ENCODER, DEPLOYED, MANIFEST)}
    encoder = Encoder(ENCODER)
    models = {"baseline": TransitionModel(DEPLOYED), "candidate": TransitionModel(args.candidate)}
    v3_cases = json.loads(V3_FINAL.read_text(encoding="utf-8"))["cases"]
    legacy_cases = enrich_legacy_cases(json.loads(LEGACY_FIXTURE.read_text(encoding="utf-8")))
    rows = []
    for threshold in protocol["threshold_selection"]["grid"]:
        values = []
        for cases in (v3_cases, legacy_cases):
            values.append(incidents.evaluate_conditions(
                cases,
                encoder,
                models,
                learned_resource_threshold=protocol["frozen_policy"]["learned_heap_threshold"],
                learned_disk_threshold=float(threshold),
            )["rules_v3_plus_jepa_candidate"]["metrics"])
        v3, legacy = values
        gates = {
            "v3_final_false_negative_zero": v3["confusion"]["false_negative"] == 0,
            "v3_final_false_positive_at_most_40": v3["confusion"]["false_positive"] <= 40,
            "legacy_false_negative_below_50": legacy["confusion"]["false_negative"] < 50,
            "legacy_false_positive_at_most_41": legacy["confusion"]["false_positive"] <= 41,
            "legacy_balanced_accuracy_above_0_818": legacy["balanced_accuracy"] > 0.818,
        }
        rows.append({
            "learned_disk_threshold": float(threshold),
            "accepted": all(gates.values()),
            "gates": gates,
            "v3_opened_development": compact(v3),
            "legacy_regression": compact(legacy),
        })

    accepted = [index for index, row in enumerate(rows) if row["accepted"]]
    selected_index = min(
        accepted,
        key=lambda index: (
            rows[index]["v3_opened_development"]["confusion"]["false_positive"]
            + rows[index]["legacy_regression"]["confusion"]["false_positive"],
            rows[index]["v3_opened_development"]["confusion"]["false_negative"]
            + rows[index]["legacy_regression"]["confusion"]["false_negative"],
            -0.5 * (
                rows[index]["v3_opened_development"]["balanced_accuracy"]
                + rows[index]["legacy_regression"]["balanced_accuracy"]
            ),
            rows[index]["learned_disk_threshold"],
        ),
    ) if accepted else None
    deployed_after = {path.name: sha256(path) for path in (ENCODER, DEPLOYED, MANIFEST)}
    if deployed_after != deployed_before:
        raise AssertionError("deployed files changed during v3.2 selection")
    passed = selected_index is not None and not guard["attempted"]
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "candidate_sha256": sha256(args.candidate),
        "development": {
            "v3_final_scenario_sha256": sha256(V3_FINAL),
            "legacy_fixture_sha256": sha256(LEGACY_FIXTURE),
            "v3_final_is_opened_development_for_v3_2": True,
        },
        "candidates": rows,
        "accepted_candidate_indices": accepted,
        "selected_candidate_index": selected_index,
        "selected_learned_disk_threshold": rows[selected_index]["learned_disk_threshold"] if selected_index is not None else None,
        "selection_passed": passed,
        "new_final_catalog_access": {"opened": guard["attempted"], "attempted_paths": guard["paths"]},
        "deployment": {
            "attempted": False,
            "sha256_before": deployed_before,
            "sha256_after": deployed_after,
            "unchanged": True,
        },
        "claim_boundary": [
            "Only the learned disk threshold was selected.",
            "Transition weights, learned heap threshold, and deterministic predicates remained frozen.",
            "The v3 final catalog is development data for v3.2, not v3.2 final evidence.",
            "The v3.2 final source and scenario catalogs were not opened during selection."
        ],
    }
    args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "selection_passed": passed,
        "candidates": len(rows),
        "accepted": len(accepted),
        "selected_candidate_index": selected_index,
        "selected_learned_disk_threshold": result["selected_learned_disk_threshold"],
        "new_final_catalog_opened": guard["attempted"],
        "deployment_unchanged": True,
    }, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
