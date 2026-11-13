"""Tests for the tw1b drivers: the budget search, the terminal rule of the SPOT authors' driver, the frog
planner against the authors' script (when its copy and dependencies are present), and the batch's job list."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
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
