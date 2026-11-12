"""Tests for the tw1c campaign builder on a synthetic placement (no cached scores are read)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tw1c_signals as S


def _placement(n=60000, end=50000, tau0=10.0):
    rng = np.random.default_rng(0)
    return S.Placement(0, "synthetic", tau0, 4.0 + rng.random(n), end, 0)


def test_rows_and_windows():
    p = _placement()
    X, info, meta = S.build(p, campaign=4000, history=3000, tail=50)
    assert (
        X.shape[0] == len(info) == len(S.CAMPAIGNS) * (1 + len(S.MAGS) * len(S.LEADS))
    )
    assert meta["steps"] == X.shape[1]
    s0 = p.end - S.REG_LEAD - 4000 - 3000
    clean = p.stream[s0 : s0 + X.shape[1]]
    ctrl = next(r for r in info if r["campaign"] == "control" and r["mag"] is None)
    assert np.array_equal(X[ctrl["row"]], clean)
    # the registered terminal start sits at the lead of 1,000 steps after the campaign
    lead = next(r for r in info if r["campaign"] == "control" and r["lead"] == 1000)
    assert s0 + lead["terminal_start"] == p.end


def test_campaigns_only_raise_inside_their_window():
    p = _placement()
    X, info, _ = S.build(p, campaign=4000, history=3000, tail=50)
    ctrl = X[
        next(r["row"] for r in info if r["campaign"] == "control" and r["mag"] is None)
    ]
    for r in info:
        d = X[r["row"]] - ctrl
        assert (d >= 0).all()
        outside = np.ones(len(d), bool)
        outside[3000:7000] = False
        if r["mag"] is not None:
            outside[r["terminal_start"] : r["terminal_start"] + S.TERMINAL] = False
        assert not d[outside].any(), r["name"]


def test_campaign_shapes():
    p = _placement()
    X, info, meta = S.build(p, campaign=4000, history=3000, tail=50)
    row = {(r["campaign"], r["mag"], r["lead"]): r["row"] for r in info}
    seg = slice(3000, 7000)
    assert np.allclose(X[row[("frog_hold", None, None)]][seg], 0.97 * p.tau0)
    frog = X[row[("frog", None, None)]][seg]
    assert abs(frog[-1] - 0.97 * p.tau0) < 1e-9 and frog[0] < 5.0
    loud = X[row[("loud", None, None)]][seg]
    assert (loud == 2 * p.tau0).sum() == 2 * 33
    subl = X[row[("subl", None, None)]][seg]
    assert (subl == 2 * p.tau0).sum() == 8 * 12
    t = X[row[("control", 1.5, 0)]]
    assert np.allclose(t[7000 : 7000 + S.TERMINAL], 1.5 * p.tau0)
    assert meta["history_median"] < 5.0


def test_names_are_unique():
    _, info, _ = S.build(
        _placement(), campaign=4000, history=3000, tail=50, terminal=1000
    )
    names = [r["name"] for r in info]
    assert len(set(names)) == len(names)
    assert any(n.endswith("_t1000") for n in names)
