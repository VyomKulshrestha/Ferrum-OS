#!/usr/bin/env python3
"""Fit the registered v5 baseline-anchored decoder without opening its test."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_incident_scenarios as incidents  # noqa: E402
import physical_stress_scenarios as stress  # noqa: E402
import select_physical_incident_jepa as selector  # noqa: E402
import train_physical_jepa as jepa  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402


PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_v5_protocol.json"
BASELINE = ROOT / "docs" / "research" / "artifacts" / "physical-jepa-v5" / "baseline_v3.bin"
INCIDENT_CATALOG = ROOT / "docs" / "research" / "physical_incident_sources_v2.json"
FINAL_CATALOG = ROOT / "docs" / "research" / "physical_incident_v5_test_sources.json"
DEPLOYED_ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
DEFAULT_REPORT = ROOT / "docs" / "research" / "physical_jepa_v5_selection.json"
DEFAULT_ARTIFACT = ROOT / "target" / "physical_world_model" / "v5_candidate.bin"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved).replace("\\", "/")


def install_final_catalog_guard() -> dict[str, bool]:
    """Fail closed if this validation-only process tries to open the final catalog."""
    protected = FINAL_CATALOG.resolve()
    state = {"attempted": False}

    def audit(event: str, arguments: tuple) -> None:
        if event != "open" or not arguments or not isinstance(arguments[0], (str, bytes)):
            return
        try:
            opened = Path(os.fsdecode(arguments[0])).resolve()
        except (OSError, TypeError, ValueError):
            return
        if opened == protected:
            state["attempted"] = True
            raise PermissionError("v5 final catalog access is forbidden during selection")

    sys.addaudithook(audit)
    return state


def predicted_latent(rows, weights) -> tuple[np.ndarray, np.ndarray]:
    state, actions, delta, _ = jepa.state_arrays(rows)
    latent = np.tanh(state @ weights["encoder_w"] + weights["encoder_b"])
    predictor_input = np.concatenate((latent, actions), axis=1)
    hidden = np.maximum(
        predictor_input @ weights["predictor_w1"] + weights["predictor_b1"], 0
    )
    predicted = hidden @ weights["predictor_w2"] + weights["predictor_b2"]
    design = np.concatenate(
        (predicted, np.ones((len(predicted), 1), dtype=np.float32)), axis=1
    )
    return design.astype(np.float64), delta.astype(np.float64)


def batch_prediction(
    weights: dict,
    state: np.ndarray,
    action: np.ndarray,
    features: np.ndarray,
) -> np.ndarray:
    action_vector = np.zeros(
        (len(state), simulator.ACTION_COUNT + simulator.ACTION_FEATURE_SIZE),
        dtype=np.float32,
    )
    action_vector[np.arange(len(state)), action] = 1.0
    action_vector[:, simulator.ACTION_COUNT :] = features
    latent = np.tanh(state @ weights["encoder_w"] + weights["encoder_b"])
    predictor_input = np.concatenate((latent, action_vector), axis=1)
    hidden = np.maximum(
        predictor_input @ weights["predictor_w1"] + weights["predictor_b1"], 0
    )
    predicted_latent = hidden @ weights["predictor_w2"] + weights["predictor_b2"]
    delta = predicted_latent @ weights["state_w"] + weights["state_b"]
    return np.clip(state + delta, -1.25, 1.25).astype(np.float32)


def prepare_evaluation(rows) -> dict:
    state = np.asarray([row[2] for row in rows], dtype=np.float32)
    action = np.asarray([row[3] for row in rows], dtype=np.int64)
    features = np.asarray([row[4] for row in rows], dtype=np.float32)
    actual = np.asarray([row[5] for row in rows], dtype=np.float32)
    danger = np.asarray([row[6] for row in rows], dtype=bool)
    grouped = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row)
    rollouts = {}
    for horizon in range(1, 6):
        initial = []
        actions = []
        action_features = []
        targets = []
        for episode_rows in grouped.values():
            episode_rows.sort(key=lambda row: row[1])
            for start in range(len(episode_rows) - horizon + 1):
                window = episode_rows[start : start + horizon]
                initial.append(window[0][2])
                actions.append([row[3] for row in window])
                action_features.append([row[4] for row in window])
                targets.append(window[-1][5])
        rollouts[horizon] = {
            "state": np.asarray(initial, dtype=np.float32),
            "action": np.asarray(actions, dtype=np.int64),
            "features": np.asarray(action_features, dtype=np.float32),
            "actual": np.asarray(targets, dtype=np.float32),
        }
    return {
        "state": state,
        "action": action,
        "features": features,
        "actual": actual,
        "danger": danger,
        "rollouts": rollouts,
    }


def batched_diagnostics(prepared: dict, weights: dict) -> dict:
    state = prepared["state"]
    action = prepared["action"]
    features = prepared["features"]
    predicted = batch_prediction(weights, state, action, features)
    errors = np.mean(
        np.abs(predicted - prepared["actual"]) / simulator.STATE_RANGES,
        axis=1,
    )
    moving = (action == simulator.MOVE) & (features[:, 2] > 0.1)
    predicted_margin = 1.0 - np.maximum(
        np.abs(state[:, simulator.X] + 0.32 * features[:, 0]),
        np.abs(state[:, simulator.Y] + 0.32 * features[:, 1]),
    )
    rules = (
        (moving & (state[:, simulator.CLEARANCE] < 0.2))
        | (moving & (state[:, simulator.HUMANS] > 0))
        | (moving & (predicted_margin < 0))
        | (moving & (state[:, simulator.BATTERY] < 0.1))
        | (moving & (state[:, simulator.LINK] < 0.1))
        | ((action != simulator.STOP) & (state[:, simulator.ESTOP] > 0.5))
        | ((action == simulator.REPAIR) & (state[:, simulator.APPROVAL] < 0.5))
    )
    learned = (
        (moving & (predicted[:, simulator.CLEARANCE] < 0.18))
        | (
            moving
            & (state[:, simulator.HUMANS] > 0)
            & (predicted[:, simulator.VELOCITY] > 0.16)
        )
        | (predicted[:, simulator.MARGIN] < 0.01)
        | (moving & (predicted[:, simulator.BATTERY] < 0.08))
        | (moving & (predicted[:, simulator.LINK] < 0.08))
        | ((action != simulator.STOP) & (state[:, simulator.ESTOP] > 0.5))
        | ((action == simulator.REPAIR) & (state[:, simulator.APPROVAL] < 0.5))
    )
    blocked = rules | learned
    danger = prepared["danger"]
    tp = int(np.sum(blocked & danger))
    fp = int(np.sum(blocked & ~danger))
    tn = int(np.sum(~blocked & ~danger))
    fn = int(np.sum(~blocked & danger))
    tpr = tp / max(1, tp + fn)
    tnr = tn / (tn + fp) if tn + fp else None
    return {
        "rows": len(state),
        "normalized_one_step_error": float(np.mean(errors)),
        "p95_normalized_one_step_error": float(np.percentile(errors, 95)),
        "all_predictions_finite": bool(np.isfinite(predicted).all()),
        "rules_plus_jepa": {
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "balanced_accuracy": 0.5 * (tpr + tnr) if tnr is not None else None,
            "false_negative_rate": fn / max(1, tp + fn),
            "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        },
    }


def batched_evaluation(prepared: dict, weights: dict) -> dict:
    rollout = {}
    for horizon, item in prepared["rollouts"].items():
        predicted = item["state"].copy()
        for offset in range(horizon):
            predicted = batch_prediction(
                weights,
                predicted,
                item["action"][:, offset],
                item["features"][:, offset],
            )
        rollout[f"h{horizon}"] = float(
            np.mean(
                np.mean(
                    np.abs(predicted - item["actual"]) / simulator.STATE_RANGES,
                    axis=1,
                )
            )
        )
    return {"rollout": rollout, "diagnostics": batched_diagnostics(prepared, weights)}


def verify_batched_equivalence(rows, weights) -> None:
    sample = rows[: min(256, len(rows))]
    scalar = selector.evaluation(sample, weights)
    batched = batched_evaluation(prepare_evaluation(sample), weights)
    for horizon in range(1, 6):
        key = f"h{horizon}"
        if not np.isclose(scalar["rollout"][key], batched["rollout"][key], atol=1e-8):
            raise AssertionError(f"batched rollout mismatch at {key}")
    if scalar["diagnostics"]["rules_plus_jepa"] != batched["diagnostics"]["rules_plus_jepa"]:
        raise AssertionError("batched safety diagnostics mismatch")
    for key in ("normalized_one_step_error", "p95_normalized_one_step_error"):
        if not np.isclose(
            scalar["diagnostics"][key], batched["diagnostics"][key], atol=1e-8
        ):
            raise AssertionError(f"batched diagnostic mismatch: {key}")


def decoder_statistics(domains, baseline) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    width = baseline["state_w"].shape[0] + 1
    xtx = np.zeros((width, width), dtype=np.float64)
    xty = np.zeros((width, simulator.STATE_SIZE), dtype=np.float64)
    for rows in domains:
        design, target = predicted_latent(rows, baseline)
        xtx += (design.T @ design) / len(design)
        xty += (design.T @ target) / len(design)
    anchor = np.concatenate(
        (baseline["state_w"], baseline["state_b"][None, :]), axis=0
    ).astype(np.float64)
    return xtx, xty, anchor


def fit_decoder(statistics, ridge_lambda: float) -> np.ndarray:
    xtx, xty, anchor = statistics
    width = len(anchor)
    penalty = np.eye(width, dtype=np.float64) * ridge_lambda
    penalty[-1, -1] = ridge_lambda * 0.1
    return np.linalg.solve(xtx + penalty, xty + penalty @ anchor)


def candidate_weights(baseline, fitted: np.ndarray, blend: float) -> dict:
    anchor = np.concatenate(
        (baseline["state_w"], baseline["state_b"][None, :]), axis=0
    ).astype(np.float64)
    decoder = anchor + blend * (fitted - anchor)
    weights = {name: value.copy() for name, value in baseline.items()}
    weights["state_w"] = decoder[:-1].astype(np.float32)
    weights["state_b"] = decoder[-1].astype(np.float32)
    return weights


def deployed_representation_metrics(rows, weights) -> dict:
    state, actions, actual_delta, _ = jepa.state_arrays(rows)
    latent = np.tanh(state @ weights["encoder_w"] + weights["encoder_b"])
    predictor_input = np.concatenate((latent, actions), axis=1)
    hidden = np.maximum(
        predictor_input @ weights["predictor_w1"] + weights["predictor_b1"], 0
    )
    predicted_latent = hidden @ weights["predictor_w2"] + weights["predictor_b2"]
    predicted_delta = predicted_latent @ weights["state_w"] + weights["state_b"]
    centered = latent - latent.mean(axis=0, keepdims=True)
    singular = np.linalg.svd(centered, full_matrices=False, compute_uv=False)
    mass = singular / max(float(singular.sum()), 1e-12)
    effective_rank = float(
        np.exp(-np.sum(mass[mass > 0] * np.log(mass[mass > 0])))
    )
    action_context = predicted_latent - latent
    action_means = []
    for action in range(simulator.ACTION_COUNT):
        mask = actions[:, action] > 0.5
        action_means.append(action_context[mask].mean(axis=0))
    return {
        "latent_standard_deviation": float(np.std(latent)),
        "effective_rank": effective_rank,
        "action_sensitivity": float(
            np.std(np.asarray(action_means, dtype=np.float32))
        ),
        "prediction_variance_ratio": float(
            np.var(predicted_delta) / max(float(np.var(actual_delta)), 1e-12)
        ),
    }


def decoder_variance_ratio(
    design: np.ndarray, actual_delta: np.ndarray, weights: dict
) -> float:
    predicted_delta = (
        design[:, :-1] @ weights["state_w"] + weights["state_b"]
    )
    return float(
        np.var(predicted_delta) / max(float(np.var(actual_delta)), 1e-12)
    )


def geometric(values) -> float:
    return math.exp(sum(math.log(max(value, 1e-12)) for value in values) / len(values))


def validation_result(candidate, current) -> dict:
    decision = selector.validation_decision(
        {
            "original_validation": candidate["base"],
            "incident_validation": candidate["incident"],
            "stress_validation": candidate["stress"],
            "anti_collapse": candidate["anti_collapse"],
        },
        current["base"],
        current["incident"],
        current["stress"],
        stress_geometric_limit=1.0,
    )
    checks = decision["checks"]
    for inherited_gate in (
        "latent_standard_deviation",
        "effective_rank",
        "action_sensitivity",
    ):
        checks.pop(inherited_gate)
    checks.update(
        {
            "all_predictions_finite": all(
                candidate[name]["diagnostics"]["all_predictions_finite"]
                for name in ("base", "incident", "stress")
            ),
            "incident_validation_false_negatives_not_increased": candidate[
                "incident"
            ]["diagnostics"]["rules_plus_jepa"]["fn"]
            <= current["incident"]["diagnostics"]["rules_plus_jepa"]["fn"],
            "stress_validation_false_negatives_not_increased": candidate["stress"][
                "diagnostics"
            ]["rules_plus_jepa"]["fn"]
            <= current["stress"]["diagnostics"]["rules_plus_jepa"]["fn"],
            "prediction_variance_ratio": candidate["anti_collapse"][
                "prediction_variance_ratio"
            ]
            >= 0.10,
        }
    )
    decision["accepted"] = all(checks.values())
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args()
    if args.artifact.resolve() == DEPLOYED_ARTIFACT.resolve():
        parser.error("validation-only selection cannot target the deployed artifact")

    catalog_guard = install_final_catalog_guard()
    final_catalog_preexisting = FINAL_CATALOG.is_file()
    deployed_sha_before = sha256(DEPLOYED_ARTIFACT)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if not protocol["registered_before_v5_test_generation"]:
        raise AssertionError("v5 protocol is not registered")
    if protocol["v5_test_open_count"] != 0:
        raise AssertionError("registered v5 protocol did not seal the final test")
    if protocol["baseline_artifact_sha256"] != sha256(BASELINE):
        raise AssertionError("v5 baseline artifact drifted")
    registered_final_catalog = PROTOCOL.parent / protocol["final_test"]["catalog"]
    if registered_final_catalog.resolve() != FINAL_CATALOG.resolve():
        raise AssertionError("v5 final catalog path drifted")
    baseline = robustness.load_artifact(BASELINE)

    fit = protocol["fit_partitions"]
    validation = protocol["selection_partitions"]
    for domain in ("base", "incident_v2", "stress"):
        for key in ("steps", "seed"):
            if fit[domain][key] != validation[domain][key]:
                raise AssertionError(f"v5 {domain} {key} drifted between fit and validation")
    if fit["base"]["episodes"] != validation["base"]["episodes"]:
        raise AssertionError("v5 base episode count drifted between fit and validation")
    if fit["incident_v2"]["catalog"] != validation["incident_v2"]["catalog"]:
        raise AssertionError("v5 incident catalog drifted between fit and validation")
    incident_catalog = PROTOCOL.parent / fit["incident_v2"]["catalog"]
    if incident_catalog.resolve() != INCIDENT_CATALOG.resolve():
        raise AssertionError("v5 incident fit catalog is not the registered v2 catalog")

    base = fit["base"]
    base_rows = simulator.generate(base["episodes"], base["steps"], base["seed"])
    _, _, base_train, base_validation, _ = jepa.split_rows(
        base_rows, base["episodes"], base["seed"]
    )
    incident_fit = fit["incident_v2"]
    incident_train, incident_train_metadata = incidents.generate_partition(
        incident_fit["partition"],
        incident_fit["episodes_per_source"],
        incident_fit["steps"],
        incident_fit["seed"],
        incident_catalog,
    )
    incident_select = validation["incident_v2"]
    incident_validation, incident_validation_metadata = incidents.generate_partition(
        incident_select["partition"],
        incident_select["episodes_per_source"],
        incident_select["steps"],
        incident_select["seed"],
        incident_catalog,
    )
    stress_fit = fit["stress"]
    stress_train, stress_train_metadata = stress.generate_partition(
        stress_fit["partition"],
        stress_fit["episodes"],
        stress_fit["steps"],
        stress_fit["seed"],
    )
    stress_select = validation["stress"]
    stress_validation, stress_validation_metadata = stress.generate_partition(
        stress_select["partition"],
        stress_select["episodes"],
        stress_select["steps"],
        stress_select["seed"],
    )
    verify_batched_equivalence(base_validation, baseline)
    prepared = {
        "base": prepare_evaluation(base_validation),
        "incident": prepare_evaluation(incident_validation),
        "stress": prepare_evaluation(stress_validation),
    }
    fit_domains = (base_train, incident_train, stress_train)
    combined_validation = [*base_validation, *incident_validation, *stress_validation]
    decoder_fit_statistics = decoder_statistics(fit_domains, baseline)
    representation = deployed_representation_metrics(combined_validation, baseline)
    validation_design, validation_delta = predicted_latent(
        combined_validation, baseline
    )
    current = {
        name: batched_evaluation(domain, baseline)
        for name, domain in prepared.items()
    }

    candidates = []
    candidate_models = []
    grid = protocol["candidate_grid"]
    for ridge_lambda in grid["decoder_ridge_lambda"]:
        fitted = fit_decoder(decoder_fit_statistics, float(ridge_lambda))
        for blend in grid["decoder_blend"]:
            weights = candidate_weights(baseline, fitted, float(blend))
            result = {
                "decoder_ridge_lambda": ridge_lambda,
                "decoder_blend": blend,
                "base": batched_evaluation(prepared["base"], weights),
                "incident": batched_evaluation(prepared["incident"], weights),
                "stress": batched_evaluation(prepared["stress"], weights),
                "anti_collapse": {
                    **representation,
                    "prediction_variance_ratio": decoder_variance_ratio(
                        validation_design, validation_delta, weights
                    ),
                },
            }
            result["selection"] = validation_result(result, current)
            candidates.append(result)
            candidate_models.append(weights)

    accepted = [index for index, item in enumerate(candidates) if item["selection"]["accepted"]]
    selected_index = (
        min(accepted, key=lambda index: candidates[index]["selection"]["selection_score"])
        if accepted
        else None
    )
    artifact_sha = None
    if selected_index is not None:
        selected_weights = candidate_models[selected_index]
        selected = candidates[selected_index]
        mean_predictor = selector.mean_delta_predictor(
            [*base_train, *incident_train, *stress_train]
        )
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        jepa.write_artifact(
            args.artifact,
            selected_weights,
            sum(len(rows) for rows in fit_domains),
            selected["base"]["rollout"]["h3"],
            simulator.rollout_error(base_validation, mean_predictor, 3),
            baseline["encoder_w"].shape[1],
            baseline["predictor_w1"].shape[1],
        )
        artifact_sha = sha256(args.artifact)

    deployed_sha_after = sha256(DEPLOYED_ARTIFACT)
    if deployed_sha_after != deployed_sha_before:
        raise AssertionError("deployed artifact changed during validation-only selection")

    report = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "baseline_artifact_sha256": sha256(BASELINE),
        "final_test_opened": False,
        "final_catalog_access": {
            "path": repository_path(FINAL_CATALOG),
            "preexisting_in_checkout": final_catalog_preexisting,
            "guard": "python_audit_hook_fail_closed",
            "access_attempted": catalog_guard["attempted"],
            "opened": False,
        },
        "fit": {
            "base_transitions": len(base_train),
            "incident": incidents.summarize(incident_train, incident_train_metadata),
            "stress": stress.summarize(stress_train, stress_train_metadata),
            "domain_weighting": "equal",
        },
        "validation": {
            "base_transitions": len(base_validation),
            "incident": incidents.summarize(
                incident_validation, incident_validation_metadata
            ),
            "stress": stress.summarize(stress_validation, stress_validation_metadata),
        },
        "baseline_validation": current,
        "candidates": candidates,
        "accepted_candidate_indices": accepted,
        "selected_candidate_index": selected_index,
        "selected_artifact": repository_path(args.artifact)
        if selected_index is not None
        else None,
        "selected_artifact_sha256": artifact_sha,
        "selection_passed": selected_index is not None,
        "deployment": {
            "attempted": False,
            "artifact": repository_path(DEPLOYED_ARTIFACT),
            "sha256_before": deployed_sha_before,
            "sha256_after": deployed_sha_after,
            "unchanged": True,
            "final_promotion_gates_evaluated": False,
            "promotion_eligibility": "not_evaluated_validation_only",
        },
        "claim_boundary": [
            "The v5 final catalog was not generated or evaluated during selection.",
            "Only the PJE1 state decoder changed; the deployed encoder and predictor remained fixed.",
            "A selected artifact is still simulation evidence and has no permit or adapter authority.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "candidates": len(candidates),
                "accepted": len(accepted),
                "selected_candidate_index": selected_index,
                "artifact_sha256": artifact_sha,
            },
            indent=2,
        )
    )
    return 0 if selected_index is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
