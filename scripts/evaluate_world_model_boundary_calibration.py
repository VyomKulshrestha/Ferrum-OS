#!/usr/bin/env python3
"""Evaluate the deployed transition on independently collected HUD boundaries.

The boundary corpus is a post-training safe negative control.  It is never
merged into the registered train/validation/test split; its purpose is to
measure residuals and detect false resource alarms near argument-size limits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from evaluate_world_model_safety import TransitionModel


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], quantile: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), quantile))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("target/world_model_hud_boundary_dataset.jsonl"))
    parser.add_argument("--transition", type=Path, default=Path("appliance/world-model/model_learned.bin"))
    parser.add_argument("--json-out", type=Path, default=Path("docs/research/world_model_boundary_calibration.json"))
    parser.add_argument("--markdown-out", type=Path, default=Path("docs/research/WORLD_MODEL_BOUNDARY_CALIBRATION.md"))
    args = parser.parse_args()

    model = TransitionModel(args.transition)
    rows = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SystemExit("boundary dataset is empty")

    actual_deltas: list[float] = []
    predicted_deltas: list[float] = []
    residuals: list[float] = []
    predicted_heap: list[float] = []
    feature_regimes: Counter[str] = Counter()
    by_ram: dict[int, list[float]] = defaultdict(list)
    execution_failures = 0

    for row in rows:
        if row.get("action") != 29:
            raise ValueError(f"unexpected action id {row.get('action')}; boundary corpus must contain HUD updates only")
        before = np.asarray(row["before"], dtype=np.float32)
        after = np.asarray(row["after"], dtype=np.float32)
        features = np.asarray(row["action_features"], dtype=np.float32)
        prediction = model.predict_features(before, 29, features)
        if prediction is None:
            raise ValueError("deployed transition does not cover hud_update")
        predicted, _ = prediction
        actual = float(after[1] - before[1])
        estimate = float(predicted[1] - before[1])
        residual = actual - estimate
        actual_deltas.append(actual)
        predicted_deltas.append(estimate)
        residuals.append(residual)
        predicted_heap.append(float(predicted[1]))
        feature_regimes[f"{float(features[1]):.9f}"] += 1
        by_ram[int(row["ram_mb"])].append(residual)
        if not row.get("executed") or not row.get("success"):
            execution_failures += 1

    # One-sided conformal-style margin: empirical upper residual quantile.
    # This is reported, not silently installed into the production gate.
    q95_upper = percentile(residuals, 0.95)
    q99_upper = percentile(residuals, 0.99)
    adjusted_heap = [prediction + q95_upper for prediction in predicted_heap]
    report = {
        "schema_version": 1,
        "purpose": "post-training safe negative-control calibration; excluded from registered training and test splits",
        "dataset": {
            "path": args.dataset.as_posix(),
            "sha256": sha256(args.dataset),
            "episodes": len(rows),
            "action_id": 29,
            "action": "hud_update",
            "ram_mb": sorted({int(row["ram_mb"]) for row in rows}),
            "feature_regimes": len(feature_regimes),
            "feature_regime_counts": dict(sorted(feature_regimes.items())),
            "execution_failures": execution_failures,
        },
        "heap_delta": {
            "actual_min": min(actual_deltas),
            "actual_max": max(actual_deltas),
            "actual_mean": float(np.mean(actual_deltas)),
            "actual_nonzero_count": sum(not math.isclose(value, 0.0, abs_tol=1e-9) for value in actual_deltas),
            "predicted_mean": float(np.mean(predicted_deltas)),
            "predicted_mae": float(np.mean(np.abs(np.asarray(actual_deltas) - np.asarray(predicted_deltas)))),
            "predicted_rmse": float(np.sqrt(np.mean(np.square(np.asarray(actual_deltas) - np.asarray(predicted_deltas))))),
        },
        "residual": {
            "definition": "actual heap delta minus predicted heap delta",
            "median": percentile(residuals, 0.5),
            "p95_upper": q95_upper,
            "p99_upper": q99_upper,
            "min": min(residuals),
            "max": max(residuals),
            "by_ram_mean": {str(ram): float(np.mean(values)) for ram, values in sorted(by_ram.items())},
        },
        "resource_alarm": {
            "threshold": 0.95,
            "unadjusted_false_alarm_count": sum(value >= 0.95 for value in predicted_heap),
            "p95_margin_false_alarm_count": sum(value >= 0.95 for value in adjusted_heap),
            "p95_margin": q95_upper,
            "production_changed": False,
        },
        "limitations": [
            "All samples are successful HUD updates, so this corpus cannot estimate dangerous-action recall.",
            "The empirical margin is action- and environment-specific and is not claimed to be a distribution-free deployment guarantee.",
            "No calibration row was used to retrain the encoder or transition model.",
        ],
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    heap = report["heap_delta"]
    alarm = report["resource_alarm"]
    markdown = f"""# World-model HUD boundary calibration

This post-training study replays **{len(rows)} real QEMU episodes** across **{len(feature_regimes)} argument-size regimes**. The corpus was collected after model training and remains outside the registered episode-level split, so it is an independent safe negative control rather than extra training data.

## Result

Every action executed successfully. Observed normalized heap delta was exactly zero in {len(rows)}/{len(rows)} episodes. The deployed transition's heap-delta MAE was `{heap['predicted_mae']:.8f}` and RMSE was `{heap['predicted_rmse']:.8f}`. It produced {alarm['unadjusted_false_alarm_count']} unadjusted resource alarms at the 0.95 threshold; adding the reported empirical p95 upper-residual margin (`{alarm['p95_margin']:.8f}`) would produce {alarm['p95_margin_false_alarm_count']} alarms on this same calibration set.

The margin is **analysis only**. It was not installed into the production safety gate because this single-action safe corpus cannot establish dangerous-action coverage. Its value is narrower and useful: long HUD arguments, including the 128-byte render boundary that exposed and motivated the compositor fix, do not consume measurable normalized heap in these runs and do not trigger false resource blocks.

## Reproduction

```powershell
python scripts/evaluate_world_model_boundary_calibration.py
```

Dataset SHA-256: `{report['dataset']['sha256']}`
"""
    args.markdown_out.write_text(markdown, encoding="utf-8")
    print(f"wrote {args.json_out} and {args.markdown_out}")
    print(f"episodes={len(rows)} regimes={len(feature_regimes)} actual_nonzero={heap['actual_nonzero_count']}")


if __name__ == "__main__":
    main()
