"""Tests for the round-2 monitors and benchmark additions (synthetic data only; no dataset is read)."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

import fi1_monitor_benchmark as B
import fi1_monitor_v4 as V4
import real_telemetry_detect_v2 as R2
from test_fi1_monitor_v3 import write_unit


def add_sensors(p, n=4000, d=6, test_excursion=None, calib_excursion=None):
    """Add scaled sensors Z (inside [-1, 1]) and action ranges to a fake unit."""
    p = Path(p)
    rng = np.random.default_rng(1)
    for f in p.glob("*_R1.npy"):
        key = f.name[: -len("_R1.npy")]
        z = (0.5 * np.tanh(rng.standard_normal((n, d)))).astype(np.float32)
        if key == "test_0" and test_excursion:
            a, b = test_excursion
            z[a:b, 2] = 1.5
        if key == "calib_1" and calib_excursion:
            a, b = calib_excursion
            z[a:b, 4] = 1.3
        np.save(p / f"{key}_Z.npy", z)
    np.save(p / "fit_vlow.npy", -np.ones(1, np.float32))
    np.save(p / "fit_vhigh.npy", np.ones(1, np.float32))


class V4Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = B.RESID
        B.RESID = Path(self.tmp.name)

    def tearDown(self):
        B.RESID = self.old
        self.tmp.cleanup()

    def pooled(self, monitor):
        u = B.Unit("u")
        info, rows, _ = B.evaluate_unit(u, monitor)
        return info, rows, B.pool([("u", rows)], 2.0, {"u": 2000})

    def test_single_state_path_reproduces_d1(self):
        p = write_unit(self.tmp.name)
        add_sensors(p)
        _, rows_a, a = self.pooled(V4.make("d1"))
        _, rows_b, b = self.pooled(V4.Single("d1"))
        for k in ("onset_detected", "detected", "unlabelled_alarm_share", "fa_per_day"):
            self.assertEqual(a[k], b[k], k)
        self.assertAlmostEqual(a["average_precision"], b["average_precision"])

    def test_plain_names_are_round1_monitors(self):
        import fi1_monitor_v3 as V3

        self.assertIs(type(V4.make("d1")), V3.D1)
        self.assertFalse(getattr(V4.make("mad+second"), "multistate", False))

    def test_pair_channels_share_the_budget_on_calibration(self):
        p = write_unit(self.tmp.name)
        add_sensors(p)
        u = B.Unit("u")
        m = V4.make("d1|second").fit(u)
        sp = u.spec
        cal = [st for st in u.streams("calib")]
        days = sum(st.steps for st in cal) / sp["spd"]
        eps = 0
        for st in cal:
            for x in m.states(u, B._arrs(st)):
                x = np.where(np.isnan(x), -np.inf, x)
                eps += len(R2.episodes(x > 1, sp["gap"]))
        self.assertLessEqual(eps, sp["budget"] * days + 1e-9)
        # each channel at half the budget: thresholds not below the full-budget ones
        t_full, _ = B.calibrate_unit(u, V4.make("d1"))
        self.assertGreaterEqual(m.tA, t_full)

    def test_union_pair_is_one_state(self):
        p = write_unit(self.tmp.name)
        add_sensors(p)
        u = B.Unit("u")
        m = V4.make("d1^second").fit(u)
        st = u.streams("test")[0]
        self.assertEqual(len(m.states(u, B._arrs(st))), 1)

    def test_onset_of_second_state_inside_running_first_state(self):
        """Rule 4: an episode of any state that starts inside an event is an onset; FA episodes add up."""
        spec = {"gap": 2, "step": 1.0}
        unit = B._CachedUnit("x", spec)
        a = np.zeros(100)
        a[10:60] = 5.0  # state A runs from before the event
        b = np.zeros(100)
        b[32:36] = 5.0  # state B starts inside the event
        b[80:85] = 5.0  # and once outside it
        lab = np.zeros(100, bool)
        lab[30:40] = True
        row = B.stream_rows(
            unit,
            B._CachedStream(100, {}),
            None,
            None,
            lab,
            np.ones(100, bool),
            [(30, 40, 0, 0)],
            np.random.default_rng(0),
            [a, b],
        )
        self.assertEqual(row["onset"], [True])
        self.assertEqual(row["fa"], 1)  # B's episode at 80; A's touches the event
        self.assertEqual(row["unlabelled_alarm"], 40 + 5)  # union of alarm time

    def test_oor_indicator(self):
        p = write_unit(self.tmp.name)
        add_sensors(p, test_excursion=(1000, 1200))
        u = B.Unit("u")
        st = u.streams("test")[0]
        g = V4.oor_indicator(u, B._arrs(st))
        self.assertTrue(np.all(g[:1000] == 0))
        np.testing.assert_allclose(g[1000:1200], 0.25)  # 0.5 beyond a span of 2
        out = B.outside_range(u, st)
        self.assertTrue(out[1000:1200].all() and not out[:1000].any())

    def test_oor_state_and_inner_masked(self):
        p = write_unit(self.tmp.name)
        add_sensors(p, test_excursion=(1000, 1200), calib_excursion=(100, 300))
        u = B.Unit("u")
        m = V4.make("oor:d1").fit(u)
        self.assertGreaterEqual(m.tO, V4.OOR_FLOOR)
        st = u.streams("test")[0]
        lab, valid, _ = B.labels_and_events(u, st)
        g, inner = B._states(u, st, m, valid)
        on = g > 1
        self.assertTrue(on[1100:1200].all())
        self.assertTrue(
            np.all(inner[on] == -np.inf)
        )  # the residual score is used only inside the range

    def test_rule5_descriptives_pooled(self):
        p = write_unit(self.tmp.name)
        add_sensors(p, test_excursion=(1000, 1200))
        _, _, row = self.pooled(V4.make("d1"))
        n_unl = 4000 - 100 - 0  # one 100-step event, all steps valid
        self.assertAlmostEqual(row["unlabelled_share_outside_range"], 200 / n_unl)
        self.assertEqual(row["events_starting_inside_range"], 1)
        self.assertEqual(row["onset_recall_inside_range"], 1.0)

    def test_rise_is_lagged_difference(self):
        p = write_unit(self.tmp.name)
        add_sensors(p)
        u = B.Unit("u")
        m = V4.single("rise2").fit(u)
        a = B._arrs(u.streams("test")[0])
        s = B.smooth(V4.V3.D1().fit(u).raw(u, a), u.spec["window"])
        r = m.smoothed(u, a)
        lag = 2 * u.spec["window"]
        np.testing.assert_allclose(r[lag + 20 :], (s[lag:] - s[:-lag])[20:])
        self.assertTrue(np.isnan(r[:lag]).all())

    def test_regime_scales_fall_back_without_actions_variation(self):
        p = write_unit(self.tmp.name)
        add_sensors(p)
        u = B.Unit("u")
        m = V4.single("regime2").fit(u)  # constant U: both clusters coincide
        a = B._arrs(u.streams("test")[0])
        self.assertTrue(np.all(np.isfinite(m.raw(u, a))))


if __name__ == "__main__":
    unittest.main()
