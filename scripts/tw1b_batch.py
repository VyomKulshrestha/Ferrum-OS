#!/usr/bin/env python3
"""tw1b: run the round's jobs in parallel, one thread per process, and resume after a restart.

    python scripts/tw1b_batch.py <tw1 python> [processes] [phase ...]

Phases, in order: harness, calib, D, B, spot, frog; B5 (amendment 5: configuration B of the Gaussian-tail
calibrator again, with the corrected reading) runs only when named. A job is done when its part file says so; a job whose
input (configuration B's parameter) is missing waits. Before each launch the free memory is checked with
fi2-tools/memfree.py (MEMFREE, default C:/Users/marcu/Videos/fi2-tools/memfree.py); the batch waits while it
is short. Logs go to target/tw1/tw1b/logs/.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "target/tw1/tw1b"
MODES = range(7)
HIST = ("full", "young")
CALIBRATED = (
    "river_q",
    "pysad_q",
    "conformal",
    "gauss",
    "likelihood",
    "pysad_spot",
    "libspot",
)
D_KEYS = ("river_tf",) + CALIBRATED
MEMFREE = os.environ.get("MEMFREE", "C:/Users/marcu/Videos/fi2-tools/memfree.py")


def done_status(path):
    if not path.exists():
        return False
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return d.get("status") is not None or d.get("chosen") is not None or "targets" in d


def jobs(phases):
    S = ROOT / "scripts"
    out = []
    for ph in phases:
        if ph == "harness":
            for m in MODES:
                for h in HIST:
                    out.append(
                        (
                            f"harness_m{m}_{h}",
                            [S / "tw1b_score_level_dev.py", "harness", m, h],
                            OUT / f"harness/tw1a_mode{m}_{h}.json",
                            None,
                        )
                    )
        elif ph == "calib":
            for k in CALIBRATED:
                for m in MODES:
                    out.append(
                        (
                            f"calib_m{m}_{k}",
                            [S / "tw1b_score_level_dev.py", "calib", m, k],
                            OUT / f"calib/mode{m}_{k}.json",
                            None,
                        )
                    )
        elif ph in ("D", "B", "B5"):
            keys = {"D": D_KEYS, "B": CALIBRATED, "B5": ("gauss",)}[ph]
            for k in keys:
                for m in MODES:
                    for h in HIST:
                        need = OUT / f"calib/mode{m}_{k}.json" if ph != "D" else None
                        out.append(
                            (
                                f"{ph}_m{m}_{h}_{k}",
                                [S / "tw1b_score_level_dev.py", "run", ph, m, h, k],
                                OUT / f"parts/{ph}_mode{m}_{h}_{k}.json",
                                need,
                            )
                        )
        elif ph == "spot":
            for h in ("young", "full"):
                for m in MODES:
                    out.append(
                        (
                            f"spotc_m{m}_{h}",
                            [S / "tw1b_spot_authors.py", "campaigns", m, h],
                            OUT / f"spot/campaigns_mode{m}_{h}.json",
                            None,
                        )
                    )
            for h in ("young", "full"):
                for m in MODES:
                    out.append(
                        (
                            f"spota_m{m}_{h}",
                            [S / "tw1b_spot_authors.py", "attacks", m, h],
                            OUT / f"spot/attacks_mode{m}_{h}.json",
                            None,
                        )
                    )
        elif ph == "frog":
            for m in MODES:
                out.append(
                    (
                        f"spotf_m{m}",
                        [S / "tw1b_spot_authors.py", "frog", m],
                        OUT / f"spot/frog_mode{m}_young.json",
                        None,
                    )
                )
    return out


def memory_ok():
    if not Path(MEMFREE).exists():
        return True
    return (
        subprocess.run(
            [sys.executable, MEMFREE, "1.2", "3"], capture_output=True
        ).returncode
        == 0
    )


def main():
    py = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    phases = sys.argv[3:] or ["harness", "calib", "D", "B", "spot", "frog"]
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        REPRO_THREADS="1",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
    )
    pending = [j for j in jobs(phases) if not done_status(j[2])]
    running = {}
    print(f"{len(pending)} jobs pending", flush=True)
    while pending or running:
        for name, p in list(running.items()):
            if p.poll() is not None:
                print(
                    time.strftime("%H:%M:%S"),
                    "finished",
                    name,
                    "exit",
                    p.returncode,
                    flush=True,
                )
                del running[name]
        launched = False
        for j in list(pending):
            if len(running) >= n:
                break
            name, cmd, part, need = j
            if need is not None and not done_status(need):
                continue
            if not memory_ok():
                break
            log = open(OUT / "logs" / f"{name}.log", "a", encoding="utf-8")
            running[name] = subprocess.Popen(
                [py, "-I", *map(str, cmd)],
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=ROOT,
                env=env,
            )
            pending.remove(j)
            print(time.strftime("%H:%M:%S"), "started", name, flush=True)
            launched = True
        if not launched:
            time.sleep(10)
    print("all done", flush=True)


if __name__ == "__main__":
    main()
