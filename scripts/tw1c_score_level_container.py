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
        s = self.c.score_stats
        if s._num_items < s._window.maxlen:
            self.low = -math.inf
            return math.inf  # the warm-up returns None for the next score
        centre = s._mean[0]
        if self._would(centre):
            self.low = math.inf
            return -math.inf
        d = A.bisect_tau(lambda v: self._would(centre - v), 0.0, A.HIGH)
        self.low = centre - d
        return A.bisect_tau(self._would, centre, A.HIGH)

    def expected(self, x, tau):
        return x > tau or x < self.low


class StreamadTDigest(A.Target):
    """TDigestCalibrator(percentile_up=99, percentile_down=0) of calibrator_usage.ipynb; alarm when the
    output is 1.0. The digest takes the score before the percentiles are read. A score far above the 99th
    percentile moves that percentile by the same small amount whatever its size, so the reading is the
    99th percentile of a copy that has taken one such score. Below the reading the decision of a copy is
    used for the lower edge (percentile 0), which no campaign approaches."""

    eps = 1e-6

    def __init__(self, up=99, down=0):
        from streamad.process import TDigestCalibrator

        self.c = TDigestCalibrator(percentile_up=up, percentile_down=down)
        self.up = up
        self.name = f"StreamAD TDigestCalibrator(percentile_up={up}, percentile_down={down}) == 1"
        self.doc = "docs/source/example/calibrator_usage.ipynb"

    def step(self, x):
        v = self.c.normalize(x)
        return v is not None and v >= 1.0

    def _copy_would(self, v):
        c = copy.deepcopy(self.c)
        out = c.normalize(v)
        return out is not None and out >= 1.0

    def tau(self):
        c = self.c
        if len(c.score_deque) + 1 < c.score_deque.maxlen:
            return math.inf
        d = copy.deepcopy(c.score_stats)
        big = max(d.percentile(100) * 10.0, 1.0)
        d.update(big)
        return d.percentile(self.up)

    def expected(self, x, tau):
        if x > tau:
            return True
        if x < 1.01 * self.c.score_stats.percentile(0):
            return self._copy_would(x)
        return False


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
