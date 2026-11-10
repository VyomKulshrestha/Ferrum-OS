"""Bounded-loosening rules and an approval gate for tt1e development (exploratory).

Definitions are fixed in docs/research/threshold_transfer_tt1e_dev_plan.md. Every rule is an online model
with tau() and update(x), the interface of threshold_rules_tt1c.py; earlier libraries are unchanged.

A ceiling rule never deploys a threshold above kappa * tau0, so under the any-alarm count it detects at
least what the static threshold kappa * tau0 detects, whatever the stream held before.
"""
from __future__ import annotations

import numpy as np

import threshold_rules_tt1c as N

KAPPAS = (1.1, 1.25, 1.5)


class Static:
    def __init__(self, tau): self.t = tau
    def tau(self): return self.t
    def update(self, x): pass


class TrackerCeil:
    """The registered symmetric tracker with its state clipped at the ceiling (no wind-up above it)."""

    def __init__(self, cfg, kappa):
        self.q, self.eta, self.p, self.cap = cfg["tau0"], cfg["eta"], cfg["p"], kappa * cfg["tau0"]

    def tau(self):
        return self.q

    def update(self, x):
        self.q = min(self.q + self.eta * ((1.0 if x > self.q else 0.0) - self.p), self.cap)


class DailyCeil:
    """Daily recalibration (day boundaries from the stream start, finite scores only) clipped at the ceiling."""

    def __init__(self, cfg, steps_per_day, kappa):
        self.t, self.p, self.spd, self.cap = cfg["tau0"], cfg["p"], steps_per_day, kappa * cfg["tau0"]
        self.buf, self.n = [], 0

    def tau(self):
        return self.t

    def update(self, x):
        self.n += 1
        if np.isfinite(x):
            self.buf.append(x)
        if self.n % self.spd == 0:
            if self.buf:
                self.t = min(float(np.quantile(np.asarray(self.buf, float), 1.0 - self.p)), self.cap)
            self.buf = []


class SpotCeil:
    """spot_gr under a ceiling: deployed threshold min(z, cap); SPOT learns only what the deployed rule
    did not alarm on."""

    def __init__(self, cfg, calib, kappa):
        self.m, self.cap = N.SpotGR(cfg, calib), kappa * cfg["tau0"]

    def tau(self):
        return min(self.m.tau(), self.cap)

    def update(self, x):
        if x > self.tau():
            return
        self.m.update(x)


class SpotGate:
    """spot_gr proposes; an approved ceiling limits it. At each review the ceiling is raised to the
    proposal if the review window held no alarm of the deployed rule."""

    def __init__(self, cfg, calib, review):
        self.m = N.SpotGR(cfg, calib)
        self.c, self.review, self.n, self.alarmed, self.approvals = self.m.tau(), review, 0, False, 0

    def tau(self):
        return min(self.m.tau(), self.c)

    def update(self, x):
        if x > self.tau():
            self.alarmed = True
        else:
            self.m.update(x)
        self.n += 1
        if self.n % self.review == 0:
            if not self.alarmed and self.m.tau() > self.c:
                self.c = self.m.tau()
                self.approvals += 1
            self.alarmed = False


def names():
    out = []
    for k in KAPPAS:
        out += [f"static_{k}", f"tracker_ceil_{k}", f"daily_ceil_{k}", f"spot_gr_ceil_{k}"]
    return out + ["spot_gate24", "spot_gate6"]


NEW_RULES = names()


def make(rule, cfg, calib, steps_per_day):
    if rule == "spot_gate24":
        return SpotGate(cfg, calib, steps_per_day)
    if rule == "spot_gate6":
        return SpotGate(cfg, calib, steps_per_day // 4)
    kind, kappa = rule.rsplit("_", 1)
    kappa = float(kappa)
    if kind == "static":
        return Static(kappa * cfg["tau0"])
    if kind == "tracker_ceil":
        return TrackerCeil(cfg, kappa)
    if kind == "daily_ceil":
        return DailyCeil(cfg, steps_per_day, kappa)
    if kind == "spot_gr_ceil":
        return SpotCeil(cfg, calib, kappa)
    raise ValueError(rule)
