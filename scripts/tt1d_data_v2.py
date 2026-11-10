"""Corrections to tt1d_data.py (a frozen file; see docs/research/monitor_audit_2026-11-10.md).

ProvICS validity after a recording gap. _p_grid marks only the grid steps inside a gap longer than 10 s as
invalid; it forward-fills them with the last row before the gap. The scores read the past: a D1 residual at
step r uses the forecast made at r - h from the states r - h - (history - 1) .. r - h, and the smoothed score
at step s averages the raw scores s - w + 1 .. s. So for w + h + history - 2 steps after the last filled step
the score still compares real data with forecasts made from forward-filled values (a level change during the
gap appears as a residual spike) and can alarm on steps marked valid. extend_invalid() marks those steps
invalid as well; provics_valid_v2() is the mask to pass to tt1d_final.clean().
"""
from __future__ import annotations

import numpy as np

from tt1d_data import *  # noqa: F401,F403  (re-export the unchanged loaders)

HISTORY, MAX_HORIZON = 3, 5          # real_telemetry_dev.HISTORY and max(real_telemetry_dev.HORIZONS)


def score_lookback(window, history=HISTORY, horizon=MAX_HORIZON):
    """Steps after the last filled step whose smoothed D1 score still depends on a filled step."""
    return int(window) + int(horizon) + int(history) - 2


def extend_invalid(valid, lookback):
    """Mark `lookback` steps after every invalid run invalid as well (the stream start is not a gap)."""
    valid = np.asarray(valid, bool)
    out = valid.copy()
    ends = np.flatnonzero(~valid[:-1] & valid[1:]) + 1          # first valid step after an invalid run
    for e in ends:
        out[e:e + lookback] = False
    return out


def provics_valid_v2(valid, window):
    return extend_invalid(valid, score_lookback(window))
