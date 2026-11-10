"""Loaders for the tt1d study: Kaspersky's Tennessee Eastman attack dataset (Filonov, Kitashov and
Lavrentyev 2017, arXiv:1709.02232; kas.pr/ics-research/dataset_tep_59).

Files (README.txt of the dataset): CSV without a header, 60 columns, one row per 0.001 h (3.6 s):
  0        time in hours
  1..41    measurements (MEAS)                -> sensors
  42..53   manipulated variables (MV)         -> actions
  54..56   is_mv_attack, is_meas_attack, is_sp_attack (True / False)
  57       state (operating mode), 58 product_rate, 59 hourly_cost (not used)
single_states.zip holds attack-free runs of 120 h, `single_state_mode_<m>_id_<i>.csv`, for modes 0 to 6;
attacks.zip holds `attack_mode_<m>_type_<t>_id_<i>.csv`, t in 21..24. Archives are read in place.

Roles of the attack-free runs, fixed by file name before any content was read (ids ascending within a
mode): 5 fit, 2 residual scale, 4 calibration, 2 rehearsal deployment, 8 sealed. Fit, scale, calibration
and rehearsal runs are development data. The sealed runs and every attack run are read only after
open_final() has recorded the access; later runs of a mode are not read at all.

An event is a maximal run of rows whose three attack indicators are constant and not all False.
"""
from __future__ import annotations

import re
import zipfile

import numpy as np
import pandas as pd

import real_telemetry_data as D

RAW = D.RAW / "tep59"
STEP_SECONDS = 3.6
MODES = tuple(range(7))
ROLE_COUNTS = (("fit", 5), ("scale", 2), ("calib", 4), ("deploy", 2), ("sealed", 8))
DEV_ROLES = ("fit", "scale", "calib", "deploy")
LEDGER_IDS = ("tep59-attacks", "tep59-sealed-normal")
SENSORS, ACTIONS, FLAGS = slice(1, 42), slice(42, 54), slice(54, 57)
_OPENED = False


def _ident(name):
    return int(re.search(r"_id_(\d+)\.csv$", name).group(1))


def clean_roles():
    """{mode: {role: [member names]}} from the archive's file names only."""
    with zipfile.ZipFile(RAW / "single_states.zip") as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
    out = {}
    for m in MODES:
        mine = sorted((n for n in names if f"_mode_{m}_" in n), key=_ident)
        out[m], at = {}, 0
        for role, count in ROLE_COUNTS:
            out[m][role] = mine[at:at + count]
            at += count
        if len(out[m]["sealed"]) < ROLE_COUNTS[-1][1]:
            raise ValueError(f"mode {m}: only {len(mine)} attack-free runs")
    return out


def attack_names():
    """{mode: [(member name, attack type)]} from the archive's file names only."""
    with zipfile.ZipFile(RAW / "attacks.zip") as z:
        names = sorted(n for n in z.namelist() if n.endswith(".csv"))
    out = {m: [] for m in MODES}
    for n in names:
        g = re.search(r"attack_mode_(\d+)_type_(\d+)_id_(\d+)\.csv$", n)
        out[int(g.group(1))].append((n, int(g.group(2))))
    return {m: sorted(v, key=lambda t: _ident(t[0])) for m, v in out.items()}


def _read(archive, name):
    with zipfile.ZipFile(RAW / archive) as z, z.open(name) as f:
        frame = pd.read_csv(f, header=None)
    if frame.shape[1] != 60:
        raise ValueError(f"{name}: {frame.shape[1]} columns")
    values = frame.to_numpy()
    flags = np.stack([np.asarray(frame[c].astype(str).str.lower() == "true") for c in (54, 55, 56)], 1)
    key = flags[:, 0] * 1 + flags[:, 1] * 2 + flags[:, 2] * 4
    return values[:, SENSORS].astype(np.float32), values[:, ACTIONS].astype(np.float32), key.astype(np.int8)


def dev_runs(mode, role):
    """Attack-free development runs of one mode as [(X, U)]."""
    if role not in DEV_ROLES:
        raise ValueError(f"{role} is not a development role")
    out = []
    for name in clean_roles()[mode][role]:
        x, u, key = _read("single_states.zip", name)
        if key.any():
            raise ValueError(f"{name}: attack indicator set in an attack-free run")
        out.append((x, u))
    return out


def open_final(reason):
    """Record the single final access to the attack runs and the sealed attack-free runs."""
    global _OPENED
    for dataset in LEDGER_IDS:
        D._record_final_access(dataset, reason)
    _OPENED = True


def sealed_runs(mode):
    """Sealed attack-free runs of one mode as [(name, X, U)]; requires open_final()."""
    if not _OPENED:
        raise RuntimeError("sealed data requested before open_final()")
    out = []
    for name in clean_roles()[mode]["sealed"]:
        x, u, key = _read("single_states.zip", name)
        if key.any():
            raise ValueError(f"{name}: attack indicator set in an attack-free run")
        out.append((name, x, u))
    return out


def attack_runs(mode):
    """Attack runs of one mode, one at a time, as (name, type, X, U, key); requires open_final()."""
    if not _OPENED:
        raise RuntimeError("attack data requested before open_final()")
    for name, kind in attack_names()[mode]:
        x, u, key = _read("attacks.zip", name)
        yield name, kind, x, u, key


def events(key):
    """Maximal runs of a constant nonzero indicator key as (start, end, key), end exclusive."""
    key = np.asarray(key)
    edges = np.flatnonzero(np.diff(key) != 0) + 1
    starts = np.concatenate([[0], edges])
    ends = np.concatenate([edges, [len(key)]])
    return [(int(a), int(b), int(key[a])) for a, b in zip(starts, ends) if key[a] != 0]


# ---------------------------------------------------------------- ProvICS
"""ProvICS (Shibbir and Tosh 2026, arXiv:2607.05989; Hugging Face trucyberlab/multimodal-ICS-provenance,
revision 18b4b0e1): a chemical reactor twin controlled by a real PLC. benign48h/physical_state.csv and
attack22h/physical_state.csv are historian exports with a `_time` column (UTC) and 22 process registers,
one row every 1 to 2 s. attack22h/ground_truth/c<k>_ground_truth.csv list the attack phases of campaign k
with columns start,end,campaign,phase,sub_phase,tactic,technique,target,description (header lines read
to write this loader; no data row of a ground-truth file and no row of the attack recording was read).

Every recording is put on a 2 s grid (last row of each bin; empty bins repeat the previous row). The
first 75 % of the rows of the attack-free recording are development data; its last 25 % are sealed.
Development data is cut into segments at gaps longer than 10 s. Deployment streams (the sealed part and
the attack recording) stay continuous so that a threshold rule keeps its state, and grid steps inside a
gap longer than 10 s are returned as invalid (they cannot alarm). Columns whose name ends in _sp, _set,
setpoint or " SP" are actions; the other registers are sensors.

An event is one ground-truth row. Its interval runs from its start to its end plus 60 s (the dataset's
own rule credits a detection window that overlaps the event; our score is a 60 s mean), at least one step.
"""
P_RAW = D.RAW / "provics"
P_STEP_SECONDS = 2.0
P_DEV_FRACTION = 0.75
P_BREAK_SECONDS = 10.0
P_TOLERANCE_SECONDS = 60.0
P_LEDGER_IDS = ("provics-attack", "provics-sealed-normal")
P_META = ("Unnamed: 0", "result", "table", "_time")
_P_OPENED = False


def _p_is_action(name):
    return name.lower().endswith(("_sp", "_set", "setpoint", " sp"))


def _p_rows(path):
    with open(path, "rb") as f:
        return sum(1 for _ in f) - 1


def _p_read(path, first=None, skip=0):
    frame = pd.read_csv(path, skiprows=range(1, skip + 1), nrows=first, low_memory=False)
    names = [c for c in frame.columns if c not in P_META]
    time = pd.to_datetime(frame["_time"], utc=True)
    if not time.is_monotonic_increasing:
        raise ValueError(f"{path}: timestamps not increasing")
    seconds = (time - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().to_numpy()
    return seconds, frame[names].to_numpy(np.float32), names


def _p_grid(seconds, values):
    """2 s grid from the first row: (grid start in epoch seconds, values per step, valid per step)."""
    t0 = seconds[0]
    bins = np.floor((seconds - t0) / P_STEP_SECONDS + 1e-9).astype(int)
    last = np.flatnonzero(np.diff(np.concatenate([bins, [bins[-1] + 1]])) != 0)       # last row of each bin
    n = int(bins[-1]) + 1
    src = np.full(n, -1)
    src[bins[last]] = last
    filled = np.maximum.accumulate(src)                                                  # previous occupied bin
    grid = values[filled]
    gap = np.concatenate([[0.0], np.diff(seconds)])
    valid = np.ones(n, bool)
    for i in np.flatnonzero(gap > P_BREAK_SECONDS):
        valid[bins[i - 1] + 1:bins[i]] = False
    return t0, grid, valid


def _p_split(names):
    sensors = [i for i, c in enumerate(names) if not _p_is_action(c)]
    actions = [i for i, c in enumerate(names) if _p_is_action(c)]
    return sensors, actions


def provics_dev():
    """Development segments [(X, U)] from the first 75 % of the attack-free rows, and the column names."""
    path = P_RAW / "benign48h" / "physical_state.csv"
    seconds, values, names = _p_read(path, first=int(P_DEV_FRACTION * _p_rows(path)))
    sensors, actions = _p_split(names)
    cuts = np.concatenate([[0], np.flatnonzero(np.diff(seconds) > P_BREAK_SECONDS) + 1, [len(seconds)]])
    segs = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b - a < 100:
            continue
        _, grid, _ = _p_grid(seconds[a:b], values[a:b])
        segs.append((grid[:, sensors], grid[:, actions]))
    return segs, {"sensors": [names[i] for i in sensors], "actions": [names[i] for i in actions]}


def provics_open_final(reason):
    global _P_OPENED
    for dataset in P_LEDGER_IDS:
        D._record_final_access(dataset, reason)
    _P_OPENED = True


def provics_sealed():
    """The sealed last 25 % of the attack-free recording as one continuous stream (X, U, valid)."""
    if not _P_OPENED:
        raise RuntimeError("sealed data requested before provics_open_final()")
    path = P_RAW / "benign48h" / "physical_state.csv"
    seconds, values, names = _p_read(path, skip=int(P_DEV_FRACTION * _p_rows(path)))
    sensors, actions = _p_split(names)
    _, grid, valid = _p_grid(seconds, values)
    return grid[:, sensors], grid[:, actions], valid


def provics_attack():
    """The attack recording as one continuous stream and its events:
    (X, U, valid, events, unobserved) with events = [(start step, end step, campaign, technique)]."""
    if not _P_OPENED:
        raise RuntimeError("attack data requested before provics_open_final()")
    seconds, values, names = _p_read(P_RAW / "attack22h" / "physical_state.csv")
    sensors, actions = _p_split(names)
    t0, grid, valid = _p_grid(seconds, values)
    events, unobserved = [], 0
    for k in (1, 2, 3, 4):
        truth = pd.read_csv(P_RAW / "attack22h" / "ground_truth" / f"c{k}_ground_truth.csv")
        epoch = pd.Timestamp("1970-01-01", tz="UTC")
        start = (pd.to_datetime(truth["start"], utc=True) - epoch).dt.total_seconds().to_numpy()
        end = (pd.to_datetime(truth["end"], utc=True) - epoch).dt.total_seconds().to_numpy()
        for s, e, tech in zip(start, end, truth["technique"].astype(str)):
            a = int(np.floor((s - t0) / P_STEP_SECONDS))
            b = int(np.ceil((max(e, s) + P_TOLERANCE_SECONDS - t0) / P_STEP_SECONDS))
            a, b = max(a, 0), min(max(b, a + 1), len(grid))
            if a >= len(grid) or b <= 0 or not valid[a:b].any():
                unobserved += 1
                continue
            events.append((a, b, k, tech))
    events.sort()
    return grid[:, sensors], grid[:, actions], valid, events, unobserved
