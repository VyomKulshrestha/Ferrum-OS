"""Online (step-by-step) versions of the threshold rules, for closed-loop attackers that read tau_t.

Each rule exposes tau() (the threshold for the next value) and update(x). With no attacker they reproduce
threshold_rules / threshold_rules_ext exactly (checked against the batch paths). Time-scale settings are
explicit: steps_per_day for daily recalibration, depth for DSPOT's moving mean, refit for maximum-
likelihood SPOT.
"""
from __future__ import annotations

from collections import deque

import numpy as np

import threshold_rules_ext as E


class Static:
    def __init__(self, tau): self.t = tau
    def tau(self): return self.t
    def update(self, x): pass


class Tracker:
    def __init__(self, cfg, eta): self.q, self.eta, self.p = cfg["tau0"], eta, cfg["p"]
    def tau(self): return self.q
    def update(self, x): self.q += self.eta * ((1.0 if x > self.q else 0.0) - self.p)


class TightenOnly(Tracker):
    def __init__(self, cfg, eta): super().__init__(cfg, eta); self.ceiling = cfg["tau0"]
    def tau(self): return min(self.ceiling, self.q)


class Daily:
    def __init__(self, cfg, steps_per_day):
        self.t, self.p, self.spd, self.n = cfg["tau0"], cfg["p"], steps_per_day, 0
        self.buf = deque(maxlen=steps_per_day)
    def tau(self): return self.t
    def update(self, x):
        self.n += 1
        if np.isfinite(x):
            self.buf.append(x)
        if self.n % self.spd == 0:
            self.t = float(np.quantile(np.fromiter(self.buf, float), 1 - self.p))


class Spot:
    def __init__(self, cfg, calib):
        self.q = cfg["p"]
        self.t, self.s1, self.s2, self.nt, self.k, g, sg = E._init(calib, self.q, E.SPOT_LEVEL)
        self.z = E._zq(self.t, g, sg, self.q, self.k, self.nt)
    def tau(self): return self.z
    def update(self, x):
        if not np.isfinite(x) or x > self.z:
            return
        self.k += 1
        if x > self.t:
            y = x - self.t
            self.s1, self.s2, self.nt = self.s1 + y, self.s2 + y * y, self.nt + 1
            g, sg = E._gpd(self.s1, self.s2, self.nt)
            self.z = E._zq(self.t, g, sg, self.q, self.k, self.nt)


class SpotMLE:
    def __init__(self, cfg, calib, refit):
        self.q, self.refit = cfg["p"], refit
        self.t = float(np.quantile(calib, E.SPOT_LEVEL))
        self.peaks = list(calib[calib > self.t] - self.t)
        self.k = len(calib)
        self.g, self.sg = E._mle(self.peaks)
        self.fitted = len(self.peaks)
        self.z = E._zq(self.t, self.g, self.sg, self.q, self.k, len(self.peaks))
    def tau(self): return self.z
    def update(self, x):
        if not np.isfinite(x) or x > self.z:
            return
        self.k += 1
        if x > self.t:
            self.peaks.append(x - self.t)
            if len(self.peaks) - self.fitted >= self.refit:
                self.g, self.sg = E._mle(self.peaks)
                self.fitted = len(self.peaks)
            self.z = E._zq(self.t, self.g, self.sg, self.q, self.k, len(self.peaks))


class DSpot(Spot):
    def __init__(self, cfg, calib, depth):
        self.depth = depth
        csum = np.concatenate([[0.0], np.cumsum(calib)])
        super().__init__(cfg, calib[depth:] - (csum[depth:-1] - csum[:-depth - 1]) / depth)
        self.win = deque(calib[-depth:].tolist())
        self.msum = float(sum(self.win))
    def tau(self): return self.msum / self.depth + self.z
    def update(self, x):
        if not np.isfinite(x):
            return
        m = self.msum / self.depth
        if x - m > self.z:
            return
        Spot.update(self, x - m)
        self.msum += x - self.win.popleft()
        self.win.append(x)


def make(rule, cfg, calib, steps_per_day, depth, refit):
    if rule == "frozen":
        return Static(cfg["tau0"])
    if rule == "margin":
        return Static(cfg["tau_half"])
    if rule == "daily":
        return Daily(cfg, steps_per_day)
    if rule == "tracker":
        return Tracker(cfg, cfg["eta"])
    if rule == "tracker_slow":
        return Tracker(cfg, cfg["eta"] / 10)
    if rule == "one_sided:none":
        return TightenOnly(cfg, cfg["eta"])
    if rule == "spot":
        return Spot(cfg, calib)
    if rule == "spot_mle":
        return SpotMLE(cfg, calib, refit)
    if rule == "dspot":
        return DSpot(cfg, calib, depth)
    raise ValueError(rule)
