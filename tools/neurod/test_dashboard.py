import unittest
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from dashboard import DashboardHandler, decode_fixture


class DashboardTests(unittest.TestCase):
    def test_registered_fixture_is_explicitly_synthetic_and_non_actuating(self):
        result = decode_fixture(12.0, "", 42)
        self.assertEqual(result["label"], "select")
        self.assertTrue(result["synthetic_only"])
        self.assertFalse(result["os_action_sent"])

    def test_no_control_and_faults_abstain(self):
        self.assertIsNone(decode_fixture(0.0, "", 42)["label"])
        for fault in ("dropout", "saturation", "blink", "line-noise"):
            self.assertIsNone(decode_fixture(12.0, fault, 42)["label"])

    def test_unregistered_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            decode_fixture(13.0, "", 42)
        with self.assertRaises(ValueError):
            decode_fixture(12.0, "unknown", 42)

    def test_local_http_surface_serves_page_and_decode_api(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            with urllib.request.urlopen(f"http://{host}:{port}/", timeout=2) as response:
                self.assertIn(b"Synthetic-only", response.read())
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            with urllib.request.urlopen(
                f"http://{host}:{port}/api/decode?frequency=12&fault=&seed=42",
                timeout=2,
            ) as response:
                payload = json.load(response)
                self.assertEqual(payload["label"], "select")
                self.assertFalse(payload["os_action_sent"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
