#!/usr/bin/env python3
"""Local-only, non-flickering dashboard for FerrumOS neural fixtures."""

from __future__ import annotations

import argparse
import json
import math
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from neurod import SsvepDecoder, SyntheticBoard

ROOT = Path(__file__).resolve().parent
ALLOWED_FREQUENCIES = (0.0, 8.0, 10.0, 12.0, 15.0)
ALLOWED_FAULTS = ("", "dropout", "saturation", "blink", "line-noise")


def decode_fixture(frequency: float, fault: str, seed: int) -> dict[str, object]:
    if frequency not in ALLOWED_FREQUENCIES:
        raise ValueError("frequency is not a registered fixture")
    if fault not in ALLOWED_FAULTS:
        raise ValueError("fault is not a registered fixture")
    if not 0 <= seed <= 1_000_000:
        raise ValueError("seed is out of range")
    board = SyntheticBoard(seed=seed)
    decoder = SsvepDecoder(250)
    result = None
    for window in range(3):
        result = decoder.decode(
            board.acquire(
                1.0,
                frequency or None,
                start_ns=1_000_000_000 + window * 1_000_000_000,
                fault=fault or None,
            )
        )
    assert result is not None
    output = asdict(result)
    output.update(
        {
            "source": "synthetic",
            "synthetic_only": True,
            "frequency_hz": frequency or None,
            "fault": fault or None,
            "seed": seed,
            "os_action_sent": False,
        }
    )
    return output


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "FerrumNeurod/1"

    def _headers(self, content_type: str, length: int, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            body = (ROOT / "dashboard.html").read_bytes()
            self._headers("text/html; charset=utf-8", len(body))
            self.wfile.write(body)
            return
        if parsed.path == "/dashboard.js":
            body = (ROOT / "dashboard.js").read_bytes()
            self._headers("text/javascript; charset=utf-8", len(body))
            self.wfile.write(body)
            return
        if parsed.path == "/api/decode":
            try:
                query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
                frequency = float(query.get("frequency", ["0"])[0])
                fault = query.get("fault", [""])[0]
                seed = int(query.get("seed", ["42"])[0])
                if not math.isfinite(frequency):
                    raise ValueError("frequency must be finite")
                payload = decode_fixture(frequency, fault, seed)
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self._headers("application/json", len(body))
            except (ValueError, TypeError) as error:
                body = json.dumps({"error": str(error), "abstained": True}).encode("utf-8")
                self._headers("application/json", len(body), 400)
            self.wfile.write(body)
            return
        body = b'{"error":"not found"}'
        self._headers("application/json", len(body), 404)
        self.wfile.write(body)

    def log_message(self, format_string: str, *args: object) -> None:
        print("neurod-dashboard:", format_string % args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("the neural fixture dashboard may only bind to localhost")
    if not 1 <= args.port <= 65_535:
        parser.error("port must be between 1 and 65535")
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Synthetic-only neural dashboard: http://{args.host}:{args.port}/")
    print("No flicker is rendered and no OS action is sent by this dashboard.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
