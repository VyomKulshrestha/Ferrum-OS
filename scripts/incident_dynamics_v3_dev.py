#!/usr/bin/env python3
"""Incident-dynamics v3 development: data assembly, training, and an evolving-world curriculum.

Development only. Never generates held-out mechanisms or any final catalog and never
reads the paper's final partitions (the v1 final guard is installed). Every trial is
retained under target/incident-dynamics-v3/ with its trace.

The `rsi` curriculum is a Dream-RSI-inspired adaptation (arXiv:2609.14858), not a
faithful reimplementation: Dream-RSI optimises an LLM agent's exploration policy by
replaying stored discovery trees. Here the analogous loop is
  (1) online: probe candidate development worlds with the current model;
  (2) evolving worlds: add the worlds the current model predicts worst to a growing pool;
  (3) offline replay: train several candidate continuations, score each on the fixed
      validation samples of every stored world (no new generation), and keep the best,
      with the current model always among the candidates.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

import evaluate_cross_domain_world_models as architecture
import incident_dynamics_data as v2data
import incident_dynamics_v3_data as v3
import incident_dynamics_v3_models as models

HISTORY = 8
SEEDS = {"train": 391001, "validation": 391002, "calibration": 391003, "probe": 391010}
PER_MECHANISM = {"train": 400, "validation": 64, "calibration": 64}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(domain: str, history: int = HISTORY) -> dict:
    guard = architecture.install_final_guard(architecture.load_json(architecture.PROTOCOL))
    spec = v3.spec_for(domain, history)
    legacy = v3.legacy_rows(domain)
    folder = v3.WORK / "dev" / domain
    mechanisms = v3.DEV_MECHANISMS[domain]
    parts = {
        "base_train": legacy["train"] + v2data.incident_rows(domain, "train", 1200, 281001),
        "base_validation": legacy["validation"] + v2data.incident_rows(domain, "validation", 256, 281002),
        "mech_train": v3.mechanism_rows(domain, "train", mechanisms, PER_MECHANISM["train"] * len(mechanisms), SEEDS["train"]),
        "mech_validation": v3.mechanism_rows(domain, "validation", mechanisms, PER_MECHANISM["validation"] * len(mechanisms), SEEDS["validation"]),
    }
    summary = {"domain": domain, "history": history, "mechanisms": mechanisms, "seeds": SEEDS, "files": {}}
    for name, rows in parts.items():
        data = v3.windows(rows, spec, complete="validation" in name)
        path = folder / f"{name}-h{history}.npz"
        v3.save(path, data)
        summary["files"][name] = {"windows": len(data.states), "episodes": len(set(data.episodes)), "sha256": sha(path)}
    if guard["attempted"]:
        raise AssertionError("final access attempted during development build")
    summary["final_access_attempted"] = False
    architecture.write_json(folder / f"manifest-h{history}.json", summary)
    return summary


def build_calibration(domain: str, history: int = HISTORY) -> dict:
    """Warning-threshold episodes: v2's registered calibration seed plus dev-mechanism episodes."""
    spec = v3.spec_for(domain, history)
    mechanisms = v3.DEV_MECHANISMS[domain]
    rows = (v2data.incident_rows(domain, "calibration", 512, 281003)
            + v3.mechanism_rows(domain, "calibration", mechanisms, PER_MECHANISM["calibration"] * len(mechanisms), SEEDS["calibration"]))
    data = v3.windows(rows, spec, complete=True)
    path = v3.WORK / "dev" / domain / f"calibration-h{history}.npz"
    v3.save(path, data)
    return {"windows": len(data.states), "episodes": len(set(data.episodes)), "sha256": sha(path)}


def warning_validation(domain, history=HISTORY):
    """Incident-only validation windows for warning diagnostics (v2 incident + dev mechanisms)."""
    base = load(domain, "base_validation", history)
    incident = np.array([e.startswith("new:") for e in base.episodes])
    base = v3.Windows(**{k: getattr(base, k)[incident] for k in v3.Windows.__dataclass_fields__})
    return v3.concat(base, load(domain, "mech_validation", history))


def load(domain: str, name: str, history: int = HISTORY):
    return v3.load(v3.WORK / "dev" / domain / f"{name}-h{history}.npz")


BLOCKS = ("legacy_validation", "incident_validation", "mech_validation")


def block(domain, name, history=HISTORY):
    if name == "mech_validation":
        return load(domain, name, history)
    base = load(domain, "base_validation", history)
    incident = np.array([e.startswith("new:") for e in base.episodes])
    keep = incident if name == "incident_validation" else ~incident
    return v3.Windows(**{k: getattr(base, k)[keep] for k in v3.Windows.__dataclass_fields__})


def reference_scores(domain):
    """v2-selected block scores (computed once on history-3 windows of the same rows)."""
    path = v3.WORK / "dev" / domain / "v2_selected_block_scores.json"
    if path.exists():
        return json.loads(path.read_text())
    import incident_dynamics_v3_eval as evaluation
    spec = v3.spec_for(domain, 3)
    values = {}
    for name in BLOCKS:
        data = block(domain, name, 3)
        errors = models.macro_errors(evaluation.v2_predict(domain, "selected", data), data, spec)
        values[name] = sum(errors.values()) / 3
    path.write_text(json.dumps(values, indent=1))
    return values


def selection_score(predict, domain, history=HISTORY):
    """Registered development metric: mean over three validation blocks (legacy, v2 incident,
    development mechanisms) of the block score divided by the v2-selected block score, where a
    block score is the mean H1/H3/H5 episode-macro normalized MAE. v2-selected scores 1.0."""
    spec = v3.spec_for(domain, history)
    reference = reference_scores(domain)
    result = {}
    for name in BLOCKS:
        data = block(domain, name, history)
        values = models.macro_errors(predict(data), data, spec)
        score = sum(values.values()) / 3
        result[name] = {**values, "score": score, "relative": score / reference[name]}
    result["selection_score"] = float(np.mean([result[name]["relative"] for name in BLOCKS]))
    return result


def training_set(domain, history=HISTORY, include_mechanisms=True):
    parts = [load(domain, "base_train", history)]
    if include_mechanisms:
        parts.append(load(domain, "mech_train", history))
    return v3.concat(*parts)


def combined_validation(domain, history=HISTORY):
    return v3.concat(load(domain, "base_validation", history), load(domain, "mech_validation", history))


# ---------------------------------------------------------------- evolving-world curriculum
def world_rows(domain, mechanism, strength, partition, episodes, seed):
    return v3.mechanism_rows(domain, partition, [mechanism], episodes, seed, strength_range=strength)


def rsi_curriculum(domain, method, seed, rounds=4, candidates_per_round=3, updates_per_round=4000,
                   hidden=256, device="cuda", log=print):
    spec = v3.spec_for(domain, HISTORY)
    base = training_set(domain, include_mechanisms=False)
    validation = combined_validation(domain)
    rng = np.random.default_rng(seed)
    # Initial pool: every development mechanism at its registered default strength range.
    cells = [(m, (0.6, 1.4)) for m in v3.DEV_MECHANISMS[domain]]
    mutations = [(m, r) for m in v3.DEV_MECHANISMS[domain] for r in ((0.3, 0.8), (1.2, 2.0), (1.8, 2.6))]
    pool, replay, history = [], {}, []

    def add_world(cell, index):
        mechanism, strength = cell
        key = f"{mechanism}@{strength[0]}-{strength[1]}"
        train_rows = world_rows(domain, mechanism, strength, f"rsi-train-{index}", 240, SEEDS["train"] + 7 * index)
        val_rows = world_rows(domain, mechanism, strength, f"rsi-val-{index}", 48, SEEDS["validation"] + 7 * index)
        pool.append((key, v3.windows(train_rows, spec)))
        replay[key] = v3.windows(val_rows, spec, complete=True)

    for index, cell in enumerate(cells):
        add_world(cell, index)
    current = None
    reference = {}

    def replay_score(model):
        scores = []
        for key, data in replay.items():
            value = models.macro_errors(models.predict(model, data), data, spec)
            raw = sum(value.values()) / 3
            # Normalise by the first-round reference so no single world dominates.
            reference.setdefault(key, raw)
            scores.append(raw / max(reference[key], 1e-9))
        base_values = models.macro_errors(models.predict(model, validation), validation, spec)
        return float(np.mean(scores)), sum(base_values.values()) / 3

    for round_index in range(rounds):
        mixtures = {"uniform": None, "error_weighted": "error", "recent": "recent"}
        trained = []
        world_data = v3.concat(*[data for _, data in pool])
        world_ids = np.concatenate([[i] * len(data.states) for i, (_, data) in enumerate(pool)])
        for name, rule in list(mixtures.items())[:candidates_per_round]:
            train_data = v3.concat(base, world_data)
            weights = np.ones(len(train_data.states), np.float64)
            offset = len(base.states)
            if rule == "error" and current is not None:
                errs = []
                for key, _ in pool:
                    data = replay[key]
                    errs.append(sum(models.macro_errors(models.predict(current, data), data, spec).values()) / 3 / reference.get(key, 1))
                weights[offset:] = np.asarray(errs)[world_ids] / np.mean(errs)
            elif rule == "recent":
                weights[offset:] = 1 + (world_ids >= len(pool) - candidates_per_round)
            candidate, info = models.train(method, spec, train_data, validation, seed + 100 * round_index,
                                           updates=updates_per_round, hidden=hidden, device=device,
                                           weights=weights / weights.sum(), init=current)
            score, base_score = replay_score(candidate)
            trained.append((score, name, candidate, info, base_score))
            log(json.dumps({"round": round_index, "candidate": name, "replay_score": score, "validation_score": base_score}))
        if current is not None:
            score, base_score = replay_score(current)
            trained.append((score, "keep_current", current, None, base_score))
        trained.sort(key=lambda item: (item[0], item[1]))
        best = trained[0]
        current = best[2]
        history.append({"round": round_index, "selected": best[1], "replay_score": best[0], "validation_score": best[4],
                        "pool": [key for key, _ in pool]})
        log(json.dumps(history[-1]))
        # Online probe: evolve the world pool toward the mutations the current model predicts worst.
        probes = []
        for cell in mutations:
            if any(key.startswith(f"{cell[0]}@{cell[1][0]}-") for key, _ in pool):
                continue
            rows = world_rows(domain, cell[0], cell[1], f"probe-{round_index}", 32, SEEDS["probe"] + round_index)
            data = v3.windows(rows, spec, complete=True)
            probes.append((sum(models.macro_errors(models.predict(current, data), data, spec).values()) / 3, cell))
        probes.sort(key=lambda item: -item[0])
        for k, (_, cell) in enumerate(probes[:candidates_per_round]):
            add_world(cell, len(pool) + 100 * (round_index + 1) + k)
    return current, {"rounds": history, "worlds": list(replay)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["build"])
    parser.add_argument("--domain", choices=["ferrumos", "physical"], required=True)
    args = parser.parse_args()
    torch.set_num_threads(4)
    print(json.dumps(build(args.domain), indent=2))


if __name__ == "__main__":
    main()
