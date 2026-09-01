#!/usr/bin/env python3
"""Fit a research-only risk adapter on opened Safety-Gymnasium development seeds."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
import multiprocessing
from pathlib import Path

import numpy as np

import evaluate_physical_jepa_robustness as robustness
import run_physical_jepa_safety_gymnasium as benchmark


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = ROOT / "docs/research/physical_jepa_safety_gymnasium_protocol_v13.json"
DEFAULT_ARTIFACT = ROOT / "target/physical-jepa-safety-adapter-v1.json"
DEFAULT_CATALOG = ROOT / "target/physical-jepa-safety-adapter-v1-development.jsonl"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sigmoid(values: np.ndarray) -> np.ndarray:
    output = np.empty_like(values, dtype=np.float64)
    positive = values >= 0.0
    output[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    exp_values = np.exp(values[~positive])
    output[~positive] = exp_values / (1.0 + exp_values)
    return output


def metrics(labels: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    predicted = scores >= threshold
    positive = labels.astype(bool)
    negative = ~positive
    tp = int(np.sum(predicted & positive))
    fp = int(np.sum(predicted & negative))
    fn = int(np.sum(~predicted & positive))
    tn = int(np.sum(~predicted & negative))
    return {
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "recall": tp / max(1, tp + fn),
        "false_positive_rate": fp / max(1, fp + tn),
        "precision": tp / max(1, tp + fp),
    }


def calibration(labels: np.ndarray, scores: np.ndarray, bins: int = 10) -> dict:
    brier = float(np.mean((scores - labels) ** 2))
    reliability = []
    ece = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        mask = (scores >= lower) & (scores < upper if index < bins - 1 else scores <= upper)
        count = int(np.sum(mask))
        if count == 0:
            reliability.append({"lower": lower, "upper": upper, "count": 0})
            continue
        confidence = float(np.mean(scores[mask]))
        observed = float(np.mean(labels[mask]))
        ece += count / labels.size * abs(confidence - observed)
        reliability.append(
            {
                "lower": lower,
                "upper": upper,
                "count": count,
                "mean_score": confidence,
                "observed_frequency": observed,
            }
        )
    return {"brier": brier, "ece": ece, "reliability": reliability}


def collect_seed(task: tuple[int, str, dict, dict]) -> tuple[int, list[dict]]:
    seed, arm, protocol, weights = task
    risk_adapter = None
    adapter_record = protocol.get("learned_risk_adapter")
    if adapter_record is not None:
        adapter_path = ROOT / adapter_record["path"]
        if sha256(adapter_path) != adapter_record["sha256"]:
            raise ValueError("behavior risk adapter mismatch")
        risk_adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
    _, cases = benchmark.run_episode(
        seed,
        arm,
        protocol["candidate_policies"][0],
        protocol,
        weights,
        risk_adapter,
        True,
    )
    return seed, cases


def collect(protocol: dict, seeds: list[int], arm: str, workers: int) -> list[dict]:
    artifact = ROOT / protocol["artifact"]["path"]
    if sha256(artifact) != protocol["artifact"]["sha256"]:
        raise ValueError("frozen Physical JEPA v5 artifact mismatch")
    weights = robustness.load_artifact(artifact)
    if workers == 1:
        _, cases = benchmark.run_policy(
            seeds,
            arm,
            protocol["candidate_policies"][0],
            protocol,
            weights,
            True,
        )
        return cases
    ordered = []
    context = multiprocessing.get_context("spawn")
    tasks = [(seed, arm, protocol, weights) for seed in seeds]
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
        for position, (seed, cases) in enumerate(executor.map(collect_seed, tasks), 1):
            ordered.extend(cases)
            if position % 16 == 0 or position == len(seeds):
                print(f"{arm}: {position}/{len(seeds)} episodes", flush=True)
    return ordered


def fit(
    train_x: np.ndarray,
    train_y: np.ndarray,
    updates: int,
    regularization: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    mean = np.mean(train_x, axis=0)
    scale = np.std(train_x, axis=0)
    scale[scale < 1e-6] = 1.0
    normalized = (train_x - mean) / scale
    weights = np.zeros(normalized.shape[1], dtype=np.float64)
    prevalence = float(np.mean(train_y))
    bias = math.log(max(prevalence, 1e-6) / max(1.0 - prevalence, 1e-6))
    first_w = np.zeros_like(weights)
    second_w = np.zeros_like(weights)
    first_b = 0.0
    second_b = 0.0
    positive_weight = (train_y.size - np.sum(train_y)) / max(1.0, np.sum(train_y))
    sample_weight = np.where(train_y > 0.5, positive_weight, 1.0)
    learning_rate = 0.02
    beta1 = 0.9
    beta2 = 0.999
    for update in range(1, updates + 1):
        probabilities = sigmoid(normalized @ weights + bias)
        residual = (probabilities - train_y) * sample_weight
        grad_w = normalized.T @ residual / train_y.size + regularization * weights
        grad_b = float(np.mean(residual))
        first_w = beta1 * first_w + (1.0 - beta1) * grad_w
        second_w = beta2 * second_w + (1.0 - beta2) * (grad_w * grad_w)
        first_b = beta1 * first_b + (1.0 - beta1) * grad_b
        second_b = beta2 * second_b + (1.0 - beta2) * grad_b * grad_b
        correction1 = 1.0 - beta1**update
        correction2 = 1.0 - beta2**update
        weights -= learning_rate * (first_w / correction1) / (
            np.sqrt(second_w / correction2) + 1e-8
        )
        bias -= learning_rate * (first_b / correction1) / (
            math.sqrt(second_b / correction2) + 1e-8
        )
    return mean, scale, weights, bias


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--input-catalog", type=Path)
    parser.add_argument("--additional-input-catalog", type=Path, nargs="*", default=[])
    parser.add_argument(
        "--published-catalog",
        type=Path,
        help="write an exact registered copy of an input development catalog",
    )
    parser.add_argument("--seed-start", type=int, default=4000)
    parser.add_argument("--seed-count", type=int, default=128)
    parser.add_argument("--danger-horizon-steps", type=int, default=3)
    parser.add_argument(
        "--danger-rollout-mode",
        choices=("constant_proposal", "nominal_controller"),
        default="constant_proposal",
    )
    parser.add_argument(
        "--collection-arm",
        choices=(
            "naive_unshielded",
            "planner_unshielded",
            "planner_rules_plus_learned",
        ),
        default="naive_unshielded",
    )
    parser.add_argument("--behavior-adapter", type=Path)
    parser.add_argument("--behavior-threshold", type=float)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--training-seed-count", type=int, default=96)
    parser.add_argument("--updates", type=int, default=4000)
    parser.add_argument(
        "--feature-transform",
        choices=("hazard_lidar_action", "hazard_lidar_action_quadratic", "safety_summary", "compact_jepa_safety", "quadratic"),
        default="compact_jepa_safety",
    )
    parser.add_argument("--regularization", type=float, default=0.01)
    args = parser.parse_args()
    if args.artifact.exists() or (args.input_catalog is None and args.catalog.exists()):
        raise FileExistsError("refusing to overwrite an existing adapter or development catalog")
    if args.published_catalog is not None and args.published_catalog.exists():
        raise FileExistsError("refusing to overwrite the published development catalog")
    if args.published_catalog is not None and args.input_catalog is None:
        raise ValueError("--published-catalog requires --input-catalog")
    if args.additional_input_catalog and args.input_catalog is None:
        raise ValueError("additional input catalogs require --input-catalog")
    if args.additional_input_catalog and args.published_catalog is None:
        raise ValueError("merged input catalogs require --published-catalog")
    if not 0 < args.training_seed_count < args.seed_count:
        raise ValueError("training seed count must leave a disjoint validation partition")
    if args.workers < 1:
        raise ValueError("workers must be at least one")

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    protocol["oracle_and_metrics"]["danger_horizon_steps"] = args.danger_horizon_steps
    protocol["oracle_and_metrics"]["danger_rollout_mode"] = args.danger_rollout_mode
    if args.behavior_adapter is not None:
        if args.collection_arm != "planner_rules_plus_learned":
            raise ValueError("a behavior adapter requires the closed-loop planner arm")
        if args.behavior_threshold is None:
            raise ValueError("a behavior threshold is required with a behavior adapter")
        protocol["learned_risk_adapter"] = {
            "path": args.behavior_adapter.resolve().relative_to(ROOT).as_posix(),
            "sha256": sha256(args.behavior_adapter),
        }
        protocol["candidate_policies"][0].update(
            fallback_mode="planner_tangent",
            learned_requires_rule_confirmation=False,
            learned_risk_threshold=args.behavior_threshold,
            rule_hazard_closeness_threshold=0.97,
            count_only_effective_interventions=True,
            tangent_away_weight=2.0,
            tangent_path_weight=0.5,
            tangent_weight=1.0,
            tangent_forward=0.35,
            tangent_forward_alignment_radians=0.45,
            tangent_turn_gain=1.5,
        )
    elif (
        args.collection_arm == "planner_rules_plus_learned"
        and args.input_catalog is None
    ):
        raise ValueError("closed-loop collection requires --behavior-adapter")
    seeds = list(range(args.seed_start, args.seed_start + args.seed_count))
    catalog_path = args.catalog if args.input_catalog is None else args.input_catalog
    if args.input_catalog is None:
        cases = collect(protocol, seeds, args.collection_arm, args.workers)
        args.catalog.parent.mkdir(parents=True, exist_ok=True)
        with args.catalog.open("x", encoding="utf-8", newline="\n") as handle:
            for case in cases:
                handle.write(json.dumps(case, sort_keys=True, separators=(",", ":")) + "\n")
    else:
        input_catalogs = [args.input_catalog, *args.additional_input_catalog]
        cases = []
        for input_catalog in input_catalogs:
            cases.extend(
                json.loads(line)
                for line in input_catalog.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        observed_seeds = sorted({int(case["seed"]) for case in cases})
        if observed_seeds != seeds:
            raise ValueError("input development catalog seed range mismatch")
        if args.published_catalog is not None:
            args.published_catalog.parent.mkdir(parents=True, exist_ok=True)
            if len(input_catalogs) == 1:
                args.published_catalog.write_bytes(args.input_catalog.read_bytes())
            else:
                with args.published_catalog.open(
                    "x",
                    encoding="utf-8",
                    newline="\n",
                ) as handle:
                    for case in cases:
                        handle.write(
                            json.dumps(case, sort_keys=True, separators=(",", ":"))
                            + "\n"
                        )
            catalog_path = args.published_catalog

    raw = np.asarray([case["risk_adapter_features"] for case in cases], dtype=np.float64)
    expanded = np.asarray(
        [benchmark.expand_risk_adapter_features(row, args.feature_transform) for row in raw],
        dtype=np.float64,
    )
    labels = np.asarray([case["dangerous_proposal"] for case in cases], dtype=np.float64)
    training_end = args.seed_start + args.training_seed_count
    train_mask = np.asarray([case["seed"] < training_end for case in cases], dtype=bool)
    validation_mask = ~train_mask
    mean, scale, weights, bias = fit(
        expanded[train_mask],
        labels[train_mask],
        args.updates,
        args.regularization,
    )
    train_scores = sigmoid((expanded[train_mask] - mean) / scale @ weights + bias)
    validation_scores = sigmoid((expanded[validation_mask] - mean) / scale @ weights + bias)
    validation_labels = labels[validation_mask]
    curve = [
        metrics(validation_labels, validation_scores, float(threshold))
        for threshold in np.linspace(0.05, 0.95, 91)
    ]
    eligible = [item for item in curve if item["false_positive_rate"] <= 0.08]
    eligible.sort(key=lambda item: (-item["recall"], item["false_positive_rate"], -item["threshold"]))
    selected = eligible[0] if eligible else None
    artifact = {
        "schema": "physical-jepa-safety-risk-adapter-v1",
        "evidence_class": "research-only supervised adapter over frozen Physical JEPA v5 predictions and local simulator observations",
        "feature_transform": args.feature_transform,
        "raw_feature_count": int(raw.shape[1]),
        "expanded_feature_count": int(expanded.shape[1]),
        "feature_mean": mean.tolist(),
        "feature_scale": scale.tolist(),
        "weights": weights.tolist(),
        "bias": bias,
        "fit": {
            "optimizer": "deterministic full-batch Adam",
            "updates": args.updates,
            "l2_regularization": args.regularization,
            "training_seed_range": {"start": args.seed_start, "count": args.training_seed_count},
            "validation_seed_range": {"start": training_end, "count": args.seed_count - args.training_seed_count},
            "training_rows": int(np.sum(train_mask)),
            "validation_rows": int(np.sum(validation_mask)),
            "training_positive_rows": int(np.sum(labels[train_mask])),
            "validation_positive_rows": int(np.sum(validation_labels)),
            "development_catalog_sha256": sha256(catalog_path),
            "frozen_jepa_artifact_sha256": protocol["artifact"]["sha256"],
            "danger_horizon_steps": args.danger_horizon_steps,
            "danger_rollout_mode": args.danger_rollout_mode,
            "collection_arm": args.collection_arm,
            "collection_workers": args.workers,
        },
        "training": {
            "threshold_0_5": metrics(labels[train_mask], train_scores, 0.5),
            "calibration": calibration(labels[train_mask], train_scores),
        },
        "validation": {
            "selected_threshold": None if selected is None else selected["threshold"],
            "selected_metrics": selected,
            "threshold_curve": curve,
            "calibration": calibration(validation_labels, validation_scores),
        },
        "authority": {
            "may_add_caution": True,
            "may_grant_permission": False,
            "physical_actuator_authority": False,
            "deployment_eligible": False,
        },
    }
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "artifact": str(args.artifact),
        "artifact_sha256": sha256(args.artifact),
        "catalog": str(catalog_path),
        "catalog_sha256": sha256(catalog_path),
        "selected_validation": selected,
    }))


if __name__ == "__main__":
    main()
