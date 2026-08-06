#!/usr/bin/env python3
"""Evaluate independently trained JEPA + transition pipelines across seeds."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
from typing import Callable

from evaluate_world_model_safety import Encoder, TransitionModel, evaluate as evaluate_safety


T_95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def interval(values: list[float]) -> dict:
    mean = statistics.mean(values)
    sample_sd = statistics.stdev(values) if len(values) > 1 else 0.0
    if len(values) <= 1:
        margin = 0.0
    else:
        critical = T_95.get(len(values) - 1, 1.96)
        margin = critical * sample_sd / (len(values) ** 0.5)
    return {
        "n": len(values),
        "mean": mean,
        "sample_standard_deviation": sample_sd,
        "confidence_interval_95_t": [mean - margin, mean + margin],
        "min": min(values),
        "max": max(values),
    }


def aggregate(rows: list[dict], name: str, accessor: Callable[[dict], float]) -> tuple[str, dict]:
    return name, interval([float(accessor(row)) for row in rows])


def ranking_metrics(records: list[dict]) -> tuple[float, float]:
    positives = [float(row["risk"]) for row in records if row["dangerous"]]
    negatives = [float(row["risk"]) for row in records if not row["dangerous"]]
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives for negative in negatives
    )
    auroc = wins / (len(positives) * len(negatives))
    ranked = sorted(records, key=lambda row: float(row["risk"]), reverse=True)
    true_so_far = 0
    precision_sum = 0.0
    for rank, row in enumerate(ranked, 1):
        if row["dangerous"]:
            true_so_far += 1
            precision_sum += true_so_far / rank
    return auroc, precision_sum / len(positives)


def evaluate_full(run_dir: Path, fixture_path: Path, seeds: list[int]) -> dict:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sorted(int(seed) for seed in manifest["seeds"]) != sorted(seeds):
        raise ValueError("run manifest seed set does not match evaluation seed set")
    results = []
    for seed in seeds:
        seed_dir = run_dir / f"seed_{seed}"
        encoder_path = seed_dir / "encoder.bin"
        transition_path = seed_dir / "transition.bin"
        encoder_metrics_path = seed_dir / "encoder_metrics.json"
        transition_metrics_path = seed_dir / "transition_metrics.json"
        for required in (encoder_path, transition_path, encoder_metrics_path, transition_metrics_path):
            if not required.is_file():
                raise FileNotFoundError(f"seed {seed} is incomplete: {required}")
        encoder_metrics = json.loads(encoder_metrics_path.read_text(encoding="utf-8"))
        transition_metrics = json.loads(transition_metrics_path.read_text(encoding="utf-8"))
        encoder_test = encoder_metrics["test"]
        evaluated, records = evaluate_safety(
            fixture,
            Encoder(encoder_path),
            TransitionModel(transition_path),
            3,
        )
        combined = evaluated["conditions"]["rules_plus_jepa"]
        confusion = combined["confusion"]
        combined_records = [row for row in records if row["condition"] == "rules_plus_jepa"]
        auroc, average_precision = ranking_metrics(combined_records)
        results.append({
            "seed": seed,
            "encoder_sha256": sha256(encoder_path),
            "transition_sha256": sha256(transition_path),
            "encoder": {
                "prediction_mse": encoder_test["prediction_mse"],
                "reconstruction_mse": encoder_test["reconstruction_mse"],
                "latent_standard_deviation": encoder_test["latent_std"],
                "effective_rank": encoder_test["effective_rank"],
                "action_sensitivity": encoder_test["action_sensitivity"],
            },
            "transition": {
                "normalized_mse": transition_metrics["normalized_mse"],
                "rollout_h3_normalized_mse": transition_metrics["rollout"]["3"]["normalized_mse"],
            },
            "safety": {
                "tp": confusion["true_positive"],
                "fn": confusion["false_negative"],
                "fp": confusion["false_positive"],
                "tn": confusion["true_negative"],
                "false_negative_rate": combined["false_negative_rate"],
                "false_positive_rate": combined["false_positive_rate"],
                "balanced_accuracy": combined["balanced_accuracy"],
                "auroc": auroc,
                "average_precision": average_precision,
            },
        })

    aggregates = dict([
        aggregate(results, "transition_normalized_mse", lambda row: row["transition"]["normalized_mse"]),
        aggregate(results, "transition_rollout_h3_normalized_mse", lambda row: row["transition"]["rollout_h3_normalized_mse"]),
        aggregate(results, "combined_false_negative_rate", lambda row: row["safety"]["false_negative_rate"]),
        aggregate(results, "combined_false_positive_rate", lambda row: row["safety"]["false_positive_rate"]),
        aggregate(results, "combined_balanced_accuracy", lambda row: row["safety"]["balanced_accuracy"]),
        aggregate(results, "combined_auroc", lambda row: row["safety"]["auroc"]),
        aggregate(results, "combined_average_precision", lambda row: row["safety"]["average_precision"]),
    ])
    return {
        "schema_version": 1,
        "protocol": "full-jepa-transition-pipeline-seeds-v1",
        "source_dataset": manifest["dataset"],
        "fixture": {"path": str(fixture_path), "sha256": sha256(fixture_path)},
        "seed_count": len(results),
        "selection_policy": "all seeds are reported; no safety-test result is used for checkpoint selection",
        "runs": results,
        "aggregate": aggregates,
        "interpretation": (
            "Each seed independently initializes the online encoder, EMA target, JEPA predictor, "
            "reconstruction/action heads, and downstream transition MLP. Confidence intervals describe "
            "between-run uncertainty on the fixed authored fixture, not population-level deployment uncertainty."
        ),
    }


def markdown(report: dict) -> str:
    lines = [
        "# FerrumOS full-pipeline seed evaluation",
        "",
        "Every row independently trains the JEPA representation and transition MLP. The authored",
        "500-episode safety fixture is fixed and is never used for checkpoint selection.",
        "",
        "| Seed | Transition normalized error | H=3 normalized error | FNR | FPR | Balanced accuracy | AUROC | AUPRC |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["runs"]:
        lines.append(
            f"| {row['seed']} | {100 * row['transition']['normalized_mse']:.2f}% | "
            f"{100 * row['transition']['rollout_h3_normalized_mse']:.2f}% | "
            f"{100 * row['safety']['false_negative_rate']:.1f}% | "
            f"{100 * row['safety']['false_positive_rate']:.1f}% | "
            f"{100 * row['safety']['balanced_accuracy']:.1f}% | {row['safety']['auroc']:.3f} | "
            f"{row['safety']['average_precision']:.3f} |"
        )
    lines.extend([
        "",
        "The selected fixed-encoder checkpoint's 3.87% H=3 error is not one of these",
        "end-to-end runs. Each row above retrains both the representation and transition",
        "model; the larger values expose seed sensitivity plus compounding rollout error",
        "instead of reusing the selected seed-42 representation.",
        "",
        "## Aggregate",
        "",
    ])
    percent_metrics = {
        "transition_normalized_mse",
        "transition_rollout_h3_normalized_mse",
        "combined_false_negative_rate",
        "combined_false_positive_rate",
        "combined_balanced_accuracy",
    }
    for name, values in report["aggregate"].items():
        lower, upper = values["confidence_interval_95_t"]
        if name in percent_metrics:
            lines.append(
                f"- `{name}`: mean {100 * values['mean']:.2f}%, sample SD "
                f"{100 * values['sample_standard_deviation']:.2f} percentage points, "
                f"95% t interval [{100 * lower:.2f}%, {100 * upper:.2f}%], "
                f"range [{100 * values['min']:.2f}%, {100 * values['max']:.2f}%]."
            )
        else:
            lines.append(
                f"- `{name}`: mean {values['mean']:.4f}, sample SD "
                f"{values['sample_standard_deviation']:.4f}, 95% t interval [{lower:.4f}, {upper:.4f}], "
                f"range [{values['min']:.4f}, {values['max']:.4f}]."
            )
    lines.extend([
        "",
        "The interval is across complete training runs on one fixed authored fixture. It does not",
        "replace independent labels, natural-prevalence evaluation, or uncertainty across operating",
        "systems and workloads.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=Path("docs/research/world_model_safety_scenarios.json"))
    parser.add_argument("--seeds", default="17,42,91,123,2026")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    args = parser.parse_args()
    seeds = [int(value) for value in args.seeds.split(",") if value.strip()]
    report = evaluate_full(args.run_dir, args.fixture, seeds)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"seeds": len(seeds), "json": str(args.json_out)}, indent=2))


if __name__ == "__main__":
    main()
