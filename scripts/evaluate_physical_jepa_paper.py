#!/usr/bin/env python3
"""Post-hoc matched-FPR and calibration analysis for the physical JEPA paper.

This script cannot select, promote, or deploy an artifact. It calibrates only on
the registered incident-v2 validation partition and reports transfer to the
already-opened v5 final partition.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_incident_scenarios as incidents  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402


DEFAULT_PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_paper_protocol_v1.json"
DEFAULT_REPORT = ROOT / "docs" / "research" / "physical_jepa_paper_results_v1.json"
DEFAULT_TABLE = ROOT / "docs" / "research" / "physical_jepa_paper_ablation_v1.csv"
DEFAULT_FIGURES = ROOT / "docs" / "research" / "figures" / "physical_jepa_paper"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_supervised_mlp(path: Path):
    raw = path.read_bytes()
    header_format = "<4sIIIIIIIffI"
    header_size = struct.calcsize(header_format)
    header = struct.unpack(header_format, raw[:header_size])
    magic, version, state_size, action_count, feature_size, hidden = header[:6]
    if (magic, version, state_size, action_count, feature_size) != (
        b"PWM1",
        1,
        simulator.STATE_SIZE,
        simulator.ACTION_COUNT,
        simulator.ACTION_FEATURE_SIZE,
    ):
        raise ValueError("unsupported supervised physical-model artifact")
    offset = header_size

    def take(shape):
        nonlocal offset
        count = int(np.prod(shape))
        end = offset + count * 4
        if end > len(raw):
            raise ValueError("truncated supervised physical-model artifact")
        value = np.frombuffer(raw[offset:end], dtype="<f4").reshape(shape).copy()
        offset = end
        return value

    weights = (
        take((simulator.INPUT_SIZE, hidden)),
        take((hidden,)),
        take((hidden, simulator.STATE_SIZE)),
        take((simulator.STATE_SIZE,)),
    )
    if offset != len(raw):
        raise ValueError("supervised physical-model artifact has trailing bytes")
    return weights


def supervised_prediction(weights, state, action, features):
    delta = simulator.predict(simulator.make_input(state, action, features), weights)[0]
    return np.clip(state + delta, -1.25, 1.25).astype(np.float32)


def learned_margin(state, action, features, nxt) -> float:
    moving = action == simulator.MOVE and features[2] > 0.1
    margins = [(0.01 - float(nxt[simulator.MARGIN])) / 0.25]
    if moving:
        margins.extend(
            [
                (0.18 - float(nxt[simulator.CLEARANCE])) / 0.18,
                (
                    (float(nxt[simulator.VELOCITY]) - 0.16) / 0.16
                    if state[simulator.HUMANS] > 0
                    else -1.0
                ),
                (0.08 - float(nxt[simulator.BATTERY])) / 0.08,
                (0.08 - float(nxt[simulator.LINK])) / 0.08,
            ]
        )
    if action != simulator.STOP:
        margins.append((float(state[simulator.ESTOP]) - 0.5) * 2.0)
    if action == simulator.REPAIR:
        margins.append((0.5 - float(state[simulator.APPROVAL])) * 2.0)
    return max(margins)


def rules_margin(state, action, features) -> float:
    moving = action == simulator.MOVE and features[2] > 0.1
    predicted_margin = 1.0 - max(
        abs(float(state[simulator.X]) + 0.32 * float(features[0])),
        abs(float(state[simulator.Y]) + 0.32 * float(features[1])),
    )
    margins = [-predicted_margin / 0.25]
    if moving:
        margins.extend(
            [
                (0.2 - float(state[simulator.CLEARANCE])) / 0.2,
                (float(state[simulator.HUMANS]) - 1e-7) / 0.5,
                (0.1 - float(state[simulator.BATTERY])) / 0.1,
                (0.1 - float(state[simulator.LINK])) / 0.1,
            ]
        )
    if action != simulator.STOP:
        margins.append((float(state[simulator.ESTOP]) - 0.5) * 2.0)
    if action == simulator.REPAIR:
        margins.append((0.5 - float(state[simulator.APPROVAL])) * 2.0)
    return max(margins)


def score_rows(rows, predictor=None):
    labels = np.asarray([bool(row[6]) for row in rows], dtype=bool)
    rules = np.asarray(
        [simulator.rules_block(row[2], row[3], row[4]) for row in rows], dtype=bool
    )
    rule_scores = np.asarray(
        [rules_margin(row[2], row[3], row[4]) for row in rows], dtype=np.float64
    )
    if predictor is None:
        return labels, rules, rule_scores
    scores = []
    for row in rows:
        nxt = predictor(row[2], row[3], row[4])
        if not np.all(np.isfinite(nxt)):
            raise ValueError("model produced a non-finite prediction")
        scores.append(learned_margin(row[2], row[3], row[4], nxt))
    return labels, rules, np.asarray(scores, dtype=np.float64)


def sigmoid(value):
    value = np.clip(value, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-value))


def fit_platt(scores, labels, regularization: float):
    labels_float = labels.astype(np.float64)

    def objective(parameters):
        logits = parameters[0] * scores + parameters[1]
        probabilities = sigmoid(logits)
        eps = 1e-12
        nll = -np.mean(
            labels_float * np.log(probabilities + eps)
            + (1.0 - labels_float) * np.log(1.0 - probabilities + eps)
        )
        return float(nll + regularization * parameters[0] ** 2)

    prior = float(np.clip(labels_float.mean(), 1e-6, 1.0 - 1e-6))
    initial = np.asarray([1.0, math.log(prior / (1.0 - prior))])
    fitted = minimize(objective, initial, method="BFGS")
    if not fitted.success:
        raise RuntimeError(f"Platt fit failed: {fitted.message}")
    return fitted.x


def probabilities(scores, parameters):
    return sigmoid(parameters[0] * scores + parameters[1])


def confusion(labels, decisions):
    tp = int(np.sum(decisions & labels))
    fp = int(np.sum(decisions & ~labels))
    tn = int(np.sum(~decisions & ~labels))
    fn = int(np.sum(~decisions & labels))
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "false_positive_rate": fp / max(1, fp + tn),
        "false_negative_rate": fn / max(1, fn + tp),
        "true_positive_rate": tp / max(1, tp + fn),
        "balanced_accuracy": 0.5
        * (tp / max(1, tp + fn) + tn / max(1, tn + fp)),
    }


def select_threshold(probability, labels, reference_fpr, fixed=None):
    fixed = np.zeros(len(labels), dtype=bool) if fixed is None else fixed
    order = np.argsort(-probability, kind="mergesort")
    candidates = [float(np.nextafter(probability[order[0]], math.inf))]
    candidates.extend(float(value) for value in np.unique(probability)[::-1])
    best = None
    for threshold in candidates:
        metrics = confusion(labels, fixed | (probability >= threshold))
        key = (
            abs(metrics["false_positive_rate"] - reference_fpr),
            metrics["false_negative_rate"],
            -threshold,
        )
        if best is None or key < best[0]:
            best = (key, threshold, metrics)
    assert best is not None
    return best[1], best[2]


def calibration_metrics(probability, labels, bins: int):
    labels_float = labels.astype(np.float64)
    order = np.argsort(probability, kind="mergesort")
    reliability = []
    ece = 0.0
    for indices in np.array_split(order, bins):
        if not len(indices):
            continue
        mean_probability = float(probability[indices].mean())
        frequency = float(labels_float[indices].mean())
        weight = len(indices) / len(labels)
        ece += weight * abs(mean_probability - frequency)
        reliability.append(
            {
                "count": int(len(indices)),
                "mean_probability": mean_probability,
                "empirical_frequency": frequency,
            }
        )
    eps = 1e-12
    return {
        "ece": float(ece),
        "brier_score": float(np.mean((probability - labels_float) ** 2)),
        "negative_log_likelihood": float(
            -np.mean(
                labels_float * np.log(probability + eps)
                + (1.0 - labels_float) * np.log(1.0 - probability + eps)
            )
        ),
        "reliability_bins": reliability,
    }


def threshold_sensitivity(probability, labels, grid, fixed=None):
    fixed = np.zeros(len(labels), dtype=bool) if fixed is None else fixed
    return [
        {"threshold": value, **confusion(labels, fixed | (probability >= value))}
        for value in grid
    ]


def plot_results(methods, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    colors = {
        "rules_only": "#727b89",
        "ordinary_supervised_mlp": "#d17a22",
        "v3": "#4472c4",
        "failed_v4": "#b33a3a",
        "v5": "#2f9e6f",
        "rules_plus_v5": "#754fc6",
    }
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
    for name, result in methods.items():
        bins = result["test_calibration"]["reliability_bins"]
        axes[0].plot(
            [item["mean_probability"] for item in bins],
            [item["empirical_frequency"] for item in bins],
            marker="o",
            linewidth=1.7,
            markersize=4,
            label=name.replace("_", " "),
            color=colors[name],
        )
        curve = result["threshold_sensitivity"]
        axes[1].plot(
            [item["false_positive_rate"] for item in curve],
            [item["false_negative_rate"] for item in curve],
            marker=".",
            linewidth=1.7,
            label=name.replace("_", " "),
            color=colors[name],
        )
    axes[0].plot([0, 1], [0, 1], linestyle="--", color="#111827", linewidth=1)
    axes[0].set(xlabel="Calibrated probability", ylabel="Empirical danger frequency", title="Held-out reliability")
    axes[1].set(xlabel="False-positive rate", ylabel="False-negative rate", title="Threshold sensitivity")
    for axis in axes:
        axis.grid(alpha=0.2)
        axis.set_xlim(left=0)
        axis.set_ylim(bottom=0)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.savefig(output / "calibration_and_threshold_sensitivity.png", dpi=220)
    plt.close(fig)

    names = list(methods)
    fpr = [methods[name]["test_operating_point"]["false_positive_rate"] for name in names]
    fnr = [methods[name]["test_operating_point"]["false_negative_rate"] for name in names]
    x = np.arange(len(names))
    fig, axis = plt.subplots(figsize=(10.5, 4.8))
    width = 0.38
    axis.bar(x - width / 2, fpr, width, label="FPR", color="#7aa6c2")
    axis.bar(x + width / 2, fnr, width, label="FNR", color="#d26a5c")
    axis.set_xticks(x, [name.replace("_", "\n") for name in names])
    axis.set_ylabel("Rate")
    axis.set_title("Validation-matched operating points transferred to v5 final")
    axis.grid(axis="y", alpha=0.2)
    axis.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output / "matched_fpr_ablation.png", dpi=220)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--figures", type=Path, default=DEFAULT_FIGURES)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    if protocol["analysis_status_at_registration"] != "not_run":
        raise ValueError("paper protocol was not frozen before analysis")

    predictors = {}
    artifact_evidence = {}
    for name, spec in protocol["artifacts"].items():
        path = ROOT / spec["path"]
        actual = sha256(path)
        if actual != spec["sha256"]:
            raise ValueError(f"{name} artifact drifted")
        artifact_evidence[name] = {"path": spec["path"], "sha256": actual}
        if name == "ordinary_supervised_mlp":
            weights = load_supervised_mlp(path)
            predictors[name] = lambda state, action, features, w=weights: supervised_prediction(
                w, state, action, features
            )
        else:
            weights = robustness.load_artifact(path)
            predictors[name] = lambda state, action, features, w=weights: robustness.prediction(
                w, state, action, features
            )

    calibration_spec = protocol["calibration_partition"]
    calibration_rows, calibration_metadata = incidents.generate_partition(
        calibration_spec["partition"],
        calibration_spec["episodes_per_source"],
        calibration_spec["steps"],
        calibration_spec["seed"],
        ROOT / calibration_spec["catalog"],
    )
    test_spec = protocol["paper_test_partition"]
    test_rows, test_metadata = incidents.generate_partition(
        test_spec["partition"],
        test_spec["episodes_per_source"],
        test_spec["steps"],
        test_spec["seed"],
        ROOT / test_spec["catalog"],
    )
    calibration_labels, calibration_rules, calibration_rule_scores = score_rows(
        calibration_rows
    )
    test_labels, test_rules, test_rule_scores = score_rows(test_rows)
    reference = confusion(calibration_labels, calibration_rules)
    regularization = protocol["probability_calibration"]["regularization"]
    bin_count = protocol["probability_calibration"]["reliability_bins"]
    grid = protocol["threshold_sensitivity"]["grid"]

    raw = {
        "rules_only": (calibration_rule_scores, test_rule_scores, None),
    }
    for name, predictor in predictors.items():
        _, _, calibration_scores = score_rows(calibration_rows, predictor)
        _, _, test_scores = score_rows(test_rows, predictor)
        raw[name] = (calibration_scores, test_scores, None)
    raw["rules_plus_v5"] = (
        np.maximum(calibration_rule_scores, raw["v5"][0]),
        np.maximum(test_rule_scores, raw["v5"][1]),
        None,
    )

    methods = {}
    for name, (calibration_scores, test_scores, _) in raw.items():
        parameters = fit_platt(calibration_scores, calibration_labels, regularization)
        calibration_probability = probabilities(calibration_scores, parameters)
        test_probability = probabilities(test_scores, parameters)
        if name == "rules_only":
            threshold = None
            calibration_operating = reference
            test_operating = confusion(test_labels, test_rules)
            sensitivity_fixed = None
            operating_source = "fixed deterministic predicate"
        elif name == "rules_plus_v5":
            v5_parameters = np.asarray(
                [
                    methods["v5"]["platt_parameters"]["slope"],
                    methods["v5"]["platt_parameters"]["intercept"],
                ]
            )
            decision_calibration_probability = probabilities(
                raw["v5"][0], v5_parameters
            )
            decision_test_probability = probabilities(raw["v5"][1], v5_parameters)
            threshold, calibration_operating = select_threshold(
                decision_calibration_probability,
                calibration_labels,
                reference["false_positive_rate"],
                calibration_rules,
            )
            test_operating = confusion(
                test_labels, test_rules | (decision_test_probability >= threshold)
            )
            sensitivity_fixed = test_rules
            sensitivity_probability = decision_test_probability
            operating_source = "fixed rules OR validation-selected v5 threshold"
        else:
            threshold, calibration_operating = select_threshold(
                calibration_probability,
                calibration_labels,
                reference["false_positive_rate"],
            )
            test_operating = confusion(test_labels, test_probability >= threshold)
            sensitivity_fixed = None
            sensitivity_probability = test_probability
            operating_source = "validation-selected learned threshold"
        if name == "rules_only":
            sensitivity_probability = test_probability
        methods[name] = {
            "platt_parameters": {
                "slope": float(parameters[0]),
                "intercept": float(parameters[1]),
            },
            "selected_probability_threshold": threshold,
            "operating_point_source": operating_source,
            "threshold_probability_source": (
                "v5 calibrated probability" if name == "rules_plus_v5" else name
            ),
            "calibration_operating_point": calibration_operating,
            "test_operating_point": test_operating,
            "test_calibration": calibration_metrics(
                test_probability, test_labels, bin_count
            ),
            "threshold_sensitivity": threshold_sensitivity(
                sensitivity_probability, test_labels, grid, sensitivity_fixed
            ),
        }

    plot_results(methods, args.figures)
    report = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(args.protocol),
        "analysis_role": "post-hoc paper characterization without selection or promotion authority",
        "artifacts": artifact_evidence,
        "calibration_evidence": incidents.summarize(calibration_rows, calibration_metadata),
        "test_evidence": incidents.summarize(test_rows, test_metadata),
        "matched_fpr_reference": reference,
        "methods": methods,
        "figures": [
            str((args.figures / "calibration_and_threshold_sensitivity.png").relative_to(ROOT)).replace("\\", "/"),
            str((args.figures / "matched_fpr_ablation.png").relative_to(ROOT)).replace("\\", "/"),
        ],
        "claim_boundary": [
            "The v5 final catalog had already been opened once before this post-hoc analysis was registered.",
            "Thresholds and calibration parameters use only the incident-v2 validation partition; final results are not retuned.",
            "All labels and transitions are generated by Ferrum's deterministic simulator from source-informed priors.",
            "These results do not alter the deployed artifact and are not physical deployment, HIL, certification, or independent safety assessment.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.table.parent.mkdir(parents=True, exist_ok=True)
    with args.table.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "method",
                "validation_fpr",
                "validation_fnr",
                "test_fpr",
                "test_fnr",
                "test_fp",
                "test_fn",
                "test_ece",
                "test_brier",
                "threshold",
            ]
        )
        for name, result in methods.items():
            writer.writerow(
                [
                    name,
                    result["calibration_operating_point"]["false_positive_rate"],
                    result["calibration_operating_point"]["false_negative_rate"],
                    result["test_operating_point"]["false_positive_rate"],
                    result["test_operating_point"]["false_negative_rate"],
                    result["test_operating_point"]["fp"],
                    result["test_operating_point"]["fn"],
                    result["test_calibration"]["ece"],
                    result["test_calibration"]["brier_score"],
                    result["selected_probability_threshold"],
                ]
            )
    print(
        json.dumps(
            {
                "report": str(args.report),
                "reference_validation_fpr": reference["false_positive_rate"],
                "methods": {
                    name: {
                        "test_fpr": result["test_operating_point"]["false_positive_rate"],
                        "test_fnr": result["test_operating_point"]["false_negative_rate"],
                        "ece": result["test_calibration"]["ece"],
                        "brier": result["test_calibration"]["brier_score"],
                    }
                    for name, result in methods.items()
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
