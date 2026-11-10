"""Regression tests for threshold_online_v2 (synthetic data only)."""
import unittest

import numpy as np

import threshold_online as O
import threshold_online_v2 as O2
import threshold_rules as T


def run(model, s):
    out = np.empty(len(s))
    for i, x in enumerate(s):
        out[i] = model.tau()
        model.update(x)
    return out


class DailyTests(unittest.TestCase):
    def stream(self):
        rng = np.random.default_rng(0)
        s = 1.0 + np.abs(rng.standard_normal(2000))
        s[:500] += 5.0                                 # day 1 sits much higher than day 2
        s[:10] = -np.inf                               # warm-up
        s[600:900] = -np.inf                           # invalid stretch inside day 2 (e.g. a recording gap)
        return s

    def cfg(self):
        return {"tau0": 4.0, "p": 0.01}

    def test_frozen_online_daily_reaches_into_the_previous_day(self):
        s = self.stream()
        batch = T.daily_path(s, 4.0, 0.01, 500)
        online = run(O.Daily(self.cfg(), 500), s)
        self.assertGreater(abs(online[1000] - batch[1000]), 1.0)   # day 3 threshold built partly from day 1

    def test_v2_matches_batch_daily_path(self):
        s = self.stream()
        np.testing.assert_allclose(run(O2.Daily(self.cfg(), 500), s), T.daily_path(s, 4.0, 0.01, 500))

    def test_v2_keeps_threshold_over_a_day_without_finite_scores(self):
        s = np.r_[np.full(500, 2.0), np.full(500, -np.inf), np.full(500, 2.0)]
        tau = run(O2.Daily(self.cfg(), 500), s)
        self.assertEqual(tau[1000], tau[600])


if __name__ == "__main__":
    unittest.main()
