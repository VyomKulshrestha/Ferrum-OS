"""Corrections to threshold_online.py (a frozen file; see docs/research/monitor_audit_2026-11-10.md).

Daily       The frozen online rule keeps a deque of the last steps_per_day FINITE scores and never clears it,
            so after a stretch of invalid (-inf / NaN) steps the "trailing day" reaches back into the previous
            day. Its own docstring and the batch reference threshold_rules.daily_path use the finite scores of
            the trailing day only. This version buffers one day at a time and keeps the old threshold when a
            day has no finite score.
make        threshold_online.make with Daily replaced.
"""
from __future__ import annotations

import numpy as np

import threshold_online as O
from threshold_online import *  # noqa: F401,F403  (re-export the unchanged rules)


class Daily:
    def __init__(self, cfg, steps_per_day):
        self.t, self.p, self.spd, self.n = cfg["tau0"], cfg["p"], steps_per_day, 0
        self.buf = []

    def tau(self):
        return self.t

    def update(self, x):
        self.n += 1
        if np.isfinite(x):
            self.buf.append(x)
        if self.n % self.spd == 0:
            if self.buf:
                self.t = float(np.quantile(np.asarray(self.buf, float), 1 - self.p))
            self.buf = []


def make(rule, cfg, calib, steps_per_day, depth, refit):
    if rule == "daily":
        return Daily(cfg, steps_per_day)
    return O.make(rule, cfg, calib, steps_per_day, depth, refit)
