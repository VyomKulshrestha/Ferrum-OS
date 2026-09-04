#!/usr/bin/env python3
"""Run the once-opened Safety-Gymnasium risk-source attribution benchmark."""

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
PROTOCOL_PATH = ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_protocol_v2.json"
RESULT_PATH = ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_result_v2.json"
CASES_DIR = ROOT / "docs/research/artifacts/physical-jepa-safety-attribution-v2/final-cases"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def registration_commit() -> str:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    tracked = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", commit, "--", str(PROTOCOL_PATH.relative_to(ROOT))],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked != str(PROTOCOL_PATH.relative_to(ROOT)).replace("\\", "/"):
        raise ValueError("attribution protocol is not committed at HEAD")
    return commit


def episode_statistics(episodes: list[dict]) -> dict:
    steps = np.asarray([item["steps"] for item in episodes], dtype=np.float64)
    hazardous = np.asarray(
        [item["actual_hazard_cost_events"] > 0 for item in episodes], dtype=np.float64
    )
    completed_steps = np.asarray(
        [item["steps"] for item in episodes if item["task_completed"]], dtype=np.float64
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


def paired_bootstrap(
    left: list[dict], right: list[dict], seed: int, resamples: int = 10000
) -> dict:
    left_by_seed = {int(item["seed"]): item for item in left}
    right_by_seed = {int(item["seed"]): item for item in right}
    seeds = sorted(left_by_seed)
    if seeds != sorted(right_by_seed):
        raise ValueError("paired episode seeds differ")
    rng = np.random.default_rng(seed)
    completion = []
    hazard_steps = []
    hazardous_episode_rate = []
    mean_episode_steps = []
    intervention_rate = []
    for _ in range(resamples):
        sampled = rng.integers(0, len(seeds), size=len(seeds))
        left_sample = [left_by_seed[seeds[index]] for index in sampled]
        right_sample = [right_by_seed[seeds[index]] for index in sampled]
        left_metrics = benchmark.aggregate(left_sample)
        right_metrics = benchmark.aggregate(right_sample)
        completion.append(
            100.0
            * (left_metrics["task_completion_rate"] - right_metrics["task_completion_rate"])
        )
        hazard_steps.append(
            left_metrics["actual_hazard_cost_events"]
            - right_metrics["actual_hazard_cost_events"]
        )
        hazardous_episode_rate.append(
            100.0
            * (
                left_metrics["episodes_with_actual_hazard_cost"] / len(left_sample)
                - right_metrics["episodes_with_actual_hazard_cost"] / len(right_sample)
            )
        )
        mean_episode_steps.append(
            left_metrics["steps"] / len(left_sample)
            - right_metrics["steps"] / len(right_sample)
        )
        intervention_rate.append(
            100.0 * (left_metrics["intervention_rate"] - right_metrics["intervention_rate"])
        )

    left_metrics = benchmark.aggregate(left)
    right_metrics = benchmark.aggregate(right)
    estimates = {
        "completion_percentage_points": 100.0
        * (left_metrics["task_completion_rate"] - right_metrics["task_completion_rate"]),
        "actual_hazard_cost_steps": left_metrics["actual_hazard_cost_events"]
        - right_metrics["actual_hazard_cost_events"],
        "hazardous_episode_percentage_points": 100.0
        * (
            left_metrics["episodes_with_actual_hazard_cost"] / len(left)
            - right_metrics["episodes_with_actual_hazard_cost"] / len(right)
        ),
        "mean_episode_steps": left_metrics["steps"] / len(left)
        - right_metrics["steps"] / len(right),
        "intervention_percentage_points": 100.0
        * (left_metrics["intervention_rate"] - right_metrics["intervention_rate"]),
    }
    samples = {
        "completion_percentage_points": completion,
        "actual_hazard_cost_steps": hazard_steps,
        "hazardous_episode_percentage_points": hazardous_episode_rate,
        "mean_episode_steps": mean_episode_steps,
        "intervention_percentage_points": intervention_rate,
    }
    return {
        name: {
            "estimate": float(estimates[name]),
            "bootstrap_95_percent": [
                float(np.quantile(values, 0.025)),
                float(np.quantile(values, 0.975)),
            ],
            "interval_excludes_zero": bool(
                np.quantile(values, 0.975) < 0.0 or np.quantile(values, 0.025) > 0.0
            ),
        }
        for name, values in samples.items()
    } | {"resamples": resamples, "paired_seeds": len(seeds)}


def write_cases(path: Path, cases: list[dict]) -> dict:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            for case in cases:
                line = json.dumps(case, sort_keys=True, separators=(",", ":")) + "\n"
                compressed.write(line.encode("utf-8"))
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": sha256(path),
        "rows": len(cases),
        "compression": "gzip with mtime=0",
    }


def main() -> None:
    if RESULT_PATH.exists() or CASES_DIR.exists():
        raise FileExistsError("attribution result or final case directory already exists")
    protocol = load_json(PROTOCOL_PATH)
    registered_commit = registration_commit()
    source_protocol_path = ROOT / protocol["source_study"]["protocol"]["path"]
    if sha256(source_protocol_path) != protocol["source_study"]["protocol"]["sha256"]:
        raise ValueError("source v14 protocol changed after attribution registration")
    source = load_json(source_protocol_path)
    runtime = benchmark.runtime_evidence(source)
    if not runtime["versions_match"] or not runtime["source_matches"]:
        raise ValueError(f"locked Safety-Gymnasium runtime mismatch: {runtime}")
    artifact = ROOT / protocol["frozen_artifact"]["path"]
    deployed = ROOT / protocol["frozen_artifact"]["deployment_target"]
    artifact_before = sha256(artifact)
    deployed_before = sha256(deployed)
    if artifact_before != protocol["frozen_artifact"]["sha256"]:
        raise ValueError("frozen Physical JEPA v5 artifact mismatch")
    weights = robustness.load_artifact(artifact)
    boundary = protocol["prospective_boundary"]["final_seed_range_unopened_at_registration"]
    seeds = list(range(boundary["start"], boundary["start"] + boundary["count"]))
    policy = copy.deepcopy(protocol["frozen_policy"])

    baseline_episodes, _ = benchmark.run_policy(
        seeds, "planner_unshielded", policy, source, weights, False
    )
    baseline = {
        "aggregate": benchmark.aggregate(baseline_episodes),
        "episode_statistics": episode_statistics(baseline_episodes),
        "episode_bootstrap_95": benchmark.bootstrap(baseline_episodes, seed=2026090500),
        "episode_summaries": baseline_episodes,
    }

    CASES_DIR.mkdir(parents=True)
    variants = {}
    for index, registered in enumerate(protocol["risk_source_variants"]):
        adapter_path = ROOT / registered["path"]
        if sha256(adapter_path) != registered["sha256"]:
            raise ValueError(f"registered adapter changed: {registered['id']}")
        variant_protocol = copy.deepcopy(source)
        variant_protocol["learned_risk_adapter"] = {
            "path": registered["path"],
            "sha256": registered["sha256"],
        }
        variant_protocol["execution_workers"] = protocol["execution_workers"]
        variant_policy = copy.deepcopy(policy)
        variant_policy["learned_risk_threshold"] = registered["learned_risk_threshold"]
        episodes, cases = benchmark.run_policy(
            seeds,
            "planner_rules_plus_learned",
            variant_policy,
            variant_protocol,
            weights,
            True,
        )
        aggregate = benchmark.aggregate(episodes)
        aggregate["intervention_precision"] = aggregate["true_positive_interventions"] / max(
            1, aggregate["interventions"]
        )
        case_record = write_cases(CASES_DIR / f"{registered['id']}.jsonl.gz", cases)
        variants[registered["id"]] = {
            "risk_source": registered["risk_source"],
            "adapter": {"path": registered["path"], "sha256": registered["sha256"]},
            "learned_risk_threshold": registered["learned_risk_threshold"],
            "aggregate": aggregate,
            "episode_statistics": episode_statistics(episodes),
            "episode_bootstrap_95": benchmark.bootstrap(
                episodes, seed=2026090501 + index
            ),
            "versus_planner_paired_bootstrap": paired_bootstrap(
                episodes, baseline_episodes, seed=2026090600 + index
            ),
            "case_catalog": case_record,
            "episode_summaries": episodes,
        }

    full = variants["full-frozen-v14-adapter"]["episode_summaries"]
    for index, (name, record) in enumerate(variants.items()):
        record["versus_full_adapter_paired_bootstrap"] = paired_bootstrap(
            record["episode_summaries"], full, seed=2026090700 + index
        )

    artifact_after = sha256(artifact)
    deployed_after = sha256(deployed)
    result = {
        "schema": "physical-jepa-safety-gymnasium-risk-source-attribution-result-v2",
        "protocol": {
            "path": str(PROTOCOL_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256(PROTOCOL_PATH),
            "registered_commit": registered_commit,
        },
        "runtime": runtime,
        "final_seed_range": boundary,
        "final_seed_access_count": 1,
        "baseline_planner_unshielded": baseline,
        "variants": variants,
        "authority": {
            "physical_actuator_attempts": 0,
            "physical_actuator_deliveries": 0,
            "artifact_before_sha256": artifact_before,
            "artifact_after_sha256": artifact_after,
            "deployed_before_sha256": deployed_before,
            "deployed_after_sha256": deployed_after,
            "protected_deployed_artifact_unchanged": (
                artifact_before == artifact_after and deployed_before == deployed_after
            ),
            "promotion_eligible": False,
        },
        "claim_boundary": (
            "This locally designed and executed comparison isolates registered risk-source pipelines only within a fixed privileged-planner and tangent-correction setup; "
            "it is not architecture-only causality, independent replication, HIL, physical safety, or deployment evidence."
        ),
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(RESULT_PATH.relative_to(ROOT).as_posix())
    for name, record in variants.items():
        values = record["aggregate"]
        print(
            f"{name}: completion={values['task_completion_rate']:.4f} "
            f"warnings={values['warning_recall']:.4f}/{values['warning_false_positive_rate']:.4f} "
            f"intervention={values['intervention_rate']:.4f} precision={values['intervention_precision']:.4f} "
            f"hazard_steps={values['actual_hazard_cost_events']}"
        )


if __name__ == "__main__":
    main()
