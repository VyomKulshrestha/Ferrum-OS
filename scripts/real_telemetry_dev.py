"""Development partitions and the world-model trial ledger for the real-telemetry study.

Development reads normal training data only. HAI: train1-4 fit, train5-6 validation (later
periods). SMD: per machine, the first 80% of the training period fits and the last 20% validates.
Every trial is appended to target/real-telemetry/development_ledger.jsonl.
"""
from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

import numpy as np

import real_telemetry_core as C
import real_telemetry_data as D

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "target" / "real-telemetry"
LEDGER = WORK / "development_ledger.jsonl"
HORIZONS = (1, 5)
HISTORY = 3


def log(entry: dict) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    entry = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), **entry}
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + chr(10))


def hai_partitions():
    data = D.hai_train()
    seg = data["segments"]
    fit, val = seg[:4], seg[4:]
    xs = C.Scaler().fit(np.concatenate([s.X for s in fit]))
    us = C.Scaler().fit(np.concatenate([s.U for s in fit]))
    pack = lambda group: [(xs(s.X), us(s.U)) for s in group]
    return {"fit": pack(fit), "val": pack(val), "sensors": data["sensors"], "actions": data["actions"],
            "x_scaler": xs, "u_scaler": us}


def smd_partitions():
    out = {}
    for name, seg in D.smd_train().items():
        cut = int(len(seg.X) * 0.8)
        scaler = C.Scaler().fit(seg.X[:cut])
        Z = scaler(seg.X)
        out[name] = {"fit": [(Z[:cut], None)], "val": [(Z[cut:], None)], "scaler": scaler}
    return out


def world_model_trials(domain: str, configs: dict) -> dict:
    """Validation MAE (scaled units) at each registered horizon for each world-model config."""
    results = {}
    if domain == "hai":
        parts = hai_partitions()
        groups = {"all": (parts["fit"], parts["val"])}
    else:
        parts = smd_partitions()
        groups = {m: (p["fit"], p["val"]) for m, p in parts.items()}
    for label, make in configs.items():
        start, errors = time.time(), {h: [] for h in HORIZONS}
        for fit, val in groups.values():
            model = make().fit(fit)
            for h in HORIZONS:
                errors[h].append(C.forecast_error(model, val, h))
        results[label] = {f"H{h}": float(np.mean(v)) for h, v in errors.items()}
        log({"kind": "world_model", "domain": domain, "config": label, "validation_mae": results[label],
             "seconds": round(time.time() - start, 1)})
        print(domain, label, results[label], round(time.time() - start), "s", flush=True)
    return results


if __name__ == "__main__":
    import sys
    domain = sys.argv[1]
    configs = {
        "persistence": lambda: C.Persistence(HORIZONS, HISTORY),
        "ridge_autonomous": lambda: C.Forecaster(HORIZONS, HISTORY, use_actions=False),
        "ridge_actions": lambda: C.Forecaster(HORIZONS, HISTORY, use_actions=True),
        "ridge_gbr_actions": lambda: C.Forecaster(HORIZONS, HISTORY, use_actions=True,
                                                  gbr=dict(n_estimators=60, num_leaves=31, learning_rate=0.1,
                                                           min_child_samples=100, subsample=0.8, subsample_freq=1)),
    }
    if domain == "smd":
        configs = {k: v for k, v in configs.items() if k != "ridge_actions"}
        configs["ridge_gbr_autonomous"] = configs.pop("ridge_gbr_actions")
        configs["ridge_gbr_autonomous"] = lambda: C.Forecaster(HORIZONS, HISTORY, use_actions=False,
                                                               gbr=dict(n_estimators=60, num_leaves=31, learning_rate=0.1,
                                                                        min_child_samples=50, subsample=0.8, subsample_freq=1))
    world_model_trials(domain, configs)
