#!/usr/bin/env python3
"""Run ferrum_experiment.py in the official Robotarium Python simulator before uploading it.

Executes the upload file unchanged except for SEED / N_EPISODES (substituted on the
command line) with the simulator's real-time throttle and figure turned off, in a temp
working directory, then reports the testbed's own validation counters (too close, out of
bounds, actuator limits), the closest approach, the estimated duration against the
600 s limit, and the label statistics.

Needs the simulator (github.com/robotarium/robotarium_python_simulator) and cvxopt, kept
out of the main environment:
  target/robotarium/venv/Scripts/python scripts/robotarium/check_in_simulator.py --seeds 101 102
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SIM = ROOT / "target/robotarium/robotarium_python_simulator"
sys.path.insert(0, str(SIM))
sys.path.insert(0, str(HERE))

import rps.robotarium as robotarium  # noqa: E402

import label_robotarium_log as L  # noqa: E402

LIMIT_S = 600.0
INIT_ALLOWANCE_S = 30.0     # the testbed drives robots onto the arena before the script's first step


def run(seed, episodes, figure=False):
    src = (HERE / "ferrum_experiment.py").read_text(encoding="utf-8")
    src = re.sub(r"^SEED = \d+", f"SEED = {seed}", src, count=1, flags=re.M)
    src = re.sub(r"^N_EPISODES = \d+", f"N_EPISODES = {episodes}", src, count=1, flags=re.M)
    created = []
    orig = robotarium.Robotarium.__init__

    def patched(self, **kw):
        kw["sim_in_real_time"] = False
        kw["show_figure"] = figure
        orig(self, **kw)
        created.append(self)

    robotarium.Robotarium.__init__ = patched
    cwd = os.getcwd()
    out = Path(tempfile.mkdtemp(prefix=f"ferrum_rbt_{seed}_"))
    try:
        os.chdir(out)
        exec(compile(src, "ferrum_experiment.py", "exec"), {"__name__": "__main__"})
    finally:
        os.chdir(cwd)
        robotarium.Robotarium.__init__ = orig
    r = created[0]
    errors = dict(r._errors)
    lab = L.label(out)
    duration = r._iteration * r.TIME_STEP
    return {"seed": seed, "dir": out, "errors": errors, "duration_s": duration, "lab": lab}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[101])
    ap.add_argument("--episodes", type=int, default=None, help="override N_EPISODES")
    ap.add_argument("--figure", action="store_true", help="also exercise the projected-fence drawing (Agg)")
    a = ap.parse_args()
    episodes = a.episodes or int(re.search(r"^N_EPISODES = (\d+)", (HERE / "ferrum_experiment.py").read_text(), re.M).group(1))
    bad = 0
    for seed in a.seeds:
        res = run(seed, episodes, a.figure)
        lab, err = res["lab"], res["errors"]
        hard = err.get("robots_too_close", 0) + err.get("robots_outside_boundaries", 0)
        total = res["duration_s"] + INIT_ALLOWANCE_S
        ok = hard == 0 and total <= LIMIT_S
        bad += not ok
        print(f"seed {seed}: {'OK ' if ok else 'BAD'} too_close={err.get('robots_too_close', 0)} "
              f"out_of_bounds={err.get('robots_outside_boundaries', 0)} actuator={err.get('exceeded_actuator_limits', 0)} | "
              f"duration {res['duration_s']:.0f} s (+{INIT_ALLOWANCE_S:.0f} s init allowance vs {LIMIT_S:.0f} s) | "
              f"{len(lab['y'])} decisions, prevalence {lab['y'].mean():.3f} (proximity {lab['proximity'].mean():.3f}, "
              f"geofence {lab['geofence'].mean():.3f}) | closest {lab['min_centre_dist_m'].min():.3f} m | {res['dir']}")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
