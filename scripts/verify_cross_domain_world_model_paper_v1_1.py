#!/usr/bin/env python3
"""Verify and freeze Prediction Is Not Permission Technical Report v1.1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pdfplumber
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "docs/research/paper/prediction_is_not_permission_technical_report_v1_1.md"
)
PDF = (
    ROOT / "docs/research/paper/Prediction_Is_Not_Permission_Technical_Report_v1.1.pdf"
)
UMBRELLA = (
    ROOT / "docs/research/cross_domain_world_model_improvement_verification_v1.json"
)
EXTERNAL_RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_result_v14.json"
EXTERNAL_VERIFICATION = (
    ROOT / "docs/research/physical_jepa_safety_gymnasium_verification_v14.json"
)
PAIRED_RESULT = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_paired_uncertainty_result_v1.json"
)
PAIRED_VERIFICATION = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_paired_uncertainty_verification_v1.json"
)
ATTRIBUTION_RESULT = (
    ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_result_v2.json"
)
ATTRIBUTION_VERIFICATION = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_attribution_verification_v2.json"
)
POSTHOC_RESULT = (
    ROOT / "docs/research/cross_domain_world_model_posthoc_sensitivity_result_v1.json"
)
POSTHOC_VERIFICATION = (
    ROOT
    / "docs/research/cross_domain_world_model_posthoc_sensitivity_verification_v1.json"
)
AUTHORITY_TEST_INVENTORY = (
    ROOT / "docs/research/cross_domain_authority_test_inventory_v1.json"
)
LEARNED_CONTRIBUTION = (
    ROOT / "docs/research/cross_domain_learned_contribution_result_v1.json"
)
FIGURE_DIR = ROOT / "docs/research/figures/cross_domain_world_model"
FIGURES = [
    FIGURE_DIR / "authority_factorization.png",
    FIGURE_DIR / "matched_rollout_results.png",
    FIGURE_DIR / "evidence_ladder.png",
    FIGURE_DIR / "causal_vs_operational.png",
]
FREEZE = ROOT / "docs/research/cross_domain_world_model_paper_freeze_v1_1.json"
RESULT = ROOT / "docs/research/cross_domain_world_model_paper_verification_v1_1.json"

TITLE = "Prediction Is Not Permission: Cross-Domain World Models Under Deterministic Runtime Authority"
REQUIRED_SOURCE_PHRASES = [
    "Technical Report v1.1 — 8 September 2026",
    "The primary contribution is an evaluation method, not a new JEPA objective.",
    "same six evidence objects named in the abstract",
    "not strictly compute-controlled",
    "GRU-minus-JEPA at H=3 is -0.004439 [-0.005735, -0.003203]",
    "registered post-hoc common-episode sensitivity",
    "registered ranking reversal cannot be isolated as a horizon effect",
    "constant-prevalence predictor has Brier 0.25",
    "Prospective Safety-Gymnasium controller and shield benchmark",
    "Warning recall and warning FPR evaluate the detector",
    "intervention rate counts only commands that actually change",
    "nominal receding-horizon controller",
    "The union passes every registered joint-objective gate relative to the frozen benchmark criteria",
    "these gates do not require superiority over the privileged planner",
    "effective action-change recall",
    "effective action-change recall is 55.00%",
    "Executed intervention precision is 23.04% (88/382)",
    "294 of 382 changed commands occur on oracle-labelled non-dangerous trajectories",
    "`rule_block` is false in all 1,024 records by construction of this estimand",
    "thresholded latent-hazard coverage negative",
    "false-negative rate is 256/256",
    "1.478%",
    "| Naive unshielded | 100.00% | 0.00% | — | — | 0.00% | 542 |",
    "| Planner unshielded | 94.53% | 0.00% | — | — | 0.00% | **70** |",
    "not learned collision-avoidance superiority over privileged planning",
    "completion/cost tradeoff over the planner",
    "paired 10,000-resample episode-bootstrap 95% CI",
    "Neither interval excludes zero",
    "descriptive rather than statistically stable",
    "no independent replication is claimed",
    "Frozen risk-source attribution on fresh layouts",
    "The v2 attribution opens seeds 8000-8127 once",
    "not the uniquely designated primary contrast",
    "Bonferroni-adjusted 98.33% interval",
    "Every one of 128 leave-one-seed-out 95% intervals",
    "no statistically resolved difference and is not a non-inferiority result",
    "The original warning metrics are on-policy",
    "identical 23,815-proposal catalog",
    "Validation FPR",
    "exploratory pipeline-level evidence",
    "physical permit unit tests do not establish FerrumOS syscall-path enforcement",
    "Python 3.12.6, NumPy 2.2.6, and PyTorch 2.6.0+cu124",
    "Hashes prove byte identity only",
    "Validation means checking an existing record",
    "protected artifacts remain byte-identical, and promotion eligibility is false",
    "Revisiting Feature Prediction for Learning Visual Representations from Video",
    "Safety-Gymnasium: A Unified Safe Reinforcement Learning Benchmark",
    "Appendix A. Claim-to-evidence ledger",
    "Appendix B. Frozen-gate and artifact audit",
    "Appendix C. Artifact locator",
]
REQUIRED_PDF_PHRASES = [
    "Prediction Is Not Permission",
    "Vyom Kulshrestha",
    "ORCID: 0009-0009-1434-7148",
    "Technical Report v1.1",
    "Architecture-controlled results",
    "Safety-Gymnasium controller and shield benchmark",
    "Threats to validity and limitations",
    "Claim-to-evidence ledger",
    "Frozen-gate and artifact audit",
    "Artifact locator",
    "Frozen risk-source attribution on fresh layouts",
    "Neither interval excludes zero",
    "Bonferroni-adjusted 98.33% interval",
    "common-episode sensitivity",
    "Validation FPR",
    "References",
]
FORBIDDEN_PATTERNS = [
    r"\bTODO\b",
    r"\bTBD\b",
    r"reviewer-requested",
    r"requested by the present review",
    r"independently executed third-party",
    r"opposite unusable extreme",
    r"Submission candidate",
    r"safety recall",
    r"The union passes every registered gate",
    r"The later Safety-Gymnasium families also sit outside",
    r"missed population rate is 1\.478%",
    r"holds compute and data constant",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def normalize_cell(value: str | None) -> str:
    normalized = " ".join((value or "").split())
    if ".json" in normalized:
        return normalized.replace(" ", "")
    return normalized


def pdf_table_rows() -> dict[int, set[tuple[str, ...]]]:
    rows: dict[int, set[tuple[str, ...]]] = {}
    with pdfplumber.open(PDF) as document:
        for page_number, page in enumerate(document.pages, start=1):
            page_rows: set[tuple[str, ...]] = set()
            for table in page.extract_tables():
                page_rows.update(
                    tuple(normalize_cell(cell) for cell in row) for row in table
                )
            rows[page_number] = page_rows
    return rows


def main() -> None:
    required_paths = [
        SOURCE,
        PDF,
        UMBRELLA,
        EXTERNAL_RESULT,
        EXTERNAL_VERIFICATION,
        PAIRED_RESULT,
        PAIRED_VERIFICATION,
        ATTRIBUTION_RESULT,
        ATTRIBUTION_VERIFICATION,
        POSTHOC_RESULT,
        POSTHOC_VERIFICATION,
        AUTHORITY_TEST_INVENTORY,
        LEARNED_CONTRIBUTION,
        *FIGURES,
    ]
    missing = [rel(path) for path in required_paths if not path.is_file()]
    if missing:
        raise SystemExit(f"missing required paper artifacts: {missing}")
    source_text = SOURCE.read_text(encoding="utf-8")
    umbrella = json.loads(UMBRELLA.read_text(encoding="utf-8"))
    external = json.loads(EXTERNAL_RESULT.read_text(encoding="utf-8"))
    external_verification = json.loads(
        EXTERNAL_VERIFICATION.read_text(encoding="utf-8")
    )
    paired = json.loads(PAIRED_RESULT.read_text(encoding="utf-8"))
    paired_verification = json.loads(PAIRED_VERIFICATION.read_text(encoding="utf-8"))
    attribution = json.loads(ATTRIBUTION_RESULT.read_text(encoding="utf-8"))
    attribution_verification = json.loads(
        ATTRIBUTION_VERIFICATION.read_text(encoding="utf-8")
    )
    posthoc = json.loads(POSTHOC_RESULT.read_text(encoding="utf-8"))
    posthoc_verification = json.loads(POSTHOC_VERIFICATION.read_text(encoding="utf-8"))
    authority_inventory = json.loads(AUTHORITY_TEST_INVENTORY.read_text(encoding="utf-8"))
    learned_contribution = json.loads(LEARNED_CONTRIBUTION.read_text(encoding="utf-8"))
    reader = PdfReader(str(PDF))
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    metadata = reader.metadata
    source_required = {
        phrase: phrase in source_text for phrase in REQUIRED_SOURCE_PHRASES
    }
    pdf_required = {phrase: phrase in pdf_text for phrase in REQUIRED_PDF_PHRASES}
    forbidden_absent = {
        pattern: re.search(pattern, source_text, flags=re.IGNORECASE) is None
        for pattern in FORBIDDEN_PATTERNS
    }
    umbrella_checks = umbrella.get("checks", {})
    protected = umbrella.get("protected_deployed_artifacts", {})
    union = external["arms"]["planner_rules_plus_learned"]["metrics"]
    intervention_precision = (
        union["true_positive_interventions"] / union["interventions"]
    )
    expected_families = {
        "ferrumos": {
            "delayed_heap_pressure",
            "delayed_process_pressure",
            "coupled_resource_pressure",
            "exogenous_heap_degradation",
        },
        "physical": {
            "delayed_battery_depletion",
            "delayed_boundary_crossing",
            "sensor_masked_human_approach",
            "link_degradation",
        },
    }
    learned_records = {
        domain: learned_contribution["domains"][domain]["case_records"]
        for domain in expected_families
    }
    table_rows = pdf_table_rows()
    all_table_rows = set().union(*table_rows.values())
    checks = {
        "source_required_phrases_present": all(source_required.values()),
        "pdf_required_phrases_present": all(pdf_required.values()),
        "forbidden_placeholders_and_review_wording_absent": all(
            forbidden_absent.values()
        ),
        "pdf_page_count_is_submission_length": 14 <= len(reader.pages) <= 20,
        "pdf_title_exact": metadata.title == TITLE,
        "pdf_author_exact": metadata.author == "Vyom Kulshrestha",
        "pdf_subject_versioned": metadata.subject
        == "Cross-domain world-model runtime authority Technical Report v1.1",
        "pdf_has_no_replacement_character": "\ufffd" not in pdf_text,
        "all_figures_nonempty": all(path.stat().st_size > 10_000 for path in FIGURES),
        "external_frozen_pass_recomputes": external["all_frozen_gates_pass"] is True
        and all(external["frozen_gates"].values())
        and external["final_seed_access_count"] == 1,
        "external_result_effective_and_attributed": union["learned_only_interventions"]
        > 0
        and external["selected_candidate"]["count_only_effective_interventions"] is True
        and external["selected_candidate"]["learned_requires_rule_confirmation"]
        is False
        and union["warning_recall"] > union["effective_intervention_recall"]
        and union["actual_hazard_cost_events"]
        > external["arms"]["planner_unshielded"]["metrics"][
            "actual_hazard_cost_events"
        ],
        "intervention_precision_recomputed": union["interventions"] == 382
        and union["true_positive_interventions"] == 88
        and union["false_positive_interventions"] == 294
        and abs(intervention_precision - 0.23036649214659685) < 1e-15,
        "delayed_hazard_construct_coverage_recomputed": learned_contribution[
            "evaluation_passed"
        ]
        is True
        and learned_contribution["final_open_count"] == 1
        and all(
            len(learned_records[domain]) == 512
            and {row["family"] for row in learned_records[domain]} == families
            and all(row["rule_block"] is False for row in learned_records[domain])
            for domain, families in expected_families.items()
        ),
        "wrapped_pdf_table_cells_positionally_correct": (
            (
                "Physical",
                "Action-conditioned JEPA",
                "93.36%",
                "0.016819",
                "0.026772",
                "0.046361",
            )
            in all_table_rows
            and (
                "Naive unshielded",
                "100.00%",
                "0.00%",
                "-",
                "-",
                "0.00%",
                "542",
            )
            in all_table_rows
            and (
                "Planner unshielded",
                "94.53%",
                "0.00%",
                "-",
                "-",
                "0.00%",
                "70",
            )
            in all_table_rows
            and (
                "External physical streams can be replayed",
                "284,398 HAI transitions",
                "Fault-condition error and event diagnostics",
                "Not live Ferrum HIL or physical recovery",
            )
            in all_table_rows
            and (
                "3D geometry/contact stress is exercised",
                "288 local PyBullet DIRECT cases",
                "Contact and simulated recovery are measured",
                "Not practical learned safety at 100% intervention",
            )
            in all_table_rows
            and (
                "External useful-autonomy test",
                "Runtime lock, dev/final seeds, candidates, five arms, joint gates",
                "One untouched final opening; raw union rows and all arms independently recompute",
                "Safety-Gymnasium DIRECT; privileged planner; actuator authority zero",
            )
            in all_table_rows
            and (
                "Paired planner-union uncertainty",
                "docs/research/physical_jepa_safety_gymnasium_paired_uncertainty_result_v1.json",
                "Recompute seed-matched completion and realized hazard-cost difference intervals",
            )
            in all_table_rows
            and (
                "JEPA outputs only",
                "96.09%",
                "20.25%",
                "1.35%",
                "15.00%",
                "104",
                "7/128",
                "184.9",
            )
            in all_table_rows
            and (
                "JEPA outputs only",
                "0.43%",
                "57.81%",
                "2.66%",
                "51.71%",
                "2.90%",
            )
            in all_table_rows
            and (
                "Physical permit and disabled driver",
                "Host unit",
                "cross_domain_authority_test_inventory_v1.json:128/128",
                "Simulator/offline adapter only; physical actuator unavailable",
            )
            in all_table_rows
        ),
        "external_verification_confirms_all_gates": external_verification[
            "overall_pass"
        ]
        is True
        and all(external_verification["checks"].values()),
        "paired_planner_union_uncertainty_verified": paired_verification["overall_pass"]
        is True
        and all(paired_verification["checks"].values())
        and paired["pairing"]["episodes"] == 128
        and paired["differences_union_minus_planner"][
            "completion_rate_percentage_points"
        ]["estimate"]
        == 1.5625
        and paired["differences_union_minus_planner"]["realized_hazard_cost_steps"][
            "estimate"
        ]
        == 14.0
        and paired["differences_union_minus_planner"][
            "completion_rate_percentage_points"
        ]["interval_excludes_zero"]
        is False
        and paired["differences_union_minus_planner"]["realized_hazard_cost_steps"][
            "interval_excludes_zero"
        ]
        is False,
        "risk_source_attribution_verified": attribution_verification[
            "all_checks_pass"
        ]
        is True
        and all(attribution_verification["checks"].values())
        and attribution["final_seed_access_count"] == 1
        and attribution["final_seed_range"] == {"start": 8000, "count": 128}
        and attribution["variants"]["jepa-outputs-only"]["aggregate"][
            "actual_hazard_cost_events"
        ]
        == 104
        and attribution["variants"]["jepa-outputs-only"][
            "versus_full_adapter_paired_bootstrap"
        ]["actual_hazard_cost_steps"]["estimate"]
        == -25.0
        and attribution["variants"]["jepa-outputs-only"][
            "versus_full_adapter_paired_bootstrap"
        ]["actual_hazard_cost_steps"]["interval_excludes_zero"]
        is True
        and attribution["variants"]["jepa-outputs-only"][
            "versus_full_adapter_paired_bootstrap"
        ]["intervention_percentage_points"]["interval_excludes_zero"]
        is True
        and attribution["variants"]["jepa-outputs-only"][
            "versus_planner_paired_bootstrap"
        ]["actual_hazard_cost_steps"]["interval_excludes_zero"]
        is False,
        "risk_source_attribution_authority_disabled": attribution["authority"][
            "physical_actuator_attempts"
        ]
        == 0
        and attribution["authority"]["physical_actuator_deliveries"] == 0
        and attribution["authority"]["promotion_eligible"] is False
        and attribution["authority"]["protected_deployed_artifact_unchanged"]
        is True,
        "posthoc_sensitivity_recomputes_and_is_nonpromotable": posthoc_verification[
            "all_checks_pass"
        ]
        is True
        and all(posthoc_verification["checks"].values())
        and posthoc["authority"]["simulator_executed"] is False
        and posthoc["authority"]["models_or_adapters_retrained"] is False
        and posthoc["authority"]["promotion_eligible"] is False,
        "common_episode_horizon_confound_is_measured": posthoc[
            "common_episode_horizon_analysis"
        ]["domains"]["ferrumos"]["common_episode_count"]
        == 238
        and posthoc["common_episode_horizon_analysis"]["domains"]["ferrumos"][
            "methods"
        ]["action_conditioned_jepa"]["rollout"]["h1"]["ensemble"]["estimate"]
        < posthoc["common_episode_horizon_analysis"]["domains"]["ferrumos"][
            "methods"
        ]["gru_dynamics"]["rollout"]["h1"]["ensemble"]["estimate"]
        and posthoc["common_episode_horizon_analysis"]["domains"]["ferrumos"][
            "paired_architecture_comparisons"
        ]["action_conditioned_jepa_minus_gru_dynamics"]["h3"][
            "interval_excludes_zero"
        ]
        is True,
        "attribution_multiplicity_and_influence_checks_pass": posthoc[
            "attribution_diagnostics"
        ]["comparisons"]["jepa-outputs-only_minus_full"][
            "bonferroni_98_333333_percent"
        ]["hazard_steps"]["percentile_interval"]
        == [-57.0, -3.0]
        and posthoc["attribution_diagnostics"]["comparisons"][
            "jepa-outputs-only_minus_full"
        ]["bonferroni_98_333333_percent"]["intervention_percentage_points"][
            "interval_excludes_zero"
        ]
        is True
        and posthoc["attribution_diagnostics"][
            "jepa_outputs_only_minus_full_leave_one_out"
        ]["all_hazard_intervals_exclude_zero"]
        is True
        and posthoc["attribution_diagnostics"][
            "jepa_outputs_only_minus_full_leave_one_out"
        ]["all_intervention_intervals_exclude_zero"]
        is True,
        "common_proposal_warning_comparison_is_reproduced": all(
            posthoc["attribution_diagnostics"]["common_proposal_warning_analysis"][
                "full_adapter_source_arm_reproduced"
            ].values()
        )
        and posthoc["attribution_diagnostics"]["common_proposal_warning_analysis"][
            "catalog_rows"
        ]
        == 23815
        and abs(
            posthoc["attribution_diagnostics"]["common_proposal_warning_analysis"][
                "variants"
            ]["jepa-outputs-only"]["warning_recall"]
            - 0.5171102661596958
        )
        < 1e-15,
        "authority_test_inventory_passes_with_scoped_execution": authority_inventory[
            "all_checks_pass"
        ]
        is True
        and authority_inventory["fresh_test_runs"]["neural_protocol"]["passed"]
        is True
        and authority_inventory["fresh_test_runs"]["physical_daemon"]["passed"]
        is True
        and any(
            item["component"] == "physical runtime permit and actuator-disabled driver"
            and item["test_class"] == "host unit test"
            and item["execution_available"] is False
            for item in authority_inventory["components"]
        ),
        "external_scope_and_nonpromotion_honest": external["independent_execution"]
        is False
        and external["physical_actuator_attempts"] == 0
        and external["physical_actuator_deliveries"] == 0
        and external["promotion_eligible"] is False,
        "umbrella_all_checks_pass": bool(umbrella_checks)
        and all(umbrella_checks.values()),
        "umbrella_binds_external_verification": umbrella.get("headline", {}).get(
            "physical_safety_gymnasium_frozen_pass_verified"
        )
        is True,
        "umbrella_promotion_ineligible": umbrella.get("promotion_eligible") is False,
        "protected_deployed_artifacts_unchanged": bool(protected)
        and all(
            item.get("unchanged") is True
            and item.get("expected_sha256") == item.get("observed_sha256")
            for item in protected.values()
        ),
    }
    freeze = {
        "schema": "cross-domain-world-model-paper-freeze-v1-1",
        "report_version": "1.1",
        "evidence_frozen_date": "2026-09-08",
        "title": TITLE,
        "author": "Vyom Kulshrestha",
        "orcid": "0009-0009-1434-7148",
        "artifacts": {
            "manuscript": {"path": rel(SOURCE), "sha256": sha256(SOURCE)},
            "pdf": {
                "path": rel(PDF),
                "sha256": sha256(PDF),
                "pages": len(reader.pages),
            },
            "figures": [
                {
                    "path": rel(path),
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
                for path in FIGURES
            ],
            "evidence_snapshot": {"path": rel(UMBRELLA), "sha256": sha256(UMBRELLA)},
            "external_result": {
                "path": rel(EXTERNAL_RESULT),
                "sha256": sha256(EXTERNAL_RESULT),
            },
            "external_verification": {
                "path": rel(EXTERNAL_VERIFICATION),
                "sha256": sha256(EXTERNAL_VERIFICATION),
            },
            "paired_uncertainty_result": {
                "path": rel(PAIRED_RESULT),
                "sha256": sha256(PAIRED_RESULT),
            },
            "paired_uncertainty_verification": {
                "path": rel(PAIRED_VERIFICATION),
                "sha256": sha256(PAIRED_VERIFICATION),
            },
            "risk_source_attribution_result": {
                "path": rel(ATTRIBUTION_RESULT),
                "sha256": sha256(ATTRIBUTION_RESULT),
            },
            "risk_source_attribution_verification": {
                "path": rel(ATTRIBUTION_VERIFICATION),
                "sha256": sha256(ATTRIBUTION_VERIFICATION),
            },
            "posthoc_sensitivity_result": {
                "path": rel(POSTHOC_RESULT),
                "sha256": sha256(POSTHOC_RESULT),
            },
            "posthoc_sensitivity_verification": {
                "path": rel(POSTHOC_VERIFICATION),
                "sha256": sha256(POSTHOC_VERIFICATION),
            },
            "authority_test_inventory": {
                "path": rel(AUTHORITY_TEST_INVENTORY),
                "sha256": sha256(AUTHORITY_TEST_INVENTORY),
            },
        },
        "claim_boundary": umbrella.get("claim_boundary", [])
        + [
            "The registered FerrumOS horizon populations differ; the common-episode post-hoc sensitivity changes the ranking, so the registered reversal is not isolated as a horizon effect.",
            "The original attribution warning metrics are on-policy. The common-proposal sensitivity fixes inputs to the full-arm visited-state catalog and is not an independent detector sample.",
            "JEPA-only versus full was one prospectively specified family member, not a unique primary contrast. Adjusted and leave-one-out intervals support an exploratory pipeline result, not preserved completion or architecture-only causality.",
            "Authority tests distinguish host unit, host integration, and QEMU in-guest coverage; physical permit unit tests do not establish FerrumOS syscall-path enforcement.",
        ],
        "promotion_eligible": False,
        "protected_deployed_artifacts": protected,
    }
    FREEZE.write_text(
        json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    overall_pass = all(checks.values())
    result = {
        "schema": "cross-domain-world-model-paper-verification-v1-1",
        "report_version": "1.1",
        "overall_pass": overall_pass,
        "checks": checks,
        "diagnostics": {
            "source_required_phrases": source_required,
            "pdf_required_phrases": pdf_required,
            "forbidden_patterns_absent": forbidden_absent,
            "pdf_pages": len(reader.pages),
            "pdf_words_extracted": len(pdf_text.split()),
            "positionally_checked_pdf_table_pages": sorted(table_rows),
            "freeze_manifest_sha256": sha256(FREEZE),
        },
        "artifacts": {
            "manuscript": {"path": rel(SOURCE), "sha256": sha256(SOURCE)},
            "pdf": {"path": rel(PDF), "sha256": sha256(PDF)},
            "freeze_manifest": {"path": rel(FREEZE), "sha256": sha256(FREEZE)},
            "evidence_snapshot": {"path": rel(UMBRELLA), "sha256": sha256(UMBRELLA)},
            "paired_uncertainty_result": {
                "path": rel(PAIRED_RESULT),
                "sha256": sha256(PAIRED_RESULT),
            },
            "paired_uncertainty_verification": {
                "path": rel(PAIRED_VERIFICATION),
                "sha256": sha256(PAIRED_VERIFICATION),
            },
            "risk_source_attribution_result": {
                "path": rel(ATTRIBUTION_RESULT),
                "sha256": sha256(ATTRIBUTION_RESULT),
            },
            "risk_source_attribution_verification": {
                "path": rel(ATTRIBUTION_VERIFICATION),
                "sha256": sha256(ATTRIBUTION_VERIFICATION),
            },
            "posthoc_sensitivity_result": {
                "path": rel(POSTHOC_RESULT),
                "sha256": sha256(POSTHOC_RESULT),
            },
            "posthoc_sensitivity_verification": {
                "path": rel(POSTHOC_VERIFICATION),
                "sha256": sha256(POSTHOC_VERIFICATION),
            },
            "authority_test_inventory": {
                "path": rel(AUTHORITY_TEST_INVENTORY),
                "sha256": sha256(AUTHORITY_TEST_INVENTORY),
            },
        },
        "promotion_eligible": False,
    }
    RESULT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"overall_pass": overall_pass, "result": rel(RESULT), "freeze": rel(FREEZE)}
        )
    )
    if not overall_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
