"""Tests for repro_env (fi1 workstream B, round 3). Run from scripts/: python -m pytest -q test_repro_env.py"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repro_env  # noqa: E402

try:
    import threadpoolctl
except ImportError:  # pragma: no cover - CI installs it with scikit-learn
    threadpoolctl = None


def blas_threads() -> set[int]:
    return {
        pool["num_threads"]
        for pool in threadpoolctl.threadpool_info()
        if pool["user_api"] == "blas"
    }


class PinThreadsTests(unittest.TestCase):
    def tearDown(self):
        repro_env.unpin()

    def test_rejects_invalid_counts(self):
        for value in (0, -1, 1.5, True, "2", None):
            with self.assertRaises(ValueError):
                repro_env.pin_threads(value)

    def test_sets_environment_for_children(self):
        repro_env.pin_threads(2)
        for name in repro_env.THREAD_ENVIRONMENT_VARIABLES:
            self.assertEqual(os.environ[name], "2")

    @unittest.skipIf(threadpoolctl is None, "threadpoolctl not installed")
    def test_limits_blas_in_this_process(self):
        np.ones((4, 4)) @ np.ones((4, 4))  # make sure the BLAS pool is loaded
        repro_env.pin_threads(1)
        self.assertEqual(blas_threads(), {1})
        repro_env.pin_threads(2)
        self.assertEqual(blas_threads(), {min(2, os.cpu_count() or 2)})

    @unittest.skipIf(threadpoolctl is None, "threadpoolctl not installed")
    def test_unpin_restores_limits_and_environment(self):
        np.ones((4, 4)) @ np.ones((4, 4))
        before_threads = blas_threads()
        before_env = {
            n: os.environ.get(n) for n in repro_env.THREAD_ENVIRONMENT_VARIABLES
        }
        repro_env.pin_threads(1)
        repro_env.pin_threads(3)  # a second pin must not lose the original state
        repro_env.unpin()
        self.assertEqual(blas_threads(), before_threads)
        self.assertEqual(
            {n: os.environ.get(n) for n in repro_env.THREAD_ENVIRONMENT_VARIABLES},
            before_env,
        )
        self.assertIsNone(repro_env.environment_record()["pinned_threads"])

    @unittest.skipIf(threadpoolctl is None, "threadpoolctl not installed")
    def test_child_process_inherits_the_pin(self):
        repro_env.pin_threads(1)
        code = (
            "import numpy, threadpoolctl, json;"
            "print(json.dumps(sorted({p['num_threads'] for p in threadpoolctl.threadpool_info()"
            " if p['user_api']=='blas'})))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        self.assertEqual(json.loads(out.stdout), [1])

    def test_lightgbm_keywords(self):
        with self.assertRaises(RuntimeError):
            repro_env.lightgbm_params({"objective": "regression"})
        pinned = repro_env.pin_threads(3)
        self.assertEqual(pinned["lightgbm"], {"num_threads": 3})
        params = repro_env.lightgbm_params(
            {"n_jobs": 8, "nthread": 5, "learning_rate": 0.1}
        )
        self.assertEqual(params, {"learning_rate": 0.1, "num_threads": 3})

    def test_torch_is_pinned_when_imported(self):
        try:
            import torch
        except ImportError:
            self.skipTest("torch not installed")
        before = torch.get_num_threads()
        result = repro_env.pin_threads(1)
        self.assertEqual(torch.get_num_threads(), 1)
        self.assertEqual(result["applied"]["torch"]["num_threads"], 1)
        repro_env.unpin()
        self.assertEqual(torch.get_num_threads(), before)


class EnvironmentRecordTests(unittest.TestCase):
    def tearDown(self):
        repro_env.unpin()

    def test_fields(self):
        record = repro_env.environment_record()
        for key in (
            "python",
            "packages",
            "thread_pools",
            "pinned_threads",
            "thread_environment",
            "logical_cpus",
            "platform",
        ):
            self.assertIn(key, record)
        self.assertEqual(record["packages"]["numpy"], np.__version__)
        self.assertEqual(record["logical_cpus"], os.cpu_count())
        self.assertEqual(set(record["packages"]), set(repro_env.PACKAGES))
        json.dumps(record)  # serialisable as it stands

    @unittest.skipIf(threadpoolctl is None, "threadpoolctl not installed")
    def test_records_blas_vendor_version_architecture_and_threads(self):
        np.ones((4, 4)) @ np.ones((4, 4))
        repro_env.pin_threads(1)
        record = repro_env.environment_record()
        blas = [p for p in record["thread_pools"] if p["user_api"] == "blas"]
        self.assertTrue(blas)
        for pool in blas:
            self.assertEqual(pool["num_threads"], 1)
            self.assertTrue(pool["internal_api"])
            self.assertIn("architecture", pool)
            self.assertIn("version", pool)
        self.assertEqual(record["pinned_threads"], 1)
        self.assertEqual(record["thread_environment"]["OPENBLAS_NUM_THREADS"], "1")


class SingleThreadRepeatabilityTests(unittest.TestCase):
    """The property the round relies on: with one BLAS thread a float32 training-sized product
    gives the same bits when repeated (fi1 B3 found the same for the full evaluators)."""

    def tearDown(self):
        repro_env.unpin()

    def test_single_thread_product_repeats_bit_for_bit(self):
        repro_env.pin_threads(1)
        rng = np.random.default_rng(0)
        a = rng.standard_normal((1024, 256), dtype=np.float32)
        b = rng.standard_normal((256, 128), dtype=np.float32)
        first = (a.T @ (a @ b)).tobytes()
        second = (a.T @ (a @ b)).tobytes()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
