#!/usr/bin/env python3
"""Validation-only selection for the incident-informed OS JEPA runtime v3."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_world_model_safety import Action, Encoder, TransitionModel, action_features  # noqa: E402
from train_world_model import (  # noqa: E402
    ACTION_FEATURE_SIZE,
    EMBEDDING_SIZE,
    NUM_TOOLS,
    TOOL_NAMES,
    build_arrays,
    load_dataset,
    read_weights,
    rollout_metrics,
    split_indices,
    transition_eligible,
    write_weights,
)
from train_world_model_encoder import extract_raw  # noqa: E402
import world_model_incident_scenarios as incidents  # noqa: E402


RESEARCH = ROOT / "docs" / "research"
PROTOCOL = RESEARCH / "world_model_jepa_v3_protocol.json"
DEVELOPMENT_CATALOG = RESEARCH / "world_model_incident_sources_v3.json"
FINAL_CATALOG = RESEARCH / "world_model_incident_final_sources_v3.json"
FINAL_SCENARIOS = RESEARCH / "world_model_incident_v3_final_catalog.json"
ENCODER = ROOT / "appliance" / "world-model" / "model_encoder.bin"
BASELINE = ROOT / "appliance" / "world-model" / "model_learned.bin"
MANIFEST = ROOT / "appliance" / "world-model" / "manifest.json"
DEFAULT_REPORT = RESEARCH / "world_model_jepa_v3_selection.json"
DEFAULT_ARTIFACT = ROOT / "target" / "world-model-v3-work" / "world_model_jepa_v3_candidate.bin"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def geometric(values: list[float]) -> float:
    return math.exp(sum(math.log(max(value, 1e-12)) for value in values) / len(values))


def install_final_guard() -> dict:
    protected = {FINAL_CATALOG.resolve(), FINAL_SCENARIOS.resolve()}
    state = {"attempted": False, "paths": []}

    def audit(event: str, arguments: tuple) -> None:
        if event != "open" or not arguments or not isinstance(arguments[0], (str, bytes)):
            return
        try:
            opened = Path(os.fsdecode(arguments[0])).resolve()
        except (OSError, TypeError, ValueError):
            return
        if opened in protected:
            state["attempted"] = True
            state["paths"].append(str(opened))
            raise PermissionError("final OS-JEPA v3 catalog access is forbidden during selection")

    sys.addaudithook(audit)
    return state


class ArrayTransitionModel:
    def __init__(self, weights: tuple[np.ndarray, ...], coverage: int):
        self.w1, self.b1, self.w2, self.b2 = weights
        self.coverage = coverage

    def predict(self, state: np.ndarray, action: Action):
        return self.predict_features(
            state,
            TOOL_NAMES.index(action.name),
            action_features(action),
        )

    def predict_features(self, state: np.ndarray, action_id: int, features: np.ndarray):
        if self.coverage & (1 << action_id) == 0:
            return None
        inputs = np.zeros(EMBEDDING_SIZE + NUM_TOOLS + ACTION_FEATURE_SIZE, dtype=np.float32)
        inputs[:EMBEDDING_SIZE] = state
        inputs[EMBEDDING_SIZE + action_id] = 1.0
        inputs[EMBEDDING_SIZE + NUM_TOOLS:] = features
        hidden = np.maximum(inputs @ self.w1 + self.b1, 0.0)
        delta = hidden @ self.w2 + self.b2
        if not np.isfinite(delta).all():
            return None
        predicted = state + delta
        predicted[:51] = np.clip(predicted[:51], 0.0, 1.0)
        predicted[51:] = np.clip(predicted[51:], -1.0, 1.0)
        raw = float(delta[0] * 64.0)
        proc_delta = math.floor(raw + 0.5) if raw >= 0 else math.ceil(raw - 0.5)
        return predicted.astype(np.float32), proc_delta


def encode_published_rows(rows: list[dict], encoder: Encoder) -> list[dict]:
    encoded = []
    for row in rows:
        if not transition_eligible(row):
            continue
        before = encoder.state(extract_raw(row["before"]))
        after = encoder.state(extract_raw(row["after"]))
        encoded.append({**row, "before": before.tolist(), "after": after.tolist()})
    return encoded


def arrays(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    x, y, _ = build_arrays(rows)
    return x, y


def decoder_statistics(domains: list[tuple[np.ndarray, np.ndarray]],
                       baseline: tuple[np.ndarray, ...]):
    w1, b1, w2, b2 = baseline
    width = w2.shape[0] + 1
    xtx = np.zeros((width, width), dtype=np.float64)
    xty = np.zeros((width, w2.shape[1]), dtype=np.float64)
    for x, y in domains:
        hidden = np.maximum(x @ w1 + b1, 0.0).astype(np.float64)
        design = np.concatenate((hidden, np.ones((len(hidden), 1))), axis=1)
        xtx += (design.T @ design) / len(design)
        xty += (design.T @ y.astype(np.float64)) / len(design)
    anchor = np.concatenate((w2, b2[None, :]), axis=0).astype(np.float64)
    return xtx, xty, anchor


def fit_decoder(statistics, ridge_lambda: float) -> np.ndarray:
    xtx, xty, anchor = statistics
    penalty = np.eye(len(anchor), dtype=np.float64) * ridge_lambda
    penalty[-1, -1] *= 0.1
    return np.linalg.solve(xtx + penalty, xty + penalty @ anchor)


def candidate_weights(baseline: tuple[np.ndarray, ...], decoder: np.ndarray,
                      blend: float) -> tuple[np.ndarray, ...]:
    w1, b1, w2, b2 = baseline
    anchor = np.concatenate((w2, b2[None, :]), axis=0).astype(np.float64)
    mixed = anchor + blend * (decoder - anchor)
    return w1.copy(), b1.copy(), mixed[:-1].astype(np.float32), mixed[-1].astype(np.float32)


def compact_conditions(result: dict) -> dict:
    return {name: value["metrics"] for name, value in result.items()}


def base_rollout(rows: list[dict], indices: np.ndarray,
                 weights: tuple[np.ndarray, ...]) -> dict:
    raw = rollout_metrics(rows, indices, weights, 5)
    return {
        f"h{horizon}": {
            "samples": raw[str(horizon)]["samples"] if str(horizon) in raw else raw[horizon]["samples"],
            "normalized_mse": raw[str(horizon)]["normalized_mse"] if str(horizon) in raw else raw[horizon]["normalized_mse"],
        }
        for horizon in (1, 3, 5)
    }


def ratio_report(candidate: dict, baseline: dict) -> dict:
    ratios = {
        key: candidate[key]["normalized_mse"] / max(baseline[key]["normalized_mse"], 1e-12)
        for key in ("h1", "h3", "h5")
    }
    return {"ratios": ratios, "geometric_ratio": geometric(list(ratios.values()))}


def variance_ratio(x: np.ndarray, y: np.ndarray, weights: tuple[np.ndarray, ...]) -> float:
    w1, b1, w2, b2 = weights
    predicted = np.maximum(x @ w1 + b1, 0.0) @ w2 + b2
    return float(np.var(predicted) / max(float(np.var(y)), 1e-12))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args()
    if args.artifact.resolve() == BASELINE.resolve():
        parser.error("validation-only selection cannot overwrite the deployed transition")

    guard = install_final_guard()
    deployed_before = {path.name: sha256(path) for path in (ENCODER, BASELINE, MANIFEST)}
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    frozen = protocol["frozen_lineage"]
    if sha256(args.dataset) != frozen["dataset_sha256"]:
        raise AssertionError("published dataset digest mismatch")
    if sha256(DEVELOPMENT_CATALOG) != protocol["source_catalogs"]["development"]["sha256"]:
        raise AssertionError("development source catalog drifted")
    if not protocol["registered_before_candidate_selection"] or protocol["final_scenario_open_count"] != 0:
        raise AssertionError("v3 protocol is not sealed for validation-only selection")

    encoder = Encoder(ENCODER)
    baseline_weights, coverage = read_weights(BASELINE)
    baseline_model = ArrayTransitionModel(baseline_weights, coverage)
    published = load_dataset(args.dataset)
    encoded = encode_published_rows(published, encoder)
    train_idx, validation_idx, _, split_mode = split_indices(encoded, 0.15, 0.15, 42)
    base_x, base_y = arrays(encoded)
    base_train = (base_x[train_idx], base_y[train_idx])

    fit = protocol["fit_partitions"]["incident"]
    incident_train_cases, incident_train_metadata = incidents.generate_partition(
        DEVELOPMENT_CATALOG, "train", fit["episodes_per_source"], fit["maximum_steps"], fit["seed"]
    )
    incident_train_rows = incidents.transition_rows(incident_train_cases, encoder)
    incident_train = arrays(incident_train_rows)
    selection = protocol["selection_partitions"]["incident"]
    incident_validation_cases, incident_validation_metadata = incidents.generate_partition(
        DEVELOPMENT_CATALOG,
        "validation",
        selection["episodes_per_source"],
        selection["maximum_steps"],
        selection["seed"],
    )
    incident_validation_rows = incidents.transition_rows(incident_validation_cases, encoder)
    incident_validation_x, incident_validation_y = arrays(incident_validation_rows)

    baseline_base = base_rollout(encoded, validation_idx, baseline_weights)
    baseline_incident = incidents.rollout_metrics(incident_validation_cases, encoder, baseline_model)
    baseline_conditions = incidents.evaluate_conditions(
        incident_validation_cases,
        encoder,
        {"baseline": baseline_model, "candidate": baseline_model},
    )
    statistics = decoder_statistics([base_train, incident_train], baseline_weights)

    candidates = []
    models = []
    grid = protocol["candidate"]
    for ridge_lambda in grid["decoder_ridge_lambda"]:
        fitted = fit_decoder(statistics, float(ridge_lambda))
        for blend in grid["decoder_blend"]:
            weights = candidate_weights(baseline_weights, fitted, float(blend))
            model = ArrayTransitionModel(weights, coverage)
            base_result = base_rollout(encoded, validation_idx, weights)
            incident_result = incidents.rollout_metrics(incident_validation_cases, encoder, model)
            conditions = incidents.evaluate_conditions(
                incident_validation_cases,
                encoder,
                {"baseline": baseline_model, "candidate": model},
            )
            base_ratio = ratio_report(base_result, baseline_base)
            incident_ratio = ratio_report(incident_result, baseline_incident)
            current_learned = baseline_conditions["jepa_only"]["metrics"]
            candidate_learned = conditions["jepa_candidate_only"]["metrics"]
            current_combined = baseline_conditions["rules_v3_plus_jepa_baseline"]["metrics"]
            candidate_combined = conditions["rules_v3_plus_jepa_candidate"]["metrics"]
            checks = {
                "all_predictions_finite": all(
                    incident_result[key]["all_predictions_finite"] for key in ("h1", "h3", "h5")
                ),
                "base_no_horizon_regression_over_two_percent": all(
                    value <= 1.02 for value in base_ratio["ratios"].values()
                ),
                "base_geometric_non_regression": base_ratio["geometric_ratio"] <= 1.0,
                "incident_geometric_improvement_at_least_five_percent": incident_ratio["geometric_ratio"] <= 0.95,
                "incident_no_horizon_regression": all(
                    value <= 1.0 for value in incident_ratio["ratios"].values()
                ),
                "learned_false_negatives_not_increased": candidate_learned["confusion"]["false_negative"]
                <= current_learned["confusion"]["false_negative"],
                "combined_false_negatives_not_increased": candidate_combined["confusion"]["false_negative"]
                <= current_combined["confusion"]["false_negative"],
                "combined_false_positive_rate_within_two_points": candidate_combined["false_positive_rate"]
                <= current_combined["false_positive_rate"] + 0.02,
                "prediction_variance_ratio": variance_ratio(
                    incident_validation_x, incident_validation_y, weights
                ) >= 0.10,
            }
            candidates.append({
                "decoder_ridge_lambda": ridge_lambda,
                "decoder_blend": blend,
                "base_validation": base_result,
                "base_ratio": base_ratio,
                "incident_validation": incident_result,
                "incident_ratio": incident_ratio,
                "conditions": compact_conditions(conditions),
                "prediction_variance_ratio": variance_ratio(
                    incident_validation_x, incident_validation_y, weights
                ),
                "checks": checks,
                "accepted": all(checks.values()),
            })
            models.append(weights)

    accepted = [index for index, item in enumerate(candidates) if item["accepted"]]
    selected_index = min(
        accepted,
        key=lambda index: (
            candidates[index]["incident_ratio"]["geometric_ratio"],
            candidates[index]["base_ratio"]["geometric_ratio"],
        ),
        default=None,
    )
    artifact_sha = None
    if selected_index is not None:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        write_weights(args.artifact, *models[selected_index], coverage)
        artifact_sha = sha256(args.artifact)

    deployed_after = {path.name: sha256(path) for path in (ENCODER, BASELINE, MANIFEST)}
    if deployed_after != deployed_before:
        raise AssertionError("deployed world-model files changed during validation selection")
    report = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "dataset_sha256": sha256(args.dataset),
        "split_mode": split_mode,
        "base_rows": {
            "eligible": len(encoded),
            "train": len(train_idx),
            "validation": len(validation_idx),
        },
        "incident_train": incident_train_metadata,
        "incident_validation": incident_validation_metadata,
        "baseline": {
            "base_validation": baseline_base,
            "incident_validation": baseline_incident,
            "conditions": compact_conditions(baseline_conditions),
        },
        "candidates": candidates,
        "accepted_candidate_indices": accepted,
        "selected_candidate_index": selected_index,
        "selection_passed": selected_index is not None,
        "selected_artifact": str(args.artifact.relative_to(ROOT)).replace("\\", "/") if selected_index is not None else None,
        "selected_artifact_sha256": artifact_sha,
        "final_catalog_access": {
            "opened": False,
            "attempted": guard["attempted"],
            "guard": "python_audit_hook_fail_closed",
            "scenario_catalog_preexisting": FINAL_SCENARIOS.exists(),
        },
        "deployment": {
            "attempted": False,
            "sha256_before": deployed_before,
            "sha256_after": deployed_after,
            "unchanged": True,
            "final_promotion_gates_evaluated": False,
        },
        "claim_boundary": [
            "Candidate selection used only the published training/validation split and registered development sources.",
            "The final source catalog and final scenario catalog were not opened during selection.",
            "The fixed v3 rules are reported separately from learned decoder changes.",
            "A selected artifact is not promoted and has no additional execution authority."
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidates": len(candidates),
        "accepted": len(accepted),
        "selected_candidate_index": selected_index,
        "selected_artifact_sha256": artifact_sha,
        "final_catalog_opened": False,
        "deployment_unchanged": True,
    }, indent=2))
    return 0 if selected_index is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
