"""Threshold rules of the tt1g exploratory round: rules from alarm practice and recalibration as a rule.

Plan: docs/research/threshold_transfer_tt1g_dev_plan.md. Every rule is an online model with tau() and
update(x, flag=False); flag marks a step that an oracle knows to be attacked (only RecalOracle reads it).

  MedianMad    tau = m + k s over the last day of scores, recomputed every hour (m median, s median absolute
               deviation); learns from the bulk of the scores
  Ewma         tau = mu + L sigma, exponentially weighted mean and standard deviation, half-life one day;
               with exclude=True, steps on which the rule alarms do not update it
  OnDelay      fixed threshold that alarms only after `delay` consecutive steps above it; no learning
  Recal        the frozen threshold, recalibrated at the end of a day on that day's scores if the day is
               accepted: mode "quiet" (no alarm episode of event length or longer) or "oracle" (no flagged step)
"""
from __future__ import annotations

from collections import deque

import numpy as np

import real_telemetry_detect_v2 as R2


class MedianMad:
    def __init__(self, init, k, steps_per_day, refresh):
        self.buf = deque(np.asarray(init, float)[-steps_per_day:], maxlen=steps_per_day)
        self.k, self.refresh, self.n = k, refresh, 0
        self._fit()

    def _fit(self):
        a = np.fromiter(self.buf, float, len(self.buf))
        self.m = float(np.median(a))
        self.s = float(np.median(np.abs(a - self.m))) + 1e-12

    def tau(self):
        return self.m + self.k * self.s

    def update(self, x, flag=False):
        if np.isfinite(x):
            self.buf.append(x)
        self.n += 1
        if self.n % self.refresh == 0:
            self._fit()


class Ewma:
    def __init__(self, init, L, half_life, exclude=False):
        init = np.asarray(init, float)
        self.mu, self.var = float(init.mean()), float(init.var()) + 1e-12
        self.L, self.alpha, self.exclude = L, 1.0 - 0.5 ** (1.0 / half_life), exclude

    def sigma(self):
        return self.var ** 0.5

    def tau(self):
        return self.mu + self.L * self.sigma()

    def update(self, x, flag=False):
        if not np.isfinite(x) or (self.exclude and x > self.tau()):
            return
        d = x - self.mu
        self.mu += self.alpha * d
        self.var = (1.0 - self.alpha) * (self.var + self.alpha * d * d)


class OnDelay:
    def __init__(self, threshold, delay):
        self.thr, self.need, self.run = threshold, delay - 1, 0

    def tau(self):
        return self.thr if self.run >= self.need else np.inf

    def update(self, x, flag=False):
        self.run = self.run + 1 if x > self.thr else 0


class Recal:
    def __init__(self, tau0, mode, steps_per_day, gap, event_l, budget, pool=None):
        self.t, self.mode, self.spd, self.gap, self.event_l, self.budget = tau0, mode, steps_per_day, gap, event_l, budget
        # pool (amendment 1 of the plan): calibration runs to which every accepted day is added; the threshold
        # is then recalibrated on the whole pool instead of on the one day
        self.pool = None if pool is None else list(pool)
        self.day, self.n, self.bad = [], 0, False
        self.first, self.last = None, None                 # the running alarm episode
        self.accepted, self.days = 0, 0

    def tau(self):
        return self.t

    def update(self, x, flag=False):
        if np.isfinite(x):
            self.day.append(x)
        if x > self.t:
            if self.last is None or self.n - self.last > self.gap + 1:
                self.first = self.n
            self.last = self.n
            if self.mode == "quiet" and self.n - self.first + 1 >= self.event_l:
                self.bad = True
        if self.mode == "oracle" and flag:
            self.bad = True
        self.n += 1
        if self.n % self.spd == 0:
            self.days += 1
            if not self.bad and len(self.day) > self.spd // 2:
                day = np.asarray(self.day, float)
                if self.pool is None:
                    self.t = R2.calibrate([day], self.gap, self.budget, self.spd)
                else:
                    self.pool.append(day)
                    self.t = R2.calibrate(self.pool, self.gap, self.budget, self.spd)
                self.accepted += 1
            self.day, self.bad = [], False


def rolling_min(a, d):
    """min of the last d values at each step (-inf while fewer than d values exist)."""
    a = np.asarray(a, float)
    out = np.full(len(a), -np.inf)
    if len(a) >= d:
        out[d - 1:] = np.lib.stride_tricks.sliding_window_view(a, d).min(axis=1)
    return out
