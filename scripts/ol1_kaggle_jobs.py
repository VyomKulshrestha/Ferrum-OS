#!/usr/bin/env python3
"""ol1 open-weight arm (exploratory): the Kaggle job file for the resized grid of
docs/research/operator_in_the_loop_ol1_notes.md, written from the registered sealed definitions.

    python scripts/ol1_kaggle_jobs.py      ->  target/ol1/kaggle/ol1_jobs_kaggle_sealed.npz

Runs the registration check (ol1_stage2.enable_sealed) before anything else, imports the registered code
without changing it, and writes the five reduced cells on replicate 0 of runs 0 and 1 of every mode: 14
placements, 70 jobs, a subset of the registered reduced grid. Needs target/ol1/ol1_dev_input.npz (written by
`python scripts/ol1_export.py dev`) for tau0, p and the tight threshold, as the registered writer does.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ol1_core as C
import ol1_export as X
import ol1_stage2 as S
import repro_env

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "target/ol1/kaggle/ol1_jobs_kaggle_sealed.npz"
RUNS = (0, 1)
REPLICATE = 0


def kaggle_jobs():
    jobs = [
        [m, C.sealed_seed(m, u, REPLICATE), c, a]
        for m in range(7)
        for u in RUNS
        for c, a in S.REDUCED
    ]
    registered = {tuple(j) for j in S.grid_jobs("claude-sonnet-5-5", "sealed")}
    assert {tuple(j) for j in jobs} <= registered, (
        "not a subset of the registered reduced grid"
    )
    return jobs


def main(out: Path = OUT, cache: Path = S.SEALED_CACHE, setup: Path = S.SETUP):
    # refuses unless the registration record matches the protocol and the code
    reg = S.enable_sealed(ROOT)
    dev = C.load_modes_from_derived(X.DEV_INPUT)
    names = json.loads(Path(setup).read_text(encoding="utf-8"))["modes"]
    modes = {}
    for m in range(7):
        z = np.load(Path(cache) / f"mode_{m}.npz", allow_pickle=False)
        runs = [
            np.asarray(z["sealed::" + r["name"]], np.float64)
            for r in names[str(m)]["sealed"]
        ]
        d = dev[m]
        modes[m] = C.Mode(m, d.tau0, d.p, d.tau_tight, [], sealed_runs=runs)
    jobs = kaggle_jobs()
    X.write_job_file(modes, jobs, out, "sealed")
    data = out.read_bytes()
    meta = json.loads(str(np.load(out)["meta"]))
    print(
        json.dumps(
            {
                "file": str(out),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "jobs": len(meta["jobs"]),
                "placements": len(meta["placements"]),
                "core_digest": meta["core_digest"],
                "registration": {
                    k: reg[k]
                    for k in ("registered_on", "code_commit", "protocol_sha256")
                },
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    repro_env.pin_from_environment()
    main()
