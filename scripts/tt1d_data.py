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
