"""Focused invariants for the new causal training path (no final catalogs)."""
import unittest

import numpy as np
import torch

import incident_dynamics_data as data
import train_incident_dynamics as train
import evaluate_incident_dynamics_development as evaluation


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


if __name__ == "__main__":
    unittest.main()
