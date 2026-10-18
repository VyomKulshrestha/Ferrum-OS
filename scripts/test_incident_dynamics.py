"""Focused invariants for the new causal training path (no final catalogs)."""
import unittest
from unittest.mock import patch
from pathlib import Path
import hashlib
import tempfile

import numpy as np
import torch

import incident_dynamics_data as data
import train_incident_dynamics as train
import evaluate_incident_dynamics_development as evaluation
import incident_dynamics_metrics as metrics
import run_incident_dynamics_study as study


class CausalWindowsTests(unittest.TestCase):
    def setUp(self):
        self.spec = data.spec_for("ferrumos")
        self.rows = data.incident_rows("ferrumos", "train", 2, 123)

    def test_future_targets_cannot_change_input(self):
        baseline = data.windows(self.rows, self.spec)
        changed = [{**row, "next_state": row["next_state"] + 10} for row in self.rows]
        modified = data.windows(changed, self.spec)
        np.testing.assert_array_equal(baseline.states, modified.states)
        np.testing.assert_array_equal(baseline.actions, modified.actions)
        self.assertFalse(np.array_equal(baseline.targets, modified.targets))

    def test_history_does_not_cross_episodes(self):
        windows = data.windows(self.rows, self.spec)
        for episode in np.unique(windows.episodes):
            first = np.flatnonzero(windows.episodes == episode)[0]
            np.testing.assert_array_equal(windows.states[first, 0], windows.states[first, -1])
            self.assertFalse(windows.actions[first, :2].any())

    def test_complete_population_is_fixed_for_all_horizons(self):
        windows = data.windows(self.rows, self.spec, complete=True)
        self.assertEqual(len(windows.states), 20)
        self.assertTrue(windows.valid.all())

    def test_padding_is_masked(self):
        windows = data.windows(self.rows, self.spec)
        self.assertEqual(windows.valid[-1].sum(), 1)
        self.assertEqual(windows.valid[-2].sum(), 2)

    def test_duplicate_steps_rejected(self):
        with self.assertRaises(ValueError):
            data.windows(self.rows + [self.rows[0]], self.spec)

    def test_missing_steps_do_not_create_fake_rollout(self):
        rows = [row for row in self.rows if row["step"] != 3]
        windows = data.windows(rows, self.spec, complete=True)
        self.assertEqual(len(windows.states), 12)

    def test_split_is_reproducible_and_disjoint(self):
        again = data.incident_rows("ferrumos", "train", 2, 123)
        validation = data.incident_rows("ferrumos", "validation", 2, 123)
        np.testing.assert_array_equal(self.rows[-1]["next_state"], again[-1]["next_state"])
        self.assertFalse({r["episode"] for r in self.rows} & {r["episode"] for r in validation})

    def test_untrained_model_is_persistence(self):
        windows = data.windows(self.rows, self.spec, complete=True)
        model = train.CausalResidual(self.spec, 16)
        predictions = train.predictions(model, windows, self.spec)
        np.testing.assert_allclose(predictions, np.repeat(windows.states[:, -1:, :], 5, 1), atol=0, rtol=0)

    def test_gradient_through_all_steps(self):
        windows = data.windows(self.rows, self.spec, complete=True)
        model = train.CausalResidual(self.spec, 16)
        result, _ = train.rollout(model, *[torch.tensor(x) for x in (windows.states, windows.actions, windows.future_actions)], self.spec)
        result[:, -1].sum().backward()
        self.assertTrue(torch.isfinite(model.linear.weight.grad).all())
        self.assertGreater(float(model.linear.weight.grad.abs().sum()), 0)

    def test_nonfinite_forecast_rejected(self):
        windows = data.windows(self.rows, self.spec, complete=True)
        values = windows.targets.copy()
        values[0, 0, 0] = np.nan
        with self.assertRaises(ValueError):
            evaluation.risk_score(values, windows, "ferrumos")

    def test_threshold_obeys_bound_and_handles_ties(self):
        scores = np.asarray([0.] * 100 + [1.] * 5)
        labels = np.asarray([False] * 100 + [True] * 5)
        threshold, calibration = evaluation.calibrate(scores, labels)
        metrics = evaluation.warning_metrics(scores, labels, threshold, calibration)
        self.assertEqual(metrics["fp"], 0)
        self.assertEqual(metrics["tp"], 5)

    def test_action_heads_do_not_use_future_targets(self):
        windows = data.windows(self.rows, self.spec, complete=True)
        model = train.ActionResidual(self.spec, 16)
        states, actions = torch.tensor(windows.states), torch.tensor(windows.actions)
        a = model(states, actions, torch.zeros((len(states), 48)))[0]
        b = model(states, actions, torch.ones((len(states), 48)))[0]
        torch.testing.assert_close(a, b, atol=0, rtol=0)

    def test_paired_warning_interval_uses_episode_counts(self):
        left = np.asarray([[8, 1, 9, 2]] * 6, dtype=float)
        right = np.asarray([[2, 1, 9, 8]] * 6, dtype=float)
        result = metrics.paired_warning_difference(left, right, 42)
        self.assertAlmostEqual(result["recall"]["difference"], .6)
        np.testing.assert_allclose(result["recall"]["interval_97_5_percent"], [.6, .6])

    def test_complete_analysis_on_known_fixture(self):
        states = np.zeros((8, 3, 48), np.float32)
        states[:, :, 0] = .5
        targets = np.zeros((8, 5, 48), np.float32)
        targets[::2, :, 0] = 1
        targets[1::2, :, 0] = .5
        actions = np.zeros((8, 3, 57), np.float32)
        future = np.zeros((8, 5, 57), np.float32)
        windows = data.Windows(states, actions, future, targets, np.ones((8, 5), np.float32),
                               np.repeat(["a", "b", "c", "d"], 2), np.asarray(["fixture"] * 8))
        wrong = targets.copy()
        wrong[:, :, 0] = .8
        predictions = {"selected": targets, "paper-gru_dynamics": wrong}
        warning = {"threshold": 0., "logistic_coefficients": [0., 50.]}
        selection = {"domains": {"ferrumos": {"pipelines": {key: {"warning": warning} for key in predictions}}}}
        protocol = {"comparison": {"primary_baseline": {"ferrumos": "paper-gru_dynamics"}}, "statistics": {"seed": 42}}
        result = study.analyze_domain("ferrumos", windows, windows, predictions, predictions, selection, protocol)
        self.assertTrue(result["primary_prediction_objective_pass"])
        self.assertTrue(result["secondary_warning_objective_pass"])
        self.assertEqual(result["methods"]["selected"]["warning"]["recall"], 1)

    def test_ambiguous_historical_episode_excluded_before_windowing(self):
        duplicate = {**self.rows[0], "episode": "ambiguous", "step": 0}
        rows = self.rows + [duplicate, duplicate.copy()]
        with patch.object(study, "VERSION", 2), patch.object(study.architecture, "os_final", return_value=(self.spec, rows, {})):
            windows, exclusions = study.historical_inputs("ferrumos", self.spec)
        self.assertNotIn("ambiguous", windows.episodes)
        self.assertEqual(exclusions["ambiguous_episode_count"], 1)
        self.assertTrue(exclusions["all_ambiguous_episodes_shorter_than_five_rows"])
        self.assertEqual(exclusions["retained_common_episodes"], 2)

    def test_metadata_newline_equivalence_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            path.write_bytes(b'{"a":1}\n')
            self.assertTrue(study.record_matches({"path": str(path), "sha256": hashlib.sha256(b'{"a":1}\r\n').hexdigest()}))
            self.assertFalse(study.record_matches({"path": str(path), "sha256": hashlib.sha256(b'{"a":2}\r\n').hexdigest()}))

    def test_binary_digest_does_not_allow_newline_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.pt"
            path.write_bytes(b'abc\n')
            self.assertFalse(study.record_matches({"path": str(path), "sha256": hashlib.sha256(b'abc\r\n').hexdigest()}))


if __name__ == "__main__":
    unittest.main()
