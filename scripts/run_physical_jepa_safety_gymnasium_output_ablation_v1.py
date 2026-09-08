#!/usr/bin/env python3
"""Run the sealed fresh-seed ablation of frozen JEPA output values."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

import evaluate_physical_jepa_robustness as robustness
import run_physical_jepa_safety_gymnasium as benchmark


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_protocol_v1.json"
)
RESULT_PATH = (
    ROOT / "docs/research/physical_jepa_safety_gymnasium_output_ablation_result_v1.json"
)
CASES_DIR = (
    ROOT / "docs/research/artifacts/physical-jepa-safety-output-ablation-v1/final-cases"
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
                f"registered toolchain file is not committed at HEAD: {path}"
            )
        if sha256(ROOT / path) != record["sha256"]:
            raise ValueError(f"registered toolchain digest mismatch: {path}")
    return commit


def episode_statistics(episodes: list[dict]) -> dict:
    steps = np.asarray([item["steps"] for item in episodes], dtype=np.float64)
    hazardous = np.asarray(
        [item["actual_hazard_cost_events"] > 0 for item in episodes],
        dtype=np.float64,
    )
    completed_steps = np.asarray(
        [item["steps"] for item in episodes if item["task_completed"]],
        dtype=np.float64,
    )
    return {
        "episodes_with_actual_hazard_cost": int(np.sum(hazardous)),
        "hazardous_episode_rate": float(np.mean(hazardous)),
        "mean_episode_steps": float(np.mean(steps)),
        "median_episode_steps": float(np.median(steps)),
        "mean_completed_episode_steps": (
            None if completed_steps.size == 0 else float(np.mean(completed_steps))
        ),
    }


def summary_metrics(episodes: list[dict]) -> dict:
    aggregate = benchmark.aggregate(episodes)
    aggregate["intervention_precision"] = aggregate[
        "true_positive_interventions"
    ] / max(1, aggregate["interventions"])
    return aggregate | episode_statistics(episodes)


def paired_metrics(left: list[dict], right: list[dict]) -> dict[str, float]:
    left_metrics = summary_metrics(left)
    right_metrics = summary_metrics(right)
    return {
        "task_completion_percentage_points": 100.0
        * (
            left_metrics["task_completion_rate"] - right_metrics["task_completion_rate"]
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
            left_metrics["mean_episode_steps"] - right_metrics["mean_episode_steps"]
        ),
    }


def paired_bootstrap(
    left: list[dict],
    right: list[dict],
    seed: int,
    resamples: int = 10000,
) -> dict:
    left_by_seed = {int(item["seed"]): item for item in left}
    right_by_seed = {int(item["seed"]): item for item in right}
    seeds = sorted(left_by_seed)
    if seeds != sorted(right_by_seed):
        raise ValueError("paired episode seeds differ")
    estimates = paired_metrics(left, right)
    samples = {name: [] for name in estimates}
    rng = np.random.default_rng(seed)
    for _ in range(resamples):
        sampled = rng.integers(0, len(seeds), size=len(seeds))
        left_sample = [left_by_seed[seeds[index]] for index in sampled]
        right_sample = [right_by_seed[seeds[index]] for index in sampled]
        for name, value in paired_metrics(left_sample, right_sample).items():
            samples[name].append(value)
    effects = {}
    for name, values in samples.items():
        lower = float(np.quantile(values, 0.025))
        upper = float(np.quantile(values, 0.975))
        effects[name] = {
            "estimate": float(estimates[name]),
            "bootstrap_95_percent": [lower, upper],
            "interval_excludes_zero": bool(lower > 0.0 or upper < 0.0),
        }
    return {
        "contrast": "observed-frozen-jepa minus development-mean-masked-jepa",
        "paired_seeds": len(seeds),
        "resamples": resamples,
        "effects": effects,
        "intervals_including_zero_retained": [
            name
            for name, record in effects.items()
            if not record["interval_excludes_zero"]
        ],
    }


def write_cases(path: Path, cases: list[dict]) -> dict:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            for case in cases:
                line = json.dumps(case, sort_keys=True, separators=(",", ":")) + "\n"
                compressed.write(line.encode("utf-8"))
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "rows": len(cases),
        "compression": "gzip with mtime=0",
    }


def protected_snapshot(protocol: dict) -> dict[str, str]:
    snapshot = {}
    for name, record in protocol["protected_files"].items():
        path = ROOT / record["path"]
        observed = sha256(path)
        if observed != record["sha256"]:
            raise ValueError(f"protected file differs from registration: {name}")
        snapshot[name] = observed
    return snapshot


def main() -> None:
    if RESULT_PATH.exists() or CASES_DIR.exists():
        raise FileExistsError("ablation result or final case directory already exists")
    protocol = load_json(PROTOCOL_PATH)
    commit = registered_commit(protocol)
    for record in protocol["registered_inputs"].values():
        if sha256(ROOT / record["path"]) != record["sha256"]:
            raise ValueError(f"registered input changed: {record['path']}")
    for record in protocol["retained_prior_evidence"].values():
        if sha256(ROOT / record["path"]) != record["sha256"]:
            raise ValueError(f"retained prior evidence changed: {record['path']}")

    source_path = ROOT / protocol["registered_inputs"]["source_protocol"]["path"]
    source = load_json(source_path)
    runtime = benchmark.runtime_evidence(source)
    if not runtime["versions_match"] or not runtime["source_matches"]:
        raise ValueError(f"locked Safety-Gymnasium runtime mismatch: {runtime}")

    artifact = ROOT / protocol["frozen_artifact"]["path"]
    adapter_path = ROOT / protocol["frozen_warning_pipeline"]["adapter"]["path"]
    if sha256(artifact) != protocol["frozen_artifact"]["sha256"]:
        raise ValueError("frozen Physical JEPA v5 artifact mismatch")
    if sha256(adapter_path) != protocol["frozen_warning_pipeline"]["adapter"]["sha256"]:
        raise ValueError("frozen risk adapter mismatch")
    weights = robustness.load_artifact(artifact)
    protected_before = protected_snapshot(protocol)

    boundary = protocol["prospective_boundary"]["fresh_final_seed_range"]
    seeds = list(range(boundary["start"], boundary["start"] + boundary["count"]))
    policy = copy.deepcopy(protocol["frozen_policy"])
    arms = {}
    CASES_DIR.mkdir(parents=True)
    for index, arm in enumerate(protocol["arms"]):
        variant_protocol = copy.deepcopy(source)
        variant_protocol["execution_workers"] = protocol["execution_workers"]
        variant_protocol["learned_risk_adapter"] = {
            "path": protocol["frozen_warning_pipeline"]["adapter"]["path"],
            "sha256": protocol["frozen_warning_pipeline"]["adapter"]["sha256"],
            "feature_intervention": arm["feature_intervention"],
        }
        episodes, cases = benchmark.run_policy(
            seeds,
            protocol["frozen_warning_pipeline"]["runner_arm"],
            copy.deepcopy(policy),
            variant_protocol,
            weights,
            True,
        )
        aggregate = benchmark.aggregate(episodes)
        aggregate["intervention_precision"] = aggregate[
            "true_positive_interventions"
        ] / max(1, aggregate["interventions"])
        arms[arm["id"]] = {
            "feature_intervention": arm["feature_intervention"],
            "adapter": protocol["frozen_warning_pipeline"]["adapter"],
            "learned_risk_threshold": policy["learned_risk_threshold"],
            "aggregate": aggregate,
            "episode_statistics": episode_statistics(episodes),
            "episode_bootstrap_95": benchmark.bootstrap(
                episodes,
                seed=protocol["uncertainty"]["absolute_bootstrap_seed"] + index,
                resamples=protocol["uncertainty"]["absolute_bootstrap_resamples"],
            ),
            "case_catalog": write_cases(CASES_DIR / f"{arm['id']}.jsonl.gz", cases),
            "episode_summaries": episodes,
        }

    contrast = paired_bootstrap(
        arms["observed-frozen-jepa"]["episode_summaries"],
        arms["development-mean-masked-jepa"]["episode_summaries"],
        seed=protocol["uncertainty"]["paired_bootstrap_seed"],
        resamples=protocol["uncertainty"]["paired_bootstrap_resamples"],
    )
    protected_after = protected_snapshot(protocol)
    protected_unchanged = protected_before == protected_after
    result = {
        "schema": "physical-jepa-safety-gymnasium-output-ablation-result-v1",
        "protocol": {
            "path": PROTOCOL_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256(PROTOCOL_PATH),
            "registered_commit": commit,
        },
        "runtime": runtime,
        "fresh_final_seed_range": boundary,
        "final_seed_range_opened_once_for_registered_two_arm_run": True,
        "arms": arms,
        "paired_output_contribution": contrast,
        "outcome_retention": {
            "all_registered_arms_written": True,
            "all_episode_summaries_written": True,
            "all_step_cases_written": True,
            "all_paired_effects_and_signs_written": True,
            "null_intervals_written": contrast["intervals_including_zero_retained"],
            "prior_negative_and_failed_evidence_left_in_place": list(
                protocol["retained_prior_evidence"]
            ),
        },
        "authority": {
            "physical_actuator_attempts": 0,
            "physical_actuator_deliveries": 0,
            "protected_before_sha256": protected_before,
            "protected_after_sha256": protected_after,
            "protected_files_unchanged": protected_unchanged,
            "promotion_eligible": False,
            "promotion_attempted": False,
        },
        "claim_boundary": protocol["claim_boundary"],
    }
    if not protected_unchanged:
        raise ValueError("a protected report or model changed during the ablation")
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
