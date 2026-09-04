#!/usr/bin/env python3
"""Register fixed risk-source adapters for a fresh Safety-Gymnasium attribution run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

import run_physical_jepa_safety_gymnasium as benchmark
import train_physical_jepa_safety_adapter_v1 as trainer


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PROTOCOL = ROOT / "docs/research/physical_jepa_safety_gymnasium_protocol_v14.json"
SOURCE_RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_result_v14.json"
DEVELOPMENT_CATALOG = (
    ROOT / "docs/research/artifacts/physical-jepa-safety-adapter-v14/development_catalog.jsonl"
)
FULL_ADAPTER = ROOT / "docs/research/artifacts/physical-jepa-safety-adapter-v14/risk_adapter.json"
ARTIFACT_DIR = ROOT / "docs/research/artifacts/physical-jepa-safety-attribution-v1"
PROTOCOL_PATH = ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_protocol_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def scores(rows: list[dict], adapter: dict) -> np.ndarray:
    return np.asarray(
        [
            benchmark.risk_adapter_score(
                np.asarray(row["risk_adapter_features"], dtype=np.float64), adapter
            )
            for row in rows
        ],
        dtype=np.float64,
    )


def choose_threshold(labels: np.ndarray, values: np.ndarray, target_fpr: float) -> dict:
    candidates = []
    for threshold in np.linspace(0.001, 0.999, 999):
        current = trainer.metrics(labels, values, float(threshold))
        candidates.append(current)
    candidates.sort(
        key=lambda item: (
            abs(item["false_positive_rate"] - target_fpr),
            item["fn"],
            -item["threshold"],
        )
    )
    return candidates[0]


def fit_adapter(
    name: str,
    indices: list[int],
    train_rows: list[dict],
    validation_rows: list[dict],
    target_fpr: float,
) -> dict:
    train_full = np.asarray(
        [row["risk_adapter_features"] for row in train_rows], dtype=np.float64
    )
    validation_full = np.asarray(
        [row["risk_adapter_features"] for row in validation_rows], dtype=np.float64
    )
    train_y = np.asarray([row["dangerous_proposal"] for row in train_rows], dtype=np.float64)
    validation_y = np.asarray(
        [row["dangerous_proposal"] for row in validation_rows], dtype=np.float64
    )
    selected = np.asarray(indices, dtype=np.int64)
    mean, scale, weights, bias = trainer.fit(
        train_full[:, selected], train_y, updates=3000, regularization=0.05
    )
    embedded_mean = np.zeros(train_full.shape[1], dtype=np.float64)
    embedded_scale = np.ones(train_full.shape[1], dtype=np.float64)
    embedded_weights = np.zeros(train_full.shape[1], dtype=np.float64)
    embedded_mean[selected] = mean
    embedded_scale[selected] = scale
    embedded_weights[selected] = weights
    adapter = {
        "schema": "physical-jepa-safety-risk-source-adapter-v1",
        "name": name,
        "feature_transform": "identity",
        "raw_feature_count": int(train_full.shape[1]),
        "included_raw_feature_indices": indices,
        "feature_mean": embedded_mean.tolist(),
        "feature_scale": embedded_scale.tolist(),
        "weights": embedded_weights.tolist(),
        "bias": float(bias),
        "fit": {
            "optimizer": "deterministic full-batch Adam",
            "updates": 3000,
            "l2_regularization": 0.05,
            "training_seed_range": {"start": 4000, "count": 96},
            "validation_seed_range": {"start": 4096, "count": 32},
            "training_rows": len(train_rows),
            "training_positive_rows": int(np.sum(train_y)),
            "validation_rows": len(validation_rows),
            "validation_positive_rows": int(np.sum(validation_y)),
        },
        "authority": {
            "may_add_caution": True,
            "may_grant_permission": False,
            "physical_actuator_authority": False,
            "deployment_eligible": False,
        },
    }
    validation_scores = scores(validation_rows, adapter)
    adapter["validation"] = {
        "selection_rule": (
            "minimum absolute FPR difference from the frozen full-adapter FPR; "
            "then fewer false negatives; then higher threshold"
        ),
        "selected": choose_threshold(validation_y, validation_scores, target_fpr),
        "calibration": trainer.calibration(validation_y, validation_scores),
    }
    return adapter


def main() -> None:
    if PROTOCOL_PATH.exists() or ARTIFACT_DIR.exists():
        raise FileExistsError("attribution protocol or adapter directory already exists")
    source = load_json(SOURCE_PROTOCOL)
    source_result = load_json(SOURCE_RESULT)
    rows = load_rows(DEVELOPMENT_CATALOG)
    if sha256(DEVELOPMENT_CATALOG) != source["learned_risk_adapter"]["development_catalog"]["sha256"]:
        raise ValueError("development catalog differs from v14 registration")
    train_rows = [row for row in rows if 4000 <= int(row["seed"]) < 4096]
    validation_rows = [row for row in rows if 4096 <= int(row["seed"]) < 4128]
    if not train_rows or not validation_rows:
        raise ValueError("registered train/validation split is empty")

    full_adapter = load_json(FULL_ADAPTER)
    full_threshold = float(source_result["selected_candidate"]["learned_risk_threshold"])
    validation_y = np.asarray(
        [row["dangerous_proposal"] for row in validation_rows], dtype=np.float64
    )
    full_validation = trainer.metrics(
        validation_y, scores(validation_rows, full_adapter), full_threshold
    )
    variants = [
        ("local-sensing-without-jepa", list(range(22)), "local observation, proposed action, goal direction, hazard closeness, and speed"),
        ("jepa-outputs-only", [22, 23, 24], "frozen JEPA clearance, velocity, and progress predictions only"),
        ("hazard-closeness-only", [20], "current maximum hazard lidar closeness only"),
    ]
    ARTIFACT_DIR.mkdir(parents=True)
    registered = [
        {
            "id": "full-frozen-v14-adapter",
            "risk_source": "local sensing plus frozen JEPA outputs and three lidar summaries",
            "path": str(FULL_ADAPTER.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256(FULL_ADAPTER),
            "feature_transform": full_adapter["feature_transform"],
            "learned_risk_threshold": full_threshold,
            "validation": full_validation,
            "adapter_reused_without_refit": True,
        }
    ]
    for name, indices, description in variants:
        adapter = fit_adapter(
            name, indices, train_rows, validation_rows, full_validation["false_positive_rate"]
        )
        path = ARTIFACT_DIR / f"{name}.json"
        path.write_text(json.dumps(adapter, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        registered.append(
            {
                "id": name,
                "risk_source": description,
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(path),
                "feature_transform": "identity",
                "learned_risk_threshold": adapter["validation"]["selected"]["threshold"],
                "validation": adapter["validation"]["selected"],
                "adapter_reused_without_refit": False,
            }
        )

    protocol = {
        "schema": "physical-jepa-safety-gymnasium-risk-source-attribution-protocol-v1",
        "protocol_id": "physical-jepa-safety-gymnasium-risk-source-attribution-v1",
        "registered_date": "2026-09-05",
        "research_question": (
            "When the privileged planner, one-command tangent correction, oracle, runtime, and final seeds are held fixed, "
            "how do full, local-only, JEPA-only, and current-geometry-only warning sources change warning quality and realized outcomes?"
        ),
        "source_study": {
            "protocol": {"path": str(SOURCE_PROTOCOL.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(SOURCE_PROTOCOL)},
            "result": {"path": str(SOURCE_RESULT.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(SOURCE_RESULT)},
            "development_catalog": {"path": str(DEVELOPMENT_CATALOG.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(DEVELOPMENT_CATALOG)},
        },
        "frozen_artifact": source["artifact"],
        "runtime_lock": source["runtime_lock"],
        "external_benchmark": source["external_benchmark"],
        "episode": source["episode"],
        "oracle_and_metrics": source["oracle_and_metrics"],
        "frozen_policy": source_result["selected_candidate"],
        "constant_factors": [
            "SafetyPointGoal1-v0 task and runtime lock",
            "privileged grid planner and all planner parameters",
            "one-command deterministic tangent correction",
            "20-step nominal-controller danger oracle",
            "frozen Physical JEPA v5 artifact",
            "seed range, episode limit, and two-worker execution",
        ],
        "changed_factor": "risk-source adapter and its development-selected threshold only",
        "risk_source_variants": registered,
        "threshold_selection": {
            "grid": {"minimum": 0.001, "maximum": 0.999, "step": 0.001},
            "target": "full frozen v14 adapter validation false-positive rate",
            "target_false_positive_rate": full_validation["false_positive_rate"],
            "tie_breaks": ["lower false-negative count", "higher threshold"],
            "final_threshold_retuning_forbidden": True,
        },
        "prospective_boundary": {
            "opened_development_seeds": {"start": 4000, "count": 128},
            "final_seed_range_unopened_at_registration": {"start": 7000, "count": 128},
            "registration_search": "repository text search found no 7000-7127 attribution result before registration",
            "final_result_write_once": True,
        },
        "execution_workers": 2,
        "estimands": [
            "task completion rate",
            "warning recall and false-positive rate on the 20-step nominal-controller oracle",
            "effective-action recall, intervention rate, and intervention precision",
            "realized hazard-cost steps and hazardous-episode frequency",
            "episode length",
            "paired seed-level differences from the planner and from the full adapter",
        ],
        "uncertainty": {
            "absolute": "5000-resample episode bootstrap plus Wilson intervals where applicable",
            "paired": "10000-resample paired seed bootstrap",
            "trained_model_scope": "conditions on the fixed fitted adapters; does not include adapter-refit variability",
        },
        "authority": {
            "physical_actuator_attempts": 0,
            "physical_actuator_deliveries": 0,
            "protected_deployed_artifact_must_remain_unchanged": True,
            "promotion_eligible": False,
        },
        "independence": {
            "benchmark_task": "externally maintained",
            "adapter_design_execution_and_analysis": "researcher-authored and locally executed",
            "independent_execution": False,
            "independent_assessment": False,
        },
        "interpretation_rule": (
            "The comparison may attribute differences to the registered risk-source pipelines under the fixed planner/correction setup; "
            "it does not identify architecture-only causality, physical safety, deployment safety, or independent replication."
        ),
    }
    PROTOCOL_PATH.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(PROTOCOL_PATH.relative_to(ROOT).as_posix())
    for item in registered:
        print(f"{item['id']}: threshold={item['learned_risk_threshold']:.3f} validation={item['validation']}")


if __name__ == "__main__":
    main()
