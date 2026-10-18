#!/usr/bin/env python3
"""Compare development checkpoints on identical windows; no final access."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
import torch

import cross_domain_world_model_models as legacy
import evaluate_cross_domain_world_models as architecture
import incident_dynamics_data as data
import train_incident_dynamics as training
import train_physical_world_model as physical


def load_candidate(path, spec, device="cpu"):
    payload = torch.load(path, map_location="cpu", weights_only=True)
    settings = payload["metadata"]["settings"]
    model = training.make_model(settings["method"], spec, settings["hidden"])
    model.load_state_dict(payload["state_dict"])
    return model.to(device).eval()


def risk_score(predictions, windows, domain):
    """Maximum signed constraint margin over the supplied command sequence.

    These are simulator state constraints, NOT real incident risk probabilities.
    Unlike legacy calibration, all five forecast steps enter the score.
    """
    if domain == "ferrumos":
        return (predictions[:, :, [0, 1, 3]].max((1, 2)) - .95).astype(np.float64)
    moving = windows.future_actions[:, :, physical.MOVE] > .5
    clearance = np.where(moving, .16 - predictions[:, :, physical.CLEARANCE], -1)
    margins = np.stack((np.abs(predictions[:, :, :2]).max(-1) - 1,
                        .08 - predictions[:, :, physical.BATTERY],
                        .08 - predictions[:, :, physical.LINK], clearance), -1)
    return margins.max((1, 2)).astype(np.float64)


def warning_metrics(score, labels, threshold, calibrator):
    warn = score >= threshold
    tp, fp = int(np.sum(warn & labels)), int(np.sum(warn & ~labels))
    positive, negative = int(labels.sum()), int((~labels).sum())
    probability = expit(calibrator[0] + calibrator[1] * score)
    return {"tp": tp, "fp": fp, "tn": negative - fp, "fn": positive - tp,
            "recall": tp / positive if positive else None, "fpr": fp / negative if negative else None,
            "brier": float(np.mean((probability - labels) ** 2)), "prevalence": float(labels.mean()),
            "threshold": threshold}


def calibrate(score, labels):
    """Monotonic logistic calibration and validation-only 1 percent FPR cutoff."""
    def objective(weights):
        logits = weights[0] + weights[1] * score
        return float(np.mean(np.logaddexp(0, logits) - labels * logits) + 1e-8 * weights[1] ** 2)
    fitted = minimize(objective, [0.0, 20.0], method="L-BFGS-B", bounds=[(-30, 30), (0, 2000)])
    if not fitted.success:
        raise AssertionError(f"calibration failed: {fitted.message}")
    negatives = np.sort(score[~labels])[::-1]
    allowed = int(np.floor(.01 * len(negatives)))
    # Strictly above the first excluded negative also handles ties conservatively.
    threshold = float(np.nextafter(negatives[allowed], np.inf))
    return threshold, fitted.x.tolist()


def episode_subset(windows, parity):
    # Independent generated episode RNGs; no sample-level split of overlapping windows.
    ids = np.unique(windows.episodes)
    selected = set(ids[parity::2])
    return np.asarray([episode in selected for episode in windows.episodes])


def simple_predictions(windows, mode):
    last = windows.states[:, -1:]
    delta = windows.states[:, -1:] - windows.states[:, -2:-1]
    if mode == "persistence":
        delta = np.zeros_like(delta)
    return last + delta * np.arange(1, 6, dtype=np.float32)[None, :, None]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, choices=["ferrumos", "physical"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("retain previous development reports")
    architecture.install_final_guard(architecture.load_json(architecture.PROTOCOL))
    torch.set_num_threads(4)
    spec = data.spec_for(args.domain)
    windows = data.load_windows(data.WORK / args.domain / "validation.npz")
    candidate_paths = sorted((data.WORK / args.domain).glob("*.pt"))
    predictions = {}
    for path in candidate_paths:
        model = load_candidate(path, spec)
        predictions[path.stem] = training.predictions(model, windows, spec)
    registered = architecture.load_json(architecture.SELECTION)["domains"][args.domain]["methods"]
    for method, runs in registered.items():
        available = [run for run in runs if (data.ROOT / run["checkpoint"]["path"]).is_file()]
        if not available:
            continue
        pieces = []
        for run in available:
            checkpoint = run["checkpoint"]
            model = legacy.load_model(data.ROOT / checkpoint["path"], method, spec, run["hidden_size"], checkpoint["sha256"])
            pieces.append(training.predictions(model, windows, spec))
        predictions[f"paper-{method}-{len(pieces)}-members"] = np.mean(pieces, axis=0)
    for mode in ("persistence", "constant_velocity"):
        predictions[mode] = simple_predictions(windows, mode)
    new = np.asarray([x.startswith("new:") for x in windows.episodes])
    calibration = new & episode_subset(windows, 0)
    diagnostic = new & ~calibration
    labels = risk_score(windows.targets, windows, args.domain) >= 0
    report = {"domain": args.domain, "final_access": False, "promotion_eligible": False, "methods": {}}
    for name, predicted in predictions.items():
        score = risk_score(predicted, windows, args.domain)
        threshold, calibrator = calibrate(score[calibration], labels[calibration])
        report["methods"][name] = {"prediction_all": training.macro_errors(predicted, windows, spec),
            "prediction_new": training.macro_errors(predicted[new], data.subset(windows, new), spec),
            "prediction_legacy": training.macro_errors(predicted[~new], data.subset(windows, ~new), spec),
            "warning_diagnostic": warning_metrics(score[diagnostic], labels[diagnostic], threshold, calibrator),
            "warning_calibration": warning_metrics(score[calibration], labels[calibration], threshold, calibrator)}
    architecture.write_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
