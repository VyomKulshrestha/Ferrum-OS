#!/usr/bin/env python3
"""Classical action-specific ridge baseline using identical training rows."""
import argparse
import json

import numpy as np

import cross_domain_world_model_models as legacy
import evaluate_cross_domain_world_models as architecture
import incident_dynamics_data as data
import train_incident_dynamics as training


def features(states, actions, spec):
    states = states / spec.scale
    causal = np.concatenate((states[:, -1:], states[:, 1:] - states[:, :-1]), axis=1)
    return np.concatenate((np.ones((len(states), 1)), causal.reshape(len(states), -1), actions.reshape(len(states), -1)), axis=1)


def predict(weights, windows, spec):
    states, actions = windows.states.copy(), windows.actions.copy()
    action_count = weights.shape[0]
    result = []
    for step in range(5):
        values = features(states, actions, spec)
        ids = actions[:, -1, :action_count].argmax(1)
        delta = np.zeros((len(states), spec.state_size), np.float32)
        for action in range(action_count):
            selected = ids == action
            delta[selected] = values[selected] @ weights[action]
        nxt = states[:, -1] + delta * spec.scale
        result.append(nxt)
        if step < 4:
            states = np.concatenate((states[:, 1:], nxt[:, None]), axis=1)
            actions = np.concatenate((actions[:, 1:], windows.future_actions[:, step + 1, None]), axis=1)
    return np.stack(result, axis=1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=["ferrumos", "physical"], required=True)
    args = parser.parse_args()
    architecture.install_final_guard(architecture.load_json(architecture.PROTOCOL))
    spec = data.spec_for(args.domain)
    train = data.load_windows(data.WORK / args.domain / "train.npz")
    validation = data.load_windows(data.WORK / args.domain / "validation.npz")
    action_count = 41 if args.domain == "ferrumos" else 7
    x = features(train.states, train.actions, spec)
    y = ((train.targets[:, 0] - train.states[:, -1]) / spec.scale).astype(np.float64)
    ids = train.actions[:, -1, :action_count].argmax(1)
    statistics = []
    for action in range(action_count):
        selected = ids == action
        a, b = x[selected], y[selected]
        statistics.append((a.T @ a, a.T @ b, int(selected.sum())))
    results = []
    for regularization in (.001, .1, 10.0):
        path = data.WORK / args.domain / f"ridge-{regularization}.npz"
        if path.exists():
            raise FileExistsError(path)
        weights = []
        penalty = np.eye(x.shape[1]) * regularization
        penalty[0, 0] = 1e-8
        for gram, cross, count in statistics:
            weights.append(np.linalg.solve(gram + penalty, cross) if count else np.zeros_like(cross))
        weights = np.stack(weights)
        predicted = predict(weights, validation, spec)
        metrics = training.macro_errors(predicted, validation, spec)
        np.savez_compressed(path, weights=weights)
        results.append({"regularization": regularization, "metrics": metrics, "score": sum(metrics.values()) / 3,
                        "checkpoint": {"path": path.relative_to(data.ROOT).as_posix(), "sha256": legacy.sha256(path)},
                        "parameters": int(weights.size)})
    report = {"domain": args.domain, "trials": results, "selected": min(results, key=lambda x: x["score"]),
              "method": "per-action ridge on normalized causal history and actions; one-step target", "final_access": False}
    architecture.write_json(data.WORK / args.domain / "ridge-selection.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
