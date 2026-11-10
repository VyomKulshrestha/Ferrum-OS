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


class SmoothingTests(unittest.TestCase):
    W = 60

    def frozen_pipeline(self, raw):                  # threshold_transfer_dev.d1 / tt1d_final.fit_scores
        s = R.smooth(raw, self.W)
        s[:R.WARMUP] = np.nan
        return s

    def raw(self):
        rng = np.random.default_rng(3)
        a = 2.0 + rng.random(500)
        a[:R.WARMUP] = 0.0                           # Scorer.raw writes zeros during the warm-up
        return a

    def test_frozen_score_at_first_scored_step_reads_future_samples(self):
        a = self.raw()
        b = a.copy()
        b[self.W - 1] += 1000.0                      # a sample 49 steps after the first scored step
        self.assertNotEqual(self.frozen_pipeline(a)[R.WARMUP], self.frozen_pipeline(b)[R.WARMUP])
        # and the warm-up zeros pull the head down: mean of 60 values of which 10 are zeros
        self.assertAlmostEqual(self.frozen_pipeline(a)[R.WARMUP], a[R.WARMUP:self.W].sum() / self.W)

    def test_v2_is_causal_and_ignores_warmup_zeros(self):
        a = self.raw()
        for k in range(R.WARMUP, 200):
            b = a.copy()
            b[k + 1:] += 1000.0                      # change only the future of step k
            self.assertEqual(R2.smooth_after_warmup(a, self.W)[k], R2.smooth_after_warmup(b, self.W)[k])
        self.assertEqual(R2.smooth_after_warmup(a, self.W)[R.WARMUP], a[R.WARMUP])
        self.assertTrue(np.isnan(R2.smooth_after_warmup(a, self.W)[:R.WARMUP]).all())

    def test_v2_equals_frozen_after_head(self):
        a = self.raw()
        k = R.WARMUP + self.W - 1
        np.testing.assert_allclose(R2.smooth_after_warmup(a, self.W)[k:], self.frozen_pipeline(a)[k:], rtol=1e-12)


if __name__ == "__main__":
    unittest.main()
