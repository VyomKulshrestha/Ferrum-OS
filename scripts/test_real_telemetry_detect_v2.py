"""Regression tests for real_telemetry_detect_v2 (synthetic data only; no dataset is read)."""
import unittest

import numpy as np

import real_telemetry_detect as R
import real_telemetry_detect_v2 as R2


class CalibrateTests(unittest.TestCase):
    def regime_scores(self):
        # three clean calibration days; the middle one sits in a higher regime for its whole length
        rng = np.random.default_rng(0)
        low = 1 + 0.1 * rng.standard_normal(8640)
        high = 3 + 0.1 * rng.standard_normal(8640)
        return [low, high, low.copy()]

    def test_frozen_calibrate_returns_threshold_with_a_day_in_alarm(self):
        segs = self.regime_scores()
        tau = R.calibrate(segs, 60, 2.0, 8640)
        share = float((np.concatenate(segs) > tau).mean())
        self.assertGreater(share, 0.15)          # old behaviour: a whole day above the threshold

    def test_v2_calibrate_stops_at_first_budget_break(self):
        segs = self.regime_scores()
        tau = R2.calibrate(segs, 60, 2.0, 8640)
        share = float((np.concatenate(segs) > tau).mean())
        self.assertLess(share, 1e-3)
        self.assertGreater(tau, 3.0)
        self.assertLessEqual(sum(len(R.episodes(s > tau, 60)) for s in segs), 2.0 * 3)

    def test_v2_agrees_when_episode_count_is_monotone(self):
        rng = np.random.default_rng(1)
        import real_telemetry_core as C
        segs = [C.rolling_mean(np.exp(0.8 * rng.standard_normal(10000)), 60)[59:] for _ in range(3)]
        self.assertEqual(R.calibrate(segs, 60, 2.0, 8640), R2.calibrate(segs, 60, 2.0, 8640))


if __name__ == "__main__":
    unittest.main()
