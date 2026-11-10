"""Regression tests for threshold_rules_tt1c_v2 (synthetic data only)."""
import unittest

import numpy as np

import threshold_rules as T
import threshold_rules_tt1c as N
import threshold_rules_tt1c_v2 as N2


def alarms_split_by_exactly_gap():
    # 40 alarms, exactly GAP quiet steps, 30 alarms: one 130-step episode under threshold_rules._episodes
    return np.r_[np.ones(40, bool), np.zeros(N.GAP, bool), np.ones(30, bool), np.zeros(10, bool)]


class EpisodeTests(unittest.TestCase):
    def test_batch_definition_merges_runs_across_gap_quiet_steps(self):
        self.assertEqual(T._episodes(alarms_split_by_exactly_gap(), N.GAP), [(0, 40 + N.GAP + 30)])

    def test_frozen_online_tracker_splits_them_and_misses_the_event(self):
        ep = N._Episodes()
        held = [ep.step(bool(a)) for a in alarms_split_by_exactly_gap()]
        self.assertFalse(any(held))                  # neither 40 nor 30 reaches EVENT_L = 60

    def test_v2_tracker_merges_them_and_holds_from_event_length(self):
        ep = N2._Episodes()
        a = alarms_split_by_exactly_gap()
        held = np.array([ep.step(bool(x)) for x in a])
        first_held = int(np.flatnonzero(held)[0])
        self.assertEqual(first_held, 40 + N.GAP)     # first alarm after the merged episode has lasted EVENT_L
        self.assertTrue(held[first_held:first_held + 30].all())

    def test_v2_tracker_hold_rises_less_through_the_event(self):
        cfg = {"tau0": 1.0, "eta": 0.01, "p": 0.001}
        s = np.where(alarms_split_by_exactly_gap(), 5.0, 0.0)
        old, new = N.TrackerHold(cfg), N2.TrackerHold(cfg)
        for x in s:
            old.update(x)
            new.update(x)
        self.assertGreater(old.tau(), new.tau())

    def test_v2_agrees_when_runs_are_far_apart(self):
        rng = np.random.default_rng(0)
        a = rng.random(20000) < 0.002
        old, new = N._Episodes(), N2._Episodes()
        gaps = np.diff(np.flatnonzero(a))
        if (gaps == N.GAP + 1).any():
            self.skipTest("random stream hit the boundary case")
        self.assertEqual([old.step(bool(x)) for x in a], [new.step(bool(x)) for x in a])


if __name__ == "__main__":
    unittest.main()
