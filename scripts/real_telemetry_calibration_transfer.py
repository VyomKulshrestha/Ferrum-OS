#!/usr/bin/env python3
"""Calibration-transfer study on real HAI telemetry (NORMAL data only).

rt2's detection failure was calibration transfer: an alarm threshold set on a
calibration period did not hold its false-alarm budget on a later period. The
false-alarm rate is a property of NORMAL data alone, so this can be reproduced
and fixed honestly WITHOUT any attack/test data.

Design per HAI release: take the normal train segments, split chronologically
into fit (50%) / calibrate (25%) / deploy-proxy (25%). Fit the forecaster on
fit, build a residual warning score, set its threshold on `calibrate` to a
target false-alarm-EPISODE rate, then MEASURE the false-alarm-episode rate on
`deploy`. transfer_ratio = deploy_rate / target (1.0 = perfect; >>1 = the rt2
failure). We compare threshold/scale methods and report which transfers.

Adopts the cycle-2 forecaster (gbr_big_h12). No attack files are read.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C
import real_telemetry_data as D
import real_telemetry_rt2 as RT2

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "research" / "real_telemetry_calibration_transfer_v1.json"
FAST = bool(os.environ.get("FAST"))
HISTORY = 3 if FAST else 12
GBR = (None if FAST else dict(n_estimators=200, num_leaves=63, learning_rate=0.05, min_child_samples=100,
           subsample=0.8, subsample_freq=1, colsample_bytree=0.8))
WARMUP = HISTORY + 2
TARGET_FA_PER_DAY = 1.0
TARGET_FPR = 1e-3        # per-step false-positive rate the threshold is calibrated to
STEPS_PER_DAY = 86400          # HAI is 1 Hz
GAP = 60                       # merge alarms within 60 s into one episode
TOPK = 3


def normal_segments(release):
    """Return normal (X, U) segments for a release. No attack/test data."""
    if release == "hai-22.04":
        d = D.hai_train()
        return [(s.X, s.U) for s in d["segments"]]
    segs, _cols = RT2.train_segments(release)   # normal train only
    return [(x, u) for x, u in segs]


def time_split(segs, cuts=(0.5, 0.75)):
    total = sum(len(x) for x, _ in segs)
    b = [int(total * c) for c in cuts]
    out = {"fit": [], "calib": [], "deploy": []}
    off = 0
    for x, u in segs:
        a, z = off, off + len(x)
        for name, lo, hi in (("fit", 0, b[0]), ("calib", b[0], b[1]), ("deploy", b[1], total)):
            s, e = max(a, lo), min(z, hi)
            if e - s > WARMUP + 10:
                out[name].append((x[s - a:e - a], u[s - a:e - a]))
        off = z
    return out


def residual_stack(model, pairs, h=1):
    """Stack per-step |residual| (N, d) over all segments (warmup rows dropped)."""
    out = []
    for Z, V in pairs:
        t = C.valid_index(len(Z), model.history, h)
        r = np.abs(model.predict(Z, V, t, h) - Z[t + h])
        out.append(r)
    return np.concatenate(out), [len(C.valid_index(len(Z), model.history, h)) for Z, _ in pairs]


def topk_score(absres, scale):
    s = absres / scale
    return -np.sort(-s, 1)[:, :TOPK].mean(1)


def episodes(alarm, gap):
    idx = np.flatnonzero(alarm)
    if not len(idx):
        return 0
    breaks = np.flatnonzero(np.diff(idx) > gap + 1)
    return len(breaks) + 1


def fa_per_day(score, thr, n_steps):
    return episodes(score > thr, GAP) / max(n_steps / STEPS_PER_DAY, 1e-9)


def calibrate_threshold(score, n_steps, target):
    """Smallest threshold whose calib false-episode rate <= target/day."""
    days = max(n_steps / STEPS_PER_DAY, 1e-9)
    allowed = target * days
    cand = np.unique(np.quantile(score, 1 - np.logspace(-6, -0.5, 240)))
    best = float(score.max()) + 1e-9
    for thr in cand[::-1]:
        if episodes(score > thr, GAP) <= allowed:
            best = float(thr)
    return best


def run_release(release):
    segs = normal_segments(release)
    parts = time_split(segs)
    xs = C.Scaler().fit(np.concatenate([x for x, _ in parts["fit"]]))
    us = C.Scaler().fit(np.concatenate([u for _, u in parts["fit"]]))
    pack = lambda g: [(xs(x), us(u)) for x, u in g]
    fit, calib, deploy = pack(parts["fit"]), pack(parts["calib"]), pack(parts["deploy"])
    model = C.Forecaster([1], HISTORY, use_actions=True, gbr=GBR).fit(fit, max_rows=30_000)

    rfit, _ = residual_stack(model, fit)
    rcal, _ = residual_stack(model, calib)
    rdep, _ = residual_stack(model, deploy)

    # Per-step false-positive-rate transfer: set the threshold so the CALIBRATION
    # false-positive rate equals TARGET_FPR exactly (split-conformal quantile),
    # then measure the DEPLOY false-positive rate. transfer_ratio = deploy/target
    # (1.0 = the budget held; >1 = the rt2 overshoot). All data is normal, so
    # every alarm is a false positive -- this is pure calibration transfer.
    sig_fit = rfit.std(0) + 1e-6
    sig_cal = rcal.std(0) + 1e-6
    mad_cal = 1.4826 * np.median(np.abs(rcal - np.median(rcal, 0)), 0) + 1e-6
    d = rcal.shape[1]

    def pooled(scale):
        sc, sd = topk_score(rcal, scale), topk_score(rdep, scale)
        thr = float(np.quantile(sc, 1.0 - TARGET_FPR))
        return float((sc > thr).mean()), float((sd > thr).mean())

    methods = {}
    for name, scale in (("S0_fit_sigma", sig_fit),      # rt2-style: scale from the fit period
                        ("S1_calib_sigma", sig_cal),    # scale from the calibration period
                        ("S2_calib_mad", mad_cal)):     # robust (MAD) scale from calibration
        cf, df = pooled(scale)
        methods[name] = {"calib_fpr": cf, "deploy_fpr": df}
    # S3: per-variable union, each variable calibrated to TARGET_FPR/d (Bonferroni)
    # so no single drifting sensor dominates a pooled threshold.
    zc, zd = rcal / mad_cal, rdep / mad_cal
    tau = np.quantile(zc, 1.0 - TARGET_FPR / d, axis=0)
    methods["S3_per_var_union"] = {"calib_fpr": float((zc > tau).any(1).mean()),
                                   "deploy_fpr": float((zd > tau).any(1).mean())}
    # S4: conservative safety margin -- calibrate MAD-pooled to TARGET_FPR/2 so a
    # typical drift still leaves deploy at or under budget.
    sc_mad, sd_mad = topk_score(rcal, mad_cal), topk_score(rdep, mad_cal)
    thr4 = float(np.quantile(sc_mad, 1.0 - TARGET_FPR / 2))
    methods["S4_margin2x"] = {"calib_fpr": float((sc_mad > thr4).mean()),
                              "deploy_fpr": float((sd_mad > thr4).mean())}
    # S5: daily re-calibration -- recompute the threshold each day on the previous
    # day of (benign) data. Models an online monitor; assumes recent normal is
    # observable (an attack in the trailing window would relax the threshold).
    W = STEPS_PER_DAY
    thr_prev, alarms = float(np.quantile(sc_mad, 1.0 - TARGET_FPR)), 0
    for start in range(0, len(sd_mad), W):
        block = sd_mad[start:start + W]
        alarms += int((block > thr_prev).sum())
        if len(block) > 100:
            thr_prev = float(np.quantile(block, 1.0 - TARGET_FPR))
    methods["S5_daily_recal"] = {"calib_fpr": TARGET_FPR, "deploy_fpr": alarms / max(len(sd_mad), 1)}
    for m in methods.values():
        m["transfer_ratio"] = m["deploy_fpr"] / TARGET_FPR
    return {"release": release, "calib_steps": int(len(rcal)), "deploy_steps": int(len(rdep)),
            "target_fpr": TARGET_FPR, "methods": methods}


def main():
    releases = sys.argv[1:] or ["hai-22.04", "hai-21.03", "hai-23.05"]
    results = {}
    for rel in releases:
        print(f"== {rel} ==", flush=True)
        r = run_release(rel)
        results[rel] = r
        for name, m in r["methods"].items():
            print(f"  {name:18s} calib FPR {m['calib_fpr']*100:.3f}%  deploy FPR {m['deploy_fpr']*100:.3f}%  "
                  f"transfer x{m['transfer_ratio']:.2f}", flush=True)
    # aggregate: geomean transfer ratio per method (1.0 = perfect)
    agg = {}
    for name in next(iter(results.values()))["methods"]:
        ratios = [results[r]["methods"][name]["transfer_ratio"] for r in results]
        agg[name] = float(np.exp(np.mean(np.log(np.maximum(ratios, 1e-6)))))
    print("\n== geomean transfer ratio (closer to 1.0 = better; >1 overshoots budget) ==")
    for name, g in sorted(agg.items(), key=lambda kv: abs(np.log(kv[1]))):
        print(f"  {name:18s} x{g:.2f}")
    OUT.write_text(json.dumps({"schema_version": "real-telemetry-calibration-transfer-v1",
                               "date": "2026-10-21", "forecaster": "gbr_big_h12", "target_fa_per_day": TARGET_FA_PER_DAY,
                               "note": "NORMAL data only; false-alarm transfer. Recall on real attacks needs a fresh registered split.",
                               "releases": results, "geomean_transfer_ratio": agg}, indent=1) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
