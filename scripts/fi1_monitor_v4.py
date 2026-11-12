"""fi1 workstream A, round 2: monitors with more than one alarm channel or output state (EXPLORATORY).

Every rule here is static: statistics and thresholds are fitted on the attack-free residual-scale and calibration
splits and then fixed; nothing reads a test stream while fitting and nothing adapts online.

A multi-state monitor returns, per stream, a list of normalised smoothed scores ("states"); state k is on where its
score exceeds 1. The benchmark scores it as rule 4 of the plan's note says: alarm time is the union of the states;
the episodes of each state (merged across the gap within that state) are counted separately, so an episode of any
state that starts inside an event is an onset, and every state's episodes outside events count as false alarms
against the one episode budget. Each state is calibrated on attack-free data to its own share of that budget, so the
sum of the states' episodes on the calibration split stays within the budget.

Names (built by `make`):

    A|B[@q]        two alarm channels: component A calibrated to share q of the budget (default 0.5), B to 1 - q;
                   A and B are names of single-score monitors (fi1_monitor_v3 names, '+'-combinations, `rise<L>`)
    A^B[@q]        one alarm channel: max(sA / tA, sB / tB) with tA, tB at shares q and 1 - q, then recalibrated
                   to the full budget (episodes of the union counted once)
    rise<L>        single score: smoothed D1 minus smoothed D1 L windows earlier (a new rise on top of a level;
                   a fixed linear filter, no state learnt from the stream)
    oor[U][@q]:X   two output states: "outside the fitted range" and the inner monitor X used only inside it.
                   Indicator: largest excess of a scaled sensor (with U: also of an action) beyond the range of the
                   world-model fit data, in units of that channel's fit span, smoothed with the registered window;
                   calibrated on the attack-free calibration split (held out of the fit, so a calibration recording
                   that leaves the range is a held-out recording leaving it) to share q (default 0.25), floored at
                   OOR_FLOOR. X is calibrated on the calibration steps outside the out-of-range state to 1 - q.
    regime<K>      D1 with residual scales conditioned on the operating regime: K clusters of the command inputs
                   (k-means on the residual-scale split), per-cluster sig1 / sig5; a step takes the scales of the
                   nearest cluster centre.
    worst          D1 with each channel's scale the largest per-recording residual std over the attack-free
                   residual-scale and calibration recordings (channels that drift between recordings weigh less).
"""

from __future__ import annotations

import re

import numpy as np

import fi1_monitor_v3 as V3

OOR_FLOOR = (
    0.05  # the descriptive definition of round 1: 5 % of the fit span beyond the range
)
NEG = -1e300  # a masked (inactive) step: finite, never above any threshold


# ---------------------------------------------------------------- helpers
def _B():
    import fi1_monitor_benchmark as B

    return B


def smoothed(unit, mon, a):
    """Smoothed score of a single-score monitor (warm-up NaN), as the benchmark computes it."""
    if hasattr(mon, "smoothed"):
        return mon.smoothed(unit, a)
    return _B().smooth(mon.raw(unit, a), unit.spec["window"])


def _arrays(st, sl=None):
    a = st.arrays()
    return {
        k: (None if v is None else np.asarray(v if sl is None else v[sl]))
        for k, v in a.items()
    }


def _samples(st):
    """Per-sample slices of an episodic stream."""
    lens = st.load("lengths", mmap=False)
    at = 0
    for n in lens:
        yield slice(at, at + n)
        at += n


def calibrate_score(unit, fn, share, mask_fn=None):
    """Threshold of a score function fn(arrays) -> smoothed score on the calibration split, to `share` of the
    budget. mask_fn(arrays) -> bool array of steps where the score is inactive (NEG there, time still counted).
    Episodic units: per-sample maxima, quantile 1 - alpha * share."""
    import real_telemetry_detect_v2 as R2

    sp = unit.spec
    if unit.episodic:
        st = unit.streams("calib")[0]
        m = []
        for sl in _samples(st):
            a = _arrays(st, sl)
            s = np.array(fn(a), np.float64)
            if mask_fn is not None:
                s[mask_fn(a)] = np.nan
            m.append(np.nanmax(s) if np.isfinite(s).any() else NEG)
        return float(np.quantile(np.array(m), 1 - sp["alpha"] * share))
    cal = []
    for st in unit.streams("calib"):
        a = _arrays(st)
        s = np.array(fn(a), np.float64)
        if mask_fn is not None:
            s[mask_fn(a) & np.isfinite(s)] = NEG
        cal.append(s[np.isfinite(s)])
    return float(R2.calibrate(cal, sp["gap"], sp["budget"] * share, sp["spd"]))


# ---------------------------------------------------------------- single scores added in round 2
class Rise(V3.D1):
    """Smoothed D1 minus its value L windows earlier (zero before that)."""

    def __init__(self, lag_windows=3):
        self.lag_windows = lag_windows
        self.name = f"rise{lag_windows}"

    def smoothed(self, unit, a):
        s = _B().smooth(super().raw(unit, a), unit.spec["window"])
        lag = self.lag_windows * unit.spec["window"]
        out = np.full_like(s, np.nan)
        if len(s) > lag:
            out[lag:] = s[lag:] - s[:-lag]
        return out

    def raw(self, unit, a):  # only smoothed() is used
        raise NotImplementedError


class Regime(V3.D1):
    def __init__(self, k=4):
        self.k = k
        self.name = f"regime{k}"

    def fit(self, unit):
        from sklearn.cluster import KMeans

        super().fit(unit)
        r1, r5, u = [], [], []
        for st in unit.streams("scale"):
            a1, a5 = np.asarray(st.load("R1")), np.asarray(st.load("R5"))
            keep = np.any(a5 != 0, 1)
            r1.append(a1[keep])
            r5.append(a5[keep])
            u.append(np.asarray(st.load("U"))[keep])
        r1, r5, u = np.concatenate(r1), np.concatenate(r5), np.concatenate(u)
        if u.shape[1] == 0 or self.k < 2:
            self.centres = None
            return self
        rng = np.random.default_rng(0)
        idx = rng.choice(len(u), min(len(u), 50000), replace=False)
        km = KMeans(self.k, n_init=4, random_state=0).fit(u[idx])
        self.centres = km.cluster_centers_
        lab = self._assign(u)
        self.s1 = np.empty((self.k, r1.shape[1]))
        self.s5 = np.empty((self.k, r5.shape[1]))
        for c in range(self.k):
            m = lab == c
            # a small cluster keeps the pooled scale (registered sig) as its floor
            if m.sum() < 500:
                self.s1[c], self.s5[c] = self.sig1, self.sig5
            else:
                self.s1[c] = np.maximum(r1[m].std(0), 0.5 * self.sig1)
                self.s5[c] = np.maximum(r5[m].std(0), 0.5 * self.sig5)
        return self

    def _assign(self, u):
        d = ((u[:, None, :] - self.centres[None]) ** 2).sum(2)
        return d.argmin(1)

    def standardised(self, a):
        if self.centres is None:
            return super().standardised(a)
        lab = self._assign(np.asarray(a["U"], np.float64))
        S1 = np.abs(a["R1"]) / self.s1[lab]
        S5 = np.abs(a["R5"]) / self.s5[lab]
        S1[: V3.WARMUP] = 0
        S5[: V3.WARMUP] = 0
        return S1, S5


class Worst(V3.D1):
    name = "worst"

    def fit(self, unit):
        super().fit(unit)
        sc = V3.recording_scales(unit)
        d = len(unit.sig1)
        if len(sc):
            self.sig1 = np.maximum(self.sig1, sc[:, :d].max(0))
            self.sig5 = np.maximum(self.sig5, sc[:, d:].max(0))
        return self


def single(name):
    m = re.fullmatch(r"rise(\d+)", name)
    if m:
        return Rise(int(m.group(1)))
    m = re.fullmatch(r"regime(\d+)", name)
    if m:
        return Regime(int(m.group(1)))
    if name == "worst":
        return Worst()
    parts = name.split("+")
    if any(p == "worst" for p in parts):
        others = [p for p in parts if p != "worst"]
        return type(
            name,
            (Worst,) + tuple(V3.MONITORS[p] for p in reversed(others)),
            {"name": name},
        )()
    return V3.make(name)


# ---------------------------------------------------------------- multi-state monitors
class Multi:
    """Base: fit(unit, share, mask_fn) and states(unit, a, mask) -> list of normalised scores (on where > 1)."""

    multistate = True


class Single(Multi):
    """One single-score monitor as one state (normalised by its threshold at its budget share)."""

    def __init__(self, name):
        self.mon = single(name)
        self.name = name

    def fit(self, unit, share=1.0, mask_fn=None):
        self.mon.fit(unit)
        self.tau = calibrate_score(
            unit, lambda a: smoothed(unit, self.mon, a), share, mask_fn
        )
        return self

    def states(self, unit, a, mask=None):
        s = smoothed(unit, self.mon, a) / self.tau
        if mask is not None:
            s = np.where(mask, -np.inf, s)
        return [s]


class Pair(Multi):
    def __init__(self, a, b, q=0.5, union=False):
        self.A, self.Bm = single(a), single(b)
        self.q, self.union = q, union
        self.name = f"{a}{'^' if union else '|'}{b}" + ("" if q == 0.5 else f"@{q:g}")

    def fit(self, unit, share=1.0, mask_fn=None):
        self._unit = unit
        self.A.fit(unit)
        self.Bm.fit(unit)
        self.tA = calibrate_score(
            unit, lambda a: smoothed(unit, self.A, a), share * self.q, mask_fn
        )
        self.tB = calibrate_score(
            unit, lambda a: smoothed(unit, self.Bm, a), share * (1 - self.q), mask_fn
        )
        if self.union:
            self.tU = calibrate_score(unit, self._union, share, mask_fn)
        return self

    def _union(self, a):
        u = self._unit
        return np.fmax(
            smoothed(u, self.A, a) / self.tA, smoothed(u, self.Bm, a) / self.tB
        )

    def states(self, unit, a, mask=None):
        sa = smoothed(unit, self.A, a) / self.tA
        sb = smoothed(unit, self.Bm, a) / self.tB
        out = [np.fmax(sa, sb) / self.tU] if self.union else [sa, sb]
        if mask is not None:
            out = [np.where(mask, -np.inf, s) for s in out]
        return out


def oor_indicator(unit, a, with_actions=False):
    """Largest excess of a scaled channel beyond the fit range, in units of its fit span (0 inside)."""
    z = np.asarray(a["Z"], np.float64)
    span = np.maximum(unit.fit_high - unit.fit_low, 1e-6)
    g = np.maximum(np.maximum(unit.fit_low - z, z - unit.fit_high), 0) / span
    g = g.max(1) if g.shape[1] else np.zeros(len(z))
    if with_actions and a.get("U") is not None and np.asarray(a["U"]).shape[1]:
        u = np.asarray(a["U"], np.float64)
        vlow, vhigh = unit.fit_vlow, unit.fit_vhigh
        vspan = np.maximum(vhigh - vlow, 1e-6)
        gu = (np.maximum(np.maximum(vlow - u, u - vhigh), 0) / vspan).max(1)
        g = np.maximum(g, gu)
    return g


class OOR(Multi):
    """Two output states: outside the fitted range, and the inner monitor inside it."""

    def __init__(self, inner, q=0.25, with_actions=False):
        self.inner = make(inner) if not isinstance(inner, Multi) else inner
        if not getattr(self.inner, "multistate", False):
            self.inner = Single(inner)
        self.q, self.with_actions = q, with_actions
        self.name = (
            f"oor{'U' if with_actions else ''}"
            + ("" if q == 0.25 else f"@{q:g}")
            + f":{inner}"
        )

    def _g(self, unit, a):
        return _B().smooth(
            oor_indicator(unit, a, self.with_actions), unit.spec["window"]
        )

    def fit(self, unit, share=1.0, mask_fn=None):
        self.tO = max(
            calibrate_score(unit, lambda a: self._g(unit, a), share * self.q, mask_fn),
            OOR_FLOOR,
        )
        def out_fn(a):
            return self._g(unit, a) > self.tO

        self.inner.fit(unit, share * (1 - self.q), out_fn)
        return self

    def states(self, unit, a, mask=None):
        g = self._g(unit, a) / self.tO
        out_state = g > 1
        inner = self.inner.states(
            unit, a, out_state if mask is None else (out_state | mask)
        )
        if mask is not None:
            g = np.where(mask, -np.inf, g)
        return [g] + inner

    def outside(self, unit, a):
        return self._g(unit, a) > self.tO


def make(name):
    m = re.fullmatch(r"oor(U?)(?:@([0-9.]+))?:(.+)", name)
    if m:
        mon = OOR(
            m.group(3), float(m.group(2)) if m.group(2) else 0.25, m.group(1) == "U"
        )
        mon.name = name
        return mon
    m = re.fullmatch(r"([^|^@]+)([|^])([^|^@]+)(?:@([0-9.]+))?", name)
    if m:
        mon = Pair(
            m.group(1),
            m.group(3),
            float(m.group(4)) if m.group(4) else 0.5,
            m.group(2) == "^",
        )
        mon.name = name
        return mon
    return single(
        name
    )  # a plain single-score monitor runs through the round-1 path unchanged
