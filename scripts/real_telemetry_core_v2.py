"""Corrections to real_telemetry_core.py (a frozen file; fi1 pipeline audit,
docs/research/fi1_reports/pipeline_round1.md).

rolling_mean() accumulates a cumulative sum in the input dtype and differences it. For float32 input the
running sum grows with the stream and its rounding error does too: on |N(0,1)| scores the error of a
10-step mean is about 0.003 after 1e5 steps and 0.025 after 1e6 steps (3 % of the mean value), and it is
largest at the end of long streams. real_telemetry_detect.Scorer.raw passes float32 residual scores to it
for the D2/D3 classifier features (the D1 path goes through smooth(), which casts to float64 first).
rolling_mean() here accumulates in float64 and returns the input dtype; the warm-up head (the first w - 1
outputs repeat the first full mean) is kept as it was, see real_telemetry_detect_v2.smooth_after_warmup for
that separate issue.
"""

from __future__ import annotations

import numpy as np


def paired_event_bootstrap(
    found_a, found_b, reps=10_000, level=0.95, seed=0, undefined="zero"
):
    """real_telemetry_core.paired_event_bootstrap with the 0/0 case made explicit.

    The relative miss reduction 1 - miss_b / miss_a is undefined in a resample where the baseline a misses no
    event. The frozen function scores such a resample as 0.0 ("no reduction"); with undefined="zero" this
    function reproduces it exactly (same resamples, same seed). undefined="drop" takes the interval over the
    defined resamples only. Both return undefined_share, the fraction of resamples where a misses nothing:
    when it exceeds the tail (1 - level) / 2, the lower end of the "zero" interval is 0.0 by convention
    alone. This decides rt2's D1-versus-DR comparison on HAI 21.03 (DR 46/50, D1 50/50, 98.75 % interval,
    undefined share 0.0167 > 0.00625): [0.0, 1.0] under "zero", [1.0, 1.0] under "drop"."""
    a, b = np.asarray(found_a, float), np.asarray(found_b, float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), (reps, len(a)))
    diff = b[idx].mean(1) - a[idx].mean(1)
    miss_a = 1 - a[idx].mean(1)
    defined = miss_a > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        reduction = np.where(defined, 1 - (1 - b[idx].mean(1)) / miss_a, 0.0)
    q = [(1 - level) / 2, 1 - (1 - level) / 2]
    point_red = 1 - (1 - b.mean()) / (1 - a.mean()) if a.mean() < 1 else 0.0
    pool = reduction if undefined == "zero" else reduction[defined]
    interval = (
        [float(x) for x in np.quantile(pool, q)]
        if len(pool)
        else [float("nan"), float("nan")]
    )
    return {
        "recall_difference": float(b.mean() - a.mean()),
        "recall_difference_interval": [float(x) for x in np.quantile(diff, q)],
        "miss_reduction": float(point_red),
        "miss_reduction_interval": interval,
        "undefined_share": float(1 - defined.mean()),
    }


def rolling_mean(a, w):
    if w <= 1:
        return a
    a = np.asarray(a)
    c = np.cumsum(
        np.concatenate([np.zeros((1,) + a.shape[1:]), a.astype(np.float64)]), 0
    )
    out = (c[w:] - c[:-w]) / w
    out = np.concatenate([np.repeat(out[:1], w - 1, 0), out])
    return out.astype(a.dtype) if np.issubdtype(a.dtype, np.floating) else out
