#!/usr/bin/env python3
"""Recover the sealed JEPA-output ablation result from retained complete catalogs."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

import run_physical_jepa_safety_gymnasium as benchmark
import run_physical_jepa_safety_gymnasium_output_ablation_v1 as analysis


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_recovery_protocol_v2.json"
)
RESULT_PATH = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_recovery_result_v2.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def registered_commit(protocol: dict) -> str:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    for record in protocol["toolchain"].values():
        path = record["path"]
        tracked = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", commit, "--", path],
            cwd=ROOT,
            text=True,
        ).strip()
        if tracked != path:
            raise ValueError(
                f"recovery toolchain file is not committed at HEAD: {path}"
            )
        if sha256(ROOT / path) != record["sha256"]:
            raise ValueError(f"recovery toolchain digest mismatch: {path}")
    return commit


def protected_snapshot(protocol: dict) -> dict[str, str]:
    snapshot = {}
    for name, record in protocol["protected_files"].items():
        observed = sha256(ROOT / record["path"])
        if observed != record["sha256"]:
            raise ValueError(
                f"protected file differs from recovery registration: {name}"
            )
        snapshot[name] = observed
    return snapshot


def reconstruct_episode_summaries(path: Path) -> list[dict]:
    episodes: dict[int, dict] = {}
    expected_next_step: dict[int, int] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            case = json.loads(line)
            seed = int(case["seed"])
            step = int(case["step"])
            if step != expected_next_step.get(seed, 0):
                raise ValueError(f"non-contiguous case sequence for seed {seed}")
            expected_next_step[seed] = step + 1
            episode = episodes.setdefault(
                seed,
                {
                    "seed": seed,
                    "proposals": 0,
                    "dangerous_proposals": 0,
                    "safe_proposals": 0,
                    "interventions": 0,
                    "true_positive_interventions": 0,
                    "false_positive_interventions": 0,
                    "false_negative_proposals": 0,
                    "true_negative_proposals": 0,
                    "warnings": 0,
                    "true_positive_warnings": 0,
                    "false_positive_warnings": 0,
                    "false_negative_warnings": 0,
                    "true_negative_warnings": 0,
                    "dangerous_recall_numerator": 0,
                    "safe_false_positive_numerator": 0,
                    "actual_hazard_cost_events": 0,
                    "actual_total_cost_events": 0,
                    "actual_vase_cost_events": 0,
                    "learned_only_interventions": 0,
                    "learned_only_dangerous_interventions": 0,
                    "base_controller_divergences": 0,
                    "task_completed": False,
                    "steps": 0,
                },
            )
            dangerous = bool(case["dangerous_proposal"])
            intervention = bool(case["intervention"])
            warning = bool(case["warning"])
            learned_only = case["intervention_source"] == "learned"
            episode["proposals"] += 1
            episode["dangerous_proposals"] += int(dangerous)
            episode["safe_proposals"] += int(not dangerous)
            episode["interventions"] += int(intervention)
            episode["true_positive_interventions"] += int(intervention and dangerous)
            episode["false_positive_interventions"] += int(
                intervention and not dangerous
            )
            episode["false_negative_proposals"] += int(not intervention and dangerous)
            episode["true_negative_proposals"] += int(
                not intervention and not dangerous
            )
            episode["warnings"] += int(warning)
            episode["true_positive_warnings"] += int(warning and dangerous)
            episode["false_positive_warnings"] += int(warning and not dangerous)
            episode["false_negative_warnings"] += int(not warning and dangerous)
            episode["true_negative_warnings"] += int(not warning and not dangerous)
            episode["dangerous_recall_numerator"] += int(warning and dangerous)
            episode["safe_false_positive_numerator"] += int(warning and not dangerous)
            episode["actual_hazard_cost_events"] += int(case["actual_hazard_cost"])
            episode["actual_total_cost_events"] += int(case["actual_total_cost"])
            episode["actual_vase_cost_events"] += int(case["actual_vase_cost"])
            episode["learned_only_interventions"] += int(intervention and learned_only)
            episode["learned_only_dangerous_interventions"] += int(
                intervention and learned_only and dangerous
            )
            episode["base_controller_divergences"] += int(
                not np.allclose(
                    case["proposed_action"],
                    case["naive_proposed_action"],
                    atol=1e-12,
                    rtol=0.0,
                )
            )
            episode["task_completed"] = bool(
                episode["task_completed"] or case["goal_reached"]
            )
            episode["steps"] = step + 1
    return [episodes[seed] for seed in sorted(episodes)]


def main() -> None:
    if RESULT_PATH.exists():
        raise FileExistsError("recovery result already exists")
    protocol = load_json(PROTOCOL_PATH)
    commit = registered_commit(protocol)
    for group in ("registered_inputs", "retained_execution_catalogs"):
        for record in protocol[group].values():
            if sha256(ROOT / record["path"]) != record["sha256"]:
                raise ValueError(f"registered recovery input changed: {record['path']}")

    source = load_json(ROOT / protocol["registered_inputs"]["source_protocol"]["path"])
    runtime = benchmark.runtime_evidence(source)
    if not runtime["versions_match"] or not runtime["source_matches"]:
        raise ValueError(f"locked Safety-Gymnasium runtime mismatch: {runtime}")
    protected_before = protected_snapshot(protocol)
    arms = {}
    for index, arm in enumerate(protocol["arms"]):
        catalog = protocol["retained_execution_catalogs"][arm["id"]]
        episodes = reconstruct_episode_summaries(ROOT / catalog["path"])
        aggregate = benchmark.aggregate(episodes)
        aggregate["intervention_precision"] = aggregate[
            "true_positive_interventions"
        ] / max(1, aggregate["interventions"])
        arms[arm["id"]] = {
            "adapter": protocol["frozen_warning_pipeline"]["adapter"],
            "feature_intervention": arm["feature_intervention"],
            "learned_risk_threshold": protocol["frozen_policy"][
                "learned_risk_threshold"
            ],
            "aggregate": aggregate,
            "episode_statistics": analysis.episode_statistics(episodes),
            "episode_bootstrap_95": benchmark.bootstrap(
                episodes,
                seed=protocol["uncertainty"]["absolute_bootstrap_seed"] + index,
                resamples=protocol["uncertainty"]["absolute_bootstrap_resamples"],
            ),
            "case_catalog": catalog,
            "episode_summaries": episodes,
        }
    contrast = analysis.paired_bootstrap(
        arms["observed-frozen-jepa"]["episode_summaries"],
        arms["development-mean-masked-jepa"]["episode_summaries"],
        seed=protocol["uncertainty"]["paired_bootstrap_seed"],
        resamples=protocol["uncertainty"]["paired_bootstrap_resamples"],
    )
    protected_after = protected_snapshot(protocol)
    if protected_before != protected_after:
        raise ValueError("a protected report or model changed during recovery analysis")
    result = {
        "schema": "physical-jepa-safety-gymnasium-output-ablation-recovery-result-v2",
        "protocol": {
            "path": PROTOCOL_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256(PROTOCOL_PATH),
            "registered_commit": commit,
        },
        "execution_evidence": {
            "fresh_seed_range": protocol["fresh_seed_execution"]["seed_range"],
            "simulator_rerun_during_recovery": False,
            "source_failed_attempt": protocol["registered_inputs"]["failed_attempt"],
            "case_catalogs_reused_without_modification": True,
        },
        "runtime": runtime,
        "arms": arms,
        "paired_output_contribution": contrast,
        "outcome_retention": {
            "all_registered_arms_written": True,
            "all_reconstructed_episode_summaries_written": True,
            "all_step_catalogs_retained_by_digest": True,
            "all_paired_effects_and_signs_written": True,
            "null_intervals_written": contrast["intervals_including_zero_retained"],
            "failed_attempt_retained": True,
        },
        "authority": {
            "physical_actuator_attempts": 0,
            "physical_actuator_deliveries": 0,
            "protected_before_sha256": protected_before,
            "protected_after_sha256": protected_after,
            "protected_files_unchanged": True,
            "promotion_eligible": False,
            "promotion_attempted": False,
        },
        "claim_boundary": protocol["claim_boundary"],
    }
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(RESULT_PATH.relative_to(ROOT).as_posix())
    for name, record in arms.items():
        values = record["aggregate"]
        print(
            f"{name}: completion={values['task_completion_rate']:.4f} "
            f"warnings={values['warning_recall']:.4f}/"
            f"{values['warning_false_positive_rate']:.4f} "
            f"intervention={values['intervention_rate']:.4f} "
            f"precision={values['intervention_precision']:.4f} "
            f"hazard_steps={values['actual_hazard_cost_events']}"
        )
    print("paired observed-minus-masked effects:")
    print(json.dumps(contrast["effects"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
