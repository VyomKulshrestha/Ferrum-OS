#!/usr/bin/env python3
"""EXPLORATORY forecasting-only GPU test: temporal JEPA vs multivariate ridge on
real HAI 86-channel telemetry, NORMAL data only.

Motivation: on the low-dimensional abstract simulators the GPU neural world model
loses badly to ridge/GBR (incident-dynamics). The open question is whether a GPU
neural model wins on HIGH-dimensional real telemetry by exploiting cross-channel
structure the per-signal ridge cannot. This measures single-step signal-forecast
MAE on held-out NORMAL HAI data -- no attack labels, no test1/test2, nothing
sealed or frozen is touched. It reuses the model code in
scripts/train_physical_hai_temporal.py (fit_signal_ridge / fit_signal_jepa /
signal_residuals), bypassing that script's detection-selection and sealing path.

NOT a registered result and NOT a detection claim (forecast gains did not transfer
to detection in the ridge world; see docs/research/real_telemetry_detection_v2_retrospective.json).

Usage: python scripts/hai_forecast_jepa_vs_ridge.py [release]   # default hai-23.05
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_physical_hai_temporal as T

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/real_telemetry_hai_forecast_jepa_vs_ridge.json"
JEPA_GRID = [dict(latent=64, hidden=128, seed=42), dict(latent=96, hidden=192, seed=91)]
JEPA_EPOCHS = 40


def load_normal(release):
    """Normal HAI train traces as T.SignalData (values only; timestamps not used by
    the models). Fit = train1-3, held-out normal eval = train4."""
    raw = ROOT / "target/real-telemetry/raw" / release
    names = sorted(p for p in raw.glob("*train*.csv"))
    if not names:
        raise SystemExit(f"no train CSVs in {raw}")
    traces = []
    for p in names:
        frame = pd.read_csv(p)
        frame.columns = [c.strip() for c in frame.columns]
        cols = [c for c in frame.columns if c.lower() not in ("timestamp", "attack", "label")]
        values = frame[cols].to_numpy(np.float32)
        values = values[:, np.isfinite(values).all(0)]   # drop any all-NaN/constant-NaN cols
        ts = np.arange(len(values)).astype("datetime64[s]")   # dummy; models use values only
        traces.append((p.name, T.SignalData(values, ts, p.name)))
    fit = [t for n, t in traces[:-1]]
    hold = traces[-1][1]
    return fit, hold, fit[0].values.shape[1]


def mae(model, trace, center, scale):
    r = T.signal_residuals(model, trace, center, scale)   # |target - pred| per step per signal
    return float(r.mean()), r.mean(0)                     # overall, per-signal


def main():
    release = sys.argv[1] if len(sys.argv) > 1 else "hai-23.05"
    fit, hold, n_sig = load_normal(release)
    center, scale = T.fit_signal_normalizer(fit)
    print(f"{release}: fit {sum(len(t.values) for t in fit)} rows, held-out {len(hold.values)} rows, {n_sig} signals", flush=True)

    t0 = time.time()
    ridge = T.fit_signal_ridge(fit, center, scale)
    ridge_mae, ridge_per = mae(ridge, hold, center, scale)
    print(f"  ridge        held-out MAE {ridge_mae:.5f}  ({round(time.time()-t0)}s)", flush=True)

    results = {"ridge": {"held_out_mae": ridge_mae}}
    for cfg in JEPA_GRID:
        t1 = time.time()
        jm = T.fit_signal_jepa(fit, center, scale, cfg["latent"], cfg["hidden"], cfg["seed"], JEPA_EPOCHS)
        j_mae, j_per = mae(jm, hold, center, scale)
        win = float(np.mean(j_per < ridge_per))   # fraction of signals JEPA forecasts better
        impr = 100 * (ridge_mae - j_mae) / ridge_mae
        results[jm["name"]] = {"held_out_mae": j_mae, "pct_vs_ridge": impr,
                               "signal_win_fraction_vs_ridge": win, "seconds": round(time.time() - t1)}
        print(f"  {jm['name']:28s} held-out MAE {j_mae:.5f}  ({impr:+.1f}% vs ridge, "
              f"wins {win*100:.0f}% of signals)  ({round(time.time()-t1)}s)", flush=True)

    best = min((k for k in results if k != "ridge"), key=lambda k: results[k]["held_out_mae"], default=None)
    verdict = ("JEPA beats ridge" if best and results[best]["held_out_mae"] < ridge_mae
               else "ridge wins (neural does not beat it)")
    doc = {"schema_version": "hai-forecast-jepa-vs-ridge-exploratory", "status": "EXPLORATORY-forecasting-only-normal-data",
           "release": release, "n_signals": n_sig, "jepa_epochs_max": JEPA_EPOCHS,
           "disclaimer": "Forecasting-only (single-step signal MAE) on NORMAL data; no attack/test/sealed data. "
                         "Not a detection claim and not a registered result.",
           "verdict": verdict, "results": results}
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"\nverdict: {verdict}\nwrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
