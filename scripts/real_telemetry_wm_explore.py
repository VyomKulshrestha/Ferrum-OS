#!/usr/bin/env python3
"""Development-only world-model method exploration on real HAI telemetry.

Goal: find a forecaster that predicts the plant's normal dynamics better than the
current ridge + gradient-boosted-residual baseline, measured ONLY on held-out
NORMAL validation data (HAI train5-6). No attack/test data is read. Lower
multi-step MAE (robust-scaled units) => a better world model.

Reuses scripts/real_telemetry_core.py unchanged (its Forecaster is parameterised
by history, ridge alpha, and the LightGBM `gbr` dict, so most variants need no
new code). Adds one new technology: a small MLP forecaster.

Usage: python scripts/real_telemetry_wm_explore.py [max_rows]
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
from sklearn.neural_network import MLPRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C
import real_telemetry_dev as dev

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "target" / "real-telemetry" / "wm_explore_hai.json"
HORIZONS = (1, 5)
HISTORY = 3


class MLPForecaster:
    """Same causal features and direct per-horizon target as C.Forecaster, but a
    small MLP instead of ridge+boosting. Matches the (fit, predict) interface."""

    def __init__(self, horizons, history=3, use_actions=True, hidden=(128, 64), seed=0, max_iter=60):
        self.horizons, self.history, self.use_actions = list(horizons), history, use_actions
        self.hidden, self.seed, self.max_iter = hidden, seed, max_iter

    def _design(self, Z, V, t, h):
        base = C.features(Z, V if self.use_actions else None, t, self.history)
        if self.use_actions and V is not None:
            base = np.concatenate([base, V[t + h] - V[t]], 1)
        return base

    def fit(self, segments, max_rows=120_000):
        rng = np.random.default_rng(self.seed)
        self.net = {}
        for h in self.horizons:
            pools = [C.valid_index(len(Z), self.history, h) for Z, _ in segments]
            total = sum(len(p) for p in pools)
            keep = max_rows / total if total > max_rows else 1.0
            rows, tgts = [], []
            for (Z, V), pool in zip(segments, pools):
                t = np.sort(rng.choice(pool, max(1, int(len(pool) * keep)), replace=False)) if keep < 1 else pool
                rows.append(self._design(Z, V, t, h))
                tgts.append(Z[t + h] - Z[t])
            A, B = np.concatenate(rows), np.concatenate(tgts)
            net = MLPRegressor(hidden_layer_sizes=self.hidden, activation="relu", solver="adam",
                               alpha=1e-4, batch_size=512, learning_rate_init=1e-3, max_iter=self.max_iter,
                               early_stopping=True, n_iter_no_change=6, random_state=self.seed)
            net.fit(A, B)
            self.net[h] = net
        return self

    def predict(self, Z, V, t, h, chunk=50_000):
        out = np.empty((len(t), Z.shape[1]), np.float32)
        for i in range(0, len(t), chunk):
            part = t[i:i + chunk]
            out[i:i + chunk] = Z[part] + self.net[h].predict(self._design(Z, V, part, h))
        return out


def build_val_eval(val, horizons, max_eval=40_000, seed=7, hist_floor=8):
    """Fixed, seeded subsample of validation indices per horizon (hist_floor lets
    models of any history up to hist_floor predict at the same points)."""
    rng = np.random.default_rng(seed)
    plan = {}
    for h in horizons:
        pools = [(i, C.valid_index(len(Z), hist_floor, h)) for i, (Z, _) in enumerate(val)]
        total = sum(len(p) for _, p in pools)
        keep = max_eval / total if total > max_eval else 1.0
        plan[h] = [(i, np.sort(rng.choice(p, max(1, int(len(p) * keep)), replace=False)) if keep < 1 else p)
                   for i, p in pools]
    return plan


def eval_mae(model, val, plan, h):
    total, count = 0.0, 0
    for i, t in plan[h]:
        Z, V = val[i]
        err = np.abs(model.predict(Z, V, t, h) - Z[t + h])
        total += float(err.sum())
        count += err.size
    return total / max(count, 1)


def ridge_gbr(history, gbr, use_actions=True, alpha=1.0):
    return lambda: C.Forecaster(HORIZONS, history, alpha=alpha, use_actions=use_actions, gbr=gbr)


class PerHorizonHistory:
    """A separate Forecaster per horizon so each horizon uses its own history
    length (short history is best for H1, long history for H5)."""

    def __init__(self, hist_by_h, gbr, use_actions=True):
        self.hist_by_h = hist_by_h
        self.models = {h: C.Forecaster([h], hh, use_actions=use_actions, gbr=gbr) for h, hh in hist_by_h.items()}
        self.history = max(hist_by_h.values())

    def fit(self, segments, max_rows=80_000):
        for m in self.models.values():
            m.fit(segments, max_rows=max_rows)
        return self

    def predict(self, Z, V, t, h):
        return self.models[h].predict(Z, V, t, h)


CONFIGS = {
    # reproduce the current selected model (baseline to beat)
    "baseline_ridge_gbr_h3": ridge_gbr(3, dict(n_estimators=60, num_leaves=31, learning_rate=0.1,
                                               min_child_samples=100, subsample=0.8, subsample_freq=1)),
    # more / deeper boosting, lower learning rate
    "gbr_big_h3": ridge_gbr(3, dict(n_estimators=200, num_leaves=63, learning_rate=0.05,
                                    min_child_samples=100, subsample=0.8, subsample_freq=1, colsample_bytree=0.8)),
    # longer history context
    "gbr_big_h5": ridge_gbr(5, dict(n_estimators=200, num_leaves=63, learning_rate=0.05,
                                    min_child_samples=100, subsample=0.8, subsample_freq=1, colsample_bytree=0.8)),
    "gbr_big_h8": ridge_gbr(8, dict(n_estimators=200, num_leaves=63, learning_rate=0.05,
                                    min_child_samples=100, subsample=0.8, subsample_freq=1, colsample_bytree=0.8)),
    # robust (Huber) boosting objective - less sensitive to spiky sensors
    "gbr_huber_h5": ridge_gbr(5, dict(n_estimators=200, num_leaves=63, learning_rate=0.05, objective="huber",
                                      min_child_samples=100, subsample=0.8, subsample_freq=1)),
    # longer-context linear only (is context or nonlinearity the win?)
    "ridge_h8": ridge_gbr(8, None),
    # new technology: small MLP
    "mlp_h3": lambda: MLPForecaster(HORIZONS, 3, hidden=(128, 64)),
    "mlp_h5": lambda: MLPForecaster(HORIZONS, 5, hidden=(192, 96)),
}


_BIG = dict(n_estimators=200, num_leaves=63, learning_rate=0.05, min_child_samples=100,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.8)
_HUBER = dict(_BIG, objective="huber")
CONFIGS2 = {
    "baseline_ridge_gbr_h3": CONFIGS["baseline_ridge_gbr_h3"],
    "gbr_big_h8": ridge_gbr(8, _BIG),
    "gbr_big_h12": ridge_gbr(12, _BIG),
    "gbr_huber_h8": ridge_gbr(8, _HUBER),
    "hybrid_h3_h8": lambda: PerHorizonHistory({1: 3, 5: 8}, _BIG),
    "hybrid_h3_h8_huber": lambda: PerHorizonHistory({1: 3, 5: 8}, _HUBER),
}


CONFIGS3 = {  # map the history-length knee
    "baseline_ridge_gbr_h3": CONFIGS["baseline_ridge_gbr_h3"],
    "gbr_big_h12": ridge_gbr(12, _BIG),
    "gbr_big_h16": ridge_gbr(16, _BIG),
    "gbr_big_h20": ridge_gbr(20, _BIG),
}


def main():
    args = sys.argv[1:]
    nums = [a for a in args if a.isdigit()]
    max_rows = int(nums[0]) if nums else 80_000
    configs = CONFIGS3 if "round3" in args else CONFIGS2 if "round2" in args else CONFIGS
    parts = dev.hai_partitions()
    fit, val = parts["fit"], parts["val"]
    plan = build_val_eval(val, HORIZONS)
    n_eval = {h: sum(len(t) for _, t in plan[h]) for h in HORIZONS}
    print(f"HAI dev: fit {sum(len(z) for z,_ in fit)} rows, val {sum(len(z) for z,_ in val)} rows, "
          f"{len(parts['sensors'])} sensors, {len(parts['actions'])} actions, max_rows={max_rows}, "
          f"val_eval_pts {n_eval}", flush=True)
    results = {}
    base = None
    for name, make in configs.items():
        t0 = time.time()
        model = make()
        try:
            model.fit(fit, max_rows=max_rows)
        except TypeError:
            model.fit(fit)
        mae = {f"H{h}": float(eval_mae(model, val, plan, h)) for h in HORIZONS}
        results[name] = {"val_mae": mae, "seconds": round(time.time() - t0, 1)}
        if name.startswith("baseline"):
            base = mae
        delta = ""
        if base and not name.startswith("baseline"):
            d1 = 100 * (base["H1"] - mae["H1"]) / base["H1"]
            d5 = 100 * (base["H5"] - mae["H5"]) / base["H5"]
            delta = f"  vs baseline: H1 {d1:+.1f}%  H5 {d5:+.1f}%"
            results[name]["pct_vs_baseline"] = {"H1": d1, "H5": d5}
        print(f"  {name:24s} H1 {mae['H1']:.5f}  H5 {mae['H5']:.5f}  ({results[name]['seconds']}s){delta}", flush=True)
    OUT.write_text(json.dumps({"dataset": "hai", "baseline": "baseline_ridge_gbr_h3", "max_rows": max_rows,
                               "results": results}, indent=1) + "\n", encoding="utf-8")
    # honest winner summary
    best5 = min(results, key=lambda k: results[k]["val_mae"]["H5"])
    print(f"\nbest H5: {best5} ({results[best5]['val_mae']['H5']:.5f}); "
          f"baseline H5 {results['baseline_ridge_gbr_h3']['val_mae']['H5']:.5f}", flush=True)


if __name__ == "__main__":
    main()
