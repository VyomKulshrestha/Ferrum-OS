"""Corrections to real_telemetry_detect.py (a frozen file; see docs/research/monitor_audit_2026-11-10.md).

real_telemetry_detect.py stays byte-identical because registered verifiers hash it. Only what is wrong
there is overridden here; everything else is re-exported from it.

calibrate   The frozen version scans every candidate threshold and keeps the smallest one whose
            false-episode count is within the budget. Episode counts are not monotone in the threshold
            (a low threshold merges alarms into a few long episodes), so it can return a threshold far
            below the point where the budget is first broken, with a large share of time in alarm. This
            version returns the smallest candidate such that it and every larger candidate meet the budget.

smooth_after_warmup
            The frozen pipeline computes smooth(raw, w) on the whole stream and then blanks the first WARMUP
            steps. core.rolling_mean fills its first w - 1 outputs with the mean of raw[0:w], so the scores
            at steps WARMUP .. w - 2 contain raw values from later steps (up to w - 1 - WARMUP steps ahead)
            and the WARMUP zeros the scorer writes for the warm-up. This version drops the warm-up before
            smoothing and uses a causal expanding mean until w raw values exist. From step WARMUP + w - 1 on
            both versions are identical.
"""
from __future__ import annotations

import numpy as np

from real_telemetry_detect import *  # noqa: F401,F403  (re-export the unchanged parts)
from real_telemetry_detect import WARMUP, episodes


def smooth_after_warmup(raw, w, warmup=WARMUP):
    """Causal trailing mean of raw[warmup:] (expanding until w values exist); NaN during the warm-up."""
    a = np.asarray(raw, np.float64)
    out = np.full(len(a), np.nan)
    v = a[warmup:]
    if not len(v):
        return out
    w = max(int(w), 1)
    c = np.cumsum(v)
    m = np.empty(len(v))
    head = min(w, len(v))
    m[:head] = c[:head] / np.arange(1, head + 1)
    m[head:] = (c[head:] - c[:-head]) / w if len(v) > head else m[head:]
    out[warmup:] = m
    return out


def calibrate(clean_scores, gap, budget_per_day, steps_per_day):
    """Smallest threshold such that it and every larger candidate keep false episodes within the budget."""
    days = sum(len(s) for s in clean_scores) / steps_per_day
    allowed = budget_per_day * days
    pooled = np.concatenate(clean_scores)
    candidates = np.unique(np.quantile(pooled, 1 - np.logspace(-7, -0.7, 300)))
    best = float(pooled.max()) + 1e-9
    for thr in candidates[::-1]:
        count = sum(len(episodes(s > thr, gap)) for s in clean_scores)
        if count > allowed:
            break
        best = float(thr)
    return best
