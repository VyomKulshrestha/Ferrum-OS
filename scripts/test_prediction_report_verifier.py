"""The release checker must detect tampering without refreshing its own baseline."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import verify_cross_domain_world_model_paper_v1_2 as verifier


class ReleaseRecordTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name, value in (("ROOT", self.root), ("FREEZE", self.root / "freeze.json"),
                            ("RESULT", self.root / "result.json")):
            active = patch.object(verifier, name, value)
            active.start()
            self.addCleanup(active.stop)

    def record(self, name, data):
        (self.root / name).write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    def test_text_newline_equivalence_only(self):
        retained = self.record("source.md", b"alpha\r\nbeta\r\n")
        current = self.record("source.md", b"alpha\nbeta\n")
        self.assertTrue(verifier.records_match(retained, current))
        current = self.record("source.md", b"alpha\nchanged\n")
        self.assertFalse(verifier.records_match(retained, current))

    def test_binary_bytes_must_match(self):
        retained = self.record("report.pdf", b"alpha\r\n")
        current = self.record("report.pdf", b"alpha\n")
        self.assertFalse(verifier.records_match(retained, current))

    def test_metrics_keys_types_and_paths_must_match(self):
        self.assertFalse(verifier.records_match({"pass": True}, {"pass": 1}))
        self.assertFalse(verifier.records_match({"mae": .1}, {"mae": .2}))
        self.assertFalse(verifier.records_match({"mae": .1}, {"mae": .1, "extra": 0}))
        self.assertFalse(verifier.records_match(
            {"path": "../outside.json", "sha256": "x"},
            {"path": "../outside.json", "sha256": "x"}))

    def test_check_is_read_only_and_rejects_tampering(self):
        freeze = {"release": {"status": "prepublication candidate", "repository_tag": None}}
        result = {"overall_pass": True, "checks": {"example": True}}
        verifier.finalize_records(freeze, result, refresh=True)
        before = [(p.read_bytes(), p.stat().st_mtime_ns)
                  for p in (verifier.FREEZE, verifier.RESULT)]
        verifier.finalize_records(freeze, result, refresh=False)
        with self.assertRaises(SystemExit):
            verifier.finalize_records({**freeze, "tamper": True}, result, refresh=False)
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns)
                                 for p in (verifier.FREEZE, verifier.RESULT)])

    def test_failed_refresh_preserves_records(self):
        verifier.FREEZE.write_text("sentinel", encoding="utf-8")
        with self.assertRaises(SystemExit):
            verifier.finalize_records({}, {"overall_pass": False, "checks": {"x": False}}, refresh=True)
        self.assertEqual(verifier.FREEZE.read_text(), "sentinel")
        self.assertFalse(verifier.RESULT.exists())

    def test_published_release_cannot_refresh(self):
        for release in ({"status": "published", "repository_tag": None},
                        {"status": "prepublication", "repository_tag": "v1.2"}):
            verifier.FREEZE.write_text(json.dumps({"release": release}), encoding="utf-8")
            before = verifier.FREEZE.read_bytes()
            with self.assertRaises(SystemExit):
                verifier.finalize_records({}, {"overall_pass": True, "checks": {"x": True}}, refresh=True)
            self.assertEqual(verifier.FREEZE.read_bytes(), before)
            self.assertFalse(verifier.RESULT.exists())


if __name__ == "__main__":
    unittest.main()
