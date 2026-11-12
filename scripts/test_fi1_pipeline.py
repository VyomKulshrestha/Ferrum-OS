"""fi1 workstream B: regression tests for the defects of the second pipeline audit, and property tests for
code paths that paper numbers depend on. Synthetic data only, except FrozenDigestTests, which hashes the
frozen files on disk. Run from scripts/: python -m pytest -q test_fi1_pipeline.py

Findings and their effects: docs/research/fi1_reports/pipeline_round1.md.
"""

from __future__ import annotations

import json
import types
import unittest

import numpy as np

import real_telemetry_core as C
import real_telemetry_core_v2 as C2
import real_telemetry_detect as R
import real_telemetry_detect_v2 as R2
import real_telemetry_injections as I
import threshold_online as O
import threshold_online_v2 as O2
import threshold_rules as T
import threshold_rules_ext as E
import threshold_rules_tt1c as N
import tt1_final as F
import tt1b_final as B
import tt1d_data as TD
import tt1d_final as M
import tt1d_final_v2 as M2


# ---------------------------------------------------------------- reference implementations
def brute_episodes(alarm, gap):
    """Alarm runs separated by at most `gap` quiet steps form one episode; (start, end) with end exclusive."""
    out, start, last = [], None, None
    for i, a in enumerate(alarm):
        if not a:
            continue
        if last is None or i - last - 1 > gap:
            if start is not None:
                out.append((start, last + 1))
            start = i
        last = i
    if start is not None:
        out.append((start, last + 1))
    return out


def brute_runs(key):
    out, i = [], 0
    while i < len(key):
        j = i
        while j < len(key) and key[j] == key[i]:
            j += 1
        if key[i] != 0:
            out.append((i, j, int(key[i])))
        i = j
    return out


def online(model, s):
    tau = np.empty(len(s))
    for i, x in enumerate(s):
        tau[i] = model.tau()
        model.update(x)
    return tau


def stream(n=6000, seed=0, warm=10):
    rng = np.random.default_rng(seed)
    s = 1.0 + np.abs(rng.standard_normal(n))
    s[rng.integers(warm, n, 40)] += 6.0
    s[:warm] = -np.inf
    return s


CFG = {"tau0": 3.0, "tau_half": 3.5, "p": 0.01, "eta": 0.05, "m0": 1.6}


# ---------------------------------------------------------------- defects
class CampaignEpisodeTests(unittest.TestCase):
    """F1: tt1d_final.play splits an alarm episode at exactly `gap` quiet steps; play_v2 merges as _episodes."""

    def fake_setup(self, gap=5):
        class Static:
            def __init__(self, t):
                self.t = t

            def tau(self):
                return self.t

            def update(self, x):
                pass

        rules = types.SimpleNamespace(make=lambda rule, cfg, calib: Static(cfg["tau0"]))
        return types.SimpleNamespace(
            rules=rules,
            gap=gap,
            lead=10,
            campaign=100,
            terminal=5,
            loud=(50, 2, 2.0),
            subl=(20, 1, 2.0),
        )

    def run_both(self, quiet):
        S = self.fake_setup()
        s = np.ones(200)
        end = 150
        c0 = end - S.lead - S.campaign
        s[c0 + 10 : c0 + 15] = 5.0  # an alarm run of 5 steps
        s[c0 + 15 + quiet : c0 + 20 + quiet] = (
            5.0  # a second run after `quiet` quiet steps
        )
        cfg = {"tau0": 3.0}
        old = M.play(S, "frozen", cfg, None, s, end, "frog")
        new = M2.play_v2(S, "frozen", cfg, None, s, end, "frog")
        batch = len(T._episodes(s[c0 : c0 + S.campaign] > 3.0, S.gap))
        return old, new, batch

    def test_exactly_gap_quiet_steps_is_one_episode(self):
        old, new, batch = self.run_both(quiet=5)
        self.assertEqual(batch, 1)
        self.assertEqual(new[3], 1)
        self.assertEqual(new[4], 15)  # longest episode spans both runs
        self.assertEqual(old[3], 2)  # the frozen counter (documented defect)
        self.assertEqual(
            old[:3], new[:3]
        )  # detections, inflation and alarm steps are unaffected

    def test_agrees_with_batch_otherwise(self):
        for quiet in (1, 4, 6, 30):
            old, new, batch = self.run_both(quiet)
            self.assertEqual(new[3], batch)
            self.assertEqual(old[3], batch)

    def test_exploratory_copies_fixed(self):
        import tt1e_defense_dev as TE
        import tt1g_baselines_dev as TG

        # tt1g: tep59 setup, frozen rule; two natural exceedance runs exactly gap quiet steps apart
        S = TG.S
        end = S.lead + S.campaign + 10
        s = np.ones(end + S.terminal)
        c0 = end - S.lead - S.campaign
        s[c0 + 100 : c0 + 105] = 5.0
        s[c0 + 105 + S.gap : c0 + 110 + S.gap] = 5.0
        out = TG.play(
            "frozen",
            {"tau0": 3.0, "p": 0.01, "eta": 0.1},
            np.ones(100),
            {},
            s,
            end,
            "frog",
        )
        self.assertEqual(out["alarm_episodes"], 1)
        # tt1e: static ceiling rule (no learning), the 24 h closed campaign of tt1b_frog_dev
        end = TE.G.LEAD + TE.G.CAMPAIGN + 10
        s = np.ones(end + TE.X.ATTACK)
        c0 = end - TE.G.LEAD - TE.G.CAMPAIGN
        s[c0 + 100 : c0 + 105] = 5.0
        s[c0 + 105 + TE.X.GAP : c0 + 110 + TE.X.GAP] = 5.0
        cfg = {"tau0": 3.0, "p": 0.01, "eta": 0.1}
        res = TE.play("static_1.1", cfg, np.ones(100), s, end, "closed")
        self.assertEqual(res[3], 1)
        self.assertEqual(res[4], 5 + TE.X.GAP + 5)


class MissReductionTests(unittest.TestCase):
    """F0: resamples in which the baseline misses nothing are scored as 0.0 relative miss reduction."""

    def test_rt2_hai2103_d1_vs_dr(self):
        dr, d1 = (
            [True] * 46 + [False] * 4,
            [True] * 50,
        )  # rt2 HAI 21.03: DR 46/50, D1 50/50
        old = C.paired_event_bootstrap(dr, d1, reps=10_000, level=0.9875, seed=0)
        zero = C2.paired_event_bootstrap(dr, d1, reps=10_000, level=0.9875, seed=0)
        drop = C2.paired_event_bootstrap(
            dr, d1, reps=10_000, level=0.9875, seed=0, undefined="drop"
        )
        self.assertEqual(
            old["miss_reduction_interval"], [0.0, 1.0]
        )  # the stored rt2 interval
        self.assertEqual(
            {k: zero[k] for k in old}, old
        )  # "zero" reproduces the frozen function exactly
        self.assertGreater(
            zero["undefined_share"], (1 - 0.9875) / 2
        )  # the convention alone sets the lower end
        self.assertEqual(drop["miss_reduction_interval"], [1.0, 1.0])

    def test_no_effect_when_baseline_always_misses(self):
        rng = np.random.default_rng(20)
        a, b = rng.random(60) < 0.6, rng.random(60) < 0.8
        z = C2.paired_event_bootstrap(a, b, seed=3)
        d = C2.paired_event_bootstrap(a, b, seed=3, undefined="drop")
        self.assertEqual(z["undefined_share"], 0.0)
        self.assertEqual(z["miss_reduction_interval"], d["miss_reduction_interval"])


class RollingMeanPrecisionTests(unittest.TestCase):
    """F2: float32 cumulative sums lose precision on long streams (D2/D3 classifier features)."""

    def test_float32_long_stream(self):
        a = np.abs(np.random.default_rng(0).standard_normal((400_000, 2))).astype(
            np.float32
        )
        ref = C.rolling_mean(a.astype(np.float64), 10)
        old = C.rolling_mean(a, 10)
        new = C2.rolling_mean(a, 10)
        self.assertGreater(
            float(np.abs(old - ref).max()), 1e-3
        )  # the frozen function (documented defect)
        self.assertLess(float(np.abs(new - ref).max()), 1e-6)
        self.assertEqual(new.dtype, np.float32)

    def test_same_as_frozen_on_float64(self):
        a = np.random.default_rng(1).standard_normal(5000)
        for w in (1, 2, 10, 60):
            np.testing.assert_allclose(
                C2.rolling_mean(a, w), C.rolling_mean(a, w), rtol=0, atol=1e-12
            )


class ProvicsIntervalTests(unittest.TestCase):
    """Checked, correct: tt1d_data.provics_attack maps a ground-truth row to [a, b). The tuple assignment
    `a, b = max(a, 0), min(max(b, a + 1), n)` uses the unclamped a, so a row that ends before the recording keeps
    b <= 0 and is counted as unobserved (a first reading suspected the opposite; this pins it down)."""

    @staticmethod
    def frozen_interval(s, e, t0, n):
        a = int(np.floor((s - t0) / TD.P_STEP_SECONDS))
        b = int(np.ceil((max(e, s) + TD.P_TOLERANCE_SECONDS - t0) / TD.P_STEP_SECONDS))
        a, b = max(a, 0), min(max(b, a + 1), n)  # as tt1d_data.py:253
        return None if a >= n or b <= 0 else (a, b)

    def test_source_line_unchanged(self):
        import inspect

        self.assertIn(
            "a, b = max(a, 0), min(max(b, a + 1), len(grid))",
            inspect.getsource(TD.provics_attack),
        )

    def test_intervals(self):
        t0, n = 10_000.0, 500
        self.assertIsNone(
            self.frozen_interval(9_000.0, 9_100.0, t0, n)
        )  # ends (with tolerance) before t0
        self.assertEqual(
            self.frozen_interval(9_990.0, 9_995.0, t0, n), (0, 28)
        )  # overlaps the start: ceil((9995 + 60 - t0) / 2)
        self.assertIsNone(
            self.frozen_interval(11_000.0, 11_100.0, t0, n)
        )  # starts after the end
        rng = np.random.default_rng(2)
        for _ in range(500):
            s = float(rng.uniform(t0 - 200, t0 + 1100))
            e = s + float(rng.uniform(-5, 300))
            iv = self.frozen_interval(s, e, t0, n)
            if iv is not None:
                self.assertTrue(0 <= iv[0] < iv[1] <= n)
                self.assertLessEqual(iv[0] * TD.P_STEP_SECONDS + t0, max(s, t0))


class Tw1Tests(unittest.TestCase):
    """F3-F5: tw1 adapters and the tw1a chance reference."""

    def test_bisect_beyond_old_ceiling(self):
        import tw1_adapters as A

        self.assertAlmostEqual(A.bisect_tau(lambda v: v > 2.5) / 2.5, 1.0, places=9)
        self.assertAlmostEqual(
            A.bisect_tau(lambda v: v > 5e13) / 5e13, 1.0, places=9
        )  # read inf before
        self.assertEqual(A.bisect_tau(lambda v: False), float("inf"))
        self.assertEqual(A.bisect_tau(lambda v: True), float("-inf"))

    def test_river_quantile_zero_never_alarms(self):
        """river classifies with score >= (quantile.get() or inf): a quantile of 0.0 means no alarm."""
        import tw1_adapters as A

        t = A.RiverQuantile.__new__(A.RiverQuantile)
        for value, expect in ((0.0, float("inf")), (None, float("inf")), (1.5, 1.5)):
            t.f = types.SimpleNamespace(
                quantile=types.SimpleNamespace(get=lambda v=value: v)
            )
            self.assertEqual(t.tau(), expect)

    def test_chance_equals_rolled_count(self):
        import tw1a_score_level_dev as W

        rng = np.random.default_rng(3)
        for _ in range(20):
            n = int(rng.integers(50, 400))
            alarm = rng.random(n) < 0.05
            events = []
            for _ in range(4):
                a = int(rng.integers(0, n - 1))
                events.append((a, int(rng.integers(a + 1, n + 1)), 0))
            shifts = np.random.default_rng(9).integers(1, n, W.SHIFTS)
            brute = (
                sum(
                    sum(bool(np.roll(alarm, int(k))[a:b].any()) for a, b, _ in events)
                    for k in shifts
                )
                / W.SHIFTS
            )
            got = (
                W.chance(alarm, events, np.random.default_rng(9))
                if alarm.any()
                else 0.0
            )
            self.assertAlmostEqual(got, brute if alarm.any() else 0.0, places=12)

    def test_tt1f_chance_equals_rolled_count(self):
        import tt1f_batadal_trace as TB

        rng = np.random.default_rng(21)
        streams = []
        for _ in range(3):
            n = int(rng.integers(100, 300))
            alarm = rng.random(n) < 0.04
            ev = [
                (a, int(rng.integers(a + 1, min(n, a + 40) + 1)))
                for a in np.sort(rng.integers(0, n - 1, 3))
            ]
            streams.append((alarm, ev))
        got = TB.chance(streams, 2)
        shifts = np.random.default_rng(7)
        any_s, on_s = np.zeros(TB.SHIFTS), np.zeros(TB.SHIFTS)
        for alarm, ev in streams:
            starts = np.zeros(len(alarm), bool)
            for a, _ in T._episodes(alarm, 2):
                starts[a] = True
            offs = shifts.integers(1, len(alarm), TB.SHIFTS)
            for j, k in enumerate(offs):
                ra, rs = np.roll(alarm, int(k)), np.roll(starts, int(k))
                any_s[j] += sum(bool(ra[a:b].any()) for a, b in ev)
                on_s[j] += sum(bool(rs[a:b].any()) for a, b in ev)
        self.assertAlmostEqual(
            got["shifted_detected_mean_lo_hi"][0], float(any_s.mean()), places=12
        )
        self.assertAlmostEqual(
            got["shifted_onset_mean_lo_hi"][0], float(on_s.mean()), places=12
        )

    def test_chance_rng_independent_of_order(self):
        import tw1a_score_level_dev as W

        a = W.chance_rng(2, "target A", "run_1").integers(0, 10**9, 5)
        W.chance_rng(2, "target B", "run_1").integers(0, 10**9, 5)
        b = W.chance_rng(2, "target A", "run_1").integers(0, 10**9, 5)
        np.testing.assert_array_equal(a, b)
        c = W.chance_rng(2, "target A", "run_2").integers(0, 10**9, 5)
        self.assertFalse(np.array_equal(a, c))


# ---------------------------------------------------------------- episodes and events
class EpisodeTests(unittest.TestCase):
    def test_against_brute_force(self):
        import tw1a_score_level_dev as W

        rng = np.random.default_rng(4)
        for _ in range(1500):
            n, gap = int(rng.integers(1, 120)), int(rng.integers(0, 8))
            alarm = rng.random(n) < rng.uniform(0.02, 0.6)
            ref = brute_episodes(alarm, gap)
            self.assertEqual([tuple(map(int, e)) for e in T._episodes(alarm, gap)], ref)
            self.assertEqual([tuple(map(int, e)) for e in R.episodes(alarm, gap)], ref)
            self.assertEqual([tuple(e) for e in W.episodes(alarm, gap)], ref)

    def test_events(self):
        rng = np.random.default_rng(5)
        for _ in range(500):
            key = rng.integers(0, 3, int(rng.integers(1, 80))) * (rng.random() < 0.9)
            key = np.repeat(key, rng.integers(1, 5, len(key)))
            self.assertEqual(
                [tuple(map(int, e)) for e in TD.events(key)], brute_runs(key)
            )
            y = (key != 0).astype(int)
            self.assertEqual(
                [tuple(map(int, e)) for e in C.events(y)],
                [(a, b) for a, b, _ in brute_runs(y)],
            )


# ---------------------------------------------------------------- threshold rules: batch equals online
class RuleEquivalenceTests(unittest.TestCase):
    def test_tracker(self):
        s = stream()
        np.testing.assert_allclose(
            T.tracker_path(s, 3.0, 0.01, 0.05),
            online(O.Tracker(CFG, 0.05), s),
            rtol=0,
            atol=1e-9,
        )

    def test_one_sided_none_is_min_of_ceiling_and_tracker(self):
        s = stream()
        tau, permits = T.one_sided_path(s, 3.0, 0.01, 0.05, 1000, 60, permit="none")
        np.testing.assert_allclose(
            tau, np.minimum(3.0, T.tracker_path(s, 3.0, 0.01, 0.05))
        )
        self.assertEqual(permits, [])
        np.testing.assert_allclose(online(O.TightenOnly(CFG, 0.05), s), tau, atol=1e-9)

    def test_daily(self):
        s = stream(n=5500)
        np.testing.assert_allclose(
            T.daily_path(s, 3.0, 0.01, 1000), online(O2.Daily(CFG, 1000), s), atol=1e-12
        )

    def test_spot_dspot(self):
        rng = np.random.default_rng(6)
        calib = 1.0 + np.abs(rng.standard_normal(4000))
        s = stream()
        np.testing.assert_allclose(
            E.spot_path(s, calib, 0.01), online(O.Spot(CFG, calib), s), rtol=1e-12
        )
        np.testing.assert_allclose(
            E.dspot_path(s, calib, 0.01, 50),
            online(O.DSpot(CFG, calib, 50), s),
            rtol=1e-12,
        )
        np.testing.assert_allclose(
            E.spot_mle_path(s, calib, 0.01, refit=40),
            online(O.SpotMLE(CFG, calib, 40), s),
            rtol=1e-12,
        )

    def test_tt1c_path_matches_manual_loop(self):
        rng = np.random.default_rng(7)
        calib = 1.0 + np.abs(rng.standard_normal(4000))
        s = stream(n=3000)
        for rule in ("tracker_hold", "tracker_capped", "daily_excl", "spot_gr"):
            a = N.path(N.make(rule, CFG, calib, 1000, 50), s)
            b = online(
                N.make(rule, CFG, calib, 1000, 50), np.where(np.isfinite(s), s, -np.inf)
            )
            np.testing.assert_allclose(a, b, rtol=0, atol=0)

    def test_every_rule_reads_threshold_before_update(self):
        """A rule's threshold at step t never depends on the score at step t (causality)."""
        rng = np.random.default_rng(8)
        calib = 1.0 + np.abs(rng.standard_normal(4000))
        s = stream(n=2500)
        s2 = s.copy()
        s2[1500] += 50.0
        for rule in E.RULES:
            a, _ = E.apply_rule(rule, s, CFG, calib, 1000, 60, 50)
            b, _ = E.apply_rule(rule, s2, CFG, calib, 1000, 60, 50)
            np.testing.assert_array_equal(a[:1501], b[:1501], err_msg=rule)


class SpotTailTests(unittest.TestCase):
    def test_method_of_moments_recovers_gpd(self):
        from scipy.stats import genpareto

        for xi, sigma in ((0.1, 1.0), (-0.2, 2.0), (0.0, 0.5)):
            y = genpareto.rvs(
                xi, scale=sigma, size=400_000, random_state=np.random.default_rng(10)
            )
            g, sg = E._gpd(float(y.sum()), float((y * y).sum()), len(y))
            self.assertAlmostEqual(g, xi, delta=0.02)
            self.assertAlmostEqual(sg / sigma, 1.0, delta=0.03)

    def test_zq_is_the_q_quantile(self):
        from scipy.stats import genpareto

        xi, sigma, t = 0.15, 1.0, 2.0
        n, nt, q = 100_000, 2_000, 1e-3
        z = E._zq(t, xi, sigma, q, n, nt)
        # P(X > z) = P(X > t) * P(Y > z - t) = (nt / n) * sf(z - t)
        self.assertAlmostEqual(
            (nt / n) * genpareto.sf(z - t, xi, scale=sigma) / q, 1.0, places=9
        )

    def test_gpd_mle_matches_scipy(self):
        from scipy.stats import genpareto

        rng = np.random.default_rng(11)
        for xi in (-0.3, 0.0, 0.2, 0.45):
            y = genpareto.rvs(xi, scale=1.0, size=2000, random_state=rng)
            g, sg, _ = N.gpd_mle(y)
            c, _, sc = genpareto.fit(y, floc=0)
            ours = -genpareto.logpdf(y, g, 0, sg).sum()
            ref = -genpareto.logpdf(y, c, 0, sc).sum()
            self.assertLessEqual(ours, ref + 1e-3)


class LaterRuleTests(unittest.TestCase):
    """tt1e ceilings, tt1g practice rules and the tt1d rule factory."""

    def test_ceiling_rules_detect_what_their_static_threshold_detects(self):
        """The H3/P3 claim: a rule capped at kappa tau0 alarms wherever s > kappa tau0, whatever came before."""
        import threshold_rules_tt1e as TE

        rng = np.random.default_rng(30)
        calib = 1.0 + np.abs(rng.standard_normal(4000))
        for seed in range(5):
            s = stream(n=4000, seed=seed)
            s[1000:2500] += (
                3.0  # a long raised stretch that inflates the adaptive rules
            )
            for k in TE.KAPPAS:
                for rule in (
                    f"tracker_ceil_{k}",
                    f"daily_ceil_{k}",
                    f"spot_gr_ceil_{k}",
                ):
                    tau = N.path(TE.make(rule, CFG, calib, 1000), s)
                    self.assertTrue(np.all(tau <= k * CFG["tau0"] + 1e-12), rule)
                    self.assertTrue(np.all((s > tau)[s > k * CFG["tau0"]]), rule)

    def test_tt1d_rule_factory_runs_every_rule(self):
        S = M.SETUPS["tep59"]
        rng = np.random.default_rng(31)
        calib = 1.0 + np.abs(rng.standard_normal(5000))
        s = stream(n=3000)
        for rule in dict.fromkeys(M.D1_RULES + M.SIDE_RULES):
            tau = M.path(S, rule, CFG, calib, s)
            self.assertTrue(np.all(np.isfinite(tau) | (tau == np.inf)), rule)

    def test_on_delay(self):
        import threshold_rules_tt1g as G

        m = G.OnDelay(2.0, 3)
        s = np.array([3, 3, 3, 3, 1, 3, 3, 1, 3, 3, 3], float)
        alarm = []
        for x in s:
            alarm.append(bool(x > m.tau()))
            m.update(x)
        self.assertEqual(
            alarm,
            [False, False, True, True, False, False, False, False, False, False, True],
        )

    def test_ewma_tracks_and_excludes(self):
        import threshold_rules_tt1g as G

        rng = np.random.default_rng(32)
        m = G.Ewma(rng.normal(5, 1, 1000), 3.0, 200)
        for x in rng.normal(10, 2, 5000):
            m.update(x)
        self.assertAlmostEqual(m.mu, 10, delta=0.5)
        self.assertAlmostEqual(m.sigma(), 2, delta=0.4)
        e = G.Ewma(np.ones(100) + rng.normal(0, 0.1, 100), 3.0, 50, exclude=True)
        mu = e.mu
        e.update(100.0)  # above its threshold: not learned
        self.assertEqual(e.mu, mu)

    def test_recal_quiet_rejects_event_days(self):
        import threshold_rules_tt1g as G

        rng = np.random.default_rng(33)
        day = 1000
        quiet = 1.0 + np.abs(rng.standard_normal(day))
        loud = quiet.copy()
        loud[300:400] = 20.0  # an event-length episode above tau0
        m = G.Recal(3.0, "quiet", day, 5, 50, 2.0)
        for x in loud:
            m.update(x)
        self.assertEqual((m.accepted, m.t), (0, 3.0))
        for x in quiet:
            m.update(x)
        self.assertEqual(m.accepted, 1)
        self.assertLessEqual(len(R.episodes(quiet > m.t, 5)), 2.0)


# ---------------------------------------------------------------- calibration and bootstraps
class CalibrationTests(unittest.TestCase):
    def test_threshold_meets_budget_on_its_input(self):
        rng = np.random.default_rng(12)
        for k in range(30):
            runs = [
                C.rolling_mean(
                    np.exp(0.7 * rng.standard_normal(int(rng.integers(3000, 9000)))), 20
                )
                for _ in range(3)
            ]
            budget, spd, gap = (
                float(rng.uniform(0.5, 3)),
                5000,
                int(rng.integers(5, 40)),
            )
            thr = R2.calibrate(runs, gap, budget, spd)
            allowed = budget * sum(len(r) for r in runs) / spd
            self.assertLessEqual(
                sum(len(R.episodes(r > thr, gap)) for r in runs), allowed
            )


class BootstrapTests(unittest.TestCase):
    def test_cluster_bootstrap_singletons_equal_event_bootstrap_point(self):
        rng = np.random.default_rng(13)
        a, b = rng.random(60) < 0.8, rng.random(60) < 0.5
        cb = M.cluster_bootstrap(list(range(60)), a.tolist(), b.tolist())
        eb = C.paired_event_bootstrap(a, b, reps=10_000)
        self.assertAlmostEqual(
            cb["recall_difference"], eb["recall_difference"], places=12
        )
        self.assertEqual(cb["discordant_base_only"], int((a & ~b).sum()))
        for x, y in zip(
            cb["recall_difference_interval"], eb["recall_difference_interval"]
        ):
            self.assertAlmostEqual(x, y, delta=0.04)

    def test_interval_coverage(self):
        """Independent paired events: the 95 % percentile interval covers the true difference ~95 % of the time."""
        rng = np.random.default_rng(14)
        cover, sims = 0, 120
        for _ in range(sims):
            a = rng.random(80) < 0.85
            b = np.where(
                rng.random(80) < 0.7, a, rng.random(80) < 0.5
            )  # true recall(b) = 0.7*0.85 + 0.3*0.5
            lo, hi = M.cluster_bootstrap(list(range(80)), a.tolist(), b.tolist())[
                "recall_difference_interval"
            ]
            cover += lo <= (0.7 * 0.85 + 0.15) - 0.85 <= hi
        self.assertGreater(cover / sims, 0.85)

    def test_cluster_groups_whole_runs(self):
        groups = ["r1"] * 10 + ["r2"] * 5
        base = [True] * 15
        other = [False] * 10 + [True] * 5
        res = M.cluster_bootstrap(groups, base, other)
        self.assertEqual(res["groups"], 2)
        # resamples: {r1,r1} -> -1, {r2,r2} -> 0, mixed -> -10/15
        self.assertAlmostEqual(res["recall_difference_interval"][0], -1.0)
        self.assertAlmostEqual(res["recall_difference_interval"][1], 0.0)


# ---------------------------------------------------------------- loaders and splits
class GridTests(unittest.TestCase):
    def test_last_row_of_each_bin_and_fill(self):
        seconds = np.array([0.0, 0.5, 1.9, 2.1, 3.0, 9.0, 30.0, 31.0])
        values = np.arange(len(seconds), dtype=np.float32)[:, None]
        t0, grid, valid = TD._p_grid(seconds, values)
        self.assertEqual(t0, 0.0)
        # bins: 0 -> rows 0-2 (last 2), 1 -> rows 3-4 (last 4), 4 -> row 5, 15 -> rows 6-7 (last 7)
        self.assertEqual(len(grid), 16)
        self.assertEqual(grid[0, 0], 2)
        self.assertEqual(grid[1, 0], 4)
        self.assertEqual(grid[2, 0], 4)  # empty bin repeats the previous row
        self.assertEqual(grid[4, 0], 5)
        self.assertEqual(grid[15, 0], 7)
        # the 21 s gap (9 -> 30 s) invalidates the empty bins between rows 5 and 6; the 6 s gap does not
        np.testing.assert_array_equal(np.flatnonzero(~valid), np.arange(5, 15))

    def test_split_partitions_in_time_order(self):
        rng = np.random.default_rng(15)
        segs = [
            (np.arange(n, dtype=float)[:, None] + off, np.zeros((n, 1)))
            for off, n in ((0, 3000), (3000, 500), (3500, 7000))
        ]
        names = ("fit", "scale", "calib", "deploy")
        parts = F.split(segs, (0.5, 0.65, 0.75), names, min_len=100)
        seen = np.concatenate([x[:, 0] for name in names for x, _ in parts[name]])
        self.assertTrue(np.all(np.diff(seen) > 0))  # chronological, no overlap
        total = sum(len(x) for x, _ in segs)
        self.assertGreaterEqual(
            len(seen), total - 3 * 100 * len(names)
        )  # only pieces <= min_len dropped
        del rng


class InjectorTests(unittest.TestCase):
    def test_labels_and_untouched_outside(self):
        rng = np.random.default_rng(16)
        Z = rng.standard_normal((6000, 8)).cumsum(0) * 0.01
        V = np.round(rng.standard_normal((6000, 4)).cumsum(0) * 0.1, 1)
        inj = I.Injector("hai", Z, V, seed=1)
        for fam in (
            I.HAI_FAMILIES["development"] + I.HAI_FAMILIES["held_out"] + [I.GENERIC]
        ):
            Zi, Vi, y = inj.apply(Z, V, fam)
            idx = np.flatnonzero(y)
            self.assertTrue(len(idx) > 0 and np.all(np.diff(idx) == 1), fam)
            out = np.ones(len(Z), bool)
            out[idx] = False
            np.testing.assert_array_equal(Zi[out], Z[out], err_msg=fam)
            np.testing.assert_array_equal(Vi[out], V[out], err_msg=fam)


# ---------------------------------------------------------------- gates and registration
class GateTests(unittest.TestCase):
    def test_tt1_g2_direction(self):
        """G2 holds when the upper end of tracker - frozen is below zero."""
        base = {
            "E4_pulse_campaign": {
                "placements_used": 10,
                "rules": {
                    r: {"terminal_detected_after_campaign": 0.0}
                    for r in ("daily", "tracker", "tracker_slow")
                },
            }
        }
        base["E4_pulse_campaign"]["rules"]["frozen"] = {
            "terminal_detected_after_campaign": 1.0
        }
        for upper, expect in ((-0.01, True), (0.0, False), (0.2, False)):
            out = dict(
                base,
                real_events={
                    "paired": {
                        "tracker_vs_frozen": {
                            "recall_difference_interval": [-0.5, upper]
                        }
                    },
                    "rules": {"frozen": {"fa_per_day": 1.0}},
                },
            )
            self.assertEqual(
                F.primary_gates(out)["G2_real_attacks_poison_tracker"], expect
            )

    def test_tt1b_h2_tolerance(self):
        def out(lower, events):
            fr = {
                "placements_used": 10,
                "variants": {
                    "closed_24h": {
                        r: {"terminal_after_campaign": 1.0, "terminal_control": 1.0}
                        for r in ("dspot", "frozen", "one_sided:none")
                    }
                },
            }
            return {
                "scores": {
                    "D1": {
                        "real_events": {
                            "paired": {
                                "tracker_vs_frozen": {
                                    "recall_difference_interval": [-0.5, -0.1]
                                },
                                "spot_mle_vs_frozen": {
                                    "recall_difference_interval": [lower, 0.1]
                                },
                            },
                            "rules": {"frozen": {"events": events}},
                        },
                        "frog": fr,
                    }
                }
            }

        self.assertTrue(B.gates(out(-0.10, 50))["H2_spot_mle_noninferior_to_frozen"])
        self.assertFalse(B.gates(out(-0.11, 50))["H2_spot_mle_noninferior_to_frozen"])
        self.assertTrue(
            B.gates(out(-0.19, 10))["H2_spot_mle_noninferior_to_frozen"]
        )  # two events' worth: 0.2


class FrozenDigestTests(unittest.TestCase):
    """verify_tt1 and verify_tt1b say "frozen files unchanged" but only compare the digests stored in the result
    with the protocol; this checks the files on disk against every registration (verify_tt1d does this too)."""

    def test_frozen_files_match_protocols(self):
        for mod in (F, B, M):
            protocol = json.loads(mod.PROTOCOL.read_text(encoding="utf-8"))[
                "frozen_file_sha256"
            ]
            now = mod.digests()
            self.assertEqual(set(protocol), set(mod.FROZEN_FILES), mod.__name__)
            self.assertEqual(
                [f for f in protocol if protocol[f] != now[f]], [], mod.__name__
            )


if __name__ == "__main__":
    unittest.main()
