#!/usr/bin/env python3
"""Compare physical-JEPA v3 sweeps rerun at different BLAS thread counts with the committed one.

Exploratory (fi1 B3). Reads target/fi1-pipeline3/sweep/t<threads>_<run>/ written by
fi1_thread_sweep_run.py. For every run: each candidate's validation checks with value, threshold
and margin; the selection (index and score gap to the runner-up); every promotion check with its
margin; the data-derived checks of verify_physical_world_model.py; and the digests.
"""

from __future__ import annotations

import math
from pathlib import Path

import fi1_thread_compare as compare

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "research"
WORK = ROOT / "target" / "fi1-pipeline3" / "sweep"
H = ("h1", "h3", "h5")


def geometric(values) -> float:
    values = list(values)
    return math.exp(sum(math.log(max(v, 1e-12)) for v in values) / len(values))


def candidate_gates(index: int, candidate: dict) -> list:
    sel = candidate["selection"]
    anti = candidate["anti_collapse"]
    p = f"candidate {index}: "
    out = [
        compare.gate(p + "original validation worst ratio <= 1.02", max(sel["original_ratios"].values()), 1.02, "<="),
        compare.gate(p + "incident validation geometric ratio <= 0.95", geometric(sel["incident_ratios"].values()), 0.95, "<="),
        compare.gate(p + "incident validation worst ratio <= 1.0", max(sel["incident_ratios"].values()), 1.0, "<="),
        compare.gate(p + "latent standard deviation >= 0.02", anti["latent_standard_deviation"], 0.02, ">="),
        compare.gate(p + "effective rank >= 4", anti["effective_rank"], 4.0, ">="),
        compare.gate(p + "action sensitivity >= 0.005", anti["action_sensitivity"], 0.005, ">="),
    ]  # fmt: skip
    if sel.get("stress_ratios"):
        out += [
            compare.gate(p + "stress validation geometric ratio <= 0.95", geometric(sel["stress_ratios"].values()), 0.95, "<="),
            compare.gate(p + "stress validation worst ratio <= 1.0", max(sel["stress_ratios"].values()), 1.0, "<="),
        ]  # fmt: skip
    return out


def promotion_gates(report: dict) -> list:
    cand, cur = report["candidate_test"], report["current_test"]

    def ratios(split):
        return [cand[split]["rollout"][h] / cur[split]["rollout"][h] for h in H]

    ci = cand["incident_test"]["diagnostics"]["rules_plus_jepa"]
    ui = cur["incident_test"]["diagnostics"]["rules_plus_jepa"]
    co, uo = cand["ood_test"]["rules_plus_jepa"], cur["ood_test"]["rules_plus_jepa"]
    p = "promotion: "
    out = [
        compare.gate(p + "original test worst ratio <= 1.02", max(ratios("original_test")), 1.02, "<="),
        compare.gate(p + "incident test geometric ratio <= 0.90", geometric(ratios("incident_test")), 0.90, "<="),
        compare.gate(p + "incident test worst ratio <= 1.0", max(ratios("incident_test")), 1.0, "<="),
        compare.gate(p + "incident test false negatives not increased", ci["fn"], ui["fn"], "<="),
        compare.gate(p + "incident test FPR within 2 points", ci["false_positive_rate"], ui["false_positive_rate"] + 0.02, "<="),
        compare.gate(p + "OOD one-step error <= 0.95 x current", cand["ood_test"]["normalized_one_step_error"], cur["ood_test"]["normalized_one_step_error"] * 0.95, "<="),
        compare.gate(p + "OOD false negatives not increased", co["fn"], uo["fn"], "<="),
        compare.gate(p + "OOD FPR within 2 points", co["false_positive_rate"], uo["false_positive_rate"] + 0.02, "<="),
    ]  # fmt: skip
    if "stress_test" in cand:
        out += [
            compare.gate(p + "stress test geometric ratio <= 0.90", geometric(ratios("stress_test")), 0.90, "<="),
            compare.gate(p + "stress test worst ratio <= 1.0", max(ratios("stress_test")), 1.0, "<="),
        ]  # fmt: skip
    return out


def verifier_gates(report: dict) -> list:
    """verify_physical_world_model.py checks that read numbers a rerun produces."""
    cand, cur = report["candidate_test"], report["current_test"]
    p = "verifier: "
    out = [
        compare.gate(p + "selected candidate index is 3", report["selected_candidate_index"], 3, "==", "verifier"),
        compare.gate(p + "OOD invalid observations rejected is 682", cand["ood_test"].get("invalid_observations_rejected"), 682, "==", "verifier"),
        compare.gate(p + "OOD rules_plus_jepa fn is 0", cand["ood_test"]["rules_plus_jepa"]["fn"], 0, "==", "verifier"),
        compare.gate(p + "ordinary test false negatives is 8", cand["original_test"]["diagnostics"]["rules_plus_jepa"]["fn"], 8, "==", "verifier"),
        compare.gate(p + "incident test false negatives is 1", cand["incident_test"]["diagnostics"]["rules_plus_jepa"]["fn"], 1, "==", "verifier"),
        compare.gate(p + "stress test false negatives is 1", cand["stress_test"]["diagnostics"]["rules_plus_jepa"]["fn"], 1, "==", "verifier"),
    ]  # fmt: skip
    for split in ("original_test", "incident_test", "stress_test"):
        out.append(
            compare.gate(
                p + f"{split} H=3 below deployed baseline",
                cand[split]["rollout"]["h3"],
                cur[split]["rollout"]["h3"],
                "<",
                "verifier",
            )
        )
    return out


def selection_summary(report: dict) -> dict:
    cands = report["candidates"]
    accepted = [i for i, c in enumerate(cands) if c["selection"]["accepted"]]
    pool = accepted or list(range(len(cands)))
    ranked = sorted(pool, key=lambda i: cands[i]["selection"]["selection_score"])
    gap = None
    if len(ranked) > 1:
        a, b = (cands[i]["selection"]["selection_score"] for i in ranked[:2])
        gap = (b - a) / a
    return {
        "selected_index": report["selected_candidate_index"],
        "accepted": accepted,
        "scores": [round(c["selection"]["selection_score"], 6) for c in cands],
        "epochs_completed": [c["epochs_completed"] for c in cands],
        "runner_up": ranked[1] if len(ranked) > 1 else None,
        "relative_score_gap_to_runner_up": gap,
        "promotion_passed": report["promotion"]["passed"],
        "promotion_failed_checks": [
            k for k, v in report["promotion"]["checks"].items() if not v
        ],
    }


def all_gates(report: dict) -> list:
    out = []
    for i, c in enumerate(report["candidates"]):
        out += candidate_gates(i, c)
    return out + promotion_gates(report) + verifier_gates(report)


def study_sweep() -> dict:
    committed = compare.load(RESEARCH / "physical_jepa_v3_selection.json")
    deployed = compare.sha256(
        RESEARCH / "artifacts" / "physical-jepa-v5" / "baseline_v3.bin"
    )
    table = {
        "committed": {
            "selection": selection_summary(committed),
            "gates": all_gates(committed),
        }
    }
    for folder in sorted(WORK.glob("t*_run*")):
        path = folder / "selection.json"
        if not path.exists():
            continue
        report = compare.load(path)
        table[folder.name] = {
            "selection": selection_summary(report),
            "checkpoint_identical_to_deployed": compare.sha256(folder / "model.bin")
            == deployed,
            "dataset_identical": compare.sha256(folder / "dataset.jsonl")
            == committed["dataset_sha256"],
            "diff_candidates": compare.diff_summary(
                report["candidates"], committed["candidates"]
            ),
            "diff_current_test": compare.diff_summary(
                report["current_test"], committed["current_test"]
            ),
            "gates": all_gates(report),
            "run": compare.load(folder / "run.json")
            if (folder / "run.json").exists()
            else None,
        }
    return {
        "study": "physical_jepa_v3_sweep",
        "committed_file": "docs/research/physical_jepa_v3_selection.json",
        "runs": table,
        "flips": compare.flips(table),
        "closest": compare.closest(table),
    }
