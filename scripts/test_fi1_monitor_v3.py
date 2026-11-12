"""Tests for the fi1 monitor benchmark and candidates (synthetic data only; no dataset is read)."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import fi1_monitor_benchmark as B
import fi1_monitor_v3 as V
import real_telemetry_detect as R


def write_unit(root, name="u", d=6, n=4000, seed=0, spec=None, bad_channel=None):
    """A fake residual cache: scale, calib and one test stream with one labelled event."""
    rng = np.random.default_rng(seed)
    p = Path(root) / name
    p.mkdir(parents=True)
    spec = spec or {
        "kind": "stream",
        "step": 1.0,
        "window": 5,
        "gap": 5,
        "budget": 2.0,
        "spd": 2000,
        "role": "selection",
    }
    groups = {}
    for group, count in (("scale", 2), ("calib", 2), ("test", 1)):
        rows = []
        for i in range(count):
            r1 = rng.standard_normal((n, d)).astype(np.float32)
            r5 = rng.standard_normal((n, d)).astype(np.float32)
            if bad_channel is not None and group == "calib" and i == 1:
                r1[:, bad_channel] *= 5
                r5[:, bad_channel] *= 5
            r1[:6] = r5[:10] = 0
            key = f"{group}_{i}"
            np.save(p / f"{key}_R1.npy", r1)
            np.save(p / f"{key}_R5.npy", r5)
            np.save(p / f"{key}_U.npy", np.zeros((n, 1), np.float32))
            if group == "test":
                y = np.zeros(n, np.int8)
                y[2000:2100] = 1
                r1[2000:2100, 0] += 30
                np.save(p / f"{key}_R1.npy", r1)
                np.save(p / f"{key}_y.npy", y)
            rows.append({"key": key, "steps": n})
        groups[group] = rows
    np.save(p / "sig1.npy", np.ones(d, np.float32))
    np.save(p / "sig5.npy", np.ones(d, np.float32))
    np.save(p / "fit_low.npy", -np.ones(d, np.float32))
    np.save(p / "fit_high.npy", np.ones(d, np.float32))
    (p / "meta.json").write_text(
        json.dumps({"unit": name, "spec": spec, "groups": groups}), encoding="utf-8"
    )
    return p


class FakeUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = B.RESID
        B.RESID = Path(self.tmp.name)

    def tearDown(self):
        B.RESID = self.old
        self.tmp.cleanup()

    def test_d1_matches_registered_scorer_formula(self):
        write_unit(self.tmp.name)
        u = B.Unit("u")
        a = u.streams("test")[0].arrays()
        raw = (
            V.make("d1")
            .fit(u)
            .raw(u, {k: (None if v is None else np.asarray(v)) for k, v in a.items()})
        )
        S1, S5 = np.abs(np.asarray(a["R1"])), np.abs(np.asarray(a["R5"]))
        S1[:10] = S5[:10] = 0
        top = lambda A: -np.sort(-A, 1)[:, :3].mean(1)
        np.testing.assert_allclose(raw, top(S1) + top(S5))

    def test_event_detected_and_metrics_consistent(self):
        write_unit(self.tmp.name)
        u = B.Unit("u")
        info, rows, sealed = B.evaluate_unit(u, V.make("d1"))
        self.assertEqual(rows[0]["found"], [True])
        self.assertEqual(rows[0]["onset"], [True])
        row = B.pool([("u", rows)], 2.0, {"u": 2000})
        self.assertEqual(row["events"], 1)
        self.assertLessEqual(row["unlabelled_alarm_share"], 1.0)
        self.assertGreater(row["average_precision"], 0.5)
        self.assertEqual(len(row["chance_any"]["ci95"]), 2)

    def test_stable_drops_channel_whose_scale_moves_between_recordings(self):
        write_unit(self.tmp.name, bad_channel=3)
        u = B.Unit("u")
        m = V.make("stable").fit(u)
        self.assertEqual(m.dropped, [3])
        self.assertNotIn(3, list(m.keep))

    def test_loro_threshold_not_below_pooled(self):
        write_unit(self.tmp.name, bad_channel=2)
        u = B.Unit("u")
        t_pool, _ = B.calibrate_unit(u, V.make("d1"))
        t_loro, _ = B.calibrate_unit(u, V.make("loro"))
        self.assertGreaterEqual(t_loro, t_pool)

    def test_combined_name_uses_both_parts(self):
        write_unit(self.tmp.name, bad_channel=1)
        u = B.Unit("u")
        m = V.make("stable+second").fit(u)
        self.assertEqual(m.dropped, [1])
        S = np.array([[9.0, 1.0, 2.0, 3.0, 0.0]])
        self.assertAlmostEqual(float(m.combine(S)[0]), 2.0)


class ClipTests(unittest.TestCase):
    """clip_correction must equal the residual of a forecaster that clips its level inputs."""

    def check(self, gbr):
        import real_telemetry_core as C

        rng = np.random.default_rng(4)
        T, d, m = 3000, 4, 2
        U = rng.standard_normal((T, m)).astype(np.float32)
        Z = np.cumsum(0.1 * rng.standard_normal((T, d)), 0)
        Z = ((Z - Z.mean(0)) / Z.std(0)).astype(np.float32)
        wm = C.Forecaster((1, 5), 3, use_actions=True, gbr=gbr).fit([(Z, U)])
        low, high = Z.min(0), Z.max(0)

        class Clipped(C.Forecaster):
            def _design(self, Zx, Vx, t, h):
                A = super()._design(Zx, Vx, t, h)
                A[:, :d] = np.clip(A[:, :d], low, high)
                return A

        cl = Clipped((1, 5), 3, use_actions=True, gbr=gbr)
        cl.ridge, cl.boost = wm.ridge, wm.boost
        Zt = Z[:800].copy()
        Zt[300:500, 1] += 4.0  # far outside the fit range
        for h in (1, 5):
            base = C.residuals(wm, Zt, U[:800], h)
            got = V.clip_correction(
                base, Zt.astype(np.float64), wm.ridge[h].coef_[:, :d], low, high, h
            )
            want = C.residuals(cl, Zt, U[:800], h)
            np.testing.assert_allclose(got, want, atol=2e-4)
            self.assertGreater(np.abs(got - base).max(), 1e-3)

    def test_ridge_only(self):
        self.check(None)

    def test_with_boosted_trees(self):
        self.check(
            dict(n_estimators=10, num_leaves=7, learning_rate=0.1, min_child_samples=20)
        )


class MetricTests(unittest.TestCase):
    def test_onset_not_credited_inside_running_alarm(self):
        spec = {"gap": 2, "step": 1.0}
        unit = B._CachedUnit("x", spec)
        s = np.zeros(100)
        s[10:60] = 5.0  # one alarm episode from step 10 to 59
        lab = np.zeros(100, bool)
        lab[30:40] = True
        row = B.stream_rows(
            unit,
            B._CachedStream(100, {}),
            s,
            1.0,
            lab,
            np.ones(100, bool),
            [(30, 40, 0, 0)],
            np.random.default_rng(0),
        )
        self.assertEqual(row["found"], [True])
        self.assertEqual(row["onset"], [False])
        self.assertEqual(row["fa"], 0)  # the episode touches the event
        self.assertEqual(row["unlabelled_alarm"], 40)

    def test_shift_counts_match_brute_force(self):
        rng = np.random.default_rng(3)
        alarm = rng.random(500) < 0.05
        starts = rng.random(500) < 0.01
        events = [(10, 40, 0, 0), (480, 500, 0, 1), (200, 201, 0, 2)]
        a, o = B._shift_counts(alarm, starts, events, np.random.default_rng(5))
        ks = np.random.default_rng(5).integers(0, 500, B.SHIFTS)
        for j, k in enumerate(ks[:20]):
            ra, rs = np.roll(alarm, k), np.roll(starts, k)
            self.assertEqual(a[j], sum(ra[x:y].any() for x, y, *_ in events))
            self.assertEqual(o[j], sum(rs[x:y].any() for x, y, *_ in events))

    def test_smooth_is_registered_smoothing(self):
        raw = np.arange(50, dtype=float)
        s = B.smooth(raw, 5)
        ref = R.smooth(raw, 5)
        self.assertTrue(np.isnan(s[:10]).all())
        np.testing.assert_array_equal(s[10:], ref[10:])

    def test_verdict_rule(self):
        base = {
            k: {"onset_recall": 0.5, "unlabelled_alarm_share": 0.1}
            for k in ("hai-20.07", "provics", "x")
        }
        better = {
            k: {"onset_recall": 0.6, "unlabelled_alarm_share": 0.05} for k in base
        }
        self.assertTrue(B.verdict(base, better)["improved"])
        worse_one = dict(
            better, x={"onset_recall": 0.4, "unlabelled_alarm_share": 0.05}
        )
        self.assertFalse(B.verdict(base, worse_one)["improved"])
        noisier = {
            k: {"onset_recall": 0.7, "unlabelled_alarm_share": 0.2} for k in base
        }
        self.assertFalse(B.verdict(base, noisier)["improved"])


if __name__ == "__main__":
    unittest.main()
