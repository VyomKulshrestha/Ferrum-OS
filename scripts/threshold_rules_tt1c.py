"""Stronger adaptive baselines and canonical SPOT for tt1c development (exploratory).

Definitions are fixed in docs/research/threshold_transfer_tt1c_dev_plan.md. Every rule is an online model
with tau() (the threshold in force for the next sample) and update(x) (learn from the sample just scored),
the interface of scripts/tt1b_frog_dev.py, so the same object serves the recorded streams, the pulse
campaign and the closed-loop frog. path() runs a model over a whole stream.

threshold_rules.py and threshold_rules_ext.py (registered / earlier development libraries) are unchanged.
"""
from __future__ import annotations

from collections import deque

import numpy as np

import threshold_rules_ext as E

EVENT_L = 60            # an alarm episode that has lasted this many steps is an event
HOLD = 3600             # hold-off after an event episode ends
GAP = 60                # alarms closer than this belong to one episode
CAP = 0.1               # tracker_capped: daily rise cap, in units of tau0
ETA_TAU = 0.01          # tracker_capped: step size, in units of tau0
NDT_W, NDT_B = 2100, 70
NDT_Z = np.arange(2.5, 12.0, 0.5)
NDT_ZMAX = 12.0
DECLUST = 60            # runs declustering: a cluster ends after this many steps at or below t


class _Episodes:
    """Tracks the rule's own alarm episodes: whether the current one is an event, and the hold-off."""

    def __init__(self):
        self.i, self.start, self.last, self.event, self.hold_until = 0, None, None, False, -1

    def step(self, alarm):
        """Call once per sample after deciding the alarm; returns True if the sample is in an event
        episode or its hold-off."""
        i = self.i
        if alarm:
            if self.last is None or i - self.last > GAP:
                self.start, self.event = i, False
            self.last = i
            if i - self.start + 1 >= EVENT_L:
                self.event = True
        elif self.event and i - self.last > GAP:
            self.hold_until, self.event = self.last + HOLD, False
        self.i += 1
        return (alarm and self.event) or i <= self.hold_until


class TrackerHold:
    def __init__(self, cfg):
        self.q, self.eta, self.p, self.ep = cfg["tau0"], cfg["eta"], cfg["p"], _Episodes()

    def tau(self):
        return self.q

    def update(self, x):
        alarm = bool(x > self.q)
        held = self.ep.step(alarm)
        if alarm and not held:
            self.q += self.eta * (1.0 - self.p)
        elif not alarm:
            self.q -= self.eta * self.p


class TrackerCapped:
    def __init__(self, cfg, steps_per_day):
        self.tau0, self.p, self.spd = cfg["tau0"], cfg["p"], steps_per_day
        self.q, self.day_start, self.n = cfg["tau0"], cfg["tau0"], 0

    def tau(self):
        return self.q

    def update(self, x):
        self.q += ETA_TAU * self.tau0 * ((1.0 if x > self.q else 0.0) - self.p)
        self.q = min(self.q, self.day_start + CAP * self.tau0)
        self.n += 1
        if self.n % self.spd == 0:
            self.day_start = self.q


class DailyExcl:
    """Daily recalibration that leaves out event episodes (under its own threshold) and their hold-off.
    Day boundaries are counted from the stream start, as in threshold_rules.daily_path."""

    def __init__(self, cfg, steps_per_day):
        self.t, self.p, self.spd = cfg["tau0"], cfg["p"], steps_per_day
        self.buf, self.carry = [], 0

    def tau(self):
        return self.t

    def update(self, x):
        self.buf.append(x)
        if len(self.buf) == self.spd:
            a = np.asarray(self.buf, float)
            keep = np.isfinite(a)
            keep[:self.carry] = False
            alarm = np.where(np.isfinite(a), a, -np.inf) > self.t
            self.carry = 0
            idx = np.flatnonzero(alarm)
            if len(idx):
                breaks = np.flatnonzero(np.diff(idx) > GAP + 1)
                starts = np.concatenate([[idx[0]], idx[breaks + 1]])
                ends = np.concatenate([idx[breaks], [idx[-1]]]) + 1
                for s, e in zip(starts, ends):
                    if e - s >= EVENT_L:
                        keep[s:min(e + HOLD, len(a))] = False
                        self.carry = max(self.carry, e + HOLD - len(a))
            if keep.sum() >= 1.0 / self.p:
                self.t = float(np.quantile(a[keep], 1.0 - self.p))
            self.buf = []


def _ndt(e):
    e = e[np.isfinite(e)]
    if len(e) < 10:
        return None
    mu, sd = float(e.mean()), float(e.std())
    if sd <= 0 or mu == 0:
        return mu + NDT_ZMAX * sd
    best, eps_best = -np.inf, mu + NDT_ZMAX * sd
    for z in NDT_Z:
        eps = mu + z * sd
        below = e[e < eps]
        idx = np.flatnonzero(e >= eps)
        if len(idx) == 0 or len(below) < 2:
            continue
        n_seq = 1 + int(np.count_nonzero(np.diff(idx) > 1))
        score = ((mu - below.mean()) / mu + (sd - below.std()) / sd) / (len(idx) + n_seq ** 2)
        if score >= best and n_seq <= 5 and len(idx) < len(e) / 2:
            best, eps_best = score, eps
    return eps_best


class NDT:
    """Telemanom's nonparametric dynamic threshold, causal: recomputed every NDT_B steps on the trailing
    NDT_W scores (Hundman et al. 2018 defaults), without the error buffer and the pruning step."""

    def __init__(self, calib):
        self.buf = deque(np.asarray(calib, float)[-NDT_W:].tolist(), maxlen=NDT_W)
        self.eps, self.n = _ndt(np.asarray(self.buf)), 0

    def tau(self):
        return self.eps

    def update(self, x):
        if np.isfinite(x):
            self.buf.append(float(x))
        self.n += 1
        if self.n % NDT_B == 0:
            e = _ndt(np.fromiter(self.buf, float))
            if e is not None:
                self.eps = e


def gpd_mle(y, bound=None, theta0=None):
    """Maximum-likelihood GPD (shape xi, scale sigma) for excesses y > 0 by the profile likelihood in
    theta = xi / sigma (Grimshaw's reduction). bound restricts |xi|. A warm start theta0 narrows the
    search to a bracket around it."""
    y = np.asarray(y, float)
    n, ymax, ybar = len(y), float(y.max()), float(y.mean())
    lo = -1.0 / ymax

    def nll(th):
        th = np.atleast_1d(th)
        out = np.full(th.shape, np.inf)
        small = np.abs(th) < 1e-9 / ybar
        out[small] = n * np.log(ybar) + n
        ok = ~small & (th > lo)
        if ok.any():
            x = 1.0 + np.outer(th[ok], y)
            xi = np.log(np.maximum(x, 1e-300)).mean(axis=1)
            sig = xi / th[ok]
            val = n * np.log(np.maximum(sig, 1e-300)) + n * (1.0 + xi)
            val[(sig <= 0) | (x.min(axis=1) <= 0)] = np.inf
            if bound is not None:
                val[np.abs(xi) > bound] = np.inf
            out[ok] = val
        return out

    if theta0 is None or not np.isfinite(theta0):
        grid = np.concatenate([lo * (1 - np.logspace(-6, 0, 24)[::-1] + 1e-12),
                               np.logspace(-6, 3, 36) / ybar, [0.0]])
    else:
        span = max(abs(theta0), 1e-6 / ybar)
        grid = np.concatenate([theta0 + span * np.linspace(-0.5, 0.5, 11), [0.0]])
    grid = grid[grid > lo]
    vals = nll(grid)
    j = int(np.argmin(vals))
    a = grid[max(j - 1, 0)]
    b = grid[min(j + 1, len(grid) - 1)]
    g = (np.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = nll(c)[0], nll(d)[0]
    for _ in range(30):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = nll(c)[0]
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = nll(d)[0]
    th = c if fc < fd else d
    if min(fc, fd) > vals[j]:
        th = grid[j]
    if abs(th) < 1e-9 / ybar:
        return 0.0, ybar, 0.0
    xi = float(np.mean(np.log(1.0 + th * y)))
    return xi, xi / th, float(th)


class SpotGR:
    """SPOT with maximum-likelihood tail refits (every peak below 100 peaks, then on 1% growth).
    declust: runs declustering (cluster maxima, tail probability from the cluster count; Coles 2001)."""

    def __init__(self, cfg, calib, bound=None, declust=False):
        calib = np.asarray(calib, float)
        calib = calib[np.isfinite(calib)]
        self.q, self.bound, self.declust = cfg["p"], bound, declust
        self.t = float(np.quantile(calib, E.SPOT_LEVEL))
        self.k = len(calib)
        if declust:
            self.peaks = self._cluster_maxima(calib)
        else:
            self.peaks = list(calib[calib > self.t] - self.t)
        self.run_max, self.below = None, 0
        self.theta = None
        self._fit()

    def _cluster_maxima(self, a):
        out, cur, below = [], None, 0
        for x in a:
            if x > self.t:
                cur = x if cur is None else max(cur, x)
                below = 0
            elif cur is not None:
                below += 1
                if below >= DECLUST:
                    out.append(cur - self.t)
                    cur = None
        if cur is not None:
            out.append(cur - self.t)
        return out

    def _fit(self):
        self.g, self.sg, self.theta = gpd_mle(self.peaks, self.bound,
                                             None if len(self.peaks) < 100 else self.theta)
        self.fitted = len(self.peaks)
        self._z()

    def _z(self):
        self.z = E._zq(self.t, self.g, self.sg, self.q, self.k, len(self.peaks))

    def tau(self):
        return self.z

    def _add_peak(self, y):
        self.peaks.append(y)
        if len(self.peaks) < 100 or len(self.peaks) >= 1.01 * self.fitted:
            self._fit()
        else:
            self._z()

    def update(self, x):
        if not np.isfinite(x) or x > self.z:        # warm-up or alarm: not learned
            return
        self.k += 1
        if not self.declust:
            if x > self.t:
                self._add_peak(x - self.t)
            else:
                self._z()
            return
        if x > self.t:
            self.run_max = x if self.run_max is None else max(self.run_max, x)
            self.below = 0
        elif self.run_max is not None:
            self.below += 1
            if self.below >= DECLUST:
                y, self.run_max = self.run_max - self.t, None
                self._add_peak(y)
                return
        self._z()


class DSpotGR(SpotGR):
    def __init__(self, cfg, calib, depth):
        calib = np.asarray(calib, float)
        calib = calib[np.isfinite(calib)]
        csum = np.concatenate([[0.0], np.cumsum(calib)])
        resid = calib[depth:] - (csum[depth:-1] - csum[:-depth - 1]) / depth
        super().__init__(cfg, resid)
        self.depth = depth
        self.win = deque(calib[-depth:].tolist())
        self.msum = float(sum(self.win))

    def tau(self):
        return self.msum / self.depth + self.z

    def update(self, x):
        if not np.isfinite(x):
            return
        m = self.msum / self.depth
        if x - m > self.z:
            return
        SpotGR.update(self, x - m)
        self.msum += x - self.win.popleft()
        self.win.append(x)


def make(rule, cfg, calib, steps_per_day, depth):
    return {"tracker_hold": lambda: TrackerHold(cfg),
            "tracker_capped": lambda: TrackerCapped(cfg, steps_per_day),
            "daily_excl": lambda: DailyExcl(cfg, steps_per_day),
            "ndt": lambda: NDT(calib),
            "spot_gr": lambda: SpotGR(cfg, calib),
            "spot_gr_bounded": lambda: SpotGR(cfg, calib, bound=0.5),
            "spot_gr_declust": lambda: SpotGR(cfg, calib, declust=True),
            "dspot_gr": lambda: DSpotGR(cfg, calib, depth)}[rule]()


NEW_RULES = ["daily_excl", "tracker_hold", "tracker_capped", "ndt", "spot_gr", "spot_gr_bounded",
             "spot_gr_declust", "dspot_gr"]


def path(model, scores):
    """Threshold in force at each step when the model runs online over the stream (-inf / NaN = warm-up)."""
    tau = np.empty(len(scores))
    for i, x in enumerate(scores):
        tau[i] = model.tau()
        model.update(x if np.isfinite(x) else -np.inf)
    return tau
