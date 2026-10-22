#!/usr/bin/env python3
"""FerrumOS real-telemetry world model v2 (the converged feat_h12_w24 forecaster).

This is the improved forecaster found by scripts/real_telemetry_wm_explore.py
(docs/research/real_telemetry_world_model_exploration_v1.json): ridge + per-horizon
LightGBM residual corrections, action-conditioned, history 12, plus engineered
features (per-sensor rolling mean/std and rate-of-change over a 24-step window).
On held-out NORMAL HAI validation it cuts 5-step MAE ~12% and 1-step ~4.5% over
the rt1/rt2 baseline.

It is a thin subclass of the registered real_telemetry_core.Forecaster (which is
FROZEN for rt1/rt2 and is NOT modified or retrained here). This module is not yet
part of any published result; it is staged for a future registered evaluation on
FRESH attack data (docs/research/real_telemetry_detection_protocol_v2.json).

CLI:
  python scripts/real_telemetry_wm_v2.py fit hai-22.04 [--save PATH]   # sanity-fit + val MAE
"""
from __future__ import annotations

import argparse
import pickle
import time
from pathlib import Path

import numpy as np

import real_telemetry_core as C

HISTORY = 12
WINDOW = 24
HORIZONS = (1, 5)
GBR = dict(n_estimators=200, num_leaves=63, learning_rate=0.05, min_child_samples=100,
           subsample=0.8, subsample_freq=1, colsample_bytree=0.8)


class WorldModelV2(C.Forecaster):
    """Action-conditioned ridge + GBR-residual forecaster with a longer history
    and rolling summary features. Rolling offsets are clamped at the segment
    start (padding with the first sample), matching core's short-prefix rule,
    so the design matrix is always in-bounds."""

    def __init__(self, horizons=HORIZONS, history=HISTORY, window=WINDOW, alpha=1.0,
                 use_actions=True, gbr=None, seed=0):
        super().__init__(horizons, history, alpha=alpha, use_actions=use_actions,
                         gbr=GBR if gbr is None else gbr, seed=seed)
        self.window = window

    def _extra(self, Z, t):
        w = self.window
        idx = np.maximum(t[:, None] - np.arange(w)[None, :], 0)   # (N, w), clamped at 0
        stack = Z[idx]                                            # (N, w, d)
        mean = stack.mean(1)
        std = stack.std(1)
        rate = Z[t] - Z[np.maximum(t - (w - 1), 0)]
        return np.concatenate([mean, std, rate], 1).astype(np.float32)

    def _design(self, Z, V, t, h):
        return np.concatenate([super()._design(Z, V, t, h), self._extra(Z, t)], 1)


def build(**kw) -> WorldModelV2:
    """The recommended v2 forecaster."""
    return WorldModelV2(**kw)


def save(model: WorldModelV2, path: Path) -> None:
    Path(path).write_bytes(pickle.dumps(model))


def load(path: Path) -> WorldModelV2:
    return pickle.loads(Path(path).read_bytes())


def _sanity_fit(release: str, save_path: str | None, max_rows: int) -> None:
    """Fit on a release's NORMAL train data, split fit/val by time, print val MAE.
    Uses only normal train data (no attack/test files)."""
    import real_telemetry_data as D
    import real_telemetry_rt2 as RT2

    if release == "hai-22.04":
        segs = [(s.X, s.U) for s in D.hai_train()["segments"]]
    else:
        segs = [(x, u) for x, u in RT2.train_segments(release)[0]]
    total = sum(len(x) for x, _ in segs)
    cut = int(total * 0.8)
    fit, val, off = [], [], 0
    for x, u in segs:
        a, z = off, off + len(x)
        for name, lo, hi in (("fit", 0, cut), ("val", cut, total)):
            s, e = max(a, lo), min(z, hi)
            if e - s > WINDOW + 10:
                (fit if name == "fit" else val).append((x[s - a:e - a], u[s - a:e - a]))
        off = z
    xs = C.Scaler().fit(np.concatenate([x for x, _ in fit]))
    us = C.Scaler().fit(np.concatenate([u for _, u in fit]))
    pack = lambda g: [(xs(x), us(u)) for x, u in g]
    t0 = time.time()
    model = build().fit(pack(fit), max_rows=max_rows)
    vp = pack(val)
    mae = {f"H{h}": round(float(C.forecast_error(model, vp, h)), 5) for h in HORIZONS}
    print(f"{release}: WorldModelV2 fit {sum(len(x) for x,_ in fit)} rows, val MAE {mae} ({round(time.time()-t0)}s)")
    if save_path:
        save(model, Path(save_path))
        print(f"saved fitted model + scalers context to {save_path} "
              f"(note: re-scale inputs with the same robust scaler at inference)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit"])
    ap.add_argument("release")
    ap.add_argument("--save")
    ap.add_argument("--max-rows", type=int, default=40_000)
    a = ap.parse_args()
    if a.cmd == "fit":
        _sanity_fit(a.release, a.save, a.max_rows)


if __name__ == "__main__":
    main()
