"""tw1: shipped targets behind one step interface.

Each adapter feeds one score to its target through the loop the target's documentation shows and returns
the target's own alarm decision. It also reads, from the target's state, the score above which the target
would alarm next (the white-box attacker's reading). An adapter never decides an alarm.

Run with the tw1 environment (river 0.26.1, PySAD 0.8.0, libspot 3.1.0), not the repository's base Python.
Plan: docs/research/thresholds_in_the_wild_tw1a_dev_plan.md.
"""

from __future__ import annotations

import copy
import importlib.util
import math
import os
from pathlib import Path

CLONES = Path(os.environ.get("TW1_SOURCES", r"C:\Users\marcu\Videos\tw1-sources"))
HIGH = 1e12  # no score of the study comes near it


def bisect_tau(would_alarm, lo=0.0, hi=HIGH, iters=80):
    """The largest score that does not alarm, by bisection on a decision that changes no state.
    Minus infinity when the lowest score already alarms, infinity when no score does."""
    if would_alarm(lo):
        return -math.inf
    # fi1 audit: a threshold above `hi` used to read as infinity ("no score alarms"); widen the bracket
    # geometrically first, so infinity means that no finite score up to 1e300 alarms
    while not would_alarm(hi):
        if hi >= 1e300:
            return math.inf
        lo, hi = hi, min(hi * 1e3, 1e300)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if would_alarm(mid):
            hi = mid
        else:
            lo = mid
        if hi - lo <= 1e-13 * max(1.0, abs(hi)):
            break
    return lo


class NoAlarm(float):
    """A reading that says explicitly that no score above the current level, up to `cap`, alarms. Its float
    value is infinity, so `math.isfinite` is False and "score > reading" is never true. Code that places
    scores relative to a reading must check for it and must not put another value in its place."""

    def __new__(cls, cap):
        obj = float.__new__(cls, math.inf)
        obj.cap = cap
        return obj

    def __repr__(self):
        return f"NoAlarm(cap={self.cap!r})"


GOLDEN = (math.sqrt(5) - 1) / 2
# Width, in log(score - level), of the smallest alarm band the search is guaranteed to find.
BAND_RESOLUTION = 1e-12


def band_reading(would, height, level, cap=HIGH, resolution=BAND_RESOLUTION):
    """The alarm band above `level` of a decision that need not be monotone in the score.

    `would(v)` is the target's own decision for a candidate score v. `height(v)` is the statistic it
    thresholds, assumed unimodal in v above `level` (true of the Gaussian-tail z-score, a ratio of a linear
    function to the square root of a quadratic one). Its maximum is located by golden-section search on
    log(v - level) between log(1e-12 max(1, |level|)) and log(cap - level), down to a bracket of width
    `resolution`. Any band of alarming scores that is at least `resolution` wide in log(v - level) contains
    the final bracket's best point, so it cannot be stepped over.

    Returns (tau, high): tau is the largest non-alarming score below the band and high the largest alarming
    score (infinity when the band reaches `cap`). Returns (NoAlarm(cap), None) when no score in
    (level, cap] alarms."""
    a = math.log(max(1.0, abs(level)) * 1e-12)
    b = math.log(cap - level)
    x1, x2 = b - GOLDEN * (b - a), a + GOLDEN * (b - a)
    h1, h2 = height(level + math.exp(x1)), height(level + math.exp(x2))
    while b - a > resolution:
        if h1 < h2:
            a, x1, h1 = x1, x2, h2
            x2 = a + GOLDEN * (b - a)
            h2 = height(level + math.exp(x2))
        else:
            b, x2, h2 = x2, x1, h1
            x1 = b - GOLDEN * (b - a)
            h1 = height(level + math.exp(x1))
    best = x1 if h1 >= h2 else x2
    peak = next(
        (
            level + math.exp(x)
            for x in (best, x1, x2, a, b)
            if would(level + math.exp(x))
        ),
        None,
    )
    if peak is None:
        return NoAlarm(cap), None
    tau = bisect_tau(would, level, peak)
    if would(cap):
        return tau, math.inf
    return tau, peak + bisect_tau(lambda d: not would(peak + d), 0.0, cap - peak)


class Target:
    name = "target"
    doc = ""  # where the configuration comes from
    ge = False  # the target alarms at "score >= threshold" (True) or "score > threshold" (False)
    eps = 0.0  # relative band around the adapter's threshold inside which it may disagree with the target
    closed_loop = True  # False: no cheap threshold reading, so only inputs that do not depend on it are run
    copyable = True

    def step(self, x: float) -> bool:
        raise NotImplementedError

    def tau(self) -> float:
        raise NotImplementedError

    def clone(self):
        return copy.deepcopy(self)

    def expected(self, x: float, tau: float) -> bool:
        return x >= tau if self.ge else x > tau


# ---------------------------------------------------------------- river
def _river():
    import river.base.anomaly_detector as rbase
    from river import anomaly

    class PassThrough(rbase.AnomalyDetector):
        """The score is produced outside river: this detector hands it on and learns nothing."""

        def learn_one(self, x):
            return None

        def score_one(self, x):
            return x["s"]

    return anomaly, PassThrough


class RiverQuantile(Target):
    """river.anomaly.QuantileFilter in the loop of its docstring: score_one, classify, learn_one."""

    ge = True

    def __init__(self, q=0.95):
        anomaly, PassThrough = _river()
        self.f = anomaly.QuantileFilter(PassThrough(), q=q)
        self.name, self.doc = (
            f"river QuantileFilter(q={q})",
            "q from the class docstring example, river/anomaly/filter.py",
        )

    def step(self, x):
        d = {"s": x}
        score = self.f.score_one(d)
        alarm = bool(self.f.classify(score))
        self.f.learn_one(d)
        return alarm

    def tau(self):
        v = self.f.quantile.get()
        # river classifies with `score >= (quantile.get() or inf)`: a quantile of exactly 0.0 never alarms
        return math.inf if not v else v


class RiverThreshold(Target):
    """river.anomaly.ThresholdFilter at a fixed threshold (static control)."""

    ge = True

    def __init__(self, threshold):
        anomaly, PassThrough = _river()
        self.f = anomaly.ThresholdFilter(PassThrough(), threshold=threshold)
        self.name, self.doc = (
            "river ThresholdFilter(tau0)",
            "threshold set to the frozen threshold of the study",
        )

    def step(self, x):
        d = {"s": x}
        alarm = bool(self.f.classify(self.f.score_one(d)))
        self.f.learn_one(d)
        return alarm

    def tau(self):
        return self.f.threshold


# ---------------------------------------------------------------- PySAD
class PysadQuantile(Target):
    ge = True

    def __init__(self, q=0.99):
        from pysad.transform.postprocessing import QuantileFilter

        self.f = QuantileFilter(q=q)
        self.name, self.doc = (
            f"PySAD QuantileFilter(q={q})",
            "docs/guides/alerts.rst, running-quantile example",
        )

    def step(self, x):
        return bool(self.f.fit_transform_partial(x))

    def tau(self):
        return self.f.meter.get() if self.f.meter.num_items > 0 else math.inf


class PysadConformal(Target):
    """fit_transform_partial puts the score into the window first, then ranks it there."""

    def __init__(self, window_size=1000, cut=0.99):
        from pysad.transform.probability_calibration import (
            ConformalProbabilityCalibrator,
        )

        self.c, self.w, self.cut = (
            ConformalProbabilityCalibrator(window_size=window_size),
            window_size,
            cut,
        )
        self.name = (
            f"PySAD ConformalProbabilityCalibrator(window_size={window_size}) >= {cut}"
        )
        self.doc = "docs/guides/alerts.rst, first example"

    def step(self, x):
        return self.c.fit_transform_partial(x) >= self.cut

    def tau(self):
        w = self.c.window.get()
        kept = (
            w[1:] if len(w) == self.w else w
        )  # the oldest score leaves when the new one enters
        n = len(kept) + 1
        k = max(0, math.ceil(self.cut * n) - 1)
        while (
            k / n < self.cut
        ):  # the smallest count of lower scores that reaches the cut, in the target's arithmetic
            k += 1
        if k == 0:
            return -math.inf
        return math.inf if k > len(kept) else sorted(kept)[k - 1]


class PysadGaussian(Target):
    """The target judges the mean of its short window after the score has entered both windows, so a large
    score raises the deviation it is judged against. The reading asks the target's own meters and its own
    `_calibrate` what they would say for a candidate score, on shallow copies, and bisects."""

    eps = 1e-9
    high = math.inf
    point = None

    def __init__(self, window_size=1000, cut=0.99):
        from pysad.transform.probability_calibration import (
            GaussianTailProbabilityCalibrator,
        )

        self.g, self.cut = (
            GaussianTailProbabilityCalibrator(window_size=window_size),
            cut,
        )
        self.name = f"PySAD GaussianTailProbabilityCalibrator(window_size={window_size}) >= {cut}"
        self.doc = "docs/guides/alerts.rst, Gaussian example; cut as in the guide's first example"

    def step(self, x):
        return self.g.fit_transform_partial(x) >= self.cut

    @staticmethod
    def _after(meter, x):
        """A running-window meter as it would stand after `update(x)`, without touching the real one."""
        m = copy.copy(meter)
        m.statistic = copy.copy(meter.statistic)
        m.statistic.update(x)
        if len(meter.window) + 1 > meter.window_size:
            m.statistic.remove(meter.window[0])
        return m

    def _shadow(self, x, prev):
        shadow = copy.copy(self.g)
        shadow.avg_meter = self._after(self.g.avg_meter, x)
        shadow.var_meter = self._after(self.g.var_meter, x)
        window = prev + [
            x
        ]  # summed as the target sums its short window (Python compensates float sums)
        return shadow, sum(window) / len(window)

    def _would(self, x, prev):
        shadow, short_mean = self._shadow(x, prev)
        return shadow._calibrate(short_mean) >= self.cut

    def _z(self, x, prev):
        """The standardised distance that the target turns into its probability; the band search climbs it."""
        shadow, short_mean = self._shadow(x, prev)
        var = shadow.var_meter.get()
        diff = short_mean - shadow.avg_meter.get()
        if var <= 0:
            return math.copysign(math.inf, diff) if diff else 0.0
        return diff / math.sqrt(var)

    def tau(self):
        g = self.g
        self.high, self.point = math.inf, None
        if not g.short_window or not g.running_statistics:
            return NoAlarm(HIGH)
        prev = (
            list(g.short_window)[-(g.short_window_size - 1) :]
            if g.short_window_size > 1
            else []
        )
        var = g.var_meter.get()
        if var == 0.0:
            # The long window holds one repeated value. Through rounding in the comparison of the two means
            # the target can alarm on exactly that value again; this single point is kept apart.
            last = g.avg_meter.window[-1]
            if self._would(last, prev):
                self.point = last

        def would(v):
            return v != self.point and self._would(v, prev)

        # The score that puts the short-window mean on the long-window mean. It does not alarm, unless the
        # long window holds one repeated value: the target then alarms on anything above that value.
        centre = (len(prev) + 1) * g.avg_meter.get() - sum(prev)
        unit = max(math.sqrt(max(var, 0.0)), 1e-9 * max(1.0, abs(centre)))
        if would(centre):
            below = next(
                (
                    centre - unit * 2.0**k
                    for k in range(80)
                    if not would(centre - unit * 2.0**k)
                ),
                None,
            )
            if below is None:
                return -math.inf
            hit, centre = centre, below
        else:
            # The decision is not monotone in the score: the score enters the long window before it is judged,
            # so a large score raises its own deviation, and at strict cuts the alarming scores form a narrow
            # band above the mean (tw1b found bands narrower than a 5% grid step). The band is located by
            # climbing the target's own z-score, which is unimodal above the mean (fi2 tw1b, amendment 5).
            tau, high = band_reading(would, lambda v: self._z(v, prev), centre, HIGH)
            if high is not None:
                self.high = high
            return tau
        if not would(HIGH):
            # a window that is not yet full: a very large score raises its own deviation enough not to alarm
            self.high = hit + bisect_tau(lambda d: not would(hit + d), 0.0, HIGH - hit)
        return bisect_tau(would, centre, hit)

    def expected(self, x, tau):
        return tau < x <= self.high or x == self.point


class PysadLikelihood(Target):
    """The likelihood is two-sided: a short-window mean far below the long-window mean alarms as well. The
    reading is the upper edge; the lower edge is kept for the consistency check."""

    eps = 1e-9
    low = -math.inf

    def expected(self, x, tau):
        return x > tau or x < self.low

    def __init__(self, cut=1 - 1e-5):
        from pysad.transform.probability_calibration import (
            AnomalyLikelihoodProbabilityCalibrator,
        )

        self.c, self.cut = AnomalyLikelihoodProbabilityCalibrator(), cut
        self.name, self.doc = (
            "PySAD AnomalyLikelihoodProbabilityCalibrator() >= 1 - 1e-5",
            "docs/guides/alerts.rst, HTM example",
        )

    def step(self, x):
        return self.c.fit_transform_partial(x) >= self.cut

    def tau(self):
        c = self.c
        would = lambda v: c.transform_partial(v) >= self.cut  # noqa: E731
        if (
            c.num_scores_ < c.learning_period + c.num_estimation_samples
            or not c.short_window_
        ):
            self.low = -math.inf
            return math.inf
        w = list(c.short_window_)
        kept = w[1:] if len(w) == c.short_window_size else w
        centre = (len(kept) + 1) * c.mean_ - sum(
            kept
        )  # the score that puts the short-window mean on the long mean
        if would(centre):
            self.low = math.inf
            return -math.inf
        down = bisect_tau(lambda v: would(centre - v), 0.0, HIGH)
        self.low = centre - down
        return bisect_tau(would, centre, centre + HIGH)


class PysadSpot(Target):
    eps = 1e-9

    def __init__(self, q=1e-3, num_init=500):
        from pysad.transform.probability_calibration import SPOTProbabilityCalibrator

        self.c, self.cut = SPOTProbabilityCalibrator(q=q, num_init=num_init), 1 - q
        self.name = (
            f"PySAD SPOTProbabilityCalibrator(q={q}, num_init={num_init}) > 1 - q"
        )
        self.doc = "docs/guides/alerts.rst, extreme-value example"

    def step(self, x):
        return self.c.fit_transform_partial(x) > self.cut

    def tau(self):
        return bisect_tau(lambda v: self.c.transform_partial(v) > self.cut)


class PysadNdt(Target):
    closed_loop = False

    def __init__(self):
        from pysad.transform.postprocessing import (
            NonparametricDynamicThresholdPostprocessor,
        )

        self.c = NonparametricDynamicThresholdPostprocessor()
        self.name, self.doc = (
            "PySAD NonparametricDynamicThresholdPostprocessor() > 0",
            "docs/guides/alerts.rst, Telemanom example",
        )

    def step(self, x):
        return self.c.fit_transform_partial(x) > 0


# ---------------------------------------------------------------- htm.core
_HTM = None


def _htm():
    global _HTM
    if _HTM is None:
        path = CLONES / "htm.core/py/htm/algorithms/anomaly_likelihood.py"
        spec = importlib.util.spec_from_file_location(
            "tw1_htm_anomaly_likelihood", path
        )
        _HTM = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_HTM)
    return _HTM


class HtmLikelihood(Target):
    """htm.core's Python AnomalyLikelihood, loaded from the catalogued file; alarm as in its docstring."""

    eps = 1e-9

    def __init__(self, period=1000, cut=0.25):
        self.h, self.cut = _htm().AnomalyLikelihood(period), cut
        self.name, self.doc = (
            f"htm.core AnomalyLikelihood(period={period}) > {cut}",
            "class docstring example",
        )

    def step(self, x):
        return self.h.compute(x) > self.cut

    def _would(self, v):
        h = self.h
        combined = 1 - (1 - h.get_likelihood(v)) * (1 - h.prev)
        return h.n_records + 1 >= h.period and h.get_log_likelihood(combined) > self.cut

    def tau(self):
        return bisect_tau(self._would)

    def __deepcopy__(self, memo):
        c = copy.copy(self)
        c.h = copy.copy(self.h)  # plain floats only
        return c


# ---------------------------------------------------------------- libspot
class LibSpot(Target):
    """libspot's Python binding: fit on an initial batch, then step. Its objects cannot be copied, so a clone
    replays the inputs. The threshold is the library's own attribute."""

    copyable = False

    def __init__(self, q=1e-4, n_init=1000):
        self.q, self.n_init, self.log, self.s = q, n_init, [], None
        self.name, self.doc = (
            f"libspot Spot(q={q}), fit on {n_init} scores",
            "q from examples/basic.py; other arguments at the binding's defaults",
        )

    def step(self, x):
        import libspot

        self.log.append(x)
        if self.s is None:
            if len(self.log) == self.n_init:
                self.s = libspot.Spot(q=self.q)
                self.s.fit(self.log)
            return False
        return self.s.step(x) == libspot.ANOMALY

    def tau(self):
        return math.inf if self.s is None else self.s.anomaly_threshold

    def clone(self):
        c = LibSpot(self.q, self.n_init)
        for x in self.log:
            c.step(x)
        return c


def documented(tau0, from_clone=False):
    """The targets of the first pass in their documented configuration. htm.core's likelihood is loaded from
    the catalogued clone, not from an installed package, so it is run only when asked for."""
    extra = [lambda: HtmLikelihood(1000, 0.25)] if from_clone else []
    return extra + [
        lambda: RiverThreshold(tau0),
        lambda: RiverQuantile(0.95),
        lambda: PysadQuantile(0.99),
        lambda: PysadConformal(1000, 0.99),
        lambda: PysadGaussian(1000, 0.99),
        lambda: PysadLikelihood(),
        lambda: PysadSpot(1e-3, 500),
        lambda: PysadNdt(),
        lambda: LibSpot(1e-4, 1000),
    ]


VERSION_FILES = {
    "river": ("river", "anomaly/filter.py", "river/river/anomaly/filter.py"),
    "river base": ("river", "base/anomaly_detector.py", "river/river/base/anomaly_detector.py"),
    "pysad postprocessors": ("pysad", "transform/postprocessing/postprocessors.py", "pysad/pysad/transform/postprocessing/postprocessors.py"),
    "pysad running postprocessors": ("pysad", "transform/postprocessing/running_postprocessors.py",
                                     "pysad/pysad/transform/postprocessing/running_postprocessors.py"),
    "pysad conformal": ("pysad", "transform/probability_calibration/conformal_prediction.py",
                        "pysad/pysad/transform/probability_calibration/conformal_prediction.py"),
    "pysad gaussian tail": ("pysad", "transform/probability_calibration/gaussian_tail.py",
                            "pysad/pysad/transform/probability_calibration/gaussian_tail.py"),
    "pysad likelihood": ("pysad", "transform/probability_calibration/anomaly_likelihood.py",
                         "pysad/pysad/transform/probability_calibration/anomaly_likelihood.py"),
    "pysad spot": ("pysad", "transform/probability_calibration/spot.py", "pysad/pysad/transform/probability_calibration/spot.py"),
}  # fmt: skip


def versions():
    """Installed versions, and whether each installed file equals the file the catalogue read."""
    import hashlib
    from importlib import metadata

    def digest(p):
        return hashlib.sha256(Path(p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()

    out = {
        "packages": {
            p: metadata.version(p) for p in ("river", "pysad", "libspot", "numpy")
        },
        "files": {},
    }
    for label, (pkg, rel, clone_rel) in VERSION_FILES.items():
        installed = Path(importlib.util.find_spec(pkg).origin).parent / rel
        a, b = digest(installed), digest(CLONES / clone_rel)
        out["files"][label] = {
            "installed_sha256": a,
            "catalogued_sha256": b,
            "identical": a == b,
        }
    out["files"]["htm.core likelihood"] = {"loaded_from_clone": True,
                                           "sha256": digest(CLONES / "htm.core/py/htm/algorithms/anomaly_likelihood.py")}  # fmt: skip
    return out
