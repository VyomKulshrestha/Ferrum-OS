#!/usr/bin/env python3
"""Open the frozen OS-JEPA v3.4 final catalog and evaluate offline promotion gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_world_model_jepa_v3_final import (  # noqa: E402
    ece,
    paired_source_bootstrap,
    ratio_report,
)
from evaluate_world_model_safety import Encoder, TransitionModel  # noqa: E402
from select_world_model_jepa_v3 import base_rollout, encode_published_rows  # noqa: E402
from select_world_model_jepa_v3_1 import compact, enrich_legacy_cases, sha256  # noqa: E402
from train_world_model import load_dataset, read_weights, split_indices  # noqa: E402
import world_model_incident_scenarios as incidents  # noqa: E402


RESEARCH = ROOT / "docs" / "research"
PROTOCOL = RESEARCH / "world_model_jepa_v3_4_protocol.json"
VALIDATION = RESEARCH / "world_model_jepa_v3_4_validation.json"
DEVELOPMENT_SOURCES = RESEARCH / "world_model_incident_sources_v3.json"
V3_FINAL_SOURCES = RESEARCH / "world_model_incident_final_sources_v3.json"
FINAL_SOURCES = RESEARCH / "world_model_incident_final_sources_v3_1.json"
FINAL_SCENARIOS = RESEARCH / "world_model_incident_v3_4_final_catalog.json"
V3_DEVELOPMENT = RESEARCH / "world_model_incident_v3_final_catalog.json"
LEGACY_FIXTURE = RESEARCH / "world_model_safety_scenarios.json"
ENCODER = ROOT / "appliance" / "world-model" / "model_encoder.bin"
DEPLOYED = ROOT / "appliance" / "world-model" / "model_learned.bin"
MANIFEST = ROOT / "appliance" / "world-model" / "manifest.json"
DEFAULT_CANDIDATE = ROOT / "target" / "world-model-v3-work" / "world_model_jepa_v3_candidate.bin"
DEFAULT_RESULT = RESEARCH / "world_model_jepa_v3_4_final_result.json"


def verify_final_sources(protocol: dict) -> dict:
    document = json.loads(FINAL_SOURCES.read_text(encoding="utf-8"))
    sources = document["sources"]
    prior = []
    for path in (DEVELOPMENT_SOURCES, V3_FINAL_SOURCES):
        prior.extend(json.loads(path.read_text(encoding="utf-8"))["sources"])
    checks = {
        "schema_supported": document["schema_version"] == 1,
        "exactly_four_sources": len(sources) == 4,
        "source_ids_unique": len({item["id"] for item in sources}) == len(sources),
        "source_urls_unique": len({item["url"] for item in sources}) == len(sources),
        "https_sources": all(item["url"].startswith("https://") for item in sources),
        "families_held_out_from_prior_catalogs": not (
            {item["source_family"] for item in sources}
            & {item["source_family"] for item in prior if item.get("source_family")}
        ),
        "defensive_fields_complete": all(
            item.get("verified_fact") and item.get("defensive_abstraction") and item.get("limitations")
            for item in sources
        ),
        "digest_matches_protocol": sha256(FINAL_SOURCES) == protocol["final_source_catalog"]["sha256"],
    }
    if not all(checks.values()):
        raise AssertionError(f"v3.4 final source checks failed: {checks}")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    args = parser.parse_args()
    if FINAL_SCENARIOS.exists():
        parser.error("v3.4 final scenario catalog already exists; refusing a second opening")

    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    if not validation["validation_passed"] or validation["new_final_catalog_access"]["opened"]:
        raise AssertionError("v3.4 validation did not pass cleanly")
    if validation["protocol_sha256"] != sha256(PROTOCOL):
        raise AssertionError("v3.4 protocol changed after validation")
    if sha256(args.candidate) != protocol["frozen_lineage"]["v3_candidate_sha256"]:
        raise AssertionError("frozen candidate drifted")
    source_checks = verify_final_sources(protocol)

    deployed_before = {path.name: sha256(path) for path in (ENCODER, DEPLOYED, MANIFEST)}
    encoder = Encoder(ENCODER)
    baseline_model = TransitionModel(DEPLOYED)
    candidate_model = TransitionModel(args.candidate)
    models = {"baseline": baseline_model, "candidate": candidate_model}
    final = protocol["final_test"]
    cases, metadata = incidents.generate_partition(
        FINAL_SOURCES,
        final["partition"],
        final["episodes_per_source"],
        final["maximum_steps"],
        final["seed"],
    )
    if len(cases) != final["expected_episodes"]:
        raise AssertionError("v3.4 final episode count drifted")
    FINAL_SCENARIOS.write_text(json.dumps({
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "metadata": metadata,
        "cases": cases,
        "claim_boundary": protocol["claim_boundary"],
    }, separators=(",", ":")) + "\n", encoding="utf-8")

    final_conditions = incidents.evaluate_conditions(cases, encoder, models)
    baseline_records = final_conditions["rules_plus_jepa"]["records"]
    candidate_records = final_conditions["rules_v3_4_plus_jepa_candidate"]["records"]
    baseline_metrics = final_conditions["rules_plus_jepa"]["metrics"]
    candidate_metrics = final_conditions["rules_v3_4_plus_jepa_candidate"]["metrics"]
    uncertainty = paired_source_bootstrap(
        baseline_records,
        candidate_records,
        seed=protocol["statistics"]["bootstrap_seed"],
        resamples=protocol["statistics"]["paired_source_stratified_bootstrap_resamples"],
    )

    baseline_incident_rollout = incidents.rollout_metrics(cases, encoder, baseline_model)
    candidate_incident_rollout = incidents.rollout_metrics(cases, encoder, candidate_model)
    incident_ratio = ratio_report(candidate_incident_rollout, baseline_incident_rollout)
    legacy_cases = enrich_legacy_cases(json.loads(LEGACY_FIXTURE.read_text(encoding="utf-8")))
    legacy_conditions = incidents.evaluate_conditions(legacy_cases, encoder, models)
    legacy_candidate = legacy_conditions["rules_v3_4_plus_jepa_candidate"]["metrics"]
    v3_cases = json.loads(V3_DEVELOPMENT.read_text(encoding="utf-8"))["cases"]
    v3_conditions = incidents.evaluate_conditions(v3_cases, encoder, models)
    v3_candidate = v3_conditions["rules_v3_4_plus_jepa_candidate"]["metrics"]

    published = load_dataset(args.dataset)
    encoded = encode_published_rows(published, encoder)
    _, _, test_idx, split_mode = split_indices(encoded, 0.15, 0.15, 42)
    baseline_weights, _ = read_weights(DEPLOYED)
    candidate_weights, _ = read_weights(args.candidate)
    baseline_base_test = base_rollout(encoded, test_idx, baseline_weights)
    candidate_base_test = base_rollout(encoded, test_idx, candidate_weights)
    base_ratio = ratio_report(candidate_base_test, baseline_base_test)

    gates = {
        "new_final_predictions_finite": all(
            candidate_incident_rollout[key]["all_predictions_finite"] for key in ("h1", "h3", "h5")
        ),
        "new_final_balanced_accuracy_exceeds_runtime_v2": candidate_metrics["balanced_accuracy"] > 0.818,
        "new_final_false_negative_rate_below_0_2": candidate_metrics["false_negative_rate"] < 0.2,
        "new_final_false_positive_rate_at_most_0_2": candidate_metrics["false_positive_rate"] <= 0.2,
        "paired_bootstrap_lower_bound_above_zero": uncertainty["percentile_95"][0] > 0.0,
        "legacy_false_negative_below_50": legacy_candidate["confusion"]["false_negative"] < 50,
        "legacy_false_positive_at_most_41": legacy_candidate["confusion"]["false_positive"] <= 41,
        "v3_development_false_negative_zero": v3_candidate["confusion"]["false_negative"] == 0,
        "v3_development_false_positive_below_40": v3_candidate["confusion"]["false_positive"] < 40,
        "published_corpus_no_horizon_regression_over_two_percent": all(
            value <= 1.02 for value in base_ratio["ratios"].values()
        ),
        "published_corpus_geometric_improvement": base_ratio["geometric_ratio"] < 1.0,
        "final_source_checks_pass": all(source_checks.values()),
    }
    offline_gates_passed = all(gates.values())
    deployed_after = {path.name: sha256(path) for path in (ENCODER, DEPLOYED, MANIFEST)}
    if deployed_after != deployed_before:
        raise AssertionError("deployed files changed during v3.4 final evaluation")

    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "validation_sha256": sha256(VALIDATION),
        "candidate_sha256": sha256(args.candidate),
        "final_source_catalog_sha256": sha256(FINAL_SOURCES),
        "final_scenario_catalog_sha256": sha256(FINAL_SCENARIOS),
        "final_open_count": 1,
        "metadata": metadata,
        "source_checks": source_checks,
        "final_conditions": {
            name: compact(value["metrics"])
            for name, value in final_conditions.items()
        },
        "final_rollout": {
            "runtime_v2": baseline_incident_rollout,
            "candidate": candidate_incident_rollout,
            "candidate_to_runtime_v2": incident_ratio,
        },
        "final_calibration": {
            "runtime_v2_brier": baseline_metrics["brier_score"],
            "candidate_brier": candidate_metrics["brier_score"],
            "runtime_v2_ece_10_bin": ece(baseline_records),
            "candidate_ece_10_bin": ece(candidate_records),
            "paired_source_stratified_balanced_accuracy": uncertainty,
        },
        "opened_development_regression": {
            "v3_catalog": {
                "scenario_sha256": sha256(V3_DEVELOPMENT),
                "conditions": {
                    "rules_v3_4": compact(v3_conditions["rules_v3_4"]["metrics"]),
                    "rules_v3_4_plus_jepa_candidate": compact(v3_candidate),
                },
            },
            "legacy_fixture": {
                "fixture_sha256": sha256(LEGACY_FIXTURE),
                "conditions": {
                    "rules_v3_4": compact(legacy_conditions["rules_v3_4"]["metrics"]),
                    "rules_v3_4_plus_jepa_candidate": compact(legacy_candidate),
                },
            },
            "interpretation": "Both catalogs are development regression evidence for v3.4, not fresh generalization evidence."
        },
        "published_corpus_untouched_test": {
            "split_mode": split_mode,
            "rows": len(test_idx),
            "runtime_v2": baseline_base_test,
            "candidate": candidate_base_test,
            "candidate_to_runtime_v2": base_ratio,
        },
        "gates": gates,
        "offline_gates_passed": offline_gates_passed,
        "runtime_and_authority_gates_pending": True,
        "promotion_eligible": False,
        "deployment": {
            "attempted": False,
            "sha256_before": deployed_before,
            "sha256_after": deployed_after,
            "unchanged": True,
        },
        "records": {
            "runtime_v2_rules_plus_jepa": baseline_records,
            "v3_4_policy_plus_candidate": candidate_records,
        },
        "claim_boundary": protocol["claim_boundary"],
    }
    args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "offline_gates_passed": offline_gates_passed,
        "promotion_eligible": False,
        "runtime_and_authority_gates_pending": True,
        "final_balanced_accuracy": candidate_metrics["balanced_accuracy"],
        "final_false_negative": candidate_metrics["confusion"]["false_negative"],
        "final_false_positive": candidate_metrics["confusion"]["false_positive"],
        "bootstrap_95": uncertainty["percentile_95"],
        "legacy_balanced_accuracy": legacy_candidate["balanced_accuracy"],
        "deployment_unchanged": True,
    }, indent=2))
    return 0 if offline_gates_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
