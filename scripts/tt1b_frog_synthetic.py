#!/usr/bin/env python3
"""tt1b development: the closed-loop frog on light-tailed synthetic scores (control for the tail effect).

Real D1 scores have heavy tails, and SPOT's threshold ran away under the closed-loop frog on them. This
runs the same attacker (tt1b_frog_dev.play) on a synthetic score with a light tail: the 60-step moving
average of |N(0, 1)|, for calibration (60,000 steps) and a stream of 250,000 steps, tau0 at the 99.95th
calibration percentile, p = 5e-4. Five seeds; campaign variants as in tt1b_frog_dev.
Writes docs/research/threshold_transfer_tt1b_frog_synthetic_v1.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tt1b_frog_dev as G

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/threshold_transfer_tt1b_frog_synthetic_v1.json"
RULES = ["frozen", "spot", "spot_mle", "dspot"]
SEEDS = (1, 2, 3, 4, 5)


def stream(rng, n):
    return np.convolve(np.abs(rng.standard_normal(n)), np.ones(60) / 60, mode="same")


def main():
    rows = {f"{m}_{d // 3600}h": {r: {"after": [], "control": [], "inflation": []} for r in RULES} for m, d in G.VARIANTS}
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        calib, s = stream(rng, 60000), stream(rng, 250000)
        tau0 = float(np.quantile(calib, 0.9995))
        m0 = float(np.median(calib))
        cfg = {"tau0": tau0, "tau_half": tau0, "p": 5e-4, "eta": 0.01 * float(np.quantile(calib, 0.999) - m0), "m0": m0}
        c0 = 43200
        end = c0 + G.CAMPAIGN + G.LEAD
        for r in RULES:
            hit_c, _, _ = G.play(r, cfg, calib, s, c0, end, False)
            for mode, length in G.VARIANTS:
                hit, infl, _ = G.play(r, cfg, calib, s, c0, end, True, mode, length)
                o = rows[f"{mode}_{length // 3600}h"][r]
                o["after"].append(hit); o["control"].append(hit_c); o["inflation"].append(infl)
    out = {"schema_version": "threshold-transfer-tt1b-frog-synthetic-v1",
           "status": "development control on synthetic light-tailed scores (no recorded data)",
           "score": "60-step moving average of |N(0,1)|; calibration 60,000 steps, stream 250,000 steps; tau0 = calibration 99.95th percentile; p = 5e-4",
           "seeds": list(SEEDS),
           "variants": {k: {r: {"terminal_after_campaign": float(np.mean(o["after"])), "terminal_control": float(np.mean(o["control"])),
                                "median_inflation": float(np.median(o["inflation"])), "max_inflation": float(np.max(o["inflation"]))}
                            for r, o in v.items()} for k, v in rows.items()}}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for k, v in out["variants"].items():
        print(k, {r: f"{m['terminal_after_campaign']:.1f}/{m['terminal_control']:.1f} x{m['median_inflation']:.3f} (max {m['max_inflation']:.3f})" for r, m in v.items()})


if __name__ == "__main__":
    main()
