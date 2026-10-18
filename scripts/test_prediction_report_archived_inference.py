"""Portable text hashes must not admit changed historical adapter values."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import verify_cross_domain_archived_inference_v1_2 as audit


class AdapterPortabilityTests(unittest.TestCase):
    def test_only_line_endings_are_equivalent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = root / "adapter.json"
            old = b'{"weight": 1}\r\n'
            expected = hashlib.sha256(old).hexdigest()
            adapter.write_bytes(old.replace(b"\r\n", b"\n"))
            record = {"path": "adapter.json", "sha256": expected}
            protocol = {"inputs": {"attribution_protocol": {"path": "protocol.json"}}}
            (root / "protocol.json").write_text(json.dumps({"risk_source_variants": [record]}))
            original = audit.sensitivity.sha256
            def compute(_):
                self.assertEqual(audit.sensitivity.sha256(adapter), expected)
                return {"score": 1}
            with patch.object(audit, "ROOT", root), patch.object(audit.sensitivity, "attribution_analysis", compute):
                self.assertEqual(audit.portable_attribution_analysis(protocol), {"score": 1})
                self.assertIs(audit.sensitivity.sha256, original)
                adapter.write_bytes(b'{"weight": 2}\n')
                with self.assertRaises(AssertionError):
                    audit.portable_attribution_analysis(protocol)
                self.assertIs(audit.sensitivity.sha256, original)

    def test_digest_hook_restored_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "protocol.json").write_text('{"risk_source_variants": []}')
            protocol = {"inputs": {"attribution_protocol": {"path": "protocol.json"}}}
            original = audit.sensitivity.sha256
            with patch.object(audit, "ROOT", root), patch.object(audit.sensitivity, "attribution_analysis", side_effect=ValueError("test")):
                with self.assertRaises(ValueError):
                    audit.portable_attribution_analysis(protocol)
            self.assertIs(audit.sensitivity.sha256, original)


if __name__ == "__main__":
    unittest.main()
