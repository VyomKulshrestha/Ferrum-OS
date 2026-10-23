"""Loaders for the tt1b replication datasets.

BATADAL (C-Town water network, scy-phy re-simulation without concealment): EPANET output with regular
15-minute reports plus extra rows at control events. Every file is put on a 15-minute grid by taking
the last row of each bin (labels: the maximum of ATT_FLAG over the bin). DATETIME holds elapsed hours.
Actions are the pump and valve STATUS columns; sensors are the PRESSURE (junctions and tank levels) and
FLOW columns. The training file is normal-only (ATT_FLAG 0 throughout, read for development). Test files
are read only through batadal_test, which records the single final access first.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import real_telemetry_data as D

RAW = D.RAW / "batadal"
BATADAL_TEST = ["test_dataset_1.csv", "test_dataset_2.csv"]
BATADAL_STEP_H = 0.25


def _batadal(name, with_label):
    frame = pd.read_csv(RAW / name)
    frame = frame.drop(columns=[c for c in frame.columns if c.startswith("Unnamed")])
    hours = frame["DATETIME"].astype(float).to_numpy()
    frame["bin"] = np.floor((hours - hours[0]) / BATADAL_STEP_H + 1e-9).astype(int)
    signals = [c for c in frame.columns if c not in ("DATETIME", "ATT_FLAG", "bin")]
    grid = frame.groupby("bin")[signals].last()
    grid = grid.reindex(range(grid.index.max() + 1)).ffill()
    out = {"sensors": [c for c in signals if not c.startswith("STATUS_")],
           "actions": [c for c in signals if c.startswith("STATUS_")], "frame": grid}
    if with_label:
        out["label"] = (frame.groupby("bin")["ATT_FLAG"].max().reindex(grid.index).fillna(0).to_numpy() > 0).astype(np.int8)
    return out


def batadal_train():
    g = _batadal("train_dataset.csv", with_label=False)
    f = g["frame"]
    return [(f[g["sensors"]].to_numpy(np.float32), f[g["actions"]].to_numpy(np.float32))], \
        {"sensors": g["sensors"], "actions": g["actions"], "steps": len(f)}


def batadal_test(reason: str):
    D._record_final_access("batadal", reason)
    out = []
    for name in BATADAL_TEST:
        g = _batadal(name, with_label=True)
        f = g["frame"]
        out.append((f[g["sensors"]].to_numpy(np.float32), f[g["actions"]].to_numpy(np.float32), g["label"]))
    return out, {"sensors": g["sensors"], "actions": g["actions"]}
