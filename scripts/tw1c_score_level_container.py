#!/usr/bin/env python3
"""tw1c (exploratory): tw1a's score-level protocol on StreamAD and htm.core, run inside a container.

Plan: docs/research/thresholds_in_the_wild_tw1c_signal_plan.md, sections 4 and 5. The harness
`tw1a_score_level_dev.py` and the adapters `tw1_adapters.py` are imported unchanged; this runner gives the
harness the new targets, the cache and setup paths of the container, and its own output directory.

Inside the container (the work directory is a copy under target/tw1c/<target>/):

    python -I tw1c_score_level_container.py <streamad|htm> versions
    python -I tw1c_score_level_container.py <streamad|htm> mode <m> <full|young>
    python -I tw1c_score_level_container.py <streamad|htm> merge

Environment: TW1C_WORK (default /work) holds cache/ (mode_<m>.npz), tep_setup.json and out/.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repro_env  # noqa: E402
import tw1_adapters as A  # noqa: E402
import tw1a_score_level_dev as H  # noqa: E402

WORK = Path(os.environ.get("TW1C_WORK", "/work"))


# ---------------------------------------------------------------- StreamAD
class StreamadZScore(A.Target):
    """ZScoreCalibrator(sigma=3, extreme_sigma=5) of calibrator_usage.ipynb; alarm when the output is 1.0.
    The statistics take the score before it is judged. The reading asks the target's own `normalize`, on
    shallow copies of its statistics, and bisects; the lower edge (a score far below the mean) is kept for
    the consistency check."""

    eps = 1e-9
    low = -math.inf

    def __init__(self, sigma=3, extreme_sigma=5):
        from streamad.process import ZScoreCalibrator

        self.c = ZScoreCalibrator(sigma=sigma, extreme_sigma=extreme_sigma)
        self.name = f"StreamAD ZScoreCalibrator(sigma={sigma}, extreme_sigma={extreme_sigma}) == 1"
        self.doc = "docs/source/example/calibrator_usage.ipynb"

    def step(self, x):
        v = self.c.normalize(x)
        return v is not None and v >= 1.0

    def _would(self, v):
        c = copy.copy(self.c)
        s = copy.copy(self.c.score_stats)
        for k in ("_max", "_min", "_sum", "_mean", "_sum_squares", "_var", "_std"):
            setattr(s, k, copy.copy(getattr(s, k)))
        s._window = copy.copy(s._window)
        c.score_stats = s
        out = c.normalize(v)
        return out is not None and out >= 1.0

    def tau(self):
        """The statistics include the score they judge: after it enters, |x - mean'| / std' equals
        |d| n / sqrt(n' ss + d^2 n) with d = x - mean, so the score at k deviations is
        mean + k sqrt(n' ss / (n^2 - k^2 n)). The alarm region above the mean starts at the extreme edge,
        or at the sigma edge for a new running maximum (the min-max branch then returns 1.0). That closed
        form only places a narrow bracket; the reading is bisected inside it on the target's own call."""
        s = self.c.score_stats
        if s._num_items < s._window.maxlen:
            self.low = -math.inf
            return math.inf  # the warm-up returns None for the next score
        n, m, ss, mx = s._num_items, s._mean[0], s._sum_squares[0], s._max[0]

        def edge(k):
            den = n * n - k * k * n
            return math.sqrt(k * k * (n + 1) * ss / den) if den > 0 else math.inf

        d5, d3 = edge(self.c.extreme_sigma), edge(self.c.sigma)
        self.low = m - d5
        guess = min(m + d5, max(m + d3, mx))
        if math.isfinite(guess) and ss > 0:
            w = max(abs(guess), 1e-9) * 1e-6
            if not self._would(guess - w) and self._would(guess + w):
                return A.bisect_tau(self._would, guess - w, guess + w)
        # fallback: the full search of tw1a's readings
        if self._would(m):
            self.low = math.inf
            return -math.inf
        d = A.bisect_tau(lambda v: self._would(m - v), 0.0, A.HIGH)
        self.low = m - d
        return A.bisect_tau(self._would, m, A.HIGH)

    def expected(self, x, tau):
        return x > tau or x < self.low


class StreamadTDigest(A.Target):
    """TDigestCalibrator(percentile_up=99, percentile_down=0) of calibrator_usage.ipynb; alarm when the
    output is 1.0. The digest takes the score before the percentiles are read, and where a score near the
    99th percentile lands among the centroids moves that percentile, so a reading needs a bisection on deep
    copies of the digest (tens of milliseconds per reading). The smoke test found the cheap reading (the
    percentile after one very large score) wrong by 1e-5 of its value, so the target runs open-loop
    (amendment 1)."""

    closed_loop = False

    def __init__(self, up=99, down=0):
        from streamad.process import TDigestCalibrator

        self.c = TDigestCalibrator(percentile_up=up, percentile_down=down)
        self.name = f"StreamAD TDigestCalibrator(percentile_up={up}, percentile_down={down}) == 1"
        self.doc = "docs/source/example/calibrator_usage.ipynb"

    def step(self, x):
        v = self.c.normalize(x)
        return v is not None and v >= 1.0


class StreamadSpot(A.Target):
    """SpotDetector() of the README quick start, given the score as its series; alarm when its score is
    1.0. A reading would need a GPD refit per candidate score, so the target runs open-loop (tw1a's rule
    for targets without a cheap reading)."""

    closed_loop = False

    def __init__(self):
        from streamad.model import SpotDetector

        self.d = SpotDetector()
        self.name, self.doc = "StreamAD SpotDetector() == 1", "README quick start"

    def step(self, x):
        import numpy as np

        v = self.d.fit_score(np.array([x]))
        return v is not None and v >= 1.0


def streamad_targets(tau0):
    return [StreamadZScore, StreamadTDigest, StreamadSpot]


# ---------------------------------------------------------------- htm.core
def htm_targets(tau0):
    from htm.algorithms import anomaly_likelihood

    A._HTM = anomaly_likelihood  # the installed module, in place of the clone's file
    return [lambda: A.HtmLikelihood(1000, 0.25)]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def versions(which):
    from importlib import metadata

    out = {"python": sys.version, "packages": {}}
    for p in (
        "numpy",
        "scipy",
        "pandas",
        "statsmodels",
        "streamad",
        "tdigest",
        "accumulation_tree",
        "htm.core",
    ):
        try:
            out["packages"][p] = metadata.version(p)
        except Exception:
            out["packages"][p] = None
    files = {}
    if which == "streamad":
        import streamad

        base = Path(streamad.__file__).parent
        for rel in ("process/zscore_calibrator.py", "process/tdigest_calibrator.py",
                    "model/spot_Detector.py", "util/math_toolkit.py", "base/detector.py"):  # fmt: skip
            files[rel] = _sha(base / rel)
    else:
        from htm.algorithms import anomaly_likelihood

        files["htm/algorithms/anomaly_likelihood.py"] = _sha(
            anomaly_likelihood.__file__
        )
    out["installed_sha256"] = files
    return out


def configure(which):
    H.CACHE = WORK / "cache"
    H.OUT = WORK / "out"
    H.SETUP = json.loads((WORK / "tep_setup.json").read_text(encoding="utf-8"))
    make = streamad_targets if which == "streamad" else htm_targets
    A.documented = lambda tau0, from_clone=False: make(tau0)
    A.versions = lambda: versions(which)


if __name__ == "__main__":
    repro_env.pin_from_environment()
    which, cmd = sys.argv[1], sys.argv[2]
    configure(which)
    if which == "streamad":
        import random

        random.seed(20261112)  # the t-digest compresses with random.shuffle
    if cmd == "versions":
        print(json.dumps(A.versions(), indent=1))
    elif cmd == "mode":
        H.run_mode(int(sys.argv[3]), sys.argv[4] if len(sys.argv) > 4 else "full")
    elif cmd == "merge":
        H.merge()
    else:
        raise SystemExit(__doc__)
