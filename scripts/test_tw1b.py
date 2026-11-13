"""Tests for the tw1b drivers: the budget search, the terminal rule of the SPOT authors' driver, the frog
planner against the authors' script (when its copy and dependencies are present), and the batch's job list."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tw1_adapters as A
import tw1b_batch as batch
import tw1b_score_level_dev as B
import tw1b_spot_authors as SP


def test_search_finds_most_sensitive_setting_within_budget():
    seen = []

    def meets(u):
        seen.append(u)
        return u >= 3.3

    u, reachable = B.search(meets, 1.0, 7.0, halvings=20)
    assert reachable and 3.3 <= u < 3.3 + 6.0 / 2**19
    assert seen[:2] == [7.0, 1.0]


def test_search_ends():
    assert B.search(lambda u: False, 1.0, 7.0) == (7.0, False)
    assert B.search(lambda u: True, 1.0, 7.0) == (1.0, True)


def test_parameter_scales_run_from_sensitive_to_insensitive():
    for key in B.CALIBRATED:
        _, param, (lo, hi), _ = B.TARGETS[key]
        a, b = param(lo), param(hi)
        if key in ("pysad_spot", "libspot"):
            assert a > b  # a larger risk q alarms more
        else:
            assert a < b  # a lower quantile or cut alarms more


def test_campaign_table_has_the_four_frog_distances():
    fracs = sorted(B.CAMPAIGNS[c][1] for c in B.FROGS)
    assert fracs == [0.97, 0.98, 0.99, 0.995]
    assert all(B.CAMPAIGNS[c][0] == "frog_cap" for c in B.FROGS)


def test_terminal_hits_first_step_rule_and_run(monkeypatch):
    K = {"mags": [1.05, 1.25, 1.5, 2.0]}
    calls = []

    def fake_run(init, data):
        calls.append(len(data))
        alarm = np.zeros(len(data), bool)
        alarm[-1] = (
            data[-1] > 14.0
        )  # a stand-in threshold of 14 on the last terminal step
        return alarm, np.zeros(len(data))

    monkeypatch.setattr(SP, "run_script", fake_run)
    terminal = np.array([1.0, 1.0, 1.0])
    hits, how = SP.terminal_hits(
        None, np.zeros(5), terminal, th_before=13.0, K=K, tau0=10.0
    )
    # 10.5 and 12.5 are below the threshold before the terminal step: each is run; 15 and 20 exceed it
    assert how == ["run", "run", "first step", "first step"]
    assert hits == [False, False, True, True]
    assert calls == [8, 8]


def _script_available():
    if not SP.SCRIPT.exists():
        return False
    try:
        import matplotlib  # noqa: F401
        import pandas  # noqa: F401
        import scipy  # noqa: F401
        import tqdm  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not _script_available(),
    reason="the authors' script copy or its dependencies are absent",
)
def test_planner_matches_the_script_on_a_planned_frog():
    rng = np.random.default_rng(1)
    init = rng.gamma(4.0, 1.0, 3000)
    stream = rng.gamma(4.0, 1.0, 400)
    p = SP.Planner(init)
    planned = []
    for k in range(len(stream)):
        if k < 300:
            stream[k] = max(stream[k], 0.97 * p.s.extreme_quantile)
        p.step(float(stream[k]))
        planned.append(p.s.extreme_quantile)
    _, th = SP.run_script(init, stream)
    assert np.array_equal(np.array(planned), th)
    assert th[299] > th[0]  # the frog raised the threshold


def test_batch_jobs_and_done_status(tmp_path):
    names = [j[0] for j in batch.jobs(["calib", "B"])]
    assert len(names) == 7 * 7 + 7 * 7 * 2
    b_jobs = [j for j in batch.jobs(["B"])]
    assert all(j[3] is not None and j[3].name.startswith("mode") for j in b_jobs)
    f = tmp_path / "x.json"
    assert not batch.done_status(f)
    f.write_text(json.dumps({"evaluations": []}), encoding="utf-8")
    assert not batch.done_status(f)
    f.write_text(json.dumps({"chosen": 0.999}), encoding="utf-8")
    assert batch.done_status(f)
    f.write_text("{", encoding="utf-8")
    assert not batch.done_status(f)


# ------------------------------------------------------------------ amendment 5: the band reading
LEVEL, UNIT = 10.0, 0.5


def _band(centre_log, half_width):
    """A synthetic calibrator above LEVEL: its statistic peaks at log(v - LEVEL) = centre_log and it alarms
    only where log(v - LEVEL) lies within half_width of the peak."""

    def height(v):
        return -((math.log(v - LEVEL) - centre_log) ** 2) if v > LEVEL else -math.inf

    def would(v):
        return v > LEVEL and abs(math.log(v - LEVEL) - centre_log) <= half_width

    return would, height


def _old_grid_hits(would):
    """The search of tw1a's Gaussian-tail reading: LEVEL + UNIT * 1.05**k for k in -40..699."""
    return [k for k in range(-40, 700) if would(LEVEL + UNIT * 1.05**k)]


@pytest.mark.parametrize("half_width", [1e-3, 1e-6, 1e-10])
def test_band_reading_finds_a_band_the_old_grid_steps_over(half_width):
    # the band sits half-way between two points of the old 5% grid, and is far narrower than one step
    centre_log = math.log(UNIT * 1.05**10.5)
    would, height = _band(centre_log, half_width)
    assert _old_grid_hits(would) == []
    tau, high = A.band_reading(would, height, LEVEL, cap=1e12)
    lo_edge = LEVEL + math.exp(centre_log - half_width)
    hi_edge = LEVEL + math.exp(centre_log + half_width)
    # the edges are bisected to 1e-13 relative (tw1_adapters.bisect_tau)
    assert not would(tau) and would(tau * (1 + 2e-13))
    assert tau == pytest.approx(lo_edge, rel=1e-12)
    assert high == pytest.approx(hi_edge, rel=1e-12)
    assert would(high) and not would(high * (1 + 2e-13))


def test_band_resolution_is_the_stated_one():
    # a band as wide as the stated resolution is still found
    centre_log = math.log(UNIT * 1.05**200.5)
    would, height = _band(centre_log, A.BAND_RESOLUTION / 2)
    tau, high = A.band_reading(would, height, LEVEL, cap=1e12)
    assert math.isfinite(tau) and high is not None


def test_band_reading_says_explicitly_when_nothing_alarms():
    would = lambda v: False  # noqa: E731
    tau, high = A.band_reading(would, lambda v: -abs(v - 50.0), LEVEL, cap=1e12)
    assert isinstance(tau, A.NoAlarm) and tau.cap == 1e12 and high is None
    assert not math.isfinite(tau) and not 1e300 > tau


def test_band_reading_on_a_half_line():
    tau, high = A.band_reading(lambda v: v > 37.5, lambda v: v, LEVEL, cap=1e12)
    assert tau == pytest.approx(37.5, rel=1e-12) and high == math.inf


# ------------------------------------------------------------------ amendment 5: no silent substitute
class _Quiet(A.Target):
    """A target with a fixed reading that alarms exactly on scores above it (never, for an infinite one)."""

    name = "quiet"

    def __init__(self, reading):
        self.reading = reading

    def step(self, x):
        return x > self.reading

    def tau(self):
        return self.reading


K_SMALL = {
    "lead": 3,
    "campaign": 8,
    "terminal": 2,
    "mags": [1.05, 2.0],
    "loud": [4, 1, 2.0],
    "subl": [4, 1, 2.0],
    "gap": 1,
    "frog_frac": 0.97,
}


@pytest.mark.parametrize(
    "reading, reason",
    [
        (A.NoAlarm(1e12), "no alarming score above the current level up to 1e+12"),
        (math.inf, "reading is infinite"),
        (-math.inf, "minus infinity"),
    ],
)
@pytest.mark.parametrize("mode, expected", [("frog_cap", 8), ("subl_cap", 2)])
def test_campaign_records_unplaced_steps_and_never_substitutes(
    reading, reason, mode, expected
):
    s = np.full(20, 1.0)
    stats = B.new_stats()
    res, during, _ = B.campaign(_Quiet(reading), s, 15, mode, K_SMALL, 10.0, stats)
    assert res["not_placed_steps"] == expected
    assert (
        res["largest_injected_over_tau0"] == 0.0
    )  # nothing was injected in place of the reading
    (why,) = res["not_placed_reasons"]
    assert reason in why and res["not_placed_reasons"][why] == expected
    # the consistency check ran against the target's own decision on every step
    assert stats["checked"] >= expected
    assert during.all() if reading == -math.inf else not during.any()


def test_campaign_places_the_frog_on_a_finite_reading():
    stats = B.new_stats()
    res, _, _ = B.campaign(
        _Quiet(5.0), np.full(20, 1.0), 15, "frog_cap", K_SMALL, 10.0, stats
    )
    assert res["not_placed_steps"] == 0
    assert res["largest_injected_over_tau0"] == pytest.approx(0.97 * 5.0 / 10.0)


def test_campaign_refuses_uncapped_modes():
    with pytest.raises(ValueError):
        B.campaign(
            _Quiet(5.0), np.full(20, 1.0), 15, "frog", K_SMALL, 10.0, B.new_stats()
        )
