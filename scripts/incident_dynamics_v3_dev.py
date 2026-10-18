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


def split_by_source(data):
    return {name: v3.Windows(**{k: getattr(data, k)[data.sources == name] for k in v3.Windows.__dataclass_fields__})
            for name in np.unique(data.sources)}


def neural_family(method, hidden=256, device="cuda", bootstrap_updates=8000, round_updates=4000):
    def fit(domain, data, weights, seed, init, select):
        spec = v3.spec_for(domain, HISTORY)
        updates = bootstrap_updates if init is None else round_updates
        validation = combined_validation(domain)
        return models.train(method, spec, data, validation, seed, updates=updates, hidden=hidden, device=device,
                            weights=weights, init=init, select_fn=select)[0]
    return fit, models.predict


def gbr_family(trees=600, leaves=63, learning_rate=0.05, direct=False):
    import incident_dynamics_v3_gbr as gbr

    def fit(domain, data, weights, seed, init, select):
        w = np.ones(len(data.states)) if weights is None else weights / weights.mean()
        family = gbr.GBRDirect if direct else gbr.GBRModel
        return family(domain, HISTORY).fit(data, w, seed, n_estimators=trees, learning_rate=learning_rate,
                                                 num_leaves=leaves, log=lambda line: None)
    return fit, lambda model, data: model.predict(data)


def rsi_curriculum(domain, family, seed, rounds=4, candidates_per_round=3, log=print, incident_weight=1.0):
    """Dream-RSI-inspired evolving-world curriculum for any model family.

    Round 0 fits on exactly the uniform-curriculum data. Each later round probes mutated development
    worlds with the current model, adds the worst-predicted worlds to the pool, fits candidate
    continuations under three pool-weighting rules, scores every candidate (and the unchanged current
    model) by replay on the stored validation samples of all worlds, and keeps the best.
    """
    import evaluate_incident_dynamics_development as v2dev
    fit, predict = family
    spec = v3.spec_for(domain, HISTORY)
    base = training_set(domain, include_mechanisms=False)
    mech_train, mech_val = load(domain, "mech_train"), load(domain, "mech_validation")
    pool = [(f"{name}@0.6-1.4", data) for name, data in split_by_source(mech_train).items()]
    replay = {f"{name}@0.6-1.4": data for name, data in split_by_source(mech_val).items()}
    mutations = [(m, r) for m in v3.DEV_MECHANISMS[domain] for r in ((0.2, 0.6), (1.4, 2.0), (2.0, 2.8))]
    reference, history = {}, []
    select = lambda model: selection_score(lambda data: predict(model, data), domain)["selection_score"]

    def error(model, data):
        return sum(models.macro_errors(predict(model, data), data, spec).values())

    def relative_to_persistence(model, data):
        persistence = sum(models.macro_errors(v2dev.simple_predictions(data, "persistence"), data, spec).values())
        return error(model, data) / max(persistence, 1e-12)

    def replay_score(model):
        values = []
        for key, data in replay.items():
            raw = error(model, data)
            reference.setdefault(key, raw)
            values.append(raw / max(reference[key], 1e-12))
        return float(np.mean(values))

    def pooled(rule, current):
        world = v3.concat(*[data for _, data in pool])
        ids = np.concatenate([[i] * len(data.states) for i, (_, data) in enumerate(pool)])
        data = v3.concat(base, world)
        incident = np.array([e.startswith(("new:", "v3:")) for e in data.episodes])
        weights = np.where(incident, incident_weight, 1.0).astype(np.float64)
        offset = len(base.states)
        if rule == "error":
            errs = np.asarray([relative_to_persistence(current, replay[key]) for key, _ in pool])
            weights[offset:] *= (errs / errs.mean())[ids]
        elif rule == "recent":
            weights[offset:] *= np.where(ids >= len(pool) - candidates_per_round, 2.0, 1.0)
        return data, weights / weights.sum()

    data, weights = pooled("uniform", None)
    current = fit(domain, data, weights, seed, None, select)
    history.append({"round": 0, "selected": "bootstrap_uniform", "replay_score": replay_score(current)})
    log(json.dumps(history[-1]))
    for round_index in range(1, rounds):
        probes = []
        for mechanism, strength in mutations:
            key = f"{mechanism}@{strength[0]}-{strength[1]}"
            if key in replay:
                continue
            rows = v3.mechanism_rows(domain, f"rsi-probe-{round_index}", [mechanism], 32, SEEDS["probe"] + round_index,
                                     strength_range=strength)
            probe = v3.windows(rows, spec, complete=True)
            probes.append((relative_to_persistence(current, probe), key, mechanism, strength))
        probes.sort(key=lambda item: (-item[0], item[1]))
        for k, (_, key, mechanism, strength) in enumerate(probes[:candidates_per_round]):
            offset = 1000 * round_index + k
            train_rows = v3.mechanism_rows(domain, f"rsi-train-{offset}", [mechanism], 240, SEEDS["train"] + offset,
                                           strength_range=strength)
            val_rows = v3.mechanism_rows(domain, f"rsi-val-{offset}", [mechanism], 48, SEEDS["validation"] + offset,
                                         strength_range=strength)
            pool.append((key, v3.windows(train_rows, spec)))
            replay[key] = v3.windows(val_rows, spec, complete=True)
        reference.clear()
        replay_score(current)
        candidates = [(1.0, "keep_current", current)]
        for rule in ("uniform", "error", "recent")[:candidates_per_round]:
            data, weights = pooled(rule, current)
            candidate = fit(domain, data, weights, seed + 100 * round_index, current, select)
            candidates.append((replay_score(candidate), rule, candidate))
        candidates.sort(key=lambda item: (item[0], item[1]))
        score, name, current = candidates[0]
        history.append({"round": round_index, "selected": name, "replay_score": score,
                        "candidates": {n: v for v, n, _ in candidates},
                        "added_worlds": [p[1] for p in probes[:candidates_per_round]], "pool_size": len(pool)})
        log(json.dumps(history[-1]))
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
