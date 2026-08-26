#!/usr/bin/env python3
"""Verify the Technical Report v1.2 PDF, freeze, and evidence attribution."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FREEZE = ROOT / "docs" / "research" / "world_model_technical_report_freeze_v1_2.json"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def require(checks: list[tuple[str, bool]], label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    args = parser.parse_args()

    freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
    source_path = ROOT / freeze["source"]["path"]
    builder_path = ROOT / freeze["builder"]["path"]
    pdf_path = ROOT / freeze["pdf"]["build_output_path"]
    validation_path = ROOT / freeze["evidence"]["validation"]["path"]
    result_path = ROOT / freeze["evidence"]["final_result"]["path"]
    evidence_verification_path = ROOT / freeze["evidence"]["verification"]["path"]

    source = source_path.read_text(encoding="utf-8")
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    evidence_verification = json.loads(evidence_verification_path.read_text(encoding="utf-8"))
    reader = PdfReader(str(pdf_path))
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    normalized_pdf_text = " ".join(pdf_text.split())

    checks: list[tuple[str, bool]] = []
    require(checks, "source hash matches freeze", digest(source_path) == freeze["source"]["sha256"])
    require(checks, "builder hash matches freeze", digest(builder_path) == freeze["builder"]["sha256"])
    require(checks, "PDF hash matches freeze", digest(pdf_path) == freeze["pdf"]["sha256"])
    require(checks, "PDF has 19 pages", len(reader.pages) == 19 == freeze["pdf"]["pages"])
    require(checks, "PDF metadata title is correct", reader.metadata.title == "When Agents Control the Kernel")
    require(checks, "PDF metadata author is correct", reader.metadata.author == "Vyom Kulshrestha")
    require(checks, "source is ASCII", source.isascii())
    require(checks, "report is v1.2", "Technical Report v1.2 - 26 August 2026" in pdf_text)
    require(checks, "report is not labelled revised", "Paper Revised" not in pdf_text and "Revised" not in pdf_text)
    require(checks, "report is not labelled research note", "Technical Research Note" not in pdf_text)
    require(checks, "author ORCID is present", "0009-0009-1434-7148" in pdf_text)

    required_sections = [
        "Claim-to-evidence map and study lineage",
        "Threat model and security boundary",
        "Original safety results and strong baselines",
        "Original false-negative decomposition and boundary calibration",
        "Registered v3-v3.4 extension",
        "Retained iterations and selection discipline",
        "v3.4 final results",
        "Ablation, interpretation, and non-promotion",
        "Limitations, validity threats, and claim registry",
        "Reproducibility and artifact checklist",
    ]
    for section in required_sections:
        require(checks, f"section present: {section}", section in pdf_text)

    final_rules = result["final_conditions"]["rules_v3_4"]
    final_combined = result["final_conditions"]["rules_v3_4_plus_jepa_candidate"]
    require(checks, "rules-only and combined final confusion are identical", final_rules["confusion"] == final_combined["confusion"])
    require(checks, "final deterministic confusion is 256/0/256/0", final_rules["confusion"] == {
        "true_positive": 256,
        "false_negative": 0,
        "true_negative": 256,
        "false_positive": 0,
    })
    require(checks, "paired bootstrap used 10000 resamples", result["final_calibration"]["paired_source_stratified_balanced_accuracy"]["resamples"] == 10000)
    interval = result["final_calibration"]["paired_source_stratified_balanced_accuracy"]["percentile_95"]
    require(checks, "paired interval matches report", 0.4634 < interval[0] < 0.4636 and 0.4881 < interval[1] < 0.4883)

    rollout = result["published_corpus_untouched_test"]
    for horizon in ("h1", "h3", "h5"):
        require(
            checks,
            f"candidate improves untouched {horizon}",
            rollout["candidate"][horizon]["normalized_mse"] < rollout["runtime_v2"][horizon]["normalized_mse"],
        )
    require(checks, "untouched geometric ratio matches report", abs(rollout["candidate_to_runtime_v2"]["geometric_ratio"] - 0.9565078468476415) < 1e-12)

    require(checks, "final stayed unopened during selection", validation["new_final_catalog_access"] == {"opened": False, "attempted_paths": []})
    require(checks, "final was opened exactly once", result["final_open_count"] == 1)
    require(checks, "offline gates passed", result["offline_gates_passed"] is True)
    require(checks, "runtime and authority gates remain pending", result["runtime_and_authority_gates_pending"] is True)
    require(checks, "promotion is disabled", result["promotion_eligible"] is False)
    require(checks, "deployment was not attempted", result["deployment"]["attempted"] is False)
    require(checks, "deployment digests are unchanged", result["deployment"]["unchanged"] is True)
    require(checks, "evidence verifier passes 27/27", evidence_verification["checks_passed"] == evidence_verification["checks_total"] == 27)

    required_phrases = [
        "not incremental learned safety value",
        "promotion_eligible: false",
        "The learned-only marginal safety contribution on the final fixture is therefore zero",
        "No deployment or learned final-fixture safety advantage is claimed",
    ]
    for phrase in required_phrases:
        require(checks, f"claim boundary present: {phrase}", phrase in normalized_pdf_text)

    failed = [label for label, passed in checks if not passed]
    for label, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
