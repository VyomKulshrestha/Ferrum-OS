#!/usr/bin/env python3
"""Check the frozen report read-only; --refresh explicitly replaces a candidate."""

from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pdfplumber
from pypdf import PdfReader
from pypdf.generic import ContentStream


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "docs/research/paper/prediction_is_not_permission_technical_report_v1_2.md"
)
PDF = (
    ROOT / "docs/research/paper/Prediction_Is_Not_Permission_Technical_Report_v1.2.pdf"
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
ABLATION_FAILED = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_failed_attempt_v1.json"
)
ABLATION_V1_PROTOCOL = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_protocol_v1.json"
)
ABLATION_RECOVERY_PROTOCOL = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_recovery_protocol_v2.json"
)
ABLATION_RECOVERY_RESULT = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_recovery_result_v2.json"
)
ABLATION_VERIFICATION_AMENDMENT = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_verification_amendment_v3.json"
)
ABLATION_RECOVERY_VERIFICATION = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_recovery_verification_v3.json"
)
FIGURE_DIR = ROOT / "docs/research/figures/cross_domain_world_model"
FIGURES = [
    FIGURE_DIR / "authority_factorization.png",
    FIGURE_DIR / "matched_rollout_results.png",
    FIGURE_DIR / "evidence_ladder_v1_2.png",
    FIGURE_DIR / "causal_vs_operational.png",
    FIGURE_DIR / "incident_dynamics_v3_v4_results.png",
]
FREEZE = ROOT / "docs/research/cross_domain_world_model_paper_freeze_v1_2.json"
RESULT = ROOT / "docs/research/cross_domain_world_model_paper_verification_v1_2.json"
# The revised v1.2 uses a report-specific copy of the shared builder (numbered table captions),
# leaving the builder bound by the published kernel report untouched.
BUILDER = ROOT / "scripts/build_prediction_report_layout_v1_2.py"
REPORT_BUILDER = ROOT / "scripts/build_prediction_is_not_permission_v1_2.py"
REPRO_REQUIREMENTS = ROOT / "requirements-prediction-report-v1_2.txt"
HISTORICAL_ARCHIVE = ROOT / "docs/research/cross_domain_inference_archive_v1_2.json"
HISTORICAL_VERIFICATION = ROOT / "docs/research/cross_domain_archived_inference_verification_v1_2.json"
HISTORICAL_VERIFIER = ROOT / "scripts/verify_cross_domain_archived_inference_v1_2.py"
RESTORATION_REVIEW = ROOT / "docs/research/cross_domain_checkpoint_restoration_review_v1_2.json"

TITLE = "Prediction Is Not Permission: Cross-Domain World Models Under Deterministic Runtime Authority"
EVIDENCE_SNAPSHOT_COMMIT = "c5098bfd099e8ef6c441f42dba90071f3bf71668"
INCIDENT_FILES = {
    name: ROOT / f"docs/research/incident_dynamics_{name}.json"
    for name in ("sources_v1", "protocol_v1", "protocol_v2", "selection_v2",
                 "result_v2", "verification_v2", "portable_verification_v2",
                 "v3_development_plan", "sources_v3", "protocol_v3", "selection_v3",
                 "result_v3", "verification_v3", "protocol_v4", "selection_v4",
                 "result_v4", "verification_v4")
}
ABLATION_DISPLAYED_ENDPOINTS = (
    "task_completion_percentage_points",
    "warning_recall_percentage_points",
    "warning_false_positive_percentage_points",
    "effective_intervention_recall_percentage_points",
    "intervention_percentage_points",
    "intervention_precision_percentage_points",
    "actual_hazard_cost_steps",
)
ABLATION_ALL_REGISTERED_OUTPUTS = (
    *ABLATION_DISPLAYED_ENDPOINTS,
    "actual_total_cost_steps",
    "actual_vase_cost_steps",
    "hazardous_episode_percentage_points",
    "mean_episode_steps",
)
REQUIRED_SOURCE_PHRASES = [
    "Technical Report v1.2 - 19 October 2026",
    "Incident-dynamics v3: broader mechanisms, boosted residual models, and an evolving-world curriculum",
    "Incident-dynamics v4: a registered successor after the failed v3 rule",
    "The primary success rule therefore fails, and the v3 result is retained as a failure.",
    "The primary rule therefore fails on that one population",
    "v3 provides no evidence of an RSI gain",
    "Warnings do not follow the prediction gains.",
    "v4 is a registered successor designed after the v3 result.",
    "Public narratives motivate local perturbations, not telemetry.",
    "Registered incident-motivated prediction and warning improvement (v2)",
    "The study is not architecture-only, parameter-matched, or FLOP-matched.",
    "Source identities are assigned to generated episodes; they do not cause distinct learned transition laws.",
    "The successful v2 final is not a rerun of v1 evidence.",
    "OS FPR rises by 1.00 point [0.45, 1.59]",
    "All 48 retained-catalog checks pass",
    "implements neither Dream-RSI's replay-policy optimization nor a controlled RSI ablation",
    "This version is archived on Zenodo under version DOI 10.5281/zenodo.23469363",
    "### Declarations",
    "This work received no external funding.",
    "The primary contribution is an evaluation method, not a new JEPA objective.",
    "The empirical contributions are:",
    "same six evidence objects named in the abstract",
    "not strictly compute-controlled",
    "GRU-minus-JEPA at H=3 is -0.004439 [-0.005735, -0.003203]",
    "complete post-hoc common-episode comparison",
    "registered ranking reversal cannot be isolated as a horizon effect",
    "Table 5 reports the complete post-hoc common-episode comparison",
    "Findings at a glance",
    "Table 1. Summary of findings.",
    "| H=1 | 0.002343 | **0.001018** | 0.002401 | +0.001325 [0.001295, 0.001356] | -0.001383 [-0.001408, -0.001358] |",
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
    "5% familywise error rate across the three non-full-versus-full pipeline contrasts within each endpoint separately",
    "Every one of 128 leave-one-seed-out 95% intervals",
    "These leave-one-out checks are sensitivity analyses, not independent replications.",
    "no statistically resolved difference and is not a non-inferiority result",
    "The original warning metrics are on-policy",
    "identical 23,815-proposal catalog",
    "Validation FPR",
    "exploratory pipeline-level evidence",
    "physical permit unit tests do not establish FerrumOS syscall-path enforcement",
    "Python 3.12.6, NumPy 2.2.6, and PyTorch 2.6.0+cu124",
    "Hashes prove byte identity only",
    f"exact pre-report scientific-evidence snapshot for this review freeze is Git commit `{EVIDENCE_SNAPSHOT_COMMIT}`",
    "Technical Report v1.2 is the evidence-changing successor to v1.1",
    "Its source, PDF, verifier, and freeze manifest are therefore immutable",
    "**Use of generative AI.**",
    "The design and simulator execution were prospective, but the v1 result remains failed and ineligible",
    "Recovery protocol v2 reused the retained catalogs without simulator execution",
    "verification v3 recomputes the catalogs, scores, aggregates, paired effects, seeds, and feature intervention and passes all 51 checks",
    "post-hoc seven-endpoint Bonferroni-adjusted 99.29% intervals",
    "Warning FPR | **[0.78468, 2.81866]** | **Excludes zero**",
    "Intervention rate | **[0.47780, 1.57510]** | **Excludes zero**",
    "Intervention precision | [-34.86661, 1.35705] | Includes zero",
    "adjustment across all 11 registered paired outputs gives the same survivor set",
    "warning FPR [0.73638, 2.89725] and intervention rate [0.45556, 1.59936]",
    "| Intervention rate, percentage points | +0.96180 | [0.58641, 1.38473] | Excludes zero |",
    "| Intervention precision, percentage points | -15.25735 | [-29.32521, -3.00212] | Excludes zero |",
    "| Realized hazard-cost steps | -10 | [-98, 59] | Includes zero |",
    "Validation means checking an existing record",
    "protected artifacts remain unchanged",
    "Revisiting Feature Prediction for Learning Visual Representations from Video",
    "Safety Gymnasium: A Unified Safe Reinforcement Learning Benchmark",
    "Appendix A. Claim-to-evidence ledger",
    "Appendix B. Frozen-gate and artifact audit",
    "Appendix C. Artifact locator",
]
REQUIRED_PDF_PHRASES = [
    "Prediction Is Not Permission",
    "The empirical contributions are:",
    "Vyom Kulshrestha",
    "ORCID: 0009-0009-1434-7148",
    "Technical Report v1.2",
    "Architecture-controlled results",
    "Safety-Gymnasium controller and shield benchmark",
    "writes await confirmation",
    "Threats to validity and limitations",
    "Claim-to-evidence ledger",
    "Frozen-gate and artifact audit",
    "Artifact locator",
    "Frozen risk-source attribution on fresh layouts",
    "Neither interval excludes zero",
    "Bonferroni-adjusted 98.33% interval",
    "common-episode sensitivity",
    "complete post-hoc common-episode comparison",
    "superiority over the planner was not established",
    "Validation FPR",
    "Retained-catalog Physical JEPA output-value ablation",
    "Registered incident-motivated prediction and warning improvement (v2)",
    "Incident-dynamics v3: broader mechanisms",
    "Incident-dynamics v4: a registered successor",
    "The primary rule therefore fails on that one population",
    "Source identities are assigned to generated episodes",
    "The study is not architecture-only, parameter-matched, or FLOP-matched.",
    "OS FPR rises by 1.00 point",
    "Observed minus development-mean masked",
    "Bonferroni-adjusted 99.29% CI",
    "The design and simulator execution were prospective",
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


def text_sha256_candidates(path: Path) -> set[str]:
    """Return byte and newline-normalized digests for committed UTF-8 JSON."""

    raw = path.read_bytes()
    normalized = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    variants = {
        raw,
        normalized.encode("utf-8"),
        normalized.replace("\n", "\r\n").encode("utf-8"),
    }
    return {hashlib.sha256(value).hexdigest() for value in variants}


def records_match(retained: object, recomputed: object) -> bool:
    """Only UTF-8 text record digests may differ through Git newline conversion."""
    if isinstance(retained, dict) and isinstance(recomputed, dict):
        if retained.keys() != recomputed.keys():
            return False
        for key in retained:
            if key == "sha256" and "path" in retained:
                if retained["path"] != recomputed["path"]:
                    return False
                path = (ROOT / retained["path"]).resolve()
                if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
                    return False
                candidates = (text_sha256_candidates(path)
                              if path.suffix in {".json", ".md", ".py", ".txt"}
                              else {sha256(path)})
                if retained[key] not in candidates or recomputed[key] not in candidates:
                    return False
            elif key == "freeze_manifest_sha256":
                candidates = text_sha256_candidates(FREEZE)
                if retained[key] not in candidates or recomputed[key] not in candidates:
                    return False
            elif not records_match(retained[key], recomputed[key]):
                return False
        return True
    if isinstance(retained, list) and isinstance(recomputed, list):
        return len(retained) == len(recomputed) and all(
            records_match(left, right) for left, right in zip(retained, recomputed)
        )
    return type(retained) is type(recomputed) and retained == recomputed


def finalize_records(freeze: dict, result: dict, *, refresh: bool) -> None:
    """Never overwrite a failed audit or silently bless changed release bytes."""
    if not result["overall_pass"] or not all(result["checks"].values()):
        failed = [name for name, passed in result["checks"].items() if not passed]
        raise SystemExit(f"paper checks failed; retained records unchanged: {failed}")
    if refresh:
        if FREEZE.exists():
            release = json.loads(FREEZE.read_text(encoding="utf-8"))["release"]
            if release.get("repository_tag") or not release.get("status", "").startswith("prepublication"):
                raise SystemExit("refusing to refresh a published or tagged release")
        for path, record in ((FREEZE, freeze), (RESULT, result)):
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8", newline="\n")
    else:
        for path, record in ((FREEZE, freeze), (RESULT, result)):
            if not path.is_file() or not records_match(
                json.loads(path.read_text(encoding="utf-8")), record
            ):
                raise SystemExit(f"release record mismatch; no files changed: {path.name}")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def output_summary_metrics(episodes: list[dict]) -> dict[str, float]:
    summed = {
        key: sum(int(item[key]) for item in episodes)
        for key in (
            "proposals",
            "dangerous_proposals",
            "safe_proposals",
            "interventions",
            "true_positive_interventions",
            "true_positive_warnings",
            "false_positive_warnings",
            "actual_hazard_cost_events",
            "actual_total_cost_events",
            "actual_vase_cost_events",
            "steps",
        )
    }
    episode_count = len(episodes)
    summed["task_completion_rate"] = sum(
        bool(item["task_completed"]) for item in episodes
    ) / max(1, episode_count)
    summed["warning_recall"] = summed["true_positive_warnings"] / max(
        1, summed["dangerous_proposals"]
    )
    summed["warning_false_positive_rate"] = summed[
        "false_positive_warnings"
    ] / max(1, summed["safe_proposals"])
    summed["effective_intervention_recall"] = summed[
        "true_positive_interventions"
    ] / max(1, summed["dangerous_proposals"])
    summed["intervention_rate"] = summed["interventions"] / max(
        1, summed["proposals"]
    )
    summed["intervention_precision"] = summed[
        "true_positive_interventions"
    ] / max(1, summed["interventions"])
    summed["hazardous_episode_rate"] = sum(
        item["actual_hazard_cost_events"] > 0 for item in episodes
    ) / max(1, episode_count)
    summed["mean_episode_steps"] = summed["steps"] / max(1, episode_count)
    return summed


def output_paired_metrics(left: list[dict], right: list[dict]) -> dict[str, float]:
    left_metrics = output_summary_metrics(left)
    right_metrics = output_summary_metrics(right)
    return {
        "task_completion_percentage_points": 100.0
        * (
            left_metrics["task_completion_rate"]
            - right_metrics["task_completion_rate"]
        ),
        "warning_recall_percentage_points": 100.0
        * (left_metrics["warning_recall"] - right_metrics["warning_recall"]),
        "warning_false_positive_percentage_points": 100.0
        * (
            left_metrics["warning_false_positive_rate"]
            - right_metrics["warning_false_positive_rate"]
        ),
        "effective_intervention_recall_percentage_points": 100.0
        * (
            left_metrics["effective_intervention_recall"]
            - right_metrics["effective_intervention_recall"]
        ),
        "intervention_percentage_points": 100.0
        * (left_metrics["intervention_rate"] - right_metrics["intervention_rate"]),
        "intervention_precision_percentage_points": 100.0
        * (
            left_metrics["intervention_precision"]
            - right_metrics["intervention_precision"]
        ),
        "actual_hazard_cost_steps": float(
            left_metrics["actual_hazard_cost_events"]
            - right_metrics["actual_hazard_cost_events"]
        ),
        "actual_total_cost_steps": float(
            left_metrics["actual_total_cost_events"]
            - right_metrics["actual_total_cost_events"]
        ),
        "actual_vase_cost_steps": float(
            left_metrics["actual_vase_cost_events"]
            - right_metrics["actual_vase_cost_events"]
        ),
        "hazardous_episode_percentage_points": 100.0
        * (
            left_metrics["hazardous_episode_rate"]
            - right_metrics["hazardous_episode_rate"]
        ),
        "mean_episode_steps": float(
            left_metrics["mean_episode_steps"]
            - right_metrics["mean_episode_steps"]
        ),
    }


def output_bootstrap_samples(
    left: list[dict],
    right: list[dict],
    endpoints: tuple[str, ...],
    *,
    seed: int,
    resamples: int,
) -> dict[str, dict]:
    left_by_seed = {int(item["seed"]): item for item in left}
    right_by_seed = {int(item["seed"]): item for item in right}
    seeds = sorted(left_by_seed)
    if seeds != sorted(right_by_seed):
        raise ValueError("output-ablation paired episode seeds differ")
    rng = np.random.default_rng(seed)
    samples = {name: [] for name in endpoints}
    for _ in range(resamples):
        sampled = rng.integers(0, len(seeds), size=len(seeds))
        left_sample = [left_by_seed[seeds[index]] for index in sampled]
        right_sample = [right_by_seed[seeds[index]] for index in sampled]
        effects = output_paired_metrics(left_sample, right_sample)
        for name in endpoints:
            samples[name].append(effects[name])
    return samples


def output_bonferroni_intervals(
    samples: dict[str, list[float]], endpoints: tuple[str, ...]
) -> dict[str, dict]:
    tail = 0.05 / (2.0 * len(endpoints))
    intervals = {}
    for name in endpoints:
        lower, upper = (
            float(value)
            for value in np.quantile(samples[name], [tail, 1.0 - tail])
        )
        intervals[name] = {
            "interval": [lower, upper],
            "excludes_zero": bool(lower > 0.0 or upper < 0.0),
        }
    return intervals


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


def pdf_font_inventory(
    reader: PdfReader,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    fonts: dict[tuple[str, str], dict[str, object]] = {}
    nonzero_character_spacing: list[dict[str, object]] = []

    def descriptor_embedded(font: object) -> bool:
        descriptor = font.get("/FontDescriptor")
        if descriptor is None:
            return False
        descriptor = descriptor.get_object()
        return any(
            key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")
        )

    for page_number, page in enumerate(reader.pages, start=1):
        resources = page.get("/Resources")
        if resources is not None:
            font_resources = resources.get_object().get("/Font")
            if font_resources is not None:
                for font_ref in font_resources.get_object().values():
                    font = font_ref.get_object()
                    base_font = str(font.get("/BaseFont", ""))
                    subtype = str(font.get("/Subtype", ""))
                    embedded = descriptor_embedded(font)
                    if subtype == "/Type0":
                        descendants = font.get("/DescendantFonts") or []
                        embedded = bool(descendants) and all(
                            descriptor_embedded(item.get_object())
                            for item in descendants
                        )
                    fonts[(base_font, subtype)] = {
                        "base_font": base_font,
                        "subtype": subtype,
                        "embedded": embedded,
                    }
        contents = page.get_contents()
        if contents is not None:
            for operands, operator in ContentStream(contents, reader).operations:
                if operator == b"Tc" and operands and abs(float(operands[0])) > 1e-12:
                    nonzero_character_spacing.append(
                        {"page": page_number, "value": float(operands[0])}
                    )
    return (
        sorted(
            fonts.values(),
            key=lambda item: (str(item["base_font"]), str(item["subtype"])),
        ),
        nonzero_character_spacing,
    )


def pdf_typography_metrics() -> dict[str, float]:
    sizes: Counter[float] = Counter()
    first_page_sizes: list[float] = []
    with pdfplumber.open(PDF) as document:
        for page_index, page in enumerate(document.pages):
            for character in page.chars:
                if str(character.get("text", "")).strip():
                    size = round(float(character["size"]), 2)
                    sizes[size] += 1
                    if page_index == 0:
                        first_page_sizes.append(size)
    total = sum(sizes.values())
    dominant_size = sizes.most_common(1)[0][0] if sizes else 0.0
    publication_body_share = (
        sum(count for size, count in sizes.items() if size >= 9.4) / total
        if total
        else 0.0
    )
    return {
        "dominant_body_font_size_points": dominant_size,
        "character_share_at_least_9_4_points": publication_body_share,
        "maximum_first_page_font_size_points": max(first_page_sizes, default=0.0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true",
                        help="explicitly replace passing prepublication freeze records")
    args = parser.parse_args()
    required_paths = [
        SOURCE,
        PDF,
        BUILDER,
        REPORT_BUILDER,
        REPRO_REQUIREMENTS,
        HISTORICAL_ARCHIVE,
        HISTORICAL_VERIFICATION,
        HISTORICAL_VERIFIER,
        RESTORATION_REVIEW,
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
        ABLATION_V1_PROTOCOL,
        ABLATION_FAILED,
        ABLATION_RECOVERY_PROTOCOL,
        ABLATION_RECOVERY_RESULT,
        ABLATION_VERIFICATION_AMENDMENT,
        ABLATION_RECOVERY_VERIFICATION,
        *INCIDENT_FILES.values(),
        *FIGURES,
    ]
    missing = [rel(path) for path in required_paths if not path.is_file()]
    if missing:
        raise SystemExit(f"missing required paper artifacts: {missing}")
    source_text = SOURCE.read_text(encoding="utf-8")
    historical_archive = json.loads(HISTORICAL_ARCHIVE.read_text(encoding="utf-8"))
    historical_verification = json.loads(HISTORICAL_VERIFICATION.read_text(encoding="utf-8"))
    restoration_review = json.loads(RESTORATION_REVIEW.read_text(encoding="utf-8"))
    builder_text = BUILDER.read_text(encoding="utf-8")
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
    ablation_v1_protocol = json.loads(
        ABLATION_V1_PROTOCOL.read_text(encoding="utf-8")
    )
    ablation_failed = json.loads(ABLATION_FAILED.read_text(encoding="utf-8"))
    ablation_recovery_protocol = json.loads(
        ABLATION_RECOVERY_PROTOCOL.read_text(encoding="utf-8")
    )
    ablation_recovery = json.loads(
        ABLATION_RECOVERY_RESULT.read_text(encoding="utf-8")
    )
    ablation_amendment = json.loads(
        ABLATION_VERIFICATION_AMENDMENT.read_text(encoding="utf-8")
    )
    ablation_verification = json.loads(
        ABLATION_RECOVERY_VERIFICATION.read_text(encoding="utf-8")
    )
    incident = {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in INCIDENT_FILES.items()
    }
    incident_result = incident["result_v2"]
    incident_verification = incident["verification_v2"]
    incident_domains = incident_result["domains"]
    reader = PdfReader(str(PDF))
    source_urls = set(re.findall(r"https?://[^\s<>\"']+", source_text))
    pdf_urls = {
        str(annotation.get_object().get("/A", {}).get("/URI", ""))
        for page in reader.pages for annotation in page.get("/Annots", [])
    }
    with pdfplumber.open(PDF) as document:
        all_text_within_page = all(
            0 <= char["x0"] <= char["x1"] <= page.width + .1
            and 0 <= char["top"] <= char["bottom"] <= page.height + .1
            for page in document.pages for char in page.chars
        )
    font_inventory, nonzero_character_spacing = pdf_font_inventory(reader)
    typography = pdf_typography_metrics()
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    pdf_search_text = " ".join(pdf_text.split())
    metadata = reader.metadata
    source_required = {
        phrase: phrase in source_text for phrase in REQUIRED_SOURCE_PHRASES
    }
    pdf_required = {
        phrase: phrase in pdf_search_text for phrase in REQUIRED_PDF_PHRASES
    }
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
    ablation_effects = ablation_recovery["paired_output_contribution"]["effects"]
    observed_ablation_episodes = ablation_recovery["arms"]["observed-frozen-jepa"][
        "episode_summaries"
    ]
    masked_ablation_episodes = ablation_recovery["arms"][
        "development-mean-masked-jepa"
    ]["episode_summaries"]
    ablation_bootstrap_seed = ablation_v1_protocol["uncertainty"][
        "paired_bootstrap_seed"
    ]
    ablation_bootstrap_resamples = ablation_v1_protocol["uncertainty"][
        "paired_bootstrap_resamples"
    ]
    ablation_bootstrap_samples = output_bootstrap_samples(
        observed_ablation_episodes,
        masked_ablation_episodes,
        ABLATION_ALL_REGISTERED_OUTPUTS,
        seed=ablation_bootstrap_seed,
        resamples=ablation_bootstrap_resamples,
    )
    all_registered_adjusted = output_bonferroni_intervals(
        ablation_bootstrap_samples,
        ABLATION_ALL_REGISTERED_OUTPUTS,
    )
    displayed_adjusted = output_bonferroni_intervals(
        ablation_bootstrap_samples,
        ABLATION_DISPLAYED_ENDPOINTS,
    )
    expected_displayed_adjusted = {
        "task_completion_percentage_points": [-3.125, 0.0],
        "warning_recall_percentage_points": [
            -11.253300870202505,
            18.182549363264535,
        ],
        "warning_false_positive_percentage_points": [
            0.7846824039950231,
            2.81866234561309,
        ],
        "effective_intervention_recall_percentage_points": [
            -7.629120645358498,
            6.2211752780409935,
        ],
        "intervention_percentage_points": [
            0.4778018711832064,
            1.5751027845626882,
        ],
        "intervention_precision_percentage_points": [
            -34.86661087127528,
            1.3570538582529057,
        ],
        "actual_hazard_cost_steps": [-134.0, 81.0],
    }
    table_rows = pdf_table_rows()
    all_table_rows = set().union(*table_rows.values())
    checks = {
        "source_required_phrases_present": all(source_required.values()),
        "pdf_required_phrases_present": all(pdf_required.values()),
        "public_graphic_uses_typographic_evidence_chain": (
            "Prediction ≠ Warning ≠ Intervention ≠ Outcome ≠ Authority"
            in builder_text
            and "Prediction != warning != intervention != outcome != authority"
            not in builder_text
        ),
        "forbidden_placeholders_and_review_wording_absent": all(
            forbidden_absent.values()
        ),
        # October adds three registered incident-dynamics studies (v2-v4) with full controls and appendices.
        "pdf_page_count_is_readable_submission_length": 20 <= len(reader.pages) <= 44,
        "pdf_body_typography_matches_publication_scale": 9.4
        <= typography["dominant_body_font_size_points"]
        <= 9.6
        # The revision adds about five data tables (Tables 19-26, D3) set below body size.
        and typography["character_share_at_least_9_4_points"] >= 0.65
        and typography["maximum_first_page_font_size_points"] <= 24.0,
        "pdf_title_exact": metadata.title == TITLE,
        "pdf_author_exact": metadata.author == "Vyom Kulshrestha",
        "pdf_subject_versioned": metadata.subject
        == "Cross-domain world-model runtime authority Technical Report v1.2",
        "pdf_has_no_replacement_character": "\ufffd" not in pdf_text,
        "pdf_has_no_text_outside_page_bounds": all_text_within_page,
        "pdf_reference_links_preserve_complete_source_urls": bool(source_urls)
        and source_urls <= pdf_urls,
        "pdf_fonts_are_embedded_and_character_spacing_is_normal": bool(font_inventory)
        and all(item["embedded"] is True for item in font_inventory)
        and not nonzero_character_spacing
        and not any(
            any(
                base14 in str(item["base_font"])
                for base14 in ("Helvetica", "Times", "Courier")
            )
            for item in font_inventory
        ),
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
                "JEPA",
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
            and (
                "H=1",
                "0.002343",
                "0.001018",
                "0.002401",
                "+0.001325 [0.001295, 0.001356]",
                "-0.001383 [-0.001408, -0.001358]",
            )
            in all_table_rows
            and (
                "Intervention rate, percentage points",
                "+0.96180",
                "[0.58641, 1.38473]",
                "Excludes zero",
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
        "output_ablation_failed_v1_retained": ablation_failed["result_eligible"]
        is False
        and ablation_failed["final_seed_range_accessed"]
        == {"start": 9000, "count": 128}
        and ablation_failed["authority"]["promotion_eligible"] is False,
        "output_ablation_recovery_is_retrospective": ablation_recovery[
            "execution_evidence"
        ]["simulator_rerun_during_recovery"]
        is False
        and ablation_recovery["execution_evidence"][
            "case_catalogs_reused_without_modification"
        ]
        is True
        and ablation_recovery["authority"]["promotion_eligible"] is False,
        "output_ablation_v3_all_51_checks_pass": ablation_verification[
            "all_checks_pass"
        ]
        is True
        and len(ablation_verification["checks"]) == 51
        and all(ablation_verification["checks"].values())
        and ablation_verification["interpretation"][
            "prospective_v1_execution_status"
        ]
        == "failed"
        and ablation_verification["interpretation"][
            "estimates_status"
        ]
        == "retrospective retained-catalog recovery analysis",
        "output_ablation_verification_amendment_is_nonexperimental": ablation_amendment[
            "scope"
        ]["verification_only"]
        is True
        and ablation_amendment["scope"]["reruns_simulator"] is False
        and ablation_amendment["scope"]["changes_estimands"] is False,
        "output_ablation_protocol_and_result_are_bound": ablation_recovery["protocol"][
            "sha256"
        ]
        == sha256(ABLATION_RECOVERY_PROTOCOL)
        and ablation_verification["result"]["sha256"]
        in text_sha256_candidates(ABLATION_RECOVERY_RESULT),
        "output_ablation_headline_effects_exact": ablation_effects[
            "task_completion_percentage_points"
        ]["estimate"]
        == -0.78125
        and ablation_effects["task_completion_percentage_points"][
            "bootstrap_95_percent"
        ]
        == [-2.34375, 0.0]
        and ablation_effects["warning_recall_percentage_points"]["interval_excludes_zero"]
        is False
        and ablation_effects["warning_false_positive_percentage_points"]["estimate"]
        == 1.6698222425453668
        and ablation_effects["intervention_percentage_points"]["estimate"]
        == 0.9618010540320184
        and ablation_effects["intervention_precision_percentage_points"]["estimate"]
        == -15.257352941176471
        and ablation_effects["actual_hazard_cost_steps"]["estimate"] == -10.0
        and ablation_effects["actual_hazard_cost_steps"]["interval_excludes_zero"]
        is False,
        "output_ablation_pre_catalog_registration_exact": ablation_v1_protocol[
            "prospective_boundary"
        ]["seed_range_status_at_registration"]
        == "unopened for this ablation"
        and ablation_v1_protocol["prospective_boundary"]["fresh_final_seed_range"]
        == {"start": 9000, "count": 128}
        and ablation_v1_protocol["uncertainty"]["paired_bootstrap_seed"]
        == ablation_recovery_protocol["uncertainty"]["paired_bootstrap_seed"]
        == 2026090810
        and ablation_v1_protocol["uncertainty"]["absolute_bootstrap_seed"]
        == ablation_recovery_protocol["uncertainty"]["absolute_bootstrap_seed"]
        == 2026090800
        and ablation_v1_protocol["toolchain"]["ablation_runner"]["sha256"]
        == ablation_recovery_protocol["toolchain"]["v1_registered_analysis_core"][
            "sha256"
        ]
        == "0034ee3100db93b6d971ebd0be01a42757fbebbd9c007099f95a1a79c821b1f7"
        and "v1 registered estimands and bootstrap seeds"
        in ablation_recovery_protocol["constant_factors"]
        and ablation_failed["failure_cause"].endswith(
            "The ablation runner did not write or invoke the report build."
        ),
        "output_ablation_seven_endpoint_bonferroni_recomputes": all(
            np.allclose(
                displayed_adjusted[name]["interval"],
                expected_interval,
                rtol=0.0,
                atol=1e-12,
            )
            for name, expected_interval in expected_displayed_adjusted.items()
        )
        and {
            name
            for name, record in displayed_adjusted.items()
            if record["excludes_zero"]
        }
        == {
            "warning_false_positive_percentage_points",
            "intervention_percentage_points",
        },
        "output_ablation_all_output_family_same_survivors": {
            name
            for name, record in all_registered_adjusted.items()
            if record["excludes_zero"]
        }
        == {
            "warning_false_positive_percentage_points",
            "intervention_percentage_points",
        }
        and np.allclose(
            all_registered_adjusted["warning_false_positive_percentage_points"][
                "interval"
            ],
            [0.7363828602, 2.897250816],
            rtol=0.0,
            atol=1e-9,
        )
        and np.allclose(
            all_registered_adjusted["intervention_percentage_points"]["interval"],
            [0.4555590006, 1.599361779],
            rtol=0.0,
            atol=1e-9,
        ),
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
    checks.update({
        "historical_archived_inference_eight_checks_pass":
            historical_verification["all_checks_pass"]
            and len(historical_verification["checks"]) == 8
            and all(historical_verification["checks"].values())
            and historical_verification["archive_manifest"]["sha256"] in text_sha256_candidates(HISTORICAL_ARCHIVE)
            and historical_verification["verifier"]["sha256"] in text_sha256_candidates(HISTORICAL_VERIFIER),
        "historical_18_archived_checkpoints_and_base_input_bound":
            len(historical_archive["checkpoints"]) == 18
            and all(sha256(ROOT / item["archived"]["path"]) == item["archived"]["sha256"] == item["original"]["sha256"]
                    for item in historical_archive["checkpoints"])
            and sha256(ROOT / historical_archive["base_dataset"]["archived"]["path"])
            == historical_archive["base_dataset"]["archived"]["sha256"],
        "restoration_failures_retained_and_no_final_access":
            restoration_review["accepted_thread16"] == 9
            and restoration_review["rejected_thread4"] == 7
            and all(not item["final_access_attempted"] for item in restoration_review["attempts"]),
        "matched_study_collapse_limit_reported":
            "no explicit latent-variance or effective-rank collapse diagnostic" in source_text
            and "constant-representation trials are separately rejected" not in source_text,
        "incident_source_strata_confound_reported":
            "source-label strata are confounded with pressure regime" in source_text,
        "incident_strong_control_context_correct": all(
            round(100 * (1 - incident_domains[domain]["methods"]["selected"]["prediction"]["h5"]["episode_macro_mae"]
                         / incident_domains[domain]["methods"][baseline]["prediction"]["h5"]["episode_macro_mae"]), 2) == expected
            for domain, baseline, expected in (("ferrumos", "persistence", 55.35),
                                               ("physical", "retrained-jepa", 15.42)))
            and "55.35% and 15.42%" in source_text,
        "reproduction_scope_and_read_only_contract_reported":
            "paper checker is read-only by default" in source_text
            and "does not independently rerun every underlying study" in source_text
            and "torch==2.6.0" in REPRO_REQUIREMENTS.read_text(encoding="utf-8"),
        "incident_primary_and_warning_gates_pass": incident_result["primary_prediction_objective_pass"]
        and incident_result["secondary_warning_objective_pass"]
        and all(domain["primary_prediction_objective_pass"] and domain["secondary_warning_objective_pass"]
                for domain in incident_domains.values()),
        "incident_four_adjusted_prediction_contrasts_pass": all(
            comparison["pass"] and comparison["relative_reduction"] >= .2
            and comparison["interval"][1] < 0 and comparison["interval_level"] == .9875
            and comparison["episodes"] == 1024 and comparison["resamples"] == 10000
            for domain in incident_domains.values()
            for comparison in domain["primary_prediction_comparisons"].values()),
        "incident_six_historical_guards_pass": all(
            guard["pass"] and guard["relative_change"] <= .05
            for domain in incident_domains.values() for guard in domain["historical_guards"].values()),
        "incident_verification_bound_and_48_checks_pass": incident_verification["all_checks_pass"]
        and len(incident_verification["checks"]) == 48 and all(incident_verification["checks"].values())
        and incident_verification["result"]["path"] == rel(INCIDENT_FILES["result_v2"])
        and incident_verification["result"]["sha256"] in text_sha256_candidates(INCIDENT_FILES["result_v2"]),
        "incident_clean_archive_audit_matches": incident["portable_verification_v2"]["all_checks_pass"]
        and incident["portable_verification_v2"]["scientific_checks"] == 48
        and incident["portable_verification_v2"]["scientific_report_exact_match"]
        and incident["portable_verification_v2"]["retained_result_sha256"] == incident_verification["result"]["sha256"],
        "incident_models_and_thresholds_unchanged_in_amendment": not incident["selection_v2"]["model_and_threshold_reselection"]
        and incident_verification["checks"]["v1_models_and_thresholds_unchanged"]
        and incident_verification["checks"]["v1_failed_attempt_retained"],
        "incident_no_promotion_or_actuator_authority": incident_result["promotion_eligible"] is False
        and incident_result["actuator_attempts"] == incident_result["actuator_deliveries"] == 0
        and all(incident_result["protected_unchanged"].values()),
        "incident_primary_table_matches_result": all(
            f"{domain['methods']['selected']['prediction'][h]['episode_macro_mae']:.6f}" in source_text
            and f"{comparison['relative_reduction'] * 100:.2f}%" in source_text
            and f"[{comparison['interval'][0]:.6f}, {comparison['interval'][1]:.6f}]" in source_text
            for domain in incident_domains.values()
            for h, comparison in domain["primary_prediction_comparisons"].items()),
        "incident_warning_table_matches_counts": all(
            f"{warning['tp']} / {warning['fp']} / {warning['tn']} / {warning['fn']}" in source_text
            and f"{warning['recall'] * 100:.2f}%" in source_text
            and f"{warning['fpr'] * 100:.2f}%" in source_text
            for domain_name, domain in incident_domains.items()
            for name, method in domain["methods"].items()
            if name in ("selected", "paper-gru_dynamics" if domain_name == "ferrumos" else "paper-action_conditioned_jepa")
            for warning in [method["warning"]]),
        "incident_os_false_positive_increase_retained": incident_domains["ferrumos"]["paired_warning"]["fpr"]["interval_97_5_percent"][0] > 0
        and "OS FPR rises by 1.00 point [0.45, 1.59]" in source_text,
    })
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts"))
    import build_incident_dynamics_v3_tables as v34_tables
    result_v3, result_v4 = incident["result_v3"], incident["result_v4"]
    verification_v3, verification_v4 = incident["verification_v3"], incident["verification_v4"]
    generated_tables = {
        "v3_primary": v34_tables.table_primary(result_v3),
        "v3_controls": v34_tables.table_controls(result_v3),
        "v3_warnings": v34_tables.table_warnings(result_v3),
        "v3_rsi": v34_tables.table_rsi(result_v3),
        "v4_primary": v34_tables.table_primary(result_v4, "v4"),
        "v4_physical_lineage": v34_tables.table_v4_physical_lineage(result_v4),
        "v4_warnings": v34_tables.table_warnings(result_v4, "v4"),
        "v3_sources": v34_tables.table_sources(),
    }
    checks.update({
        "incident_v3_v4_tables_match_retained_results": all(table in source_text for table in generated_tables.values()),
        "incident_v3_primary_failure_reported": result_v3["primary_prediction_objective_pass"] is False
        and "The primary success rule therefore fails, and the v3 result is retained as a failure." in source_text,
        "incident_v4_primary_failure_reported": result_v4["primary_prediction_objective_pass"] is False
        and "The primary rule therefore fails on that one population" in source_text,
        "incident_v4_physical_gates_and_guards_pass": all(
            x["pass"] for p in result_v4["domains"]["physical"]["populations"].values() for x in p["primary_prediction"].values())
        and all(g["pass"] for g in result_v4["domains"]["physical"]["historical_guards"].values()),
        "incident_v3_v4_verifications_pass": verification_v3["all_checks_pass"] and len(verification_v3["checks"]) == 48
        and verification_v4["all_checks_pass"] and len(verification_v4["checks"]) == 46
        and verification_v3["result"]["sha256"] in text_sha256_candidates(INCIDENT_FILES["result_v3"])
        and verification_v4["result"]["sha256"] in text_sha256_candidates(INCIDENT_FILES["result_v4"]),
        "incident_v3_v4_no_promotion_or_actuator_authority": all(
            r["promotion_eligible"] is False and r["actuator_attempts"] == r["actuator_deliveries"] == 0 and all(r["protected_unchanged"].values())
            for r in (result_v3, result_v4)),
        "incident_v3_rsi_negative_reported": all(
            result_v3["domains"]["ferrumos"]["populations"][pop]["rsi_ablation"]["h5"]["relative_reduction"] < 0.05 for pop in ("A", "B"))
        and "v3 provides no evidence of an RSI gain" in source_text,
        "incident_v3_v4_selection_frozen_without_final_access": not incident["selection_v3"]["final_access_attempted"]
        and not incident["selection_v4"]["final_access_attempted"],
    })
    freeze = {
        "schema": "cross-domain-world-model-paper-freeze-v1-2",
        "report_version": "1.2",
        "evidence_frozen_date": "2026-10-19",
        "title": TITLE,
        "author": "Vyom Kulshrestha",
        "orcid": "0009-0009-1434-7148",
        "release": {
            "status": "published v1.2 (Zenodo version DOI 10.5281/zenodo.23469363); v1.1 remains retained",
            "evidence_snapshot_commit": EVIDENCE_SNAPSHOT_COMMIT,
            "repository_tag": "prediction-is-not-permission-v1.2",
            "version_doi": "10.5281/zenodo.23469363",
        },
        "artifacts": {
            **{f"incident_dynamics_{name}": {"path": rel(path), "sha256": sha256(path)}
               for name, path in INCIDENT_FILES.items()},
            "report_builder": {"path": rel(REPORT_BUILDER), "sha256": sha256(REPORT_BUILDER)},
            "report_layout_builder": {"path": rel(BUILDER), "sha256": sha256(BUILDER)},
            "paper_verifier": {"path": rel(Path(__file__)), "sha256": sha256(Path(__file__))},
            "reproduction_requirements": {"path": rel(REPRO_REQUIREMENTS), "sha256": sha256(REPRO_REQUIREMENTS)},
            **{name: {"path": rel(path), "sha256": sha256(path)} for name, path in (
                ("historical_inference_archive", HISTORICAL_ARCHIVE),
                ("historical_inference_verification", HISTORICAL_VERIFICATION),
                ("historical_inference_verifier", HISTORICAL_VERIFIER),
                ("checkpoint_restoration_review", RESTORATION_REVIEW))},
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
            "output_ablation_v1_protocol": {
                "path": rel(ABLATION_V1_PROTOCOL),
                "sha256": sha256(ABLATION_V1_PROTOCOL),
            },
            "output_ablation_failed_attempt": {
                "path": rel(ABLATION_FAILED),
                "sha256": sha256(ABLATION_FAILED),
            },
            "output_ablation_recovery_protocol": {
                "path": rel(ABLATION_RECOVERY_PROTOCOL),
                "sha256": sha256(ABLATION_RECOVERY_PROTOCOL),
            },
            "output_ablation_recovery_result": {
                "path": rel(ABLATION_RECOVERY_RESULT),
                "sha256": sha256(ABLATION_RECOVERY_RESULT),
            },
            "output_ablation_verification_amendment": {
                "path": rel(ABLATION_VERIFICATION_AMENDMENT),
                "sha256": sha256(ABLATION_VERIFICATION_AMENDMENT),
            },
            "output_ablation_recovery_verification": {
                "path": rel(ABLATION_RECOVERY_VERIFICATION),
                "sha256": sha256(ABLATION_RECOVERY_VERIFICATION),
            },
        },
        "claim_boundary": umbrella.get("claim_boundary", [])
        + [
            "The registered FerrumOS horizon populations differ; the common-episode post-hoc sensitivity changes the ranking, so the registered reversal is not isolated as a horizon effect.",
            "The original attribution warning metrics are on-policy. The common-proposal sensitivity fixes inputs to the full-arm visited-state catalog and is not an independent detector sample.",
            "JEPA-only versus full was one prospectively specified family member, not a unique primary contrast. Adjusted and leave-one-out intervals support an exploratory pipeline result, not preserved completion or architecture-only causality.",
            "Authority tests distinguish host unit, host integration, and QEMU in-guest coverage; physical permit unit tests do not establish FerrumOS syscall-path enforcement.",
            "Multiplicity control is familywise across three non-full-versus-full pipeline contrasts within each endpoint; it does not cover every endpoint or comparison, and leave-one-out checks are sensitivity analyses rather than independent replications.",
            "The output-ablation design, estimands, fresh seed range, and bootstrap seeds were fixed before either catalog existed. The simulator execution was prospective, but its result failed the final protected-file gate; recovery v2 is the retrospective reportable analysis.",
            "The output-ablation multiplicity checks are post-hoc. Seven displayed endpoints and all 11 registered paired outputs leave only warning FPR and intervention rate separated from zero; neither result establishes benefit.",
            "Incident-dynamics v2 passes four adjusted prediction and two warning gates on fresh locally generated episodes, with six historical point-estimate regression guards; source labels are not independent dynamics or telemetry holdout.",
            "The new study changes data, objective, model and calibration together, with unequal budgets and seed counts; it does not identify architecture-only, Dream-RSI, controller-outcome or physical-safety benefit.",
            "The new OS warning gain has a statistically resolved false-positive increase; the 1 percent calibration target is not a population guarantee.",
            "The failed incident-dynamics v1 schema attempt is retained; v2 uses unchanged selected models and thresholds with a prospectively registered fresh seed.",
        ],
        "promotion_eligible": False,
        "protected_deployed_artifacts": protected,
    }
    freeze_digest = (hashlib.sha256(
        (json.dumps(freeze, indent=2, sort_keys=True) + "\n").encode("utf-8")
    ).hexdigest() if args.refresh else sha256(FREEZE))
    overall_pass = all(checks.values())
    result = {
        "schema": "cross-domain-world-model-paper-verification-v1-2",
        "report_version": "1.2",
        "overall_pass": overall_pass,
        "checks": checks,
        "diagnostics": {
            "source_required_phrases": source_required,
            "pdf_required_phrases": pdf_required,
            "public_graphic_uses_typographic_evidence_chain": checks[
                "public_graphic_uses_typographic_evidence_chain"
            ],
            "forbidden_patterns_absent": forbidden_absent,
            "pdf_pages": len(reader.pages),
            "pdf_missing_source_urls": sorted(source_urls - pdf_urls),
            "pdf_words_extracted": len(pdf_text.split()),
            "positionally_checked_pdf_table_pages": sorted(table_rows),
            "pdf_font_inventory": font_inventory,
            "pdf_nonzero_character_spacing": nonzero_character_spacing,
            "pdf_typography": typography,
            "output_ablation_bonferroni_7_endpoint": displayed_adjusted,
            "output_ablation_bonferroni_11_output": all_registered_adjusted,
            "freeze_manifest_sha256": freeze_digest,
        },
        "artifacts": {
            "manuscript": {"path": rel(SOURCE), "sha256": sha256(SOURCE)},
            "pdf": {"path": rel(PDF), "sha256": sha256(PDF)},
            "freeze_manifest": {"path": rel(FREEZE), "sha256": freeze_digest},
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
            "output_ablation_v1_protocol": {
                "path": rel(ABLATION_V1_PROTOCOL),
                "sha256": sha256(ABLATION_V1_PROTOCOL),
            },
            "output_ablation_failed_attempt": {
                "path": rel(ABLATION_FAILED),
                "sha256": sha256(ABLATION_FAILED),
            },
            "output_ablation_recovery_protocol": {
                "path": rel(ABLATION_RECOVERY_PROTOCOL),
                "sha256": sha256(ABLATION_RECOVERY_PROTOCOL),
            },
            "output_ablation_recovery_result": {
                "path": rel(ABLATION_RECOVERY_RESULT),
                "sha256": sha256(ABLATION_RECOVERY_RESULT),
            },
            "output_ablation_verification_amendment": {
                "path": rel(ABLATION_VERIFICATION_AMENDMENT),
                "sha256": sha256(ABLATION_VERIFICATION_AMENDMENT),
            },
            "output_ablation_recovery_verification": {
                "path": rel(ABLATION_RECOVERY_VERIFICATION),
                "sha256": sha256(ABLATION_RECOVERY_VERIFICATION),
            },
        },
        "promotion_eligible": False,
    }
    finalize_records(freeze, result, refresh=args.refresh)
    print(
        json.dumps(
            {"overall_pass": overall_pass, "read_only": not args.refresh,
             "result": rel(RESULT), "freeze": rel(FREEZE)}
        )
    )
    if not overall_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
