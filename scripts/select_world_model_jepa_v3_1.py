#!/usr/bin/env python3
"""Select the OS-JEPA v3.1 learned-risk threshold without opening its final catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_world_model_safety import Encoder, TransitionModel  # noqa: E402
import world_model_incident_scenarios as incidents  # noqa: E402


RESEARCH = ROOT / "docs" / "research"
PROTOCOL = RESEARCH / "world_model_jepa_v3_1_protocol.json"
V3_FINAL = RESEARCH / "world_model_incident_v3_final_catalog.json"
LEGACY_FIXTURE = RESEARCH / "world_model_safety_scenarios.json"
NEW_FINAL_SOURCES = RESEARCH / "world_model_incident_final_sources_v3_1.json"
NEW_FINAL_SCENARIOS = RESEARCH / "world_model_incident_v3_1_final_catalog.json"
ENCODER = ROOT / "appliance" / "world-model" / "model_encoder.bin"
DEPLOYED = ROOT / "appliance" / "world-model" / "model_learned.bin"
MANIFEST = ROOT / "appliance" / "world-model" / "manifest.json"
DEFAULT_CANDIDATE = ROOT / "target" / "world-model-v3-work" / "world_model_jepa_v3_candidate.bin"
DEFAULT_RESULT = RESEARCH / "world_model_jepa_v3_1_selection.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
            raise PermissionError("v3.1 final catalog access is forbidden during threshold selection")

    sys.addaudithook(audit)
    return state


def enrich_legacy_cases(document: dict) -> list[dict]:
    return [
        {
            **case,
            "source_id": "published-authored-fixture",
            "source_family": case["category"],
            "scenario_profile": case["category"],
        }
        for case in document["cases"]
    ]


def compact(metrics: dict) -> dict:
    return {
        "confusion": metrics["confusion"],
        "false_negative_rate": metrics["false_negative_rate"],
        "false_positive_rate": metrics["false_positive_rate"],
        "balanced_accuracy": metrics["balanced_accuracy"],
        "brier_score": metrics["brier_score"],
        "by_profile": metrics["by_profile"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    args = parser.parse_args()
    guard = install_final_guard()

    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if not protocol["registered_before_threshold_selection"]:
        raise AssertionError("threshold protocol was not preregistered")
    if protocol["final_scenario_open_count"] != 0:
        raise AssertionError("v3.1 final catalog was already opened")
    lineage = protocol["frozen_lineage"]
    if sha256(args.candidate) != lineage["v3_candidate_sha256"]:
        raise AssertionError("frozen v3 candidate drifted")
    if sha256(V3_FINAL) != lineage["v3_final_scenario_sha256"]:
        raise AssertionError("opened v3 development catalog drifted")
    if sha256(DEPLOYED) != lineage["deployed_transition_sha256"]:
        raise AssertionError("deployed runtime-v2 transition drifted")

    deployed_before = {path.name: sha256(path) for path in (ENCODER, DEPLOYED, MANIFEST)}
    encoder = Encoder(ENCODER)
    deployed_model = TransitionModel(DEPLOYED)
    candidate_model = TransitionModel(args.candidate)
    models = {"baseline": deployed_model, "candidate": candidate_model}
    v3_cases = json.loads(V3_FINAL.read_text(encoding="utf-8"))["cases"]
    legacy_cases = enrich_legacy_cases(json.loads(LEGACY_FIXTURE.read_text(encoding="utf-8")))

    rows = []
    for threshold in protocol["threshold_selection"]["grid"]:
        v3 = incidents.evaluate_conditions(
            v3_cases, encoder, models,
            learned_resource_threshold=float(threshold),
        )["rules_v3_plus_jepa_candidate"]["metrics"]
        legacy = incidents.evaluate_conditions(
            legacy_cases, encoder, models,
            learned_resource_threshold=float(threshold),
        )["rules_v3_plus_jepa_candidate"]["metrics"]
        gates = {
            "v3_final_false_negative_zero": v3["confusion"]["false_negative"] == 0,
            "v3_final_false_positive_at_most_40": v3["confusion"]["false_positive"] <= 40,
            "legacy_false_negative_below_50": legacy["confusion"]["false_negative"] < 50,
            "legacy_false_positive_at_most_41": legacy["confusion"]["false_positive"] <= 41,
            "legacy_balanced_accuracy_above_0_818": legacy["balanced_accuracy"] > 0.818,
        }
        rows.append({
            "threshold": float(threshold),
            "accepted": all(gates.values()),
            "gates": gates,
            "v3_opened_development": compact(v3),
            "legacy_regression": compact(legacy),
        })

    accepted = [index for index, row in enumerate(rows) if row["accepted"]]
    selected_index = None
    if accepted:
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
                rows[index]["threshold"],
            ),
        )

    deployed_after = {path.name: sha256(path) for path in (ENCODER, DEPLOYED, MANIFEST)}
    if deployed_after != deployed_before:
        raise AssertionError("deployed files changed during v3.1 selection")
    selection_passed = selected_index is not None and not guard["attempted"]
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "candidate_sha256": sha256(args.candidate),
        "development": {
            "v3_final_scenario_sha256": sha256(V3_FINAL),
            "legacy_fixture_sha256": sha256(LEGACY_FIXTURE),
            "v3_final_is_opened_development_for_v3_1": True,
        },
        "candidates": rows,
        "accepted_candidate_indices": accepted,
        "selected_candidate_index": selected_index,
        "selected_threshold": rows[selected_index]["threshold"] if selected_index is not None else None,
        "selection_passed": selection_passed,
        "new_final_catalog_access": {
            "opened": guard["attempted"],
            "attempted_paths": guard["paths"],
        },
        "deployment": {
            "attempted": False,
            "sha256_before": deployed_before,
            "sha256_after": deployed_after,
            "unchanged": True,
        },
        "claim_boundary": [
            "Only the learned cumulative-resource threshold was selected.",
            "The v3 transition weights and deterministic v3 predicates remained frozen.",
            "The v3 final catalog is development data for v3.1, not v3.1 final evidence.",
            "The v3.1 final source and scenario catalogs were not opened during selection."
        ],
    }
    args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "selection_passed": selection_passed,
        "candidates": len(rows),
        "accepted": len(accepted),
        "selected_candidate_index": selected_index,
        "selected_threshold": result["selected_threshold"],
        "new_final_catalog_opened": guard["attempted"],
        "deployment_unchanged": True,
    }, indent=2))
    return 0 if selection_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
