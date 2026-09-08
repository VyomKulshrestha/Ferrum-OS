#!/usr/bin/env python3
"""Compute registered post-hoc sensitivity analyses from frozen evidence only."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cross_domain_world_model_models as models  # noqa: E402
import evaluate_cross_domain_world_models as architecture  # noqa: E402


PROTOCOL = ROOT / "docs/research/cross_domain_world_model_posthoc_sensitivity_protocol_v1.json"
OUTPUT = ROOT / "docs/research/cross_domain_world_model_posthoc_sensitivity_result_v1.json"
METHODS = ("direct_mlp", "action_conditioned_jepa", "gru_dynamics")
VARIANTS = (
    "full-frozen-v14-adapter",
    "local-sensing-without-jepa",
    "jepa-outputs-only",
    "hazard-closeness-only",
)


def expand_adapter_features(features: np.ndarray, transform: str) -> np.ndarray:
    """Mirror the frozen runtime's two transforms used by the four adapters."""
    if transform == "identity":
        return features
    if transform == "safety_summary":
        hazards = features[:16]
        summary = np.asarray(
            [
                float(np.max(hazards[10:15])),
                float(np.mean(hazards[10:15])),
                float(np.max(hazards[3:15])),
            ],
            dtype=np.float64,
        )
        return np.concatenate((features, summary))
    raise ValueError(f"unsupported registered adapter transform: {transform}")


def adapter_score(features: np.ndarray, adapter: dict) -> float:
    """Apply the frozen linear-logistic adapter without importing the simulator."""
    if not np.all(np.isfinite(features)):
        return 1.0
    expanded = expand_adapter_features(
        features, adapter.get("feature_transform", "identity")
    )
    mean = np.asarray(adapter["feature_mean"], dtype=np.float64)
    scale = np.asarray(adapter["feature_scale"], dtype=np.float64)
    weights = np.asarray(adapter["weights"], dtype=np.float64)
    if expanded.shape != mean.shape or mean.shape != scale.shape or scale.shape != weights.shape:
        raise ValueError("risk adapter feature shape mismatch")
    if (
        not np.all(np.isfinite(mean))
        or not np.all(np.isfinite(scale))
        or not np.all(np.isfinite(weights))
        or not math.isfinite(float(adapter["bias"]))
        or np.any(scale <= 0.0)
    ):
        return 1.0
    logit = float(np.dot((expanded - mean) / scale, weights) + adapter["bias"])
    if not math.isfinite(logit):
        return 1.0
    if logit >= 0.0:
        return 1.0 / (1.0 + math.exp(-logit))
    exp_logit = math.exp(logit)
    return exp_logit / (1.0 + exp_logit)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def registered_commit() -> str:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    relative = PROTOCOL.relative_to(ROOT).as_posix()
    tracked = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", commit, "--", relative],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked != relative:
        raise ValueError("post-hoc protocol is not committed at HEAD")
    committed = subprocess.check_output(
        ["git", "show", f"{commit}:{relative}"], cwd=ROOT
    )
    if hashlib.sha256(committed).hexdigest() != sha256(PROTOCOL):
        raise ValueError("working protocol differs from the registered HEAD version")
    return commit


def verify_inputs(protocol: dict) -> None:
    for name, record in protocol["inputs"].items():
        path = ROOT / record["path"]
        if not path.is_file() or sha256(path) != record["sha256"]:
            raise ValueError(f"registered input drifted: {name}")


def episode_bootstrap(
    errors: np.ndarray, episodes: np.ndarray, seed: int, resamples: int
) -> dict:
    unique = np.unique(episodes)
    values = np.asarray(
        [errors[episodes == episode].mean() for episode in unique], dtype=np.float64
    )
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(values), size=(resamples, len(values)))
    samples = values[draws].mean(axis=1)
    interval = np.quantile(samples, [0.025, 0.975])
    return {
        "estimate": float(values.mean()),
        "bootstrap_95_percent": [float(interval[0]), float(interval[1])],
        "episodes": int(len(unique)),
        "resamples": resamples,
    }


def paired_episode_bootstrap(
    left: np.ndarray,
    right: np.ndarray,
    episodes: np.ndarray,
    seed: int,
    resamples: int,
) -> dict:
    unique = np.unique(episodes)
    differences = np.asarray(
        [
            (left[episodes == episode] - right[episodes == episode]).mean()
            for episode in unique
        ],
        dtype=np.float64,
    )
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(differences), size=(resamples, len(differences)))
    samples = differences[draws].mean(axis=1)
    interval = np.quantile(samples, [0.025, 0.975])
    return {
        "estimate": float(differences.mean()),
        "bootstrap_95_percent": [float(interval[0]), float(interval[1])],
        "interval_excludes_zero": bool(interval[1] < 0.0 or interval[0] > 0.0),
        "episodes": int(len(unique)),
        "resamples": resamples,
    }


def common_episode_domain(
    domain: str,
    spec: models.DomainSpec,
    rows: list[dict],
    selection: dict,
    seed: int,
    resamples: int,
) -> dict:
    _, _, _, _, h5_episodes, _ = models.rollout_arrays(rows, spec, 5)
    common_ids = set(str(value) for value in np.unique(h5_episodes))
    common_rows = [row for row in rows if str(row["episode"]) in common_ids]
    if not common_rows:
        raise ValueError(f"{domain} has no H=5-eligible episodes")

    output = {
        "episode_rule": "episode has at least one H=5 rollout endpoint",
        "common_episode_count": len(common_ids),
        "common_row_count": len(common_rows),
        "episode_ids_sha256": models.canonical_sha256(sorted(common_ids)),
        "methods": {},
    }
    errors_by_method: dict[str, dict[int, tuple[np.ndarray, np.ndarray]]] = {}
    for method_index, method in enumerate(METHODS):
        runs = selection["methods"][method]
        loaded = [
            models.load_model(
                ROOT / run["checkpoint"]["path"],
                method,
                spec,
                run["hidden_size"],
                run["checkpoint"]["sha256"],
            )
            for run in runs
        ]
        method_record = {"ensemble_size": len(loaded), "rollout": {}}
        errors_by_method[method] = {}
        for horizon in (1, 3, 5):
            predictions = []
            members = []
            actual = episodes = None
            for run, model in zip(runs, loaded):
                predicted, current_actual, current_episodes, _ = models.rollout_predictions(
                    model, common_rows, spec, horizon
                )
                current_errors = models.normalized_errors(
                    predicted, current_actual, spec
                )
                predictions.append(predicted)
                members.append(
                    {
                        "seed": run["seed"],
                        **episode_bootstrap(
                            current_errors,
                            current_episodes,
                            seed + 1000 * method_index + 100 * horizon + run["seed"],
                            resamples,
                        ),
                    }
                )
                actual, episodes = current_actual, current_episodes
            ensemble = np.stack(predictions).mean(axis=0)
            ensemble_errors = models.normalized_errors(ensemble, actual, spec)
            errors_by_method[method][horizon] = (ensemble_errors, episodes)
            method_record["rollout"][f"h{horizon}"] = {
                "members": members,
                "ensemble": episode_bootstrap(
                    ensemble_errors,
                    episodes,
                    seed + 10000 * method_index + horizon,
                    resamples,
                ),
                "rollout_endpoints": int(len(ensemble_errors)),
            }
        output["methods"][method] = method_record

    comparisons = {}
    pair_index = 0
    for left_index, left in enumerate(METHODS):
        for right in METHODS[left_index + 1 :]:
            record = {}
            for horizon in (1, 3, 5):
                left_errors, episodes = errors_by_method[left][horizon]
                right_errors, right_episodes = errors_by_method[right][horizon]
                if not np.array_equal(episodes, right_episodes):
                    raise AssertionError("common-episode endpoints drifted between methods")
                record[f"h{horizon}"] = paired_episode_bootstrap(
                    left_errors,
                    right_errors,
                    episodes,
                    seed + 50000 + 1000 * pair_index + horizon,
                    resamples,
                )
            comparisons[f"{left}_minus_{right}"] = record
            pair_index += 1
    output["paired_architecture_comparisons"] = comparisons
    return output


def aggregate_episode_sample(items: list[dict], indices: np.ndarray) -> tuple[int, int, int, int]:
    hazards = np.asarray(
        [item["actual_hazard_cost_events"] for item in items], dtype=np.int64
    )
    interventions = np.asarray([item["interventions"] for item in items], dtype=np.int64)
    proposals = np.asarray([item["proposals"] for item in items], dtype=np.int64)
    completions = np.asarray([item["task_completed"] for item in items], dtype=np.int64)
    return (
        int(hazards[indices].sum()),
        int(interventions[indices].sum()),
        int(proposals[indices].sum()),
        int(completions[indices].sum()),
    )


def paired_samples(
    left: list[dict], right: list[dict], seed: int, resamples: int
) -> dict[str, np.ndarray | float]:
    left_by_seed = {int(item["seed"]): item for item in left}
    right_by_seed = {int(item["seed"]): item for item in right}
    seeds = sorted(left_by_seed)
    if seeds != sorted(right_by_seed):
        raise ValueError("attribution episode seeds differ")
    left_items = [left_by_seed[value] for value in seeds]
    right_items = [right_by_seed[value] for value in seeds]
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(seeds), size=(resamples, len(seeds)))

    def array(key: str, values: list[dict]) -> np.ndarray:
        return np.asarray([item[key] for item in values], dtype=np.float64)

    left_hazard = array("actual_hazard_cost_events", left_items)
    right_hazard = array("actual_hazard_cost_events", right_items)
    left_interventions = array("interventions", left_items)
    right_interventions = array("interventions", right_items)
    left_proposals = array("proposals", left_items)
    right_proposals = array("proposals", right_items)
    left_completion = array("task_completed", left_items)
    right_completion = array("task_completed", right_items)
    return {
        "seeds": np.asarray(seeds, dtype=np.int64),
        "hazard_episode_differences": left_hazard - right_hazard,
        "intervention_episode_differences": left_interventions - right_interventions,
        "completion_episode_differences": left_completion - right_completion,
        "hazard_samples": left_hazard[draws].sum(axis=1)
        - right_hazard[draws].sum(axis=1),
        "intervention_samples": 100.0
        * (
            left_interventions[draws].sum(axis=1)
            / left_proposals[draws].sum(axis=1)
            - right_interventions[draws].sum(axis=1)
            / right_proposals[draws].sum(axis=1)
        ),
        "completion_samples": 100.0
        * (left_completion[draws].mean(axis=1) - right_completion[draws].mean(axis=1)),
        "hazard_estimate": float(left_hazard.sum() - right_hazard.sum()),
        "intervention_estimate": float(
            100.0
            * (
                left_interventions.sum() / left_proposals.sum()
                - right_interventions.sum() / right_proposals.sum()
            )
        ),
        "completion_estimate": float(
            100.0 * (left_completion.mean() - right_completion.mean())
        ),
    }


def interval_record(samples: np.ndarray, estimate: float, alpha: float) -> dict:
    lower, upper = np.quantile(samples, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "estimate": estimate,
        "confidence_level": 1.0 - alpha,
        "percentile_interval": [float(lower), float(upper)],
        "interval_excludes_zero": bool(upper < 0.0 or lower > 0.0),
    }


def count_directions(values: np.ndarray, *, lower_is_better: bool) -> dict:
    improved = values < 0 if lower_is_better else values > 0
    worsened = values > 0 if lower_is_better else values < 0
    return {
        "improved": int(np.sum(improved)),
        "worsened": int(np.sum(worsened)),
        "unchanged": int(np.sum(values == 0)),
        "direction_definition": (
            "negative paired difference is improved"
            if lower_is_better
            else "positive paired difference is improved"
        ),
    }


def leave_one_out(
    left: list[dict],
    right: list[dict],
    seed_base: int,
    resamples: int,
) -> dict:
    left_by_seed = {int(item["seed"]): item for item in left}
    right_by_seed = {int(item["seed"]): item for item in right}
    seeds = sorted(left_by_seed)
    records = []
    for index, omitted in enumerate(seeds):
        keep = [seed for seed in seeds if seed != omitted]
        values = paired_samples(
            [left_by_seed[seed] for seed in keep],
            [right_by_seed[seed] for seed in keep],
            seed_base + index,
            resamples,
        )
        records.append(
            {
                "omitted_seed": omitted,
                "hazard_steps": interval_record(
                    values["hazard_samples"], values["hazard_estimate"], 0.05
                ),
                "intervention_percentage_points": interval_record(
                    values["intervention_samples"],
                    values["intervention_estimate"],
                    0.05,
                ),
            }
        )
    return {
        "omissions": len(records),
        "resamples_per_omission": resamples,
        "all_hazard_intervals_exclude_zero": all(
            item["hazard_steps"]["interval_excludes_zero"] for item in records
        ),
        "all_intervention_intervals_exclude_zero": all(
            item["intervention_percentage_points"]["interval_excludes_zero"]
            for item in records
        ),
        "hazard_interval_endpoint_range": [
            min(item["hazard_steps"]["percentile_interval"][0] for item in records),
            max(item["hazard_steps"]["percentile_interval"][1] for item in records),
        ],
        "intervention_interval_endpoint_range": [
            min(
                item["intervention_percentage_points"]["percentile_interval"][0]
                for item in records
            ),
            max(
                item["intervention_percentage_points"]["percentile_interval"][1]
                for item in records
            ),
        ],
        "records": records,
    }


def common_proposal_metrics(protocol: dict) -> dict:
    attribution_protocol = load_json(ROOT / protocol["inputs"]["attribution_protocol"]["path"])
    catalog = ROOT / protocol["inputs"]["common_proposal_catalog"]["path"]
    registered = {
        item["id"]: item for item in attribution_protocol["risk_source_variants"]
    }
    variants = {}
    with gzip.open(catalog, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    labels = np.asarray([bool(row["dangerous_proposal"]) for row in rows])
    rule_blocks = np.asarray([bool(row["rule_block"]) for row in rows])
    features = [np.asarray(row["risk_adapter_features"], dtype=np.float64) for row in rows]
    motion = np.asarray(
        [
            np.linalg.norm(row["proposed_action"]) > 1e-12 or feature[21] > 1e-6
            for row, feature in zip(rows, features)
        ]
    )
    for name in VARIANTS:
        item = registered[name]
        adapter_path = ROOT / item["path"]
        if sha256(adapter_path) != item["sha256"]:
            raise ValueError(f"attribution adapter drifted: {name}")
        adapter = load_json(adapter_path)
        scores = np.asarray(
            [adapter_score(feature, adapter) for feature in features]
        )
        warnings = rule_blocks | (motion & (scores >= item["learned_risk_threshold"]))
        tp = int(np.sum(warnings & labels))
        fn = int(np.sum(~warnings & labels))
        fp = int(np.sum(warnings & ~labels))
        tn = int(np.sum(~warnings & ~labels))
        variants[name] = {
            "threshold": item["learned_risk_threshold"],
            "tp": tp,
            "fn": fn,
            "fp": fp,
            "tn": tn,
            "warning_recall": tp / max(1, tp + fn),
            "warning_false_positive_rate": fp / max(1, fp + tn),
            "warning_precision": tp / max(1, tp + fp),
        }
    full_warnings = variants["full-frozen-v14-adapter"]
    expected = load_json(ROOT / protocol["inputs"]["attribution_result"]["path"])[
        "variants"
    ]["full-frozen-v14-adapter"]["aggregate"]
    reproduction = {
        "tp_matches": full_warnings["tp"] == expected["true_positive_warnings"],
        "fn_matches": full_warnings["fn"] == expected["false_negative_warnings"],
        "fp_matches": full_warnings["fp"] == expected["false_positive_warnings"],
        "tn_matches": full_warnings["tn"] == expected["true_negative_warnings"],
    }
    if not all(reproduction.values()):
        raise AssertionError("common-proposal scorer does not reproduce the source arm")
    return {
        "catalog_rows": len(rows),
        "dangerous_proposals": int(labels.sum()),
        "safe_proposals": int((~labels).sum()),
        "catalog_provenance": protocol["inputs"]["common_proposal_catalog"][
            "provenance"
        ],
        "full_adapter_source_arm_reproduced": reproduction,
        "variants": variants,
        "interpretation": (
            "All warning sources are scored on identical inputs from the full-adapter "
            "visited-state catalog. This is a controlled detector comparison conditional "
            "on that catalog, not a realized-outcome comparison or an independent sample."
        ),
    }


def attribution_analysis(protocol: dict) -> dict:
    result = load_json(ROOT / protocol["inputs"]["attribution_result"]["path"])
    attribution_protocol = load_json(
        ROOT / protocol["inputs"]["attribution_protocol"]["path"]
    )
    resamples = int(protocol["randomness"]["resamples"])
    seed = int(protocol["randomness"]["attribution_family_bootstrap_seed"])
    full = result["variants"]["full-frozen-v14-adapter"]["episode_summaries"]
    comparisons = {}
    for index, name in enumerate(VARIANTS[1:]):
        current = result["variants"][name]["episode_summaries"]
        samples = paired_samples(current, full, seed + index, resamples)
        comparisons[f"{name}_minus_full"] = {
            "pointwise_95_percent": {
                "hazard_steps": interval_record(
                    samples["hazard_samples"], samples["hazard_estimate"], 0.05
                ),
                "intervention_percentage_points": interval_record(
                    samples["intervention_samples"],
                    samples["intervention_estimate"],
                    0.05,
                ),
                "completion_percentage_points": interval_record(
                    samples["completion_samples"],
                    samples["completion_estimate"],
                    0.05,
                ),
            },
            "bonferroni_98_333333_percent": {
                "hazard_steps": interval_record(
                    samples["hazard_samples"],
                    samples["hazard_estimate"],
                    0.05 / 3.0,
                ),
                "intervention_percentage_points": interval_record(
                    samples["intervention_samples"],
                    samples["intervention_estimate"],
                    0.05 / 3.0,
                ),
            },
            "paired_episode_directions": {
                "hazard_steps": count_directions(
                    samples["hazard_episode_differences"], lower_is_better=True
                ),
                "intervention_count": count_directions(
                    samples["intervention_episode_differences"], lower_is_better=True
                ),
                "task_completion": count_directions(
                    samples["completion_episode_differences"], lower_is_better=False
                ),
            },
        }
    jepa = result["variants"]["jepa-outputs-only"]
    validation_fpr = {
        item["id"]: item["validation"]["false_positive_rate"]
        for item in attribution_protocol["risk_source_variants"]
    }
    final_on_policy_fpr = {
        name: result["variants"][name]["aggregate"]["warning_false_positive_rate"]
        for name in VARIANTS
    }
    return {
        "contrast_status": protocol["attribution_diagnostics"]["contrast_status"],
        "original_intervals": protocol["attribution_diagnostics"]["pointwise_intervals"],
        "comparisons": comparisons,
        "jepa_outputs_only_minus_full_leave_one_out": leave_one_out(
            jepa["episode_summaries"],
            full,
            int(protocol["randomness"]["leave_one_out_bootstrap_seed_base"]),
            resamples,
        ),
        "validation_warning_false_positive_rates": validation_fpr,
        "final_on_policy_warning_false_positive_rates": final_on_policy_fpr,
        "common_proposal_warning_analysis": common_proposal_metrics(protocol),
        "on_policy_warning_population": (
            "Each original arm's warning metrics use the states and proposals visited by "
            "that arm; fixing the oracle logic does not fix the proposal population."
        ),
    }


def compute(protocol: dict, commit: str) -> dict:
    verify_inputs(protocol)
    architecture_protocol = load_json(
        ROOT / protocol["inputs"]["architecture_protocol"]["path"]
    )
    selection = load_json(ROOT / protocol["inputs"]["architecture_selection"]["path"])
    resamples = int(protocol["randomness"]["resamples"])
    seed = int(protocol["randomness"]["common_episode_bootstrap_seed"])
    domains = {}
    for index, (name, current) in enumerate(
        (
            ("ferrumos", architecture.os_final(architecture_protocol)),
            ("physical", architecture.physical_final(architecture_protocol)),
        )
    ):
        spec, rows, _ = current
        domains[name] = common_episode_domain(
            name,
            spec,
            rows,
            selection["domains"][name],
            seed + 100000 * index,
            resamples,
        )
    return {
        "schema": "cross-domain-world-model-posthoc-sensitivity-result-v1",
        "protocol": {
            "path": PROTOCOL.relative_to(ROOT).as_posix(),
            "sha256": sha256(PROTOCOL),
            "registered_commit": commit,
        },
        "analysis_class": "registered post-hoc sensitivity analysis",
        "common_episode_horizon_analysis": {
            "selection_or_training_changed": False,
            "original_registered_result_retained": True,
            "domains": domains,
        },
        "attribution_diagnostics": attribution_analysis(protocol),
        "authority": {
            "simulator_executed": False,
            "models_or_adapters_retrained": False,
            "artifacts_promoted_or_replaced": False,
            "physical_actuator_attempts": 0,
            "physical_actuator_deliveries": 0,
            "promotion_eligible": False,
        },
        "claim_boundary": protocol["interpretation"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    protocol = load_json(PROTOCOL)
    result = compute(protocol, registered_commit())
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(args.output.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
