#!/usr/bin/env python3
"""Verify and freeze Prediction Is Not Permission Technical Report v1.1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/research/paper/prediction_is_not_permission_technical_report_v1_1.md"
PDF = ROOT / "docs/research/paper/Prediction_Is_Not_Permission_Technical_Report_v1.1.pdf"
UMBRELLA = ROOT / "docs/research/cross_domain_world_model_improvement_verification_v1.json"
EXTERNAL_RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_result_v14.json"
EXTERNAL_VERIFICATION = ROOT / "docs/research/physical_jepa_safety_gymnasium_verification_v14.json"
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
    "Technical Report v1.1 — 1 September 2026",
    "Architecture rankings are domain-dependent.",
    "operationally unusable extreme",
    "Prospective Safety-Gymnasium controller and shield benchmark",
    "Warning recall and warning FPR evaluate the detector",
    "intervention rate counts only commands that actually change",
    "nominal receding-horizon controller",
    "The union passes every registered gate",
    "effective action-change recall",
    "not learned collision-avoidance superiority over privileged planning",
    "completion/cost tradeoff over the planner",
    "no independent replication is claimed",
    "No protected research result was promoted.",
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
    "References",
]
FORBIDDEN_PATTERNS = [
    r"\bTODO\b",
    r"\bTBD\b",
    r"reviewer-requested",
    r"independently executed third-party",
    r"opposite unusable extreme",
    r"Submission candidate",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> None:
    required_paths = [
        SOURCE,
        PDF,
        UMBRELLA,
        EXTERNAL_RESULT,
        EXTERNAL_VERIFICATION,
        *FIGURES,
    ]
    missing = [rel(path) for path in required_paths if not path.is_file()]
    if missing:
        raise SystemExit(f"missing required paper artifacts: {missing}")
    source_text = SOURCE.read_text(encoding="utf-8")
    umbrella = json.loads(UMBRELLA.read_text(encoding="utf-8"))
    external = json.loads(EXTERNAL_RESULT.read_text(encoding="utf-8"))
    external_verification = json.loads(EXTERNAL_VERIFICATION.read_text(encoding="utf-8"))
    reader = PdfReader(str(PDF))
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    metadata = reader.metadata
    source_required = {phrase: phrase in source_text for phrase in REQUIRED_SOURCE_PHRASES}
    pdf_required = {phrase: phrase in pdf_text for phrase in REQUIRED_PDF_PHRASES}
    forbidden_absent = {
        pattern: re.search(pattern, source_text, flags=re.IGNORECASE) is None
        for pattern in FORBIDDEN_PATTERNS
    }
    umbrella_checks = umbrella.get("checks", {})
    protected = umbrella.get("protected_deployed_artifacts", {})
    union = external["arms"]["planner_rules_plus_learned"]["metrics"]
    checks = {
        "source_required_phrases_present": all(source_required.values()),
        "pdf_required_phrases_present": all(pdf_required.values()),
        "forbidden_placeholders_and_review_wording_absent": all(forbidden_absent.values()),
        "pdf_page_count_is_14": len(reader.pages) == 14,
        "pdf_title_exact": metadata.title == TITLE,
        "pdf_author_exact": metadata.author == "Vyom Kulshrestha",
        "pdf_subject_versioned": metadata.subject
        == "Cross-domain world-model runtime authority Technical Report v1.1",
        "pdf_has_no_replacement_character": "\ufffd" not in pdf_text,
        "all_figures_nonempty": all(path.stat().st_size > 10_000 for path in FIGURES),
        "external_frozen_pass_recomputes": external["all_frozen_gates_pass"] is True
        and all(external["frozen_gates"].values())
        and external["final_seed_access_count"] == 1,
        "external_result_effective_and_attributed": union["learned_only_interventions"] > 0
        and external["selected_candidate"]["count_only_effective_interventions"] is True
        and external["selected_candidate"]["learned_requires_rule_confirmation"] is False
        and union["warning_recall"] > union["effective_intervention_recall"]
        and union["actual_hazard_cost_events"]
        > external["arms"]["planner_unshielded"]["metrics"]["actual_hazard_cost_events"],
        "external_verification_confirms_all_gates": external_verification[
            "overall_pass"
        ]
        is True
        and all(external_verification["checks"].values()),
        "external_scope_and_nonpromotion_honest": external["independent_execution"] is False
        and external["physical_actuator_attempts"] == 0
        and external["physical_actuator_deliveries"] == 0
        and external["promotion_eligible"] is False,
        "umbrella_all_checks_pass": bool(umbrella_checks) and all(umbrella_checks.values()),
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
        "evidence_frozen_date": "2026-09-01",
        "title": TITLE,
        "author": "Vyom Kulshrestha",
        "orcid": "0009-0009-1434-7148",
        "artifacts": {
            "manuscript": {"path": rel(SOURCE), "sha256": sha256(SOURCE)},
            "pdf": {"path": rel(PDF), "sha256": sha256(PDF), "pages": len(reader.pages)},
            "figures": [
                {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size}
                for path in FIGURES
            ],
            "evidence_snapshot": {"path": rel(UMBRELLA), "sha256": sha256(UMBRELLA)},
            "external_result": {"path": rel(EXTERNAL_RESULT), "sha256": sha256(EXTERNAL_RESULT)},
            "external_verification": {
                "path": rel(EXTERNAL_VERIFICATION),
                "sha256": sha256(EXTERNAL_VERIFICATION),
            },
        },
        "claim_boundary": umbrella.get("claim_boundary", []),
        "promotion_eligible": False,
        "protected_deployed_artifacts": protected,
    }
    FREEZE.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
            "freeze_manifest_sha256": sha256(FREEZE),
        },
        "artifacts": {
            "manuscript": {"path": rel(SOURCE), "sha256": sha256(SOURCE)},
            "pdf": {"path": rel(PDF), "sha256": sha256(PDF)},
            "freeze_manifest": {"path": rel(FREEZE), "sha256": sha256(FREEZE)},
            "evidence_snapshot": {"path": rel(UMBRELLA), "sha256": sha256(UMBRELLA)},
        },
        "promotion_eligible": False,
    }
    RESULT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"overall_pass": overall_pass, "result": rel(RESULT), "freeze": rel(FREEZE)}))
    if not overall_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
