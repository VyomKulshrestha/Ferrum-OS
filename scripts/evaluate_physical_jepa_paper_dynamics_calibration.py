#!/usr/bin/env python3
"""Registered shared-catalog dynamics and calibration uncertainty audit.

This post-hoc evaluator has no selection, promotion, replacement, or deployment
authority. It refuses to overwrite its evidence output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_paper as paper  # noqa: E402
import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_incident_scenarios as incidents  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402


DEFAULT_PROTOCOL = (
    ROOT / "docs" / "research" / "physical_jepa_paper_dynamics_calibration_protocol_v1.json"
)
DEFAULT_OUTPUT = (
    ROOT / "docs" / "research" / "physical_jepa_paper_dynamics_calibration_result_v1.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile_interval(values: np.ndarray, alpha: float) -> dict[str, float]:
    lower, upper = np.quantile(values, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {"lower": float(lower), "upper": float(upper)}


def episode_rollout_errors(rows, predictor, horizons):
    grouped = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row)
    episode_ids = np.asarray(sorted(grouped), dtype=np.int64)
    errors = {horizon: [] for horizon in horizons}
    for episode in episode_ids:
        episode_rows = sorted(grouped[int(episode)], key=lambda row: row[1])
        for horizon in horizons:
            windows = []
            for start in range(len(episode_rows) - horizon + 1):
                predicted = episode_rows[start][2].copy()
                for offset in range(horizon):
                    row = episode_rows[start + offset]
                    predicted = np.clip(
                        predicted + predictor(predicted, row[3], row[4]),
                        -1.25,
                        1.25,
                    )
                actual = episode_rows[start + horizon - 1][5]
                windows.append(
                    np.mean(np.abs(predicted - actual) / simulator.STATE_RANGES)
                )
            errors[horizon].append(float(np.mean(windows)))
    return episode_ids, {
        horizon: np.asarray(values, dtype=np.float64)
        for horizon, values in errors.items()
    }


def source_stratified_counts(metadata, episode_ids, resamples, seed):
    source_to_indices = {}
    for index, episode in enumerate(episode_ids):
        source = metadata[int(episode)]["source_id"]
        source_to_indices.setdefault(source, []).append(index)
    rng = np.random.default_rng(seed)
    counts = np.zeros((resamples, len(episode_ids)), dtype=np.uint16)
    for source in sorted(source_to_indices):
        indices = np.asarray(source_to_indices[source], dtype=np.int64)
        draws = rng.multinomial(
            len(indices),
            np.full(len(indices), 1.0 / len(indices)),
            size=resamples,
        )
        counts[:, indices] = draws.astype(np.uint16)
    return counts, {source: len(indices) for source, indices in sorted(source_to_indices.items())}


def dynamics_audit(rows, metadata, protocol, paper_protocol, final_test, counts):
    horizons = protocol["dynamics"]["horizons"]
    artifacts = paper_protocol["artifacts"]
    mlp_weights = paper.load_supervised_mlp(ROOT / artifacts["ordinary_supervised_mlp"]["path"])
    jepa_weights = {
        name: robustness.load_artifact(ROOT / artifacts[name]["path"])
        for name in ("v3", "v5")
    }
    predictors = {
        "ordinary_supervised_mlp": lambda state, action, features: simulator.predict(
            simulator.make_input(state, action, features), mlp_weights
        )[0],
        "v3": lambda state, action, features: robustness.prediction(
            jepa_weights["v3"], state, action, features
        )
        - state,
        "v5": lambda state, action, features: robustness.prediction(
            jepa_weights["v5"], state, action, features
        )
        - state,
    }
    methods = {}
    raw = {}
    episode_ids = None
    for name, predictor in predictors.items():
        current_ids, errors = episode_rollout_errors(rows, predictor, horizons)
        if episode_ids is None:
            episode_ids = current_ids
        elif not np.array_equal(episode_ids, current_ids):
            raise ValueError("episode ordering changed across dynamics methods")
        raw[name] = errors
        methods[name] = {}
        for horizon in horizons:
            bootstrap = counts @ errors[horizon] / counts.sum(axis=1)
            methods[name][f"h{horizon}"] = {
                "estimate": float(errors[horizon].mean()),
                "bootstrap_95_percent": percentile_interval(
                    bootstrap, protocol["bootstrap"]["alpha"]
                ),
            }

    paired = {}
    for baseline in ("ordinary_supervised_mlp", "v3"):
        paired[baseline] = {}
        for horizon in horizons:
            reduction = raw[baseline][horizon] - raw["v5"][horizon]
            bootstrap = counts @ reduction / counts.sum(axis=1)
            interval = percentile_interval(bootstrap, protocol["bootstrap"]["alpha"])
            paired[baseline][f"h{horizon}"] = {
                "mean_error_reduction_baseline_minus_v5": float(reduction.mean()),
                "bootstrap_95_percent": interval,
                "interval_excludes_zero": interval["lower"] > 0.0
                or interval["upper"] < 0.0,
            }

    tolerance = protocol["reproduction_tolerance"]
    reproduced = True
    for name, frozen_key in (("v3", "baseline_final"), ("v5", "candidate_final")):
        for horizon in horizons:
            reproduced &= abs(
                methods[name][f"h{horizon}"]["estimate"]
                - final_test[frozen_key]["rollout"][f"h{horizon}"]
            ) <= tolerance
    return {
        "unit": "episode",
        "methods": methods,
        "paired_reductions": paired,
        "v3_and_v5_reproduce_frozen_final_test": bool(reproduced),
    }


def calibration_probabilities(rows, protocol, paper_protocol, paper_results):
    labels, _, _ = paper.score_rows(rows)
    result = {}
    for name in protocol["calibration"]["methods"]:
        artifact = paper_protocol["artifacts"][name]
        path = ROOT / artifact["path"]
        if name == "ordinary_supervised_mlp":
            weights = paper.load_supervised_mlp(path)
            predictor = lambda state, action, features, w=weights: paper.supervised_prediction(
                w, state, action, features
            )
        else:
            weights = robustness.load_artifact(path)
            predictor = lambda state, action, features, w=weights: robustness.prediction(
                w, state, action, features
            )
        _, _, scores = paper.score_rows(rows, predictor)
        params = paper_results["methods"][name]["platt_parameters"]
        result[name] = paper.probabilities(
            scores, np.asarray([params["slope"], params["intercept"]])
        )
    return labels, result


def calibration_audit(rows, episode_ids, protocol, paper_protocol, paper_results, counts):
    labels, probabilities = calibration_probabilities(
        rows, protocol, paper_protocol, paper_results
    )
    episode_index = {int(episode): index for index, episode in enumerate(episode_ids)}
    row_episode = np.asarray([episode_index[int(row[0])] for row in rows], dtype=np.int64)
    labels_float = labels.astype(np.float64)
    bins = protocol["calibration"]["equal_mass_bins"]
    if len(rows) % bins:
        raise ValueError("equal-mass bootstrap requires equally sized bins")
    rows_per_bin = len(rows) // bins
    methods = {}
    bootstrap_values = {}
    for name, probability in probabilities.items():
        point = paper.calibration_metrics(probability, labels, bins)
        frozen = paper_results["methods"][name]["test_calibration"]
        if any(
            abs(point[key] - frozen[key]) > protocol["reproduction_tolerance"]
            for key in ("ece", "brier_score")
        ):
            raise ValueError(f"{name} calibration point estimate did not reproduce")

        squared = (probability - labels_float) ** 2
        episode_brier_sum = np.bincount(
            row_episode, weights=squared, minlength=len(episode_ids)
        )
        brier_bootstrap = counts @ episode_brier_sum / len(rows)
        order = np.argsort(probability, kind="mergesort")
        sorted_probability = probability[order]
        sorted_labels = labels_float[order]
        ece_bootstrap = np.empty(len(counts), dtype=np.float64)
        for replicate, episode_counts in enumerate(counts):
            weights = episode_counts[row_episode][order]
            expanded = np.repeat(np.arange(len(rows)), weights)
            if len(expanded) != len(rows):
                raise ValueError("bootstrap replicate changed sample size")
            bin_probability = sorted_probability[expanded].reshape(bins, rows_per_bin)
            bin_labels = sorted_labels[expanded].reshape(bins, rows_per_bin)
            ece_bootstrap[replicate] = float(
                np.mean(np.abs(bin_probability.mean(axis=1) - bin_labels.mean(axis=1)))
            )
        bootstrap_values[name] = {
            "ece": ece_bootstrap,
            "brier_score": brier_bootstrap,
        }
        methods[name] = {
            "ece": {
                "estimate": point["ece"],
                "bootstrap_95_percent": percentile_interval(
                    ece_bootstrap, protocol["bootstrap"]["alpha"]
                ),
            },
            "brier_score": {
                "estimate": point["brier_score"],
                "bootstrap_95_percent": percentile_interval(
                    brier_bootstrap, protocol["bootstrap"]["alpha"]
                ),
            },
        }

    paired = {}
    for baseline in protocol["calibration"]["paired_v5_comparators"]:
        paired[baseline] = {}
        for metric in ("ece", "brier_score"):
            difference = bootstrap_values["v5"][metric] - bootstrap_values[baseline][metric]
            interval = percentile_interval(difference, protocol["bootstrap"]["alpha"])
            paired[baseline][metric] = {
                "difference_v5_minus_baseline": methods["v5"][metric]["estimate"]
                - methods[baseline][metric]["estimate"],
                "bootstrap_95_percent": interval,
                "interval_excludes_zero": interval["lower"] > 0.0
                or interval["upper"] < 0.0,
            }
    return {"unit": "episode", "methods": methods, "paired_differences": paired}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {args.output}")

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    if protocol["analysis_status_at_registration"] != "not_run":
        raise ValueError("analysis protocol was not registered before execution")
    inputs = {}
    for name, record in protocol["inputs"].items():
        path = ROOT / record["path"]
        actual = sha256(path)
        if actual != record["sha256"]:
            raise ValueError(f"registered input drifted: {name}")
        inputs[name] = {"path": record["path"], "sha256": actual}

    paper_protocol = json.loads((ROOT / protocol["inputs"]["paper_protocol"]["path"]).read_text(encoding="utf-8"))
    paper_results = json.loads((ROOT / protocol["inputs"]["paper_results"]["path"]).read_text(encoding="utf-8"))
    final_test = json.loads((ROOT / protocol["inputs"]["v5_final_test"]["path"]).read_text(encoding="utf-8"))
    spec = paper_protocol["paper_test_partition"]
    rows, metadata = incidents.generate_partition(
        spec["partition"], spec["episodes_per_source"], spec["steps"], spec["seed"], ROOT / spec["catalog"]
    )
    summary = incidents.summarize(rows, metadata)
    if summary != paper_results["test_evidence"]:
        raise ValueError("regenerated final partition does not match frozen paper evidence")

    episode_ids = np.asarray(sorted(metadata), dtype=np.int64)
    counts, source_counts = source_stratified_counts(
        metadata,
        episode_ids,
        protocol["bootstrap"]["resamples"],
        protocol["bootstrap"]["seed"],
    )
    dynamics = dynamics_audit(
        rows, metadata, protocol, paper_protocol, final_test, counts
    )
    calibration = calibration_audit(
        rows, episode_ids, protocol, paper_protocol, paper_results, counts
    )
    checks = {
        "registered_inputs_match": True,
        "final_partition_reproduces": True,
        "source_strata_match": source_counts == summary["source_episode_counts"],
        "v3_and_v5_dynamics_reproduce_frozen_final_test": dynamics[
            "v3_and_v5_reproduce_frozen_final_test"
        ],
        "deployed_artifact_unchanged": sha256(
            ROOT / protocol["inputs"]["deployed_artifact"]["path"]
        )
        == protocol["inputs"]["deployed_artifact"]["sha256"],
    }
    report = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(args.protocol),
        "analysis_role": protocol["analysis_role"],
        "inputs": inputs,
        "test_evidence": summary,
        "bootstrap": {
            **protocol["bootstrap"],
            "source_episode_counts": source_counts,
        },
        "shared_catalog_dynamics": dynamics,
        "calibration_uncertainty": calibration,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "claim_boundary": "Post-hoc deterministic-simulator analysis of an already-opened final catalog; not selection, promotion, replacement, deployment, HIL, physical evidence, certification, or independent assessment.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
