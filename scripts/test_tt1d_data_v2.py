"""Regression tests for tt1d_data_v2 (synthetic recordings only; no file of the dataset is read)."""
import unittest

import numpy as np

import real_telemetry_core as C
import real_telemetry_detect as R
import tt1d_data as TD
import tt1d_data_v2 as TD2

WINDOW = 30                                   # tt1d ProvICS smoothing: 60 s at a 2 s step


def recording(rng):
    """1 s rows; the process level steps up by 5 scale units during a 120 s recording gap."""
    t = np.r_[np.arange(0, 4000.0), np.arange(4120.0, 8000.0)]
    x = 0.05 * rng.standard_normal((len(t), 4))
    x[t >= 4120.0] += 5.0
    u = np.zeros((len(t), 2), np.float32)
    return t, np.concatenate([x, u], 1).astype(np.float32)


def scores(rng):
    t, values = recording(rng)
    _, grid, valid = TD._p_grid(t, values)
    z, v = grid[:, :4], grid[:, 4:]
    fit = [(0.05 * rng.standard_normal((3000, 4)).astype(np.float32), np.zeros((3000, 2), np.float32))]
    scorer = R.Scorer(C.Persistence((1, 5), 3), fit)
    scorer.residual_scales(fit)
    s = R.smooth(scorer.raw(z, v)[0]["D1"], WINDOW)
    s[:R.WARMUP] = np.nan
    clean = s[np.isfinite(s) & valid]
    tau0 = float(np.quantile(clean[:1500], 0.999)) * 1.5      # well above anything the clean data reach
    return s, valid, tau0


class ProvicsGapTests(unittest.TestCase):
    def test_frozen_mask_leaves_gap_artefact_alarms_on_valid_steps(self):
        s, valid, tau0 = scores(np.random.default_rng(0))
        self.assertGreater(int((~valid).sum()), 0)
        alarm = np.where(np.isfinite(s) & valid, s, -np.inf) > tau0
        self.assertGreater(int(alarm.sum()), 10)             # every alarm sits right after the gap
        first_valid_after_gap = int(np.flatnonzero(~valid[:-1] & valid[1:])[0]) + 1
        self.assertTrue((np.flatnonzero(alarm) >= first_valid_after_gap).all())
        self.assertTrue((np.flatnonzero(alarm) < first_valid_after_gap + TD2.score_lookback(WINDOW)).all())

    def test_v2_mask_removes_them_and_keeps_the_rest(self):
        s, valid, tau0 = scores(np.random.default_rng(0))
        v2 = TD2.provics_valid_v2(valid, WINDOW)
        alarm = np.where(np.isfinite(s) & v2, s, -np.inf) > tau0
        self.assertEqual(int(alarm.sum()), 0)
        self.assertEqual(int((valid & ~v2).sum()), TD2.score_lookback(WINDOW))

    def test_extend_invalid_ignores_stream_start_and_clips_at_end(self):
        valid = np.array([True, False, False, True, True, True, False, True], bool)
        np.testing.assert_array_equal(TD2.extend_invalid(valid, 2),
                                      [True, False, False, False, False, True, False, False])


if __name__ == "__main__":
    unittest.main()
