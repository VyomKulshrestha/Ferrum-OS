#!/usr/bin/env python3
"""Run FerrumOS's preregistered synthetic neural decoder evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools" / "neurod"))

from neurod import SsvepDecoder, SyntheticBoard  # noqa: E402

PROTOCOL = {
    "schema_version": 1,
    "source": "deterministic synthetic fixtures; not human EEG",
    "sample_rate_hz": 250,
    "channels": 8,
    "window_seconds": 1.0,
    "required_dwell_windows": 3,
    "minimum_posterior": 0.80,
    "minimum_margin": 0.15,
    "targets_hz": {"focus-left": 8.0, "focus-right": 10.0, "select": 12.0, "cancel": 15.0},
    "signal_seeds": 50,
    "noise_uv": [2.0, 6.0, 12.0],
    "artifact_seeds": 100,
    "faults": ["dropout", "saturation", "blink", "line-noise"],
    "no_control_windows": 10_000,
    "no_control_seed": 99173,
    "pass_thresholds": {
        "accepted_signal_accuracy": 0.98,
        "artifact_abstention_rate": 1.0,
        "no_control_emitted_intents": 0,
    },
}


def evaluate() -> dict[str, object]:
    correct = 0
    accepted = 0
    abstained = 0
    misclassified = 0
    signal_trials = 0
    by_noise: dict[str, dict[str, int]] = {}
    for noise in PROTOCOL["noise_uv"]:
        noise_metrics = {"trials": 0, "correct": 0, "abstained": 0, "misclassified": 0}
        for label, frequency in PROTOCOL["targets_hz"].items():
            for seed in range(PROTOCOL["signal_seeds"]):
                signal_trials += 1
                noise_metrics["trials"] += 1
                board = SyntheticBoard(seed=seed + round(noise * 10_000))
                decoder = SsvepDecoder(250)
                result = None
                for window in range(3):
                    result = decoder.decode(
                        board.acquire(1.0, frequency, 1_000_000_000 + window * 1_000_000_000, noise)
                    )
                assert result is not None
                if result.label == label:
                    correct += 1
                    accepted += 1
                    noise_metrics["correct"] += 1
                elif result.label is None:
                    abstained += 1
                    noise_metrics["abstained"] += 1
                else:
                    accepted += 1
                    misclassified += 1
                    noise_metrics["misclassified"] += 1
        by_noise[str(noise)] = noise_metrics

    fault_metrics: dict[str, dict[str, int]] = {}
    artifact_trials = 0
    artifact_abstentions = 0
    for fault in PROTOCOL["faults"]:
        emitted = 0
        for seed in range(PROTOCOL["artifact_seeds"]):
            artifact_trials += 1
            decoder = SsvepDecoder(250, required_dwell_windows=1)
            result = decoder.decode(SyntheticBoard(seed=seed + 400_000).acquire(1.0, 12.0, fault=fault))
            if result.label is None:
                artifact_abstentions += 1
            else:
                emitted += 1
        fault_metrics[fault] = {
            "trials": PROTOCOL["artifact_seeds"],
            "abstentions": PROTOCOL["artifact_seeds"] - emitted,
            "emitted_intents": emitted,
        }

    no_control_emitted = 0
    no_control_labels: dict[str, int] = {label: 0 for label in PROTOCOL["targets_hz"]}
    no_control_board = SyntheticBoard(seed=PROTOCOL["no_control_seed"])
    no_control_decoder = SsvepDecoder(250)
    for window in range(PROTOCOL["no_control_windows"]):
        result = no_control_decoder.decode(
            no_control_board.acquire(1.0, None, 10_000_000_000 + window * 1_000_000_000)
        )
        if result.label is not None:
            no_control_emitted += 1
            no_control_labels[result.label] += 1

    accepted_accuracy = correct / accepted if accepted else 0.0
    overall_accuracy = correct / signal_trials
    artifact_abstention_rate = artifact_abstentions / artifact_trials
    gates = {
        "accepted_signal_accuracy": accepted_accuracy >= PROTOCOL["pass_thresholds"]["accepted_signal_accuracy"],
        "artifact_abstention": artifact_abstention_rate >= PROTOCOL["pass_thresholds"]["artifact_abstention_rate"],
        "no_control": no_control_emitted == PROTOCOL["pass_thresholds"]["no_control_emitted_intents"],
    }
    protocol_bytes = json.dumps(PROTOCOL, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "signal": {
            "trials": signal_trials,
            "accepted": accepted,
            "correct": correct,
            "misclassified": misclassified,
            "abstained": abstained,
            "accepted_accuracy": round(accepted_accuracy, 6),
            "overall_accuracy": round(overall_accuracy, 6),
            "by_noise_uv": by_noise,
        },
        "artifact": {
            "trials": artifact_trials,
            "abstentions": artifact_abstentions,
            "abstention_rate": round(artifact_abstention_rate, 6),
            "by_fault": fault_metrics,
        },
        "no_control_soak": {
            "windows": PROTOCOL["no_control_windows"],
            "simulated_seconds": PROTOCOL["no_control_windows"],
            "emitted_intents": no_control_emitted,
            "unintended_committable_intents": no_control_emitted,
            "labels": no_control_labels,
        },
        "gates": gates,
        "passed": all(gates.values()),
        "claim_boundary": [
            "Synthetic decoder evidence only; no human EEG accuracy or usability claim.",
            "No-control emitted intents are decoder candidates; OS commit additionally requires pairing, calibration, a local non-neural arm, signed preview, and revision checks.",
            "Physical neural intents remain proposal-only and cannot invoke an adapter.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "docs" / "research" / "neural_simulator_evaluation.json",
    )
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "passed": result["passed"], "gates": result["gates"]}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
