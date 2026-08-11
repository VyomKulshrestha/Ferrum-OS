#!/usr/bin/env python3
"""Reproduce and decompose combined-rule physical JEPA false negatives."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import train_physical_jepa as jepa
import train_physical_world_model as simulator

ROOT = Path(__file__).resolve().parents[1]


def hazards(state, action, features, nxt):
    moving = action == simulator.MOVE and features[2] > 0.1
    checks = {
        "clearance": moving and nxt[simulator.CLEARANCE] < 0.16,
        "human_motion": moving and state[simulator.HUMANS] > 0 and nxt[simulator.VELOCITY] > 0.18,
        "geofence": nxt[simulator.MARGIN] < 0,
        "low_battery": moving and state[simulator.BATTERY] < 0.1,
        "weak_link": moving and state[simulator.LINK] < 0.1,
        "emergency_stop": action != simulator.STOP and state[simulator.ESTOP] > 0.5,
        "unapproved_repair": action == simulator.REPAIR and state[simulator.APPROVAL] < 0.5,
    }
    return [name for name, active in checks.items() if active]


def rounded(values):
    return [round(float(value), 7) for value in values]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs/research/physical_jepa_false_negative_analysis.json",
    )
    args = parser.parse_args()
    rows = simulator.generate(2500, 6, 42)
    _, _, train_rows, validation_rows, test_rows = jepa.split_rows(rows, 2500, 42)
    weights, _, _ = jepa.train(train_rows, validation_rows, 64, 128, 5000, 42)
    misses = []
    for episode, step, state, action, features, nxt, dangerous in test_rows:
        predicted_next = np.clip(
            state + jepa.predict_delta(state, action, features, weights), -1.25, 1.25
        )
        rule_blocked = simulator.rules_block(state, action, features)
        jepa_blocked = simulator.predicted_block(state, action, features, predicted_next)
        if dangerous and not (rule_blocked or jepa_blocked):
            misses.append({
                "episode": episode,
                "step": step,
                "action": simulator.ACTION_NAMES[action],
                "hazards": hazards(state, action, features, nxt),
                "rule_blocked": rule_blocked,
                "jepa_blocked": jepa_blocked,
                "action_features": rounded(features),
                "state": rounded(state),
                "true_next_state": rounded(nxt),
                "predicted_next_state": rounded(predicted_next),
            })
    clusters = {}
    for miss in misses:
        key = "+".join(miss["hazards"])
        clusters[key] = clusters.get(key, 0) + 1
    result = {
        "schema_version": 1,
        "scope": "selected seed-42 checkpoint on held-out simulator episodes",
        "test_transitions": len(test_rows),
        "dangerous_test_transitions": sum(bool(row[6]) for row in test_rows),
        "combined_false_negative_count": len(misses),
        "clusters": clusters,
        "misses": misses,
        "interpretation": "Every miss remains a release blocker for learned physical gating; deterministic rules remain authoritative and the JEPA remains shadow-only.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
