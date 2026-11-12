#!/usr/bin/env python3
"""fi1 pipeline audit: does the gpd_mle cold-start cap bind on the spot_gr initial fits of tt1d TEP?

threshold_rules_tt1c.gpd_mle searches theta = xi / sigma up to 1000 / mean(y) when it has no warm start, and
SpotGR's first fit (on the calibration peaks) is always cold. The first audit left open whether the cap ever
binds on a reported number. This compares the cold fit with scipy's maximum likelihood on the attack-free
calibration pools of every Tennessee Eastman mode, cached by the tt1f round (development data; no attack or
sealed array is read). Output: target/real-telemetry/fi1/pipeline/gpd_cold_check.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import genpareto

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import threshold_rules_ext as E  # noqa: E402
import threshold_rules_tt1c as N  # noqa: E402
import repro_env  # noqa: E402


def nll(y, xi, sigma):
    return float(-genpareto.logpdf(y, xi, 0, sigma).sum())


def main():
    rows = []
    for m in range(7):
        pooled = np.load(ROOT / f"target/real-telemetry/tt1f/mode_{m}.npz")["pooled"]
        pooled = pooled[np.isfinite(pooled)]
        t = float(np.quantile(pooled, E.SPOT_LEVEL))
        y = pooled[pooled > t] - t
        xi, sg, th = N.gpd_mle(y)
        c, _, sc = genpareto.fit(y, floc=0)
        rows.append(
            {
                "mode": m,
                "peaks": int(len(y)),
                "cold_xi": float(xi),
                "cold_sigma": float(sg),
                "theta_over_cap": float(th * y.mean() / 1000),
                "scipy_xi": float(c),
                "scipy_sigma": float(sc),
                "nll_cold": nll(y, xi, sg),
                "nll_scipy": nll(y, c, sc),
            }
        )
        print(rows[-1], flush=True)
    out = ROOT / "target/real-telemetry/fi1/pipeline/gpd_cold_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    repro_env.stamp_json(out)


if __name__ == "__main__":
    repro_env.pin_from_environment()
    main()
