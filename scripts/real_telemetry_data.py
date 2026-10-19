"""Load the verified HAI 22.04 and SMD files into compact float32 caches (no model code here).

HAI 22.04: 86 tags at 1 Hz. Tags are split into actions (setpoints, demands and controller or
operator commands, taken from the HAI technical manual) and sensors (everything measured).
Constant training columns are dropped. The six training files are normal operation; the four
test files carry the per-second `Attack` label. SMD: 28 machines, 38 normalised metrics at one
minute; no commands exist, so SMD models are autonomous forecasters. Raw files are read as data
only; this module never imports or executes anything from the download folders.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from real_telemetry_core import Segment

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "target" / "real-telemetry" / "raw"
CACHE = ROOT / "target" / "real-telemetry" / "cache"

# Setpoints, demands, schedules, controller outputs and operator commands (HAI manual, Table 2).
HAI_ACTIONS = [
    "P1_B2004", "P1_B2016", "P1_B3004", "P1_B3005", "P1_B4002", "P1_B4005", "P1_B400B", "P1_B4022",
    "P1_FCV01D", "P1_FCV02D", "P1_FCV03D", "P1_LCV01D", "P1_PCV01D", "P1_PCV02D",
    "P1_PP01AD", "P1_PP01BD", "P1_PP02D", "P1_PP04", "P1_PP04SP", "P1_SOL01D", "P1_SOL03D", "P1_STSP",
    "P2_AutoGO", "P2_AutoSD", "P2_Emerg", "P2_MASW", "P2_ManualGO", "P2_ManualSD", "P2_OnOff", "P2_RTR",
    "P2_SCO", "P2_TripEx", "P2_VTR01", "P2_VTR02", "P2_VTR03", "P2_VTR04",
    "P3_LCP01D", "P3_LCV01D", "P3_LH01", "P3_LL01",
    "P4_HT_LD", "P4_HT_PS", "P4_LD", "P4_ST_LD", "P4_ST_PS",
]
HAI_TRAIN = [f"train{i}.csv" for i in range(1, 7)]
HAI_TEST = [f"test{i}.csv" for i in range(1, 5)]
SMD_MACHINES = [f"machine-{a}-{b}" for a, n in ((1, 8), (2, 9), (3, 11)) for b in range(1, n + 1)]


FINAL_LEDGER = ROOT / "target" / "real-telemetry" / "final_access.jsonl"


def _record_final_access(dataset: str, reason: str) -> None:
    """Every read of recorded attack or incident data is appended to a ledger."""
    import datetime
    FINAL_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with FINAL_LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"dataset": dataset, "reason": reason,
                                 "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}) + chr(10))


def _read_hai(name: str) -> pd.DataFrame:
    frame = pd.read_csv(RAW / "hai-22.04" / name, engine="c", low_memory=True)
    frame.columns = [c.strip() for c in frame.columns]
    return frame


def hai_columns() -> dict:
    """Sensor and action columns, decided from the normal training files only."""
    path = CACHE / "hai-22.04-columns.json"
    if not path.exists():
        tags, low, high = None, None, None
        for name in HAI_TRAIN:                      # one file at a time keeps memory low
            frame = _read_hai(name)
            tags = tags or [c for c in frame.columns if c not in ("timestamp", "Attack")]
            values = frame[tags].to_numpy(np.float64)
            low = values.min(0) if low is None else np.minimum(low, values.min(0))
            high = values.max(0) if high is None else np.maximum(high, values.max(0))
            del frame, values
        varying = [c for c, a, b in zip(tags, low, high) if b - a > 1e-9]
        meta = {"sensors": [c for c in varying if c not in HAI_ACTIONS], "actions": [c for c in HAI_ACTIONS if c in varying],
                "dropped_constant": [c for c in tags if c not in varying], "tags": tags}
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def hai_train() -> dict:
    """Normal training segments (development data). Never reads the test files."""
    path = CACHE / "hai-22.04-train.npz"
    cols = hai_columns()
    if not path.exists():
        arrays = {}
        for i, name in enumerate(HAI_TRAIN):
            f = _read_hai(name)
            assert int(f["Attack"].sum()) == 0 if "Attack" in f else True, f"{name} contains attack labels"
            arrays[f"X{i}"] = f[cols["sensors"]].to_numpy(np.float32)
            arrays[f"U{i}"] = f[cols["actions"]].to_numpy(np.float32)
        np.savez_compressed(path, **arrays)
    data = np.load(path, allow_pickle=False)
    return {"segments": [Segment(n, data[f"X{i}"], data[f"U{i}"]) for i, n in enumerate(HAI_TRAIN)], **cols}


def hai_test(reason: str) -> dict:
    """Recorded attacks: final evaluation only; every call is ledgered."""
    _record_final_access("hai-22.04", reason)
    cols = hai_columns()
    segments = []
    for name in HAI_TEST:
        f = _read_hai(name)
        segments.append(Segment(name, f[cols["sensors"]].to_numpy(np.float32), f[cols["actions"]].to_numpy(np.float32),
                                f["Attack"].to_numpy(np.int8)))
    return {"segments": segments, **cols}


def smd_train() -> dict:
    """Per-machine normal-period training data (development). Never reads test files or labels."""
    return {m: Segment(f"{m}-train", np.loadtxt(RAW / "smd" / "train" / f"{m}.txt", delimiter=",", dtype=np.float32))
            for m in SMD_MACHINES}


def smd_test(reason: str) -> dict:
    """Recorded incidents: final evaluation only; every call is ledgered."""
    _record_final_access("smd", reason)
    return {m: Segment(f"{m}-test", np.loadtxt(RAW / "smd" / "test" / f"{m}.txt", delimiter=",", dtype=np.float32),
                       y=np.loadtxt(RAW / "smd" / "test_label" / f"{m}.txt", delimiter=",", dtype=np.int8))
            for m in SMD_MACHINES}
