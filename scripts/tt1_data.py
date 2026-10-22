"""Loaders for the threshold-transfer study tt1 fresh datasets (HAI 20.07, HyGrid-ICS, voraus-AD).

Development functions read only data the registered split assigns to development and never read a
label column. Final functions append to target/real-telemetry/final_access.jsonl before reading
anything else. Column roles (actions vs sensors) are fixed here from documentation and training
headers only.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

import real_telemetry_data as D

RAW = D.RAW
CACHE = D.CACHE

# ---------------------------------------------------------------- HAI 20.07 (1 Hz)
HAI2007_TRAIN = ["train1.csv.gz", "train2.csv.gz"]
HAI2007_TEST = ["test1.csv.gz", "test2.csv.gz"]
HAI2007_LABELS = ("attack", "attack_P1", "attack_P2", "attack_P3")
# Release-specific setpoint, demand and command tags (HAI 1.0 tag list); all others are sensors.
HAI2007_EXTRA_ACTIONS = ["P2_Auto", "P2_Emgy", "P2_On", "P2_SD01", "P3_LH", "P3_LL", "P4_HT_LD"]


def _hai2007_read(name, usecols=None):
    return pd.read_csv(RAW / "hai-20.07" / name, sep=";", usecols=usecols)


def hai2007_columns() -> dict:
    path = CACHE / "hai-20.07-columns.json"
    if not path.exists():
        low = high = tags = None
        for name in HAI2007_TRAIN:
            frame = _hai2007_read(name)
            tags = tags or [c for c in frame.columns if c != "time" and c not in HAI2007_LABELS]
            normal = frame["attack"].to_numpy() == 0           # train2 holds two labelled attack runs (776 s)
            frame = frame[normal]
            vals = frame[tags].to_numpy(np.float64)
            low = vals.min(0) if low is None else np.minimum(low, vals.min(0))
            high = vals.max(0) if high is None else np.maximum(high, vals.max(0))
        varying = [t for t, a, b in zip(tags, low, high) if b - a > 1e-9]
        actions = set(D.HAI_ACTIONS) | set(HAI2007_EXTRA_ACTIONS)
        meta = {"sensors": [t for t in varying if t not in actions], "actions": [t for t in varying if t in actions],
                "dropped_constant": [t for t in tags if t not in varying]}
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


HAI2007_ATTACK_MARGIN = 600      # seconds removed on each side of a labelled attack run in the train files


def hai2007_train():
    """Normal training segments; labelled attack runs in train2 (plus a 600 s margin) are cut out."""
    cols = hai2007_columns()
    segs = []
    for name in HAI2007_TRAIN:
        frame = _hai2007_read(name, usecols=cols["sensors"] + cols["actions"] + ["attack"])
        bad = frame["attack"].to_numpy() > 0
        if bad.any():
            idx = np.flatnonzero(bad)
            for i in idx:
                bad[max(0, i - HAI2007_ATTACK_MARGIN):i + HAI2007_ATTACK_MARGIN + 1] = True
        edges = np.diff(np.concatenate([[1], bad.astype(int), [1]]))
        for a, b in zip(np.flatnonzero(edges == -1), np.flatnonzero(edges == 1)):
            if b - a > 3600:
                part = frame.iloc[a:b]
                segs.append((part[cols["sensors"]].to_numpy(np.float32), part[cols["actions"]].to_numpy(np.float32)))
    return segs, cols


def hai2007_test(reason: str):
    D._record_final_access("hai-20.07", reason)
    cols = hai2007_columns()
    out = []
    for name in HAI2007_TEST:
        frame = _hai2007_read(name)
        out.append((frame[cols["sensors"]].to_numpy(np.float32), frame[cols["actions"]].to_numpy(np.float32),
                    frame["attack"].to_numpy(np.int8)))
    return out, cols


# ---------------------------------------------------------------- HyGrid-ICS (5 Hz, averaged to 1 Hz)
HYGRID_FILE = "scada_cps_dataset.csv"
HYGRID_LABELS = ("attack_id", "Attack_Type", "Is_Attack")
HYGRID_ACTIONS = ["HR0", "HR1", "HR2", "HR3", "cooling_mode", "prot_bitmask",
                  "irradiance", "wind_speed", "cloud_pct", "T_ambient"]          # commands, setpoints, exogenous drivers
HYGRID_SENSORS = ["freq_hz", "min_voltage", "total_kw", "solar_kw", "losses_kw", "alarm", "v_sub", "v_ind", "v_res",
                  "v_com", "T_oil", "T_hotspot", "SoH", "T_battery", "aging_rate", "SoC"]
HYGRID_DEV_FRACTION = 0.40      # chronological, label-blind: first 40% development, last 60% final


def _hygrid_frame(usecols):
    frame = pd.read_csv(RAW / "hygrid-ics" / HYGRID_FILE, usecols=["timestamp"] + usecols)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame.sort_values("timestamp", kind="stable").reset_index(drop=True)


def _to_1hz(frame, cols, how="mean"):
    sec = frame["timestamp"].dt.floor("s")
    return frame.groupby(sec)[cols].agg(how)


def hygrid_dev():
    frame = _hygrid_frame(HYGRID_SENSORS + HYGRID_ACTIONS)
    cut = int(len(frame) * HYGRID_DEV_FRACTION)
    dev = _to_1hz(frame.iloc[:cut], HYGRID_SENSORS + HYGRID_ACTIONS).ffill().bfill()
    return [(dev[HYGRID_SENSORS].to_numpy(np.float32), dev[HYGRID_ACTIONS].to_numpy(np.float32))], \
        {"sensors": HYGRID_SENSORS, "actions": HYGRID_ACTIONS, "rows_raw_dev": cut, "rows_raw_total": len(frame)}


def hygrid_test(reason: str):
    D._record_final_access("hygrid-ics", reason)
    frame = _hygrid_frame(HYGRID_SENSORS + HYGRID_ACTIONS + ["Is_Attack"])
    cut = int(len(frame) * HYGRID_DEV_FRACTION)
    fin = frame.iloc[cut:]
    agg = _to_1hz(fin, HYGRID_SENSORS + HYGRID_ACTIONS).ffill().bfill()
    lab = _to_1hz(fin, ["Is_Attack"], how="max").reindex(agg.index).fillna(0)
    return [(agg[HYGRID_SENSORS].to_numpy(np.float32), agg[HYGRID_ACTIONS].to_numpy(np.float32),
             lab["Is_Attack"].to_numpy(np.int8))], {"sensors": HYGRID_SENSORS, "actions": HYGRID_ACTIONS}


# ---------------------------------------------------------------- voraus-AD (100 Hz, divided to 10 Hz, episodic)
VORAUS_FILE = "voraus-ad-dataset-100hz.parquet"
VORAUS_META = ("time", "sample", "anomaly", "category", "setting", "action", "active")
VORAUS_LABELS = ("anomaly", "category")
VORAUS_DIVIDER = 10
VORAUS_TRAIN_SETTING = 72    # Variant.PRE_A in the official voraus_ad.py enum (948 samples), the official training set


def voraus_columns():
    import pyarrow.parquet as pq
    names = pq.ParquetFile(RAW / "voraus-ad" / VORAUS_FILE).schema_arrow.names
    signals = [n for n in names if n not in VORAUS_META]
    actions = [n for n in signals if n.startswith("target_")]
    sensors = [n for n in signals if not n.startswith("target_")]
    return {"sensors": sensors, "actions": actions}


def _voraus_frame(columns):
    frame = pd.read_parquet(RAW / "voraus-ad" / VORAUS_FILE, columns=columns)
    frame = frame[frame.index.values % VORAUS_DIVIDER == 0]
    return frame


def voraus_train():
    cols = voraus_columns()
    frame = _voraus_frame(["sample", "setting"] + cols["sensors"] + cols["actions"])
    train = frame[frame["setting"] == VORAUS_TRAIN_SETTING]
    segs = [(g[cols["sensors"]].to_numpy(np.float32), g[cols["actions"]].to_numpy(np.float32))
            for _, g in train.groupby("sample", sort=True)]
    return segs, cols | {"train_samples": len(segs)}


def voraus_test(reason: str):
    D._record_final_access("voraus-ad", reason)
    cols = voraus_columns()
    frame = _voraus_frame(["sample", "setting", "anomaly"] + cols["sensors"] + cols["actions"])
    test = frame[frame["setting"] != VORAUS_TRAIN_SETTING]
    out = [(g[cols["sensors"]].to_numpy(np.float32), g[cols["actions"]].to_numpy(np.float32),
            int(bool(g["anomaly"].iloc[0]))) for _, g in test.groupby("sample", sort=True)]
    return out, cols
