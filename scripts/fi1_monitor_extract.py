#!/usr/bin/env python3
"""fi1 workstream A: residuals of the registered D1 monitor, cached once per benchmark unit (EXPLORATORY).

Plan: docs/research/ferrumos_improvement_fi1_plan.md. Every dataset here is spent; recorded attacks are read
only through the registered loaders, which append to target/real-telemetry/final_access.jsonl, with a reason
that starts with "EXPLORATORY fi1".

For each unit the registered monitor is refitted with the registered code (tt1_final.fit_monitor on the
registered split of the registered normal data). Then the H1 and H5 world-model residuals R1, R5 (scaled units,
per sensor) of every stream are written to target/real-telemetry/fi1/monitor/resid/<unit>/, with the scaled
actions U, the scaled sensors Z (not for Tennessee Eastman, to save disk), labels, events and validity masks.
The registered D1 score is exactly top3(|R1| / sig1) + top3(|R5| / sig5) smoothed, so the baseline and every
candidate score of fi1_monitor_v3 are computed from this cache without refitting.

    python scripts/fi1_monitor_extract.py <unit> [<unit> ...]      units: see UNITS

Groups per unit: "scale" (the residual-scale split), "calib" (the calibration split), "test" (attack streams),
and for Tennessee Eastman and ProvICS "sealed" (sealed attack-free streams the registered study scored).
"""

from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_k, "2")

import json
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "target/real-telemetry/fi1/monitor"
RESID = WORK / "resid"
REASON = "EXPLORATORY fi1 monitor (workstream A): residuals of the registered D1 monitor for the fi1 monitor benchmark"
LGB_THREADS = int(os.environ.get("FI1_LGB_THREADS", "2"))

HAI = dict(kind="stream", step=1.0, window=60, gap=60, budget=2.0, spd=86400)
UNITS = {
    "hai-21.03": dict(HAI, role="selection"),
    "hai-22.04": dict(HAI, role="selection"),
    "hai-20.07": dict(HAI, role="check"),
    "hai-23.05": dict(HAI, role="check"),
    "hygrid-ics": dict(HAI, role="check"),
    "batadal": dict(
        kind="stream", step=900.0, window=4, gap=4, budget=1 / 7, spd=96, role="check"
    ),
    "voraus-ad": dict(kind="episodic", step=0.1, window=10, alpha=0.05, role="check"),
    "provics": dict(
        kind="stream", step=2.0, window=30, gap=30, budget=2.0, spd=43200, role="check"
    ),
    **{
        f"tep-m{m}": dict(
            kind="stream",
            step=3.6,
            window=17,
            gap=17,
            budget=2.0,
            spd=24000,
            role="selection" if m <= 3 else "check",
        )
        for m in range(7)
    },
}


_LGBM = lgb.LGBMRegressor


def _lgbm(**k):
    """LightGBM with the thread count capped (the registered core asks for 4). Checked to reproduce tau0."""
    k["n_jobs"] = LGB_THREADS
    return _LGBM(**k)


def cap_threads():
    C.lgb.LGBMRegressor = _lgbm


# ---------------------------------------------------------------- registered data and monitor per unit
def _stream_unit(unit):
    """(scorer, pack, parts, kx, ku, cfg_registered_path) for HAI, HyGrid and BATADAL, as the registered harnesses do."""
    import threshold_transfer_dev as X
    import tt1_data as TD
    import tt1_final as F
    import tt1b_data as TB

    if unit == "hai-20.07":
        segs, _ = TD.hai2007_train()
    elif unit == "hygrid-ics":
        segs, _ = TD.hygrid_dev()
    elif unit == "batadal":
        segs, _ = TB.batadal_train()
    else:
        segs = X.normal_segments(unit)
    kx, ku = F.varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    min_len = 200 if unit == "batadal" else 1000
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=min_len)
    del segs
    scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
    return scorer, pack, parts, kx, ku


def _stream_test(unit, kx, ku):
    """Labelled attack streams as [(x, u, y)] through the ledgered registered loaders."""
    import real_telemetry_data as D
    import real_telemetry_rt2 as RT2
    import tt1_data as TD
    import tt1b_data as TB

    if unit == "hai-20.07":
        raw = TD.hai2007_test(REASON)[0]
    elif unit == "hygrid-ics":
        raw = TD.hygrid_test(REASON)[0]
    elif unit == "batadal":
        raw = TB.batadal_test(REASON)[0]
    elif unit == "hai-22.04":
        raw = [(s.X, s.U, s.y) for s in D.hai_test(REASON)["segments"]]
    else:
        raw = RT2.test_segments(unit, REASON)
    return [(x[:, kx], u[:, ku], np.asarray(y, np.int8)) for x, u, y in raw]


def _save_stream(d, key, scorer, z, v, extra, keep_z=True):
    r1 = C.residuals(scorer.wm, z, v, 1).astype(np.float32)
    r5 = C.residuals(scorer.wm, z, v, 5).astype(np.float32)
    np.save(d / f"{key}_R1.npy", r1)
    np.save(d / f"{key}_R5.npy", r5)
    np.save(d / f"{key}_U.npy", np.asarray(v, np.float32))
    if keep_z:
        np.save(d / f"{key}_Z.npy", np.asarray(z, np.float32))
    for name, arr in extra.items():
        np.save(d / f"{key}_{name}.npy", arr)
    return {"key": key, "steps": int(len(z))}


def _save_scorer(d, scorer):
    for h in (1, 5):
        np.save(d / f"ridge_coef_h{h}.npy", scorer.wm.ridge[h].coef_)
    if hasattr(scorer, "vlow"):
        np.save(d / "fit_vlow.npy", scorer.vlow)
        np.save(d / "fit_vhigh.npy", scorer.vhigh)
    np.save(d / "sig1.npy", scorer.sig1)
    np.save(d / "sig5.npy", scorer.sig5)
    np.save(d / "fit_low.npy", scorer.low)
    np.save(d / "fit_high.npy", scorer.high)


def prepare(unit):
    spec = UNITS[unit]
    t0 = time.time()
    d = RESID / unit
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "unit": unit,
        "spec": spec,
        "reason": REASON,
        "lgb_threads": LGB_THREADS,
        "groups": {},
    }
    cap_threads()
    if unit.startswith("tep-"):
        meta |= _prepare_tep(unit, d)
    elif unit == "provics":
        meta |= _prepare_provics(d)
    elif unit == "voraus-ad":
        meta |= _prepare_voraus(d)
    else:
        scorer, pack, parts, kx, ku = _stream_unit(unit)
        _save_scorer(d, scorer)
        print(unit, "monitor fitted", round(time.time() - t0), "s", flush=True)
        for group in ("scale", "calib"):
            meta["groups"][group] = [
                _save_stream(d, f"{group}_{i}", scorer, z, v, {})
                for i, (z, v) in enumerate(pack(parts[group]))
            ]
        del parts
        test = _stream_test(unit, kx, ku)
        rows = []
        for i, ((z, v), (_, _, y)) in enumerate(
            zip(pack([(x, u) for x, u, _ in test]), test)
        ):
            rows.append(_save_stream(d, f"test_{i}", scorer, z, v, {"y": y}))
            print(unit, "test stream", i, round(time.time() - t0), "s", flush=True)
        meta["groups"]["test"] = rows
    meta["seconds"] = round(time.time() - t0)
    (d / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(unit, "done", meta["seconds"], "s", flush=True)


def _prepare_tep(unit, d):
    import tt1_final as F
    import tt1d_data as TD

    mode = int(unit[len("tep-m") :])
    dev = {role: TD.dev_runs(mode, role) for role in ("fit", "scale", "calib")}
    kx, ku = F.varying_columns(dev["fit"] + dev["scale"] + dev["calib"])
    cut = lambda runs: [(x[:, kx], u[:, ku]) for x, u in runs]
    scorer, pack, _, _, _ = F.fit_monitor(cut(dev["fit"]), cut(dev["scale"]))
    _save_scorer(d, scorer)
    groups = {}
    for group in ("scale", "calib"):
        groups[group] = [
            _save_stream(d, f"{group}_{i}", scorer, z, v, {})
            for i, (z, v) in enumerate(pack(cut(dev[group])))
        ]
    del dev
    TD.open_final(REASON)
    groups["sealed"] = []
    for i, (name, x, u) in enumerate(TD.sealed_runs(mode)):
        z, v = pack([(x[:, kx], u[:, ku])])[0]
        groups["sealed"].append(
            _save_stream(d, f"sealed_{i}", scorer, z, v, {}) | {"name": name}
        )
    groups["test"] = []
    for i, (name, kind, x, u, key) in enumerate(TD.attack_runs(mode)):
        z, v = pack([(x[:, kx], u[:, ku])])[0]
        row = _save_stream(
            d, f"test_{i}", scorer, z, v, {"key": np.asarray(key, np.int8)}
        )
        groups["test"].append(row | {"name": name, "type": int(kind)})
        print(unit, "attack run", i, name, flush=True)
    return {"groups": groups}


def _prepare_provics(d):
    import tt1_final as F
    import tt1d_data as TD
    import tt1d_provics_amendment1 as A1

    TD._p_read = A1.read_filled  # amendment 1 of tt1d, as the registered ProvICS final
    segs, _ = TD.provics_dev()
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=500)
    kx, ku = F.varying_columns(parts["fit"] + parts["scale"] + parts["calib"])
    cut = lambda runs: [(x[:, kx], u[:, ku]) for x, u in runs]
    scorer, pack, _, _, _ = F.fit_monitor(cut(parts["fit"]), cut(parts["scale"]))
    _save_scorer(d, scorer)
    groups = {}
    for group in ("scale", "calib"):
        groups[group] = [
            _save_stream(d, f"{group}_{i}", scorer, z, v, {})
            for i, (z, v) in enumerate(pack(cut(parts[group])))
        ]
    TD.provics_open_final(REASON)
    x, u, valid, events, unobserved = TD.provics_attack()
    z, v = pack([(x[:, kx], u[:, ku])])[0]
    ev = np.array([[a, b, k] for a, b, k, _ in events], np.int64)
    groups["test"] = [
        _save_stream(
            d, "test_0", scorer, z, v, {"valid": np.asarray(valid, bool), "events": ev}
        )
        | {"unobserved_events": int(unobserved), "techniques": [t for *_, t in events]}
    ]
    xs, us, vs = TD.provics_sealed()
    z, v = pack([(xs[:, kx], us[:, ku])])[0]
    groups["sealed"] = [
        _save_stream(d, "sealed_0", scorer, z, v, {"valid": np.asarray(vs, bool)})
    ]
    return {"groups": groups}


def _prepare_voraus(d):
    """Episodic: one stream per sample. Groups are concatenated per group with offsets (many short samples)."""
    import tt1_data as TD
    import tt1_final as F

    samples, _ = TD.voraus_train()
    kx, ku = F.varying_columns(samples)
    samples = [(x[:, kx], u[:, ku]) for x, u in samples]
    n = len(samples)
    cuts = [int(n * c) for c in F.FINAL_CUTS]
    fit_raw, scale_raw, calib_raw = (
        samples[: cuts[0]],
        samples[cuts[0] : cuts[1]],
        samples[cuts[1] :],
    )
    scorer, pack, _, _, _ = F.fit_monitor(fit_raw, scale_raw)
    _save_scorer(d, scorer)
    del samples, fit_raw
    groups = {}

    def save_group(name, pairs, flags=None):
        r1, r5, us, zs, lens = [], [], [], [], []
        for z, v in pairs:
            r1.append(C.residuals(scorer.wm, z, v, 1).astype(np.float32))
            r5.append(C.residuals(scorer.wm, z, v, 5).astype(np.float32))
            us.append(v.astype(np.float32))
            zs.append(z.astype(np.float32))
            lens.append(len(z))
        np.save(d / f"{name}_R1.npy", np.concatenate(r1))
        np.save(d / f"{name}_R5.npy", np.concatenate(r5))
        np.save(d / f"{name}_U.npy", np.concatenate(us))
        np.save(d / f"{name}_Z.npy", np.concatenate(zs))
        np.save(d / f"{name}_lengths.npy", np.array(lens, np.int64))
        if flags is not None:
            np.save(d / f"{name}_flags.npy", np.asarray(flags, np.int8))
        return {"key": name, "samples": len(lens), "steps": int(sum(lens))}

    groups["scale"] = [save_group("scale", pack(scale_raw))]
    groups["calib"] = [save_group("calib", pack(calib_raw))]
    raw = [(x[:, kx], u[:, ku], flag) for x, u, flag in TD.voraus_test(REASON)[0]]
    groups["test"] = [
        save_group("test", pack([(x, u) for x, u, _ in raw]), [f for _, _, f in raw])
    ]
    return {"groups": groups}


def coefs(unit):
    """Refit the monitor of an already-extracted stream unit (normal data only) to add the ridge coefficients
    and action ranges to its cache. Refuses if the refit residual scales differ from the cached ones, so it
    also checks that the fit is deterministic under the capped thread settings."""
    d = RESID / unit
    cap_threads()
    scorer, *_ = _stream_unit(unit)
    old = np.load(d / "sig1.npy")
    if not np.array_equal(old, scorer.sig1):
        raise SystemExit(
            f"{unit}: refit sig1 differs from the cache (max abs diff {np.abs(old - scorer.sig1).max()})"
        )
    _save_scorer(d, scorer)
    print(unit, "coefficients added; refit is bit-identical", flush=True)


def tep_add_sensors(unit):
    """Add the scaled sensors Z and the ridge coefficients to a Tennessee Eastman unit cached without them.

    The scaler is refitted on the fit runs (median and spread, deterministic). The ridge part of the world
    model is refitted without the boosted trees: Forecaster.fit draws its rows and fits the ridge before any
    tree, so the ridge is the one inside the cached monitor. Attack and sealed runs are reread (ledgered)."""
    import tt1_final as F
    import tt1d_data as TD

    d = RESID / unit
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    mode = int(unit[len("tep-m") :])
    dev = {role: TD.dev_runs(mode, role) for role in ("fit", "scale", "calib")}
    kx, ku = F.varying_columns(dev["fit"] + dev["scale"] + dev["calib"])
    cut = lambda runs: [(x[:, kx], u[:, ku]) for x, u in runs]
    fit = cut(dev["fit"])
    xs = C.Scaler().fit(np.concatenate([x for x, _ in fit]))
    us = C.Scaler().fit(np.concatenate([u for _, u in fit]))
    pack = lambda g: [(xs(x), us(u)) for x, u in g]
    packed_fit = pack(fit)
    if not np.array_equal(
        np.concatenate([z for z, _ in packed_fit]).max(0), np.load(d / "fit_high.npy")
    ):
        raise SystemExit(
            f"{unit}: refitted scaler does not reproduce the cached fit range"
        )
    ridge = C.Forecaster((1, 5), 3, use_actions=True, gbr=None).fit(packed_fit)
    for h in (1, 5):
        np.save(d / f"ridge_coef_h{h}.npy", ridge.ridge[h].coef_)
    V = np.concatenate([v for _, v in packed_fit])
    np.save(d / "fit_vlow.npy", V.min(0))
    np.save(d / "fit_vhigh.npy", V.max(0))
    for group in ("scale", "calib"):
        for row, (z, v) in zip(meta["groups"][group], pack(cut(dev[group]))):
            if not np.array_equal(np.load(d / f"{row['key']}_U.npy"), v):
                raise SystemExit(f"{unit} {row['key']}: actions differ from the cache")
            np.save(d / f"{row['key']}_Z.npy", z)
    del dev
    TD.open_final(REASON + " (adding the scaled sensors to the cache)")
    for row, (name, x, u) in zip(meta["groups"]["sealed"], TD.sealed_runs(mode)):
        assert row["name"] == name
        np.save(d / f"{row['key']}_Z.npy", pack([(x[:, kx], u[:, ku])])[0][0])
    for row, (name, _, x, u, _) in zip(meta["groups"]["test"], TD.attack_runs(mode)):
        assert row["name"] == name
        np.save(d / f"{row['key']}_Z.npy", pack([(x[:, kx], u[:, ku])])[0][0])
    print(unit, "sensors and ridge coefficients added", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "tep-add-sensors":
        for name in sys.argv[2:]:
            tep_add_sensors(name)
        raise SystemExit(0)
    if sys.argv[1] == "coefs":
        for name in sys.argv[2:]:
            coefs(name)
        raise SystemExit(0)
    for name in sys.argv[1:]:
        if name not in UNITS:
            raise SystemExit(f"unknown unit {name}; choose from {list(UNITS)}")
    for name in sys.argv[1:]:
        prepare(name)
