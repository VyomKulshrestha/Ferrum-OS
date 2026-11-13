#!/usr/bin/env python3
"""tw1c: feed the tw1c series to Netdata's statsd collector, one value per gauge per second.

Runs inside a python:3.10-slim container (standard library only), with /data mounted from
target/tw1c/netdata/feed. Reads series.bin (float64, rows x steps) and series.json (names), sends
"<name>:<value>|g" over UDP to the Netdata container and records progress in progress.json.

    python feeder.py <host> <port>

Step k is sent at start + k seconds (start is the first whole second after launch), so Netdata's 1-second
statsd chart holds value k at second start + k. The start time is written to progress.json before the first
value. A restarted feeder does not resume: the plan restarts the run from the beginning.
"""

from __future__ import annotations

import array
import json
import math
import socket
import sys
import time
from pathlib import Path

DATA = Path("/data")


def main(host, port):
    names = json.loads((DATA / "series.json").read_text())["names"]
    steps = json.loads((DATA / "series.json").read_text())["steps"]
    raw = array.array("d")
    raw.frombytes((DATA / "series.bin").read_bytes())
    n = len(names)
    assert len(raw) == n * steps
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (host, int(port))
    start = math.floor(time.time()) + 2
    prog = {"start": start, "steps": steps, "series": n, "late": 0, "max_late_s": 0.0}
    (DATA / "progress.json").write_text(json.dumps(prog))
    for k in range(steps):
        due = start + k + 0.5  # the middle of second k
        now = time.time()
        if now < due:
            time.sleep(due - now)
        else:
            prog["late"] += 1
            prog["max_late_s"] = max(prog["max_late_s"], now - due)
        packet = []
        size = 0
        for i in range(n):
            line = f"{names[i]}:{raw[i * steps + k]:.6f}|g"
            if size + len(line) + 1 > 1400:
                sock.sendto("\n".join(packet).encode(), addr)
                packet, size = [], 0
            packet.append(line)
            size += len(line) + 1
        if packet:
            sock.sendto("\n".join(packet).encode(), addr)
        if k % 60 == 0 or k == steps - 1:
            prog["sent"] = k + 1
            prog["time"] = time.time()
            (DATA / "progress.json").write_text(json.dumps(prog))
    prog["done"] = True
    (DATA / "progress.json").write_text(json.dumps(prog))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
