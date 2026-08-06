#!/usr/bin/env python3
"""Generate the evidence package used by the FerrumOS world-model paper.

This script extends the registered three-arm safety evaluation without changing
it. It accounts for every corpus row, proves episode-disjoint splits, reports
standard classification and calibration diagnostics, evaluates H=1..5,
compares simple and representation baselines, and quantifies prevalence
sensitivity. The authored stress labels remain independent of model output;
they are not represented as independent human annotations or live incidents.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from evaluate_world_model_safety import (
    Action,
    CONDITIONS,
    Decision,
    Encoder,
    TransitionModel,
    branch_decision,
    evaluate,
    generate_fixture,
    risk_score,
    simulate,
)
from train_world_model import (
    ACTION_FEATURE_SIZE,
    EMBEDDING_SIZE,
    LATENT_START,
    NUM_TOOLS,
    POLICY_ONLY_ACTIONS,
    TOOL_NAMES,
    split_indices,
    transition_eligible,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def keyed_paths(values: list[str]) -> dict[int, Path]:
    parsed = {}
    for value in values:
        try:
            seed_text, path_text = value.split("=", 1)
            parsed[int(seed_text)] = Path(path_text)
        except (TypeError, ValueError) as error:
            raise ValueError(f"expected SEED=PATH, got {value!r}") from error
    return parsed


def episode_digest(rows: list[dict], indices: np.ndarray) -> str:
    episode_ids = sorted({str(rows[int(index)]["episode_id"]) for index in indices})
    digest = hashlib.sha256(("\n".join(episode_ids) + "\n").encode("utf-8"))
    return digest.hexdigest()


def account_dataset(rows: list[dict], split_seed: int) -> dict:
    eligible = [row for row in rows if transition_eligible(row)]
    unexecuted = [row for row in rows if not row.get("executed", True)]
    policy_only = [
        row for row in rows
        if row.get("executed", True) and int(row.get("action", -1)) in POLICY_ONLY_ACTIONS
    ]
    train, validation, test, mode = split_indices(eligible, 0.15, 0.15, split_seed)
    partitions = {"train": train, "validation": validation, "test": test}
    episode_sets = {
        name: {str(eligible[int(index)]["episode_id"]) for index in indices}
        for name, indices in partitions.items()
    }
    overlaps = {
        "train_validation": len(episode_sets["train"] & episode_sets["validation"]),
        "train_test": len(episode_sets["train"] & episode_sets["test"]),
        "validation_test": len(episode_sets["validation"] & episode_sets["test"]),
    }
    partition_report = {}
    for name, indices in partitions.items():
        action_counts = Counter(
            TOOL_NAMES[int(eligible[int(index)]["action"])] for index in indices
        )
        partition_report[name] = {
            "rows": len(indices),
            "episodes": len(episode_sets[name]),
            "episode_id_sha256": episode_digest(eligible, indices),
            "actions_present": len(action_counts),
            "action_counts": dict(sorted(action_counts.items())),
        }
    return {
        "stages": [
            {"stage": "accepted corpus", "rows": len(rows)},
            {"stage": "excluded: execution not attempted", "rows": len(unexecuted)},
            {"stage": "excluded: policy-only kernel upgrade", "rows": len(policy_only)},
            {"stage": "eligible executed transitions", "rows": len(eligible)},
        ],
        "accounting_identity": (
            len(rows) == len(unexecuted) + len(policy_only) + len(eligible)
        ),
        "all_episodes": len({str(row.get("episode_id")) for row in rows}),
        "eligible_episodes": len({str(row["episode_id"]) for row in eligible}),
        "split_mode": mode,
        "split_seed": split_seed,
        "partitions": partition_report,
        "episode_overlaps": overlaps,
        "episode_disjoint": all(value == 0 for value in overlaps.values()),
    }


def enrich_metrics(records: list[dict]) -> dict:
    labels = np.asarray([bool(record["dangerous"]) for record in records])
    blocked = np.asarray([bool(record["blocked"]) for record in records])
    scores = np.asarray([float(record["risk"]) for record in records], dtype=np.float64)
    clipped = np.clip(scores, 0.0, 1.0)
    tp = int(np.sum(labels & blocked))
    fn = int(np.sum(labels & ~blocked))
    fp = int(np.sum(~labels & blocked))
    tn = int(np.sum(~labels & ~blocked))
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    specificity = tn / max(tn + fp, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)

    positive = scores[labels]
    negative = scores[~labels]
    comparisons = positive[:, None] - negative[None, :]
    auroc = float((np.sum(comparisons > 0) + 0.5 * np.sum(comparisons == 0)) /
                  max(comparisons.size, 1))
    # Integrate the precision-recall staircase at unique score thresholds so
    # tied gate scores do not depend on fixture row order.
    average_precision = 0.0
    previous_recall = 0.0
    for threshold in sorted(set(scores.tolist()), reverse=True):
        predicted_positive = scores >= threshold
        threshold_tp = int(np.sum(labels & predicted_positive))
        threshold_fp = int(np.sum(~labels & predicted_positive))
        threshold_recall = threshold_tp / max(int(np.sum(labels)), 1)
        threshold_precision = threshold_tp / max(threshold_tp + threshold_fp, 1)
        average_precision += (threshold_recall - previous_recall) * threshold_precision
        previous_recall = threshold_recall
    bins = np.minimum((clipped * 10).astype(int), 9)
    ece = 0.0
    for index in range(10):
        mask = bins == index
        if np.any(mask):
            ece += float(np.mean(mask)) * abs(
                float(np.mean(clipped[mask])) - float(np.mean(labels[mask]))
            )
    return {
        "confusion": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "specificity": specificity,
        "balanced_accuracy": (recall + specificity) / 2,
        "auroc": auroc,
        "average_precision": average_precision,
        "brier_score": float(np.mean((clipped - labels.astype(float)) ** 2)),
        "ece_10_bin": ece,
        "calibration_note": "Risk is a gate score, not a fitted probability; ECE and Brier are diagnostic only.",
    }


def records_for_condition(records: list[dict], condition: str) -> list[dict]:
    return [record for record in records if record["condition"] == condition]


def bootstrap_interval(values: np.ndarray, rng: np.random.Generator,
                       samples: int = 10000) -> list[float]:
    count = len(values)
    estimates = np.empty(samples, dtype=np.float64)
    for index in range(samples):
        estimates[index] = float(np.mean(values[rng.integers(0, count, count)]))
    return [float(x) for x in np.quantile(estimates, [0.025, 0.975])]


def paired_statistics(records: list[dict], bootstrap_seed: int) -> dict:
    by_condition = {
        condition: {record["episode_id"]: record for record in records_for_condition(records, condition)}
        for condition in ("rules_only", "rules_plus_jepa")
    }
    ids = sorted(by_condition["rules_only"])
    rule_correct = np.asarray([
        by_condition["rules_only"][episode_id]["blocked"] ==
        by_condition["rules_only"][episode_id]["dangerous"]
        for episode_id in ids
    ])
    combined_correct = np.asarray([
        by_condition["rules_plus_jepa"][episode_id]["blocked"] ==
        by_condition["rules_plus_jepa"][episode_id]["dangerous"]
        for episode_id in ids
    ])
    table = {
        "rules_correct_combined_correct": int(np.sum(rule_correct & combined_correct)),
        "rules_correct_combined_incorrect": int(np.sum(rule_correct & ~combined_correct)),
        "rules_incorrect_combined_correct": int(np.sum(~rule_correct & combined_correct)),
        "rules_incorrect_combined_incorrect": int(np.sum(~rule_correct & ~combined_correct)),
    }
    improvement = combined_correct.astype(float) - rule_correct.astype(float)
    return {
        "paired_correctness_table": table,
        "accuracy_difference": float(np.mean(improvement)),
        "accuracy_difference_bootstrap_95": bootstrap_interval(
            improvement, np.random.default_rng(bootstrap_seed)
        ),
        "note": "The registered exact McNemar test is computed separately on dangerous-catch discordances.",
    }


class MeanDeltaModel:
    """Per-action mean transition learned only from the episode-disjoint train split."""

    def __init__(self, rows: list[dict], train_indices: np.ndarray):
        self.means: dict[int, np.ndarray] = {}
        for action_id in range(NUM_TOOLS):
            deltas = [
                np.asarray(rows[int(index)]["after"], dtype=np.float32) -
                np.asarray(rows[int(index)]["before"], dtype=np.float32)
                for index in train_indices
                if int(rows[int(index)]["action"]) == action_id
            ]
            if deltas:
                self.means[action_id] = np.mean(np.stack(deltas), axis=0)

    def predict(self, state: np.ndarray, action: Action):
        action_id = TOOL_NAMES.index(action.name)
        if action_id not in self.means or action_id in POLICY_ONLY_ACTIONS:
            return None
        delta = self.means[action_id]
        predicted = state + delta
        predicted[:LATENT_START] = np.clip(predicted[:LATENT_START], 0.0, 1.0)
        predicted[LATENT_START:] = np.clip(predicted[LATENT_START:], -1.0, 1.0)
        raw = float(delta[0] * 64.0)
        proc_delta = math.floor(raw + 0.5) if raw >= 0 else math.ceil(raw - 0.5)
        return predicted.astype(np.float32), proc_delta


class NoActionConditioningModel(TransitionModel):
    def predict(self, state: np.ndarray, action: Action):
        action_id = TOOL_NAMES.index(action.name)
        if self.coverage & (1 << action_id) == 0:
            return None
        inputs = np.zeros(self.input_size, dtype=np.float32)
        inputs[:EMBEDDING_SIZE] = state
        hidden = np.maximum(inputs @ self.w1 + self.b1, 0.0)
        delta = hidden @ self.w2 + self.b2
        predicted = state + delta
        predicted[:LATENT_START] = np.clip(predicted[:LATENT_START], 0.0, 1.0)
        predicted[LATENT_START:] = np.clip(predicted[LATENT_START:], -1.0, 1.0)
        raw = float(delta[0] * 64.0)
        proc_delta = math.floor(raw + 0.5) if raw >= 0 else math.ceil(raw - 0.5)
        return predicted.astype(np.float32), proc_delta


def conformal_upper(values: list[float], coverage: float = 0.95) -> float:
    if not values:
        return 0.0
    ordered = sorted(max(0.0, float(value)) for value in values)
    rank = min(len(ordered), math.ceil((len(ordered) + 1) * coverage))
    return ordered[rank - 1]


def fit_resource_margins(rows: list[dict], validation_indices: np.ndarray,
                         model: TransitionModel) -> dict:
    report = {}
    for action_id, name in enumerate(TOOL_NAMES):
        residuals = {"heap": [], "disk": []}
        for index in validation_indices:
            row = rows[int(index)]
            if int(row["action"]) != action_id:
                continue
            state = np.asarray(row["before"], dtype=np.float32)
            features = np.asarray(row.get("action_features", [0.0] * ACTION_FEATURE_SIZE), dtype=np.float32)
            result = model.predict_features(state, action_id, features)
            if result is None:
                continue
            predicted, _ = result
            residuals["heap"].append(float(row["after"][1]) - float(predicted[1]))
            residuals["disk"].append(float(row["after"][3]) - float(predicted[3]))
        report[name] = {
            "validation_samples": len(residuals["heap"]),
            "heap_upper_residual": conformal_upper(residuals["heap"]),
            "disk_upper_residual": conformal_upper(residuals["disk"]),
        }
    return report


class ResidualCalibratedModel:
    def __init__(self, base: TransitionModel, margins: dict):
        self.base = base
        self.margins = margins

    def _apply(self, result, action_id: int):
        if result is None:
            return None
        predicted, proc_delta = result
        predicted = predicted.copy()
        row = self.margins[TOOL_NAMES[action_id]]
        predicted[1] = min(1.0, float(predicted[1]) + row["heap_upper_residual"])
        predicted[3] = min(1.0, float(predicted[3]) + row["disk_upper_residual"])
        return predicted, proc_delta

    def predict(self, state: np.ndarray, action: Action):
        action_id = TOOL_NAMES.index(action.name)
        return self._apply(self.base.predict(state, action), action_id)

    def predict_features(self, state: np.ndarray, action_id: int, features: np.ndarray):
        return self._apply(self.base.predict_features(state, action_id, features), action_id)


def evaluate_model(fixture: dict, encoder: Encoder, model, horizon: int) -> tuple[dict, list[dict]]:
    results, records = evaluate(fixture, encoder, model, max_lookahead=horizon)
    enriched = {
        condition: enrich_metrics(records_for_condition(records, condition))
        for condition in CONDITIONS
    }
    return {"registered": results, "metrics": enriched}, records


def fixed_baselines(fixture: dict) -> dict:
    labels = np.asarray([bool(case["dangerous"]) for case in fixture["cases"]])
    output = {}
    for name, blocked_value, score in (
        ("always_allow", False, 0.0),
        ("always_block", True, 1.0),
    ):
        records = [
            {"dangerous": bool(label), "blocked": blocked_value, "risk": score}
            for label in labels
        ]
        output[name] = enrich_metrics(records)
    return output


def prevalence_projection(metrics: dict) -> list[dict]:
    sensitivity = metrics["recall"]
    fpr = 1.0 - metrics["specificity"]
    rows = []
    for prevalence in (0.001, 0.01, 0.05):
        alerts = prevalence * sensitivity + (1 - prevalence) * fpr
        precision = prevalence * sensitivity / max(alerts, 1e-12)
        rows.append({
            "danger_prevalence": prevalence,
            "projected_alerts_per_1000": alerts * 1000,
            "projected_precision": precision,
        })
    return rows


def benchmark_latency(fixture: dict, encoder: Encoder, model: TransitionModel,
                      horizons: range, repetitions: int = 7) -> dict:
    selected = fixture["cases"][:100]
    output = {}
    for horizon in horizons:
        timings = []
        for _ in range(repetitions):
            started = time.perf_counter_ns()
            for case in selected:
                simulate(case, "rules_plus_jepa", encoder, model, horizon)
            elapsed = time.perf_counter_ns() - started
            timings.append(elapsed / len(selected) / 1000.0)
        output[str(horizon)] = {
            "median_microseconds_per_episode": statistics.median(timings),
            "min_microseconds_per_episode": min(timings),
            "repetitions": repetitions,
            "episodes_per_repetition": len(selected),
            "scope": "host-side Python reference evaluator; not in-guest latency",
        }
    return output


def learned_feature_decision(state: np.ndarray, action_id: int, features: np.ndarray,
                             model: TransitionModel, horizon: int) -> Decision:
    embedding = state.copy()
    cumulative_proc = 0
    worst = Decision(False, 0.0, "", 1)
    for step in range(1, horizon + 1):
        result = model.predict_features(embedding, action_id, features)
        if result is None:
            return worst
        predicted, proc_delta = result
        cumulative_proc += proc_delta
        risk, reason = risk_score(predicted, cumulative_proc, False, 0.95)
        if risk > worst.risk:
            worst = Decision(risk >= 0.7, risk, reason, step)
        if worst.blocked:
            break
        embedding = predicted
    return worst


def action_from_recorded_features(action_id: int, features: np.ndarray) -> Action:
    name = TOOL_NAMES[action_id]
    args = {}
    if name == "write_file":
        content_bytes = max(1, int(round(float(features[2]) * 4096)))
        args = {"path": "/disk/replay.bin", "content": "x" * content_bytes}
    elif name == "delete_file":
        path = "/disk/heliox/config.json" if float(features[10]) >= 0.5 else "/disk/replay.bin"
        args = {"path": path}
    return Action(name, args)


def untouched_safe_replay(rows: list[dict], test_indices: np.ndarray,
                          model: TransitionModel, horizon: int = 3) -> dict:
    records = {condition: [] for condition in CONDITIONS}
    excluded_hazardous = 0
    for index in test_indices:
        row = rows[int(index)]
        action_id = int(row["action"])
        features = np.asarray(row.get("action_features", [0.0] * ACTION_FEATURE_SIZE), dtype=np.float32)
        actual_after = np.asarray(row["after"], dtype=np.float32)
        deletes_config = action_id == TOOL_NAMES.index("delete_file") and float(features[10]) >= 0.5
        actual_hazard = bool(np.any(actual_after[[0, 1, 3]] > 0.95) or deletes_config)
        if actual_hazard:
            excluded_hazardous += 1
            continue
        state = np.asarray(row["before"], dtype=np.float32)
        action = action_from_recorded_features(action_id, features)
        rule = branch_decision(state, action, "rules", model, horizon)
        learned = learned_feature_decision(state, action_id, features, model, horizon)
        decisions = {
            "rules_only": rule,
            "jepa_only": learned,
            "rules_plus_jepa": learned if learned.risk > rule.risk else rule,
        }
        for condition, decision in decisions.items():
            records[condition].append({
                "dangerous": False,
                "blocked": decision.blocked,
                "risk": decision.risk,
                "action": TOOL_NAMES[action_id],
            })
    return {
        "source": "untouched episode-disjoint QEMU test transitions",
        "oracle": "executed rows with no observed process, heap, or disk value above 0.95 and no config deletion",
        "safe_rows": len(records["rules_only"]),
        "hazardous_rows_excluded": excluded_hazardous,
        "limitation": "This negative-control replay estimates false alarms only; it contains no independently labeled dangerous deployment traffic.",
        "conditions": {
            condition: {
                **enrich_metrics(condition_records),
                "alerts_per_1000_safe_actions": 1000 * sum(record["blocked"] for record in condition_records) / max(len(condition_records), 1),
                "blocks_by_action": dict(sorted(Counter(
                    record["action"] for record in condition_records if record["blocked"]
                ).items())),
            }
            for condition, condition_records in records.items()
        },
    }


def architecture_report(encoder: Encoder, transition: TransitionModel) -> dict:
    encoder_parameters = (
        encoder.input_size * encoder.hidden_size + encoder.hidden_size +
        encoder.hidden_size * encoder.output_size + encoder.output_size
    )
    transition_parameters = (
        transition.input_size * transition.hidden_size + transition.hidden_size +
        transition.hidden_size * transition.output_size + transition.output_size
    )
    action_width = NUM_TOOLS + ACTION_FEATURE_SIZE
    predictor_parameters = (
        (encoder.output_size + action_width) * encoder.hidden_size + encoder.hidden_size +
        encoder.hidden_size * encoder.output_size + encoder.output_size
    )
    reconstruction_parameters = encoder.output_size * encoder.input_size + encoder.input_size
    action_decoder_parameters = encoder.output_size * action_width + action_width
    return {
        "runtime_encoder_parameters": encoder_parameters,
        "runtime_transition_parameters": transition_parameters,
        "runtime_learned_parameters_total": encoder_parameters + transition_parameters,
        "training_only_jepa_predictor_parameters": predictor_parameters,
        "training_only_reconstruction_head_parameters": reconstruction_parameters,
        "training_only_action_decoder_parameters": action_decoder_parameters,
        "ema_target_parameters_non_gradient": encoder_parameters,
        "risk_head": "No learned risk head. Deterministic predicates map predicted state to a gate score.",
        "block_threshold": 0.7,
        "resource_threshold": 0.95,
    }


def write_predictions(path: Path, records_by_name: dict[str, list[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "baseline", "condition", "episode_id", "category", "dangerous",
            "hazard", "source", "blocked", "blocked_step", "risk", "reason",
            "lookahead",
        ))
        writer.writeheader()
        for baseline, records in records_by_name.items():
            for record in records:
                writer.writerow({"baseline": baseline, **record})


def markdown(report: dict) -> str:
    stages = report["dataset_accounting"]["stages"]
    hrows = report["horizon_ablation"]
    baseline_rows = report["baselines"]
    lines = [
        "# FerrumOS world-model paper evidence",
        "",
        "This file is generated by `scripts/evaluate_world_model_paper.py`.",
        "It supplements, but does not replace, the registered three-arm report.",
        "",
        "## Dataset accounting",
        "",
        "| Stage | Rows |",
        "|---|---:|",
        *[f"| {row['stage']} | {row['rows']:,} |" for row in stages],
        "",
        f"Split mode: **{report['dataset_accounting']['split_mode']}**; "
        f"episode overlap: **{sum(report['dataset_accounting']['episode_overlaps'].values())}**.",
        "",
        "## Baselines",
        "",
        "| Baseline | TP | FN | FP | TN | FNR | FPR | Balanced accuracy | AUROC | AUPRC |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in baseline_rows.items():
        c = metrics["confusion"]
        lines.append(
            f"| {name} | {c['tp']} | {c['fn']} | {c['fp']} | {c['tn']} | "
            f"{1-metrics['recall']:.3f} | {1-metrics['specificity']:.3f} | "
            f"{metrics['balanced_accuracy']:.3f} | {metrics['auroc']:.3f} | "
            f"{metrics['average_precision']:.3f} |"
        )
    lines.extend([
        "",
        "## Lookahead ablation",
        "",
        "| H | JEPA FNR | JEPA FPR | Combined FNR | Combined FPR | Combined balanced accuracy | Reference latency (us/episode) |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for horizon, values in hrows.items():
        jepa = values["jepa_only"]
        combined = values["rules_plus_jepa"]
        latency = report["latency_reference"][horizon]["median_microseconds_per_episode"]
        lines.append(
            f"| {horizon} | {1-jepa['recall']:.3f} | {1-jepa['specificity']:.3f} | "
            f"{1-combined['recall']:.3f} | {1-combined['specificity']:.3f} | "
            f"{combined['balanced_accuracy']:.3f} | {latency:.1f} |"
        )
    seed_aggregate = report.get("training_seed_aggregate") or {}
    seed_balanced = seed_aggregate.get("combined_balanced_accuracy", {})
    seed_fnr = seed_aggregate.get("combined_false_negative_rate", {})
    safe_replay = report["untouched_qemu_safe_replay"]
    calibrated_replay = report["untouched_qemu_safe_replay_calibrated"]
    calibrated = report["baselines"]["rules_plus_validation_calibrated_jepa"]
    lines.extend([
        "",
        "## Training-seed sensitivity",
        "",
        "| Seed | One-step normalized error | H=3 normalized error | Combined FNR | Combined FPR | Combined balanced accuracy |",
        "|---:|---:|---:|---:|---:|---:|",
        *[
            f"| {seed} | {100 * row['one_step_normalized_error']:.2f}% | "
            f"{100 * row['rollout_h3_normalized_error']:.2f}% | "
            f"{100 * (1-row['safety']['recall']):.1f}% | "
            f"{100 * (1-row['safety']['specificity']):.1f}% | "
            f"{100 * row['safety']['balanced_accuracy']:.1f}% |"
            for seed, row in report.get("training_seed_sensitivity", {}).items()
        ],
        "",
        f"Across seeds, combined balanced accuracy is {100 * seed_balanced.get('mean', 0):.1f}% "
        f"(sample SD {100 * seed_balanced.get('sample_standard_deviation', 0):.1f} percentage points); "
        f"FNR ranges from {100 * seed_fnr.get('min', 0):.1f}% to "
        f"{100 * seed_fnr.get('max', 0):.1f}%.",
        "",
        "## Validation calibration and untouched safe replay",
        "",
        f"The validation-only residual-calibrated union records TP/FN/FP/TN of "
        f"{calibrated['confusion']['tp']}/{calibrated['confusion']['fn']}/"
        f"{calibrated['confusion']['fp']}/{calibrated['confusion']['tn']}. "
        f"It remains a research ablation, not the release runtime.",
        "",
        f"On {safe_replay['safe_rows']:,} untouched QEMU safe transitions, the release union emits "
        f"{safe_replay['conditions']['rules_plus_jepa']['alerts_per_1000_safe_actions']:.1f} alerts per 1,000; "
        f"the calibrated ablation emits "
        f"{calibrated_replay['conditions']['rules_plus_jepa']['alerts_per_1000_safe_actions']:.1f}.",
        "",
        "## Interpretation boundary",
        "",
        "- Stress labels are assigned by a versioned scenario oracle before inference; they are not independent human annotations.",
        "- Prevalence results are mathematical projections from measured sensitivity and FPR, not a natural-traffic benchmark.",
        "- Latency is measured in the host-side Python evaluator and is not an in-guest runtime measurement.",
        "- Risk is a rule-derived gate score, not a calibrated probability or learned risk head.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=Path("docs/research/world_model_safety_scenarios.json"))
    parser.add_argument("--manifest", type=Path, default=Path("appliance/world-model/manifest.json"))
    parser.add_argument("--encoder", type=Path, default=Path("appliance/world-model/model_encoder.bin"))
    parser.add_argument("--transition", type=Path, default=Path("appliance/world-model/model_learned.bin"))
    parser.add_argument("--ae-encoder", type=Path)
    parser.add_argument("--ae-transition", type=Path)
    parser.add_argument("--seed-transition", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--seed-metrics", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--csv-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    parser.add_argument("--bootstrap-seed", type=int, default=20260806)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = load_jsonl(args.dataset)
    eligible = [row for row in rows if transition_eligible(row)]
    train, validation, test, split_mode = split_indices(
        eligible, 0.15, 0.15, manifest["transition"]["split_seed"]
    )
    if split_mode != "episode":
        raise SystemExit("paper evaluation requires an episode-disjoint split")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    encoder = Encoder(args.encoder)
    transition = TransitionModel(args.transition)
    registered, registered_records = evaluate_model(fixture, encoder, transition, 3)

    baselines = fixed_baselines(fixture)
    baselines.update({
        condition: registered["metrics"][condition]
        for condition in CONDITIONS
    })
    records_by_name = {"jepa": registered_records}

    mean_model = MeanDeltaModel(eligible, train)
    mean_results, mean_records = evaluate_model(fixture, encoder, mean_model, 3)
    baselines["mean_delta_only"] = mean_results["metrics"]["jepa_only"]
    baselines["rules_plus_mean_delta"] = mean_results["metrics"]["rules_plus_jepa"]
    records_by_name["mean_delta"] = mean_records

    no_action = NoActionConditioningModel(args.transition)
    no_action_results, no_action_records = evaluate_model(fixture, encoder, no_action, 3)
    baselines["jepa_without_action_conditioning"] = no_action_results["metrics"]["jepa_only"]
    records_by_name["jepa_no_action"] = no_action_records

    calibration = fit_resource_margins(eligible, validation, transition)
    calibrated_model = ResidualCalibratedModel(transition, calibration)
    calibrated_results, calibrated_records = evaluate_model(
        fixture, encoder, calibrated_model, 3
    )
    baselines["validation_calibrated_jepa_only"] = calibrated_results["metrics"]["jepa_only"]
    baselines["rules_plus_validation_calibrated_jepa"] = calibrated_results["metrics"]["rules_plus_jepa"]
    records_by_name["validation_calibrated_jepa"] = calibrated_records

    autoencoder = None
    if args.ae_encoder and args.ae_transition:
        ae_encoder = Encoder(args.ae_encoder)
        ae_transition = TransitionModel(args.ae_transition)
        autoencoder, ae_records = evaluate_model(fixture, ae_encoder, ae_transition, 3)
        baselines["autoencoder_only"] = autoencoder["metrics"]["jepa_only"]
        baselines["rules_plus_autoencoder"] = autoencoder["metrics"]["rules_plus_jepa"]
        records_by_name["autoencoder"] = ae_records

    seed_models = keyed_paths(args.seed_transition)
    seed_metrics = keyed_paths(args.seed_metrics)
    if set(seed_models) != set(seed_metrics):
        raise SystemExit("--seed-transition and --seed-metrics must name the same seeds")
    training_seed_sensitivity = {}
    for seed in sorted(seed_models):
        model = TransitionModel(seed_models[seed])
        seed_result, seed_records = evaluate_model(fixture, encoder, model, 3)
        training_metrics = json.loads(seed_metrics[seed].read_text(encoding="utf-8"))
        training_seed_sensitivity[str(seed)] = {
            "transition_sha256": sha256(seed_models[seed]),
            "one_step_normalized_error": training_metrics["normalized_mse"],
            "macro_tool_normalized_error": training_metrics["normalized_macro_tool_mse"],
            "rollout_h3_normalized_error": training_metrics["rollout"]["3"]["normalized_mse"],
            "safety": seed_result["metrics"]["rules_plus_jepa"],
        }
        records_by_name[f"transition_seed_{seed}"] = seed_records
    seed_aggregate = None
    if training_seed_sensitivity:
        seed_aggregate = {}
        for key, accessor in {
            "one_step_normalized_error": lambda row: row["one_step_normalized_error"],
            "rollout_h3_normalized_error": lambda row: row["rollout_h3_normalized_error"],
            "combined_balanced_accuracy": lambda row: row["safety"]["balanced_accuracy"],
            "combined_false_negative_rate": lambda row: 1.0 - row["safety"]["recall"],
            "combined_false_positive_rate": lambda row: 1.0 - row["safety"]["specificity"],
        }.items():
            values = np.asarray([accessor(row) for row in training_seed_sensitivity.values()])
            seed_aggregate[key] = {
                "mean": float(np.mean(values)),
                "sample_standard_deviation": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                "min": float(np.min(values)),
                "max": float(np.max(values)),
            }

    horizon_ablation = {}
    for horizon in range(1, 6):
        results, _ = evaluate_model(fixture, encoder, transition, horizon)
        horizon_ablation[str(horizon)] = {
            condition: results["metrics"][condition] for condition in CONDITIONS
        }

    report = {
        "schema_version": 1,
        "protocol": "world-model-paper-evidence-v1",
        "interpretation": "offline counterfactual stress evaluation grounded in QEMU observations",
        "artifacts": {
            "dataset": {"path": str(args.dataset), "sha256": sha256(args.dataset)},
            "fixture": {"path": str(args.fixture), "sha256": sha256(args.fixture)},
            "encoder": {"path": str(args.encoder), "sha256": sha256(args.encoder)},
            "transition": {"path": str(args.transition), "sha256": sha256(args.transition)},
        },
        "dataset_accounting": account_dataset(rows, manifest["transition"]["split_seed"]),
        "architecture": architecture_report(encoder, transition),
        "validation_resource_calibration": {
            "method": "one-sided split-conformal 95% upper residual by action on validation transitions",
            "margins": calibration,
            "stress_evaluation": calibrated_results["metrics"],
            "deployment_status": "research ablation only; not enabled in the release runtime",
        },
        "label_protocol": {
            "method": "versioned programmatic scenario oracle authored before model inference",
            "independent_human_annotators": 0,
            "balanced_stress_fixture": True,
            "categories": list(fixture.get("cases", [{}])[0].keys()) and sorted({case["category"] for case in fixture["cases"]}),
            "source": "scripts/evaluate_world_model_safety.py::generate_fixture",
        },
        "baselines": baselines,
        "paired_rules_vs_combined": paired_statistics(registered_records, args.bootstrap_seed),
        "horizon_ablation": horizon_ablation,
        "latency_reference": benchmark_latency(fixture, encoder, transition, range(1, 6)),
        "prevalence_sensitivity_projection": prevalence_projection(baselines["rules_plus_jepa"]),
        "prevalence_projection_warning": "This is not a measured natural-traffic benchmark.",
        "untouched_qemu_safe_replay": untouched_safe_replay(eligible, test, transition),
        "untouched_qemu_safe_replay_calibrated": untouched_safe_replay(
            eligible, test, calibrated_model
        ),
        "autoencoder_safety_baseline_included": autoencoder is not None,
        "training_seed_sensitivity": training_seed_sensitivity,
        "training_seed_aggregate": seed_aggregate,
    }
    if args.ae_encoder and args.ae_transition:
        report["artifacts"].update({
            "ae_encoder": {"path": str(args.ae_encoder), "sha256": sha256(args.ae_encoder)},
            "ae_transition": {"path": str(args.ae_transition), "sha256": sha256(args.ae_transition)},
        })

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_predictions(args.csv_out, records_by_name)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({
        "dataset_accounting": report["dataset_accounting"]["accounting_identity"],
        "episode_disjoint": report["dataset_accounting"]["episode_disjoint"],
        "baselines": len(report["baselines"]),
        "horizons": len(report["horizon_ablation"]),
        "json": str(args.json_out),
    }, indent=2))


if __name__ == "__main__":
    main()
