#!/usr/bin/env python3
"""ol1: derived inputs from the tt1f score cache.

    python scripts/ol1_export.py dev [--cache DIR] [--out FILE]
        target/ol1/ol1_dev_input.npz: per mode the four calibration runs as development blocks, tau0, the
        per-step exceedance target p and the benign condition's tight threshold. Reads only the arrays `cfg`
        and `pooled` of each cache file; no sealed run, attack run or label array is read.
    python scripts/ol1_export.py jobs --seeds 1-2 --modes 0-6 [--conditions ..] [--arms ..] [--out FILE]
        a job file for the Kaggle script: the background windows of each development placement (float64,
        the D1 score only), the mode constants and the job list. No sensor value, label or attack run.

The sealed job file is written by the stage-2 runner after registration (ol1_core.ALLOW_SEALED); this script
refuses sealed seeds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ol1_core as C
import repro_env

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = Path(
    r"C:\Users\marcu\Videos\cursor-os-base-tt1\target\real-telemetry\tt1f"
)
DEV_INPUT = ROOT / "target/ol1/ol1_dev_input.npz"
JOBS_OUT = ROOT / "target/ol1/ol1_jobs_dev.npz"
CALIB_RUNS = 4


def dev(cache: Path, out: Path):
    arrays, meta = (
        {},
        {"source": "tt1f score cache, arrays cfg and pooled only", "modes": {}},
    )
    for m in range(7):
        z = np.load(cache / f"mode_{m}.npz", allow_pickle=False)
        cfg = json.loads(str(z["cfg"]))
        pooled = np.asarray(z["pooled"], dtype=np.float64)
        n = len(pooled) // CALIB_RUNS
        if n * CALIB_RUNS != len(pooled):
            raise SystemExit(
                f"mode {m}: pooled length {len(pooled)} is not {CALIB_RUNS} equal runs"
            )
        blocks = [pooled[i * n : (i + 1) * n] for i in range(CALIB_RUNS)]
        tight = C.nuisance_threshold(blocks)
        check = C.calibrate(blocks, C.BUDGET_PER_DAY)
        fa = sum(C.count_episodes(b, tight) for b in blocks) / (len(pooled) / C.SPD)
        meta["modes"][str(m)] = {
            "tau0": cfg["tau0"],
            "p": cfg["p"],
            "tau_tight": tight,
            "tau_tight_over_tau0": tight / cfg["tau0"],
            "tight_episodes_per_day": fa,
            "budget_rule_check_over_tau0": check / cfg["tau0"],
            "dev_blocks": CALIB_RUNS,
            "block_steps": n,
        }
        for i, b in enumerate(blocks):
            arrays[f"dev::{m}::{i}"] = b
        print(
            f"mode {m}: tau0 {cfg['tau0']:.3f} tight {tight / cfg['tau0']:.3f} tau0 ({fa:.1f}/day) budget-rule check {check / cfg['tau0']:.4f}"
        )
    meta["environment"] = repro_env.environment_record()
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, meta=np.array(json.dumps(meta)), **arrays)
    print("written", out, f"{out.stat().st_size / 1e6:.1f} MB")


def jobs(seeds, mode_list, conditions, arms, out: Path, source="dev"):
    if source != "dev":
        raise C.SealedSeedError("the sealed job file is written by the stage-2 runner")
    for s in seeds:
        C.assert_development(s)
    modes = C.load_modes_from_derived(DEV_INPUT)
    arrays, placements = {}, []
    for m in mode_list:
        for s in seeds:
            bg, twin, rec = modes[m].placement(s, source)
            arrays[f"w::{m}::{s}::bg"] = np.asarray(bg, np.float64)
            arrays[f"w::{m}::{s}::twin"] = np.asarray(twin, np.float64)
            placements.append({"mode": m, "seed": s, "record": rec})
    meta = {
        "status": "development job file (ol1 stage 1); D1 scores of attack-free calibration runs only",
        "source": source,
        "modes": {
            str(m): {k: getattr(modes[m], k) for k in ("tau0", "p", "tau_tight")}
            for m in mode_list
        },
        "placements": placements,
        "jobs": [
            [m, s, c, a]
            for m in mode_list
            for s in seeds
            for c in conditions
            for a in arms
        ],
        "core_digest": C.digest(Path(C.__file__).read_text(encoding="utf-8")),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, meta=np.array(json.dumps(meta)), **arrays)
    print(
        "written",
        out,
        f"{out.stat().st_size / 1e6:.2f} MB,",
        len(placements),
        "placements,",
        len(meta["jobs"]),
        "jobs",
    )


def parse_range(s):
    out = []
    for part in str(s).split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


if __name__ == "__main__":
    repro_env.pin_from_environment()
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "dev":
        dev(
            Path(repro_env.option_value(a, "--cache", DEFAULT_CACHE)),
            Path(repro_env.option_value(a, "--out", DEV_INPUT)),
        )
    elif cmd == "jobs":
        jobs(
            parse_range(repro_env.option_value(a, "--seeds", "1-2")),
            parse_range(repro_env.option_value(a, "--modes", "0-6")),
            repro_env.option_value(a, "--conditions", ",".join(C.CONDITIONS)).split(
                ","
            ),
            repro_env.option_value(a, "--arms", ",".join(C.ARMS)).split(","),
            Path(repro_env.option_value(a, "--out", JOBS_OUT)),
        )
    else:
        raise SystemExit(__doc__)
