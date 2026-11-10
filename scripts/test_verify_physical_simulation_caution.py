"""The simulation-caution verifier ties the grant's digest constant to the shipped model bytes.

python -m unittest scripts.test_verify_physical_simulation_caution
"""

from __future__ import annotations

import hashlib
import unittest

from scripts import verify_physical_simulation_caution as V


class ServiceDigestBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = V.SERVICE.read_text(encoding="utf-8")
        self.digest = hashlib.sha256(V.ARTIFACT.read_bytes()).hexdigest()

    def test_committed_service_binds_the_shipped_bytes(self) -> None:
        self.assertEqual(V.service_bound_digest(self.service), self.digest)
        self.assertTrue(V.service_binds_artifact(self.service, self.digest))

    def test_swapped_model_bytes_are_caught(self) -> None:
        other = hashlib.sha256(V.ARTIFACT.read_bytes() + b"\0").hexdigest()
        self.assertFalse(V.service_binds_artifact(self.service, other))

    def test_stale_constant_is_caught_even_if_the_status_string_is_updated(self) -> None:
        stale = self.service.replace("0x23, 0xa0, 0x6f", "0x24, 0xa0, 0x6f", 1)
        self.assertNotEqual(stale, self.service)
        self.assertFalse(V.service_binds_artifact(stale, self.digest))


if __name__ == "__main__":
    unittest.main()
