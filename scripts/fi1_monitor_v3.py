"""fi1 workstream A: monitor candidates (static rules fitted on attack-free data only).

Every monitor maps the cached world-model residuals of one stream (R1, R5 in scaled units, per sensor) to a
per-step raw score; the benchmark (fi1_monitor_benchmark.py) smooths it with the registered window and
calibrates a static threshold on the attack-free calibration split with real_telemetry_detect_v2.calibrate,
unless the monitor brings its own threshold rule. Per-channel statistics come from the residual-scale split
(the split the registered sig1 / sig5 come from); thresholds from the calibration split. Nothing here reads a
test stream while fitting, and nothing adapts online.

    d1          registered D1: top3(|R1| / sig1) + top3(|R5| / sig5)
    mad         centre and scale per channel from the median and MAD of the residual-scale split
    tail        per-channel scale = 99.9th percentile of |R| on the residual-scale split (equal tails)
    max         D1 with the largest standardised residual instead of the top-3 mean
    second      D1 without the single largest channel: mean of ranks 2-4 (two channels must agree)
    stable      D1 on the channels whose residual scale stays within a factor STABLE_FACTOR across the
                attack-free recordings of the scale and calibration splits
    loro        D1 with the threshold of the worst attack-free calibration recording (leave-one-recording-out:
                the largest of the per-recording calibrated thresholds)
    h1 / h5     one horizon only (twice the top-3 mean, so the scale matches D1)
"""

from __future__ import annotations

import numpy as np

WARMUP = 10
STABLE_FACTOR = 2.0
TAIL_Q = 0.999


def topk_mean(A, k):
    k = min(k, A.shape[1])
    return -np.sort(-A, 1)[:, :k].mean(1)


def ranks_mean(A, lo, hi):
    """Mean of the lo-th to (hi-1)-th largest entries of each row (0-based ranks)."""
    hi = min(hi, A.shape[1])
    return -np.sort(-A, 1)[:, lo:hi].mean(1)


def scale_rows(unit, group="scale"):
    """Residual rows of a group with the warm-up (all-zero) rows removed: (R1, R5)."""
    r1, r5 = [], []
    for st in unit.streams(group):
        a1, a5 = np.asarray(st.load("R1")), np.asarray(st.load("R5"))
        keep = np.any(a5 != 0, 1)
        r1.append(a1[keep])
        r5.append(a5[keep])
    return np.concatenate(r1), np.concatenate(r5)


class D1:
    """Registered D1 (real_telemetry_detect.Scorer.raw), computed from cached residuals."""

    name = "d1"

    def fit(self, unit):
        self.c1 = self.c5 = 0.0
        self.sig1, self.sig5 = unit.sig1, unit.sig5
        self.keep = None
        return self

    def standardised(self, a):
        S1 = np.abs(a["R1"] - self.c1) / self.sig1
        S5 = np.abs(a["R5"] - self.c5) / self.sig5
        if self.keep is not None:
            S1, S5 = S1[:, self.keep], S5[:, self.keep]
        S1[:WARMUP] = 0
        S5[:WARMUP] = 0
        return S1, S5

    def combine(self, S):
        return topk_mean(S, 3)

    def raw(self, unit, a):
        S1, S5 = self.standardised(a)
        return self.combine(S1) + self.combine(S5)


class Mad(D1):
    name = "mad"

    def fit(self, unit):
        super().fit(unit)
        r1, r5 = scale_rows(unit)
        self.c1, self.c5 = np.median(r1, 0), np.median(r5, 0)
        self.sig1 = 1.4826 * np.median(np.abs(r1 - self.c1), 0) + 1e-3
        self.sig5 = 1.4826 * np.median(np.abs(r5 - self.c5), 0) + 1e-3
        return self


class Tail(D1):
    name = "tail"

    def fit(self, unit):
        super().fit(unit)
        r1, r5 = scale_rows(unit)
        # rescaled so that a Gaussian channel keeps its D1 scale (q99.9 of |N(0,1)| = 3.29)
        self.sig1 = np.quantile(np.abs(r1), TAIL_Q, 0) / 3.29 + 1e-3
        self.sig5 = np.quantile(np.abs(r5), TAIL_Q, 0) / 3.29 + 1e-3
        return self


class Max(D1):
    name = "max"

    def combine(self, S):
        return S.max(1)


class Second(D1):
    name = "second"

    def combine(self, S):
        return ranks_mean(S, 1, 4)


def recording_scales(unit):
    """Per-recording residual std of every channel (H1 and H5 stacked) over the scale and calib streams."""
    out = []
    for group in ("scale", "calib"):
        for st in unit.streams(group):
            a1, a5 = np.asarray(st.load("R1")), np.asarray(st.load("R5"))
            keep = np.any(a5 != 0, 1)
            if keep.sum() < 100:
                continue
            out.append(np.concatenate([a1[keep].std(0), a5[keep].std(0)]))
    return np.array(out)


class Stable(D1):
    name = "stable"

    def fit(self, unit):
        super().fit(unit)
        sc = recording_scales(unit)
        d = len(unit.sig1)
        if len(sc) >= 2:
            ratio = (sc.max(0) + 1e-3) / (sc.min(0) + 1e-3)
            bad = (ratio[:d] > STABLE_FACTOR) | (ratio[d:] > STABLE_FACTOR)
        else:  # one recording: compare its halves
            bad = np.zeros(d, bool)
        if bad.all():
            bad[:] = False
        self.keep = np.flatnonzero(~bad)
        self.dropped = [int(j) for j in np.flatnonzero(bad)]
        return self


class Loro(D1):
    """Threshold of the worst attack-free calibration recording (each calibrated alone)."""

    name = "loro"

    def threshold(self, unit, cal):
        import real_telemetry_detect_v2 as R2

        sp = unit.spec
        parts = [c for c in cal if len(c)]
        if len(parts) == 1:  # one recording: its two halves
            c = parts[0]
            parts = [c[: len(c) // 2], c[len(c) // 2 :]]
        pooled = R2.calibrate(cal, sp["gap"], sp["budget"], sp["spd"])
        each = [R2.calibrate([c], sp["gap"], sp["budget"], sp["spd"]) for c in parts]
        return max([pooled] + each)


class H1(D1):
    name = "h1"

    def raw(self, unit, a):
        S1, _ = self.standardised(a)
        return 2 * self.combine(S1)


class H5(D1):
    name = "h5"

    def raw(self, unit, a):
        _, S5 = self.standardised(a)
        return 2 * self.combine(S5)


HISTORY = 3  # real_telemetry_dev.HISTORY


def clip_correction(R, Z, coef_level, low, high, h):
    """Residual of the world model whose level inputs Z[t] are clipped to the fit range [low, high].

    The ridge part of real_telemetry_core.Forecaster is linear in the level features (the first d design
    columns), so clipping them changes the forecast of Z[t+h] by -W (Z[t] - clip(Z[t])) and the residual by
    +W (Z[t] - clip(Z[t])). The gradient-boosted part is unchanged: a tree routes a value beyond the largest
    (smallest) training value exactly as that value, because every split threshold lies inside the training
    range. The result is the exact residual of the clipped-input model, without refitting."""
    R = np.array(R, np.float64, copy=True)
    excess = Z - np.clip(Z, low, high)
    if not np.any(excess):
        return R
    corr = excess @ coef_level.T
    t = np.arange(HISTORY, len(Z) - h)
    R[t + h] += corr[t]
    return R


class Clip(D1):
    """D1 of the world model with its sensor-level inputs clipped to the range seen in the fit data."""

    name = "clip"

    def fit(self, unit):
        super().fit(unit)
        d = len(unit.sig1)
        self.w = {h: np.load(unit.d / f"ridge_coef_h{h}.npy")[:, :d] for h in (1, 5)}
        self.low, self.high = unit.fit_low, unit.fit_high
        return self

    def raw(self, unit, a):
        a = dict(a)
        z = np.asarray(a["Z"], np.float64)
        a["R1"] = clip_correction(a["R1"], z, self.w[1], self.low, self.high, 1)
        a["R5"] = clip_correction(a["R5"], z, self.w[5], self.low, self.high, 5)
        return super().raw(unit, a)


MONITORS = {m.name: m for m in (D1, Mad, Tail, Max, Second, Stable, Loro, H1, H5, Clip)}


def make(name):
    """A monitor by name; '+'-joined names combine a scale class, a combination and a threshold rule,
    e.g. 'stable+second' (later parts override the methods they define)."""
    parts = name.split("+")
    if len(parts) == 1:
        return MONITORS[name]()
    bases = tuple(MONITORS[p] for p in reversed(parts))
    return type(name, bases, {"name": name})()
