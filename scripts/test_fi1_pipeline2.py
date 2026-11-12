"""fi1 workstream B, round 2: tests for the code behind the PINP report (incident dynamics, rt1/rt2,
cross-domain learned contribution).

Synthetic data except the classes named *Stored*, which read committed result JSON files only.
Run from scripts/: python -m pytest -q test_fi1_pipeline2.py
"""

from __future__ import annotations

import importlib.util
import json
import math
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs/research"


def _load(name):
    return json.loads((RESEARCH / name).read_text(encoding="utf-8"))


class PosthocMatchedRateTests(unittest.TestCase):
    """R1: the Table 30 search keeps the lowest candidate within budget, past the first budget break."""

    @staticmethod
    def _streams():
        # One test file, no labelled steps. Isolated spikes at level 5 every 200 steps (1,000 episodes
        # above 3.5) and, on every fifth step, values in [2.5, 3.5]. Just below 5 the spikes alone break
        # the budget; near 3 the dense mid-level alarms merge everything into a few long episodes.
        rng = np.random.default_rng(0)
        s = np.full(200_000, 2.0)
        s[::5] = rng.uniform(2.5, 3.5, 40_000)
        s[100::200] = 5.0
        return [s], [np.zeros(len(s), np.int8)]

    def test_lowest_rule_passes_the_first_break(self):
        import real_telemetry_posthoc_rt1 as P

        scores, labels = self._streams()
        lowest = P.matched_threshold(scores, labels, allowed=20, rule="lowest")
        first = P.matched_threshold(scores, labels, allowed=20, rule="first_break")
        self.assertLess(
            lowest, 3.1
        )  # 10 % of the stream in alarm, a handful of long episodes
        self.assertGreaterEqual(first, 5.0)  # nothing alarms
        self.assertLessEqual(P.false_episodes(scores, labels, lowest), 20)
        self.assertGreater(
            P.false_episodes(scores, labels, 4.0), 20
        )  # a higher threshold breaks the budget
        self.assertGreater(float(np.mean(scores[0] > lowest)), 0.09)

    def test_first_break_keeps_every_higher_candidate_within_budget(self):
        import real_telemetry_posthoc_rt1 as P

        rng = np.random.default_rng(3)
        for _ in range(6):
            s = rng.gamma(1.0, 1.0, 20_000)
            s[rng.integers(0, 20_000, 40)] += rng.uniform(3, 9, 40)
            y = np.zeros(len(s), np.int8)
            y[5_000:5_300] = 1
            allowed = float(rng.integers(1, 6))
            thr = P.matched_threshold([s], [y], allowed, rule="first_break")
            pooled = s[y == 0]
            candidates = np.unique(np.quantile(pooled, 1 - np.logspace(-6, -1, 250)))
            for c in candidates[candidates >= thr]:
                self.assertLessEqual(P.false_episodes([s], [y], c), allowed)

    def test_lowest_rule_equals_the_published_inline_loop(self):
        import real_telemetry_detect as R
        import real_telemetry_posthoc_rt1 as P

        rng = np.random.default_rng(7)
        s = rng.gamma(1.0, 1.0, 30_000)
        y = np.zeros(len(s), np.int8)
        y[10_000:10_500] = 1
        allowed = 3.0
        # The loop as committed in 20f2ea6 (body of main), applied to one detector.
        pooled_normal = s[(y == 0) & np.isfinite(s)]
        candidates = np.unique(np.quantile(pooled_normal, 1 - np.logspace(-6, -1, 250)))
        best = float(pooled_normal.max()) + 1e-9
        for thr in candidates[::-1]:
            labelled = y.astype(bool)
            false = sum(
                1
                for a, b in R.episodes(s > thr, R.GAP["hai"])
                if not labelled[a:b].any()
            )
            if false <= allowed:
                best = float(thr)
        self.assertEqual(P.matched_threshold([s], [y], allowed, rule="lowest"), best)


# The module under test imports torch at the top. CI installs no torch, so these two tests run only where
# torch is present (the development machine); the skip is reported by name.
@unittest.skipUnless(importlib.util.find_spec("torch"), "torch is not installed")
class IncidentCalibrationTests(unittest.TestCase):
    """evaluate_incident_dynamics_development.calibrate: the 1 % empirical-FPR rule behind Tables 19, 23, 27."""

    def test_fpr_at_most_one_percent_with_ties(self):
        import evaluate_incident_dynamics_development as dev

        rng = np.random.default_rng(11)
        for n in (100, 257, 1000, 4096):
            score = np.round(rng.normal(size=n), 1)  # heavy ties
            labels = rng.random(n) < 0.2
            labels[:2] = [True, False]
            thr, coef = dev.calibrate(score, labels)
            negatives = score[~labels]
            self.assertLessEqual(
                np.sum(negatives >= thr), math.floor(0.01 * len(negatives))
            )
            self.assertGreaterEqual(coef[1], 0.0)

    def test_threshold_is_just_above_the_first_excluded_negative(self):
        import evaluate_incident_dynamics_development as dev

        score = np.arange(300, dtype=float)
        labels = np.zeros(300, bool)
        labels[::3] = True
        thr, _ = dev.calibrate(score, labels)
        negatives = np.sort(score[~labels])[::-1]
        self.assertEqual(
            thr, float(np.nextafter(negatives[2], np.inf))
        )  # floor(0.01 * 200) = 2


class IncidentMetricTests(unittest.TestCase):
    """incident_dynamics_metrics: episode bootstrap and warning summaries used for Tables 17-27."""

    @staticmethod
    def _episodes(n_episodes=40, per=10, seed=0):
        rng = np.random.default_rng(seed)
        episodes = np.repeat(np.array([f"e{i:03d}" for i in range(n_episodes)]), per)
        return rng, episodes

    def test_bootstrap_estimate_is_the_macro_difference(self):
        import incident_dynamics_metrics as M

        rng, episodes = self._episodes()
        left, right = rng.gamma(2, 1, len(episodes)), rng.gamma(2, 1, len(episodes))
        out = M.bootstrap_difference(left, right, episodes, 5, (0.00625, 0.99375))
        macro = (
            M.episode_means(left, episodes)[1].mean()
            - M.episode_means(right, episodes)[1].mean()
        )
        self.assertAlmostEqual(out["estimate"], macro, places=12)
        self.assertLess(out["interval"][0], out["estimate"])
        self.assertGreater(out["interval"][1], out["estimate"])
        self.assertAlmostEqual(out["interval_level"], 0.9875)

    def test_warning_counts_sum_by_episode(self):
        import incident_dynamics_metrics as M

        rng, episodes = self._episodes()
        scores = rng.normal(size=len(episodes))
        labels = rng.random(len(episodes)) < 0.3
        report, counts = M.warning_summary(scores, labels, 0.5, [0.0, 1.0], episodes)
        self.assertEqual(counts.shape, (40, 4))
        self.assertEqual(int(counts.sum()), len(episodes))
        self.assertEqual(report["tp"], int(np.sum((scores >= 0.5) & labels)))
        self.assertEqual(report["fp"], int(np.sum((scores >= 0.5) & ~labels)))

    def test_paired_warning_point_is_the_recall_difference(self):
        import incident_dynamics_metrics as M

        rng, episodes = self._episodes()
        labels = rng.random(len(episodes)) < 0.3
        a, b = rng.normal(size=len(episodes)), rng.normal(size=len(episodes))
        ra, ca = M.warning_summary(a, labels, 0.0, [0.0, 1.0], episodes)
        rb, cb = M.warning_summary(b, labels, 0.0, [0.0, 1.0], episodes)
        out = M.paired_warning_difference(ca, cb, 9)
        self.assertAlmostEqual(
            out["recall"]["difference"], ra["recall"] - rb["recall"], places=12
        )
        self.assertAlmostEqual(
            out["fpr"]["difference"], ra["fpr"] - rb["fpr"], places=12
        )
        lo, hi = out["recall"]["interval_97_5_percent"]
        self.assertLessEqual(lo, out["recall"]["difference"])
        self.assertGreaterEqual(hi, out["recall"]["difference"])


class StoredIncidentDynamicsTests(unittest.TestCase):
    """Committed incident-dynamics results agree with the tables of PINP v1.3."""

    def test_v3_v4_primary_and_warning_cells(self):
        expected = {  # (version, population, domain, horizon): (reduction %, pass) as in Tables 21 and 25
            (3, "A", "physical", "h5"): (28.4, True),
            (3, "B", "ferrumos", "h5"): (18.4, False),
            (4, "A", "ferrumos", "h5"): (5.7, False),
            (4, "B", "physical", "h3"): (23.8, True),
        }
        for (v, pop, dom, h), (reduction, gate) in expected.items():
            cell = _load(f"incident_dynamics_result_v{v}.json")["domains"][dom][
                "populations"
            ][pop]["primary_prediction"][h]
            self.assertEqual(round(100 * cell["relative_reduction"], 1), reduction)
            self.assertIs(cell["pass"], gate)

    def test_v2_physical_warning_gain_is_mostly_same_data_retraining(self):
        """Finding I1: Table 19's +45.85-point recall gain is against the paper JEPA; the same-data
        retrained JEPA, stored in the same result file, is within one point of the selected ensemble."""
        methods = _load("incident_dynamics_result_v2.json")["domains"]["physical"][
            "methods"
        ]
        recall = {
            k: m["warning"]["tp"] / (m["warning"]["tp"] + m["warning"]["fn"])
            for k, m in methods.items()
        }
        self.assertAlmostEqual(
            recall["selected"] - recall["paper-action_conditioned_jepa"],
            0.4585,
            places=4,
        )
        self.assertLess(recall["selected"] - recall["retrained-jepa"], 0.01)


class StoredRealTelemetryTests(unittest.TestCase):
    """verify_real_telemetry recomputes each gate from the gate's own stored fields. These tests tie the
    gate fields to the comparison they summarise, which the verifier does not do."""

    def test_rt1_gate_fields_equal_the_primary_comparison(self):
        for name, block in _load("real_telemetry_result_v1.json")["datasets"].items():
            gate, comparison = block["primary_gate"], block["comparisons"]["D2_vs_D1"]
            self.assertEqual(gate["miss_reduction"], comparison["miss_reduction"], name)
            self.assertEqual(
                gate["interval"], comparison["miss_reduction_interval"], name
            )
            self.assertEqual(
                gate["false_episodes_per_day"],
                block["detectors"]["D2"]["false_episodes_per_day"],
                name,
            )

    def test_rt2_gate_follows_from_primary_comparisons(self):
        for name, block in _load("real_telemetry_result_rt2.json")["releases"].items():
            prim = block["primary_comparisons"]
            redo = all(
                p["miss_reduction"] >= 0.2 and p["miss_reduction_interval"][0] > 0
                for p in prim.values()
            )
            redo = redo and block["detectors"]["D1"]["false_episodes_per_day"] <= 4.0
            self.assertEqual(redo, block["primary_gate"]["passes"], name)


class StoredLearnedContributionTests(unittest.TestCase):
    """Finding X2 (cross-domain, Table 7): under the frozen Platt map the threshold 0.99 needs a score no
    development or final case reaches, so learned-only TP = FP = 0 is fixed before the final opens."""

    def test_threshold_unreachable_in_both_domains(self):
        selection = _load("cross_domain_learned_contribution_selection_v1.json")[
            "domains"
        ]
        result = _load("cross_domain_learned_contribution_result_v1.json")["domains"]
        logit = math.log(0.99 / 0.01)
        for domain in ("ferrumos", "physical"):
            dev = selection[domain]["development"]
            needed = (logit - dev["calibration"]["intercept"]) / dev["calibration"][
                "slope"
            ]
            self.assertEqual(
                dev["threshold_selection"]["metrics"]["tp"], 0
            )  # known at selection
            top = max(r["score"] for r in result[domain]["case_records"])
            self.assertLess(top, needed / 4, domain)
            self.assertFalse(
                any(r["learned_block"] for r in result[domain]["case_records"])
            )


class AttributionThresholdTieTests(unittest.TestCase):
    """Finding P1: the float FPR distance hides an exact tie, so the registered FN tie-break never runs."""

    @staticmethod
    def _validation():
        # 3,471 negatives and 23 positives, as on validation seeds 4096-4127. No threshold gives 14 FP:
        # thresholds in (0.74, 0.9] give 13 FP and 4 FN; thresholds at or below 0.735 give 15 FP and 3 FN.
        negatives = np.r_[np.full(3456, 0.1), np.full(2, 0.74), np.full(13, 0.9)]
        positives = np.r_[np.full(19, 0.95), [0.735], np.full(3, 0.05)]
        values = np.r_[negatives, positives]
        labels = np.r_[np.zeros(len(negatives)), np.ones(len(positives))]
        return labels, values

    def test_float_key_breaks_an_exact_tie(self):
        self.assertLess(abs(13 / 3471 - 14 / 3471), abs(15 / 3471 - 14 / 3471))

    def test_exact_rule_applies_the_false_negative_tie_break(self):
        import physical_jepa_threshold_choice_v2 as T

        labels, values = self._validation()
        old = T.choose_threshold_float(labels, values, 14 / 3471)
        new = T.choose_threshold_exact(labels, values, 14, 3471)
        self.assertEqual((old["fp"], old["fn"]), (13, 4))
        self.assertEqual((new["fp"], new["fn"]), (15, 3))
        self.assertAlmostEqual(new["threshold"], 0.735)


if __name__ == "__main__":
    unittest.main()
