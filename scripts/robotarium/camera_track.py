#!/usr/bin/env python3
"""Camera tracking for the Robotarium runs: robot and obstacle positions measured from the
rectified overhead frames, so a state model can run on camera input. Branch work, not main.

Input is the 256 px `inspect` stack that video_frames.py writes (top-down, runtime extent
+-1.5, y up; 1 px = 0.0117 runtime units = 8.2 mm in the arena). Both GRITSbots are dark
blobs on the light floor (grey < 70); the dark frame border outside the arena is ignored.

Which blob is the parked obstacle is decided causally from frames 0..t only: it is the
frame-0 blob that has stayed within 3 px in every frame so far while the other one has
moved. Until the robot first moves, the projected disc decides (ring just outside the body
darker than the floor further out); the disc is faint in the rectified frames, so this
fallback is weak and only matters before the first move. The robot at step t is the blob
farthest from that obstacle; if no robot blob is seen, the last position is held.

`state_features` builds exactly the columns of vision_runtime_proxy_final.state_features
from tracked positions (obstacle per step instead of per episode).

Usage (diagnostic against the logged positions, not evidence):
  python scripts/robotarium/camera_track.py                # all runs with processed frames
  python scripts/robotarium/camera_track.py seed701 seed703
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNS = ROOT / "target/robotarium/runs"
OUT = ROOT / "docs/research/vision_caution_camera_track_check_v1.json"

EXTENT_RT, SIZE = 1.5, 256          # must match video_frames.py (EXTENT_RT, INSPECT_SIZE)
DARK, BG_DROP, AREA, MAX_RT = 70, 60, (40, 400), 1.25
FRAG_PX, MERGE_PX, STAY_PX, MIN_SEP_PX = 15, 12.0, 3.0, 6.0
_YY, _XX = np.mgrid[:SIZE, :SIZE]


def px2rt(c):
    """Pixel centre (col, row) of the rectified frame -> runtime coordinates (x, y)."""
    return np.array([(c[0] + 0.5) / SIZE * 2 * EXTENT_RT - EXTENT_RT,
                     EXTENT_RT - (c[1] + 0.5) / SIZE * 2 * EXTENT_RT], np.float32)


def run_background(inspect):
    """Per-pixel median over every frame of a run: the empty scene with the projected fence (robots
    move and the obstacle changes place between episodes). Scenery only, no label information."""
    return np.median(inspect.reshape(-1, SIZE, SIZE), axis=0)


def blobs(img, bg=None):
    """Centroids (px) of robot-sized dark blobs inside the arena. A pixel counts when it is dark
    and, given a background, at least BG_DROP darker than it (rejects pieces of the fence line);
    fragments within MERGE_PX are merged by area (the parked robot sometimes splits on its disc).
    Robot and obstacle are always >= 24 px apart, so they never merge."""
    mask = img < DARK
    if bg is not None:
        mask &= (bg.astype(np.float32) - img) > BG_DROP
    n, _, st, cen = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    parts = [[cen[i] * st[i, cv2.CC_STAT_AREA], float(st[i, cv2.CC_STAT_AREA])]
             for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= FRAG_PX]
    merged = True
    while merged:
        merged = False
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                if np.hypot(*(parts[i][0] / parts[i][1] - parts[j][0] / parts[j][1])) < MERGE_PX:
                    parts[i] = [parts[i][0] + parts[j][0], parts[i][1] + parts[j][1]]
                    del parts[j]
                    merged = True
                    break
            if merged:
                break
    keep = [(a, s / a) for s, a in parts if AREA[0] <= a <= AREA[1] and np.abs(px2rt(s / a)).max() < MAX_RT]
    return [c for _, c in sorted(keep, key=lambda x: -x[0])]          # largest first


def _ring(img, c, r0, r1):
    d = np.hypot(_XX - c[0], _YY - c[1])
    sel = (d >= r0) & (d < r1) & (img >= DARK)
    return float(img[sel].mean()) if sel.any() else 255.0


def disc_contrast(img, c):
    """Lower = more disc-like: ring just outside the body (disc radius 0.09 m = 11 px) minus the floor beyond."""
    return _ring(img, c, 8, 11) - _ring(img, c, 14, 18)


def track_episode(frames, bg=None):
    """frames (T, 256, 256) uint8 -> dict of per-step arrays (runtime units); step t uses frames 0..t only:
    robot, obstacle (T, 2); alt_robot, alt_obstacle (T, 2) = the swapped assignment while identity is
    unresolved (equal to robot/obstacle once resolved); robot_seen, identity_by_motion (T,) bool."""
    T = len(frames)
    found = [blobs(frames[k], bg) for k in range(T)]
    b0 = list(found[0])[:2]                               # the two largest blobs
    if len(b0) < 2:                                       # merged or missed at frame 0: pad with the centre
        b0 = (b0 + [np.array([SIZE / 2, SIZE / 2])] * 2)[:2]
    b0 = sorted(b0, key=lambda c: disc_contrast(frames[0], c))
    miss = [0, 0]                                         # frames so far with no blob at the frame-0 spot
    out = {k: np.zeros((T, 2), np.float32) for k in ("robot", "obstacle", "alt_robot", "alt_obstacle")}
    seen, by_motion = np.zeros(T, bool), np.zeros(T, bool)
    last, ob = None, 0
    for t in range(T):
        for i in (0, 1):
            miss[i] += not any(np.hypot(*(c - b0[i])) < STAY_PX for c in found[t])
        lo, hi = min(miss), max(miss)
        by_motion[t] = (lo == 0 and hi >= 1) or hi - lo >= 2     # one dropout of a still blob does not decide
        if by_motion[t]:
            ob = int(np.argmin(miss))
        oc, rc0 = b0[ob], b0[1 - ob]
        cand = [c for c in found[t] if np.hypot(*(c - oc)) > MIN_SEP_PX]
        if cand:
            last = px2rt(max(cand, key=lambda c: np.hypot(*(c - oc))))
            seen[t] = True
        out["obstacle"][t] = px2rt(oc)
        out["robot"][t] = last if last is not None else px2rt(rc0)
        if by_motion[t]:
            out["alt_robot"][t], out["alt_obstacle"][t] = out["robot"][t], out["obstacle"][t]
        else:                                             # still before the first move: the other reading
            out["alt_robot"][t], out["alt_obstacle"][t] = px2rt(oc), out["robot"][t]
    out.update(robot_seen=seen, identity_by_motion=by_motion)
    return out


def track(inspect):
    """inspect (n_ep, T, 256, 256) -> dict of arrays with leading shape (n_ep, T) (see track_episode)."""
    bg = run_background(inspect)
    eps = [track_episode(ep, bg) for ep in inspect]
    return {k: np.stack([o[k] for o in eps]) for k in eps[0]}


def state_features(robot, obstacle, idx):
    """vision_runtime_proxy_final.state_features (same 22 columns) from tracked positions.
    robot (n_ep, T, 2); obstacle (n_ep, T, 2) per step or (n_ep, 2) per episode."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import train_physical_world_model as simulator
    import vision_runtime_domain_render as R
    e, t = idx["e"], idx["t"]
    r = robot[e, t]
    o = obstacle[e, t] if obstacle.ndim == 3 else obstacle[e]
    a = idx["a10"]
    moving = ((idx["kind"] == simulator.MOVE) & (a[:, 9] > 0.1)).astype(np.float32)
    nxt = r + R.STEP_GAIN * a[:, 7:9] * moving[:, None]
    clr = lambda p: np.clip(np.hypot(*(p - o).T) - 0.16, 0, 1)
    mar = lambda p: 1.0 - np.abs(p).max(1)
    return np.column_stack([r, o, o - r, clr(r), mar(r), nxt, clr(nxt), mar(nxt), a]).astype(np.float32)


def check_run(path):
    d = np.load(path / "frames.npz")
    tr = track(d["inspect"])
    er = np.hypot(*(tr["robot"] - d["robot_xy"]).reshape(-1, 2).T)
    eo = np.hypot(*(tr["obstacle"] - d["obstacle_xy"][:, None, :]).reshape(-1, 2).T)
    dec = np.zeros(d["robot_xy"].shape[:2], bool)
    dec[:, 1:-1] = True                                   # decision steps t = 1..T-2 (vision_runtime_proxy_final.decisions)
    eo_dec = np.hypot(*(tr["obstacle"] - d["obstacle_xy"][:, None, :])[dec].T)
    q = lambda x, p: float(np.quantile(x, p))
    return {"steps": int(er.size), "robot_err_rt": {"median": q(er, .5), "p90": q(er, .9), "max": float(er.max())},
            "obstacle_err_rt": {"median": q(eo, .5), "p90": q(eo, .9)},
            "obstacle_wrong_frac": float(np.mean(eo > 0.1)), "obstacle_wrong_frac_decision_steps": float(np.mean(eo_dec > 0.1)),
            "robot_seen_frac": float(tr["robot_seen"].mean()),
            "identity_by_motion_frac": float(tr["identity_by_motion"].mean())}


def main():
    names = sys.argv[1:] or sorted(p.name for p in RUNS.glob("seed*") if (p / "frames.npz").exists())
    res = {}
    for n in names:
        res[n] = check_run(RUNS / n)
        r = res[n]
        print(f"{n}: robot err median {r['robot_err_rt']['median']:.4f} p90 {r['robot_err_rt']['p90']:.4f} rt | "
              f"obstacle wrong {r['obstacle_wrong_frac']:.1%} (decision steps {r['obstacle_wrong_frac_decision_steps']:.1%}) | robot seen {r['robot_seen_frac']:.1%} | "
              f"identity by motion {r['identity_by_motion_frac']:.1%}", flush=True)
    er = np.array([r["robot_err_rt"]["median"] for r in res.values()])
    ow = np.array([r["obstacle_wrong_frac_decision_steps"] for r in res.values()])
    summary = {"runs": len(res), "robot_err_median_of_run_medians_rt": float(np.median(er)),
               "robot_err_median_m": float(np.median(er) * 0.7),
               "obstacle_wrong_frac_decision_steps_mean": float(ow.mean()),
               "worst_run_obstacle_wrong": max(res, key=lambda n: res[n]["obstacle_wrong_frac_decision_steps"])}
    print("summary:", json.dumps(summary))
    if not sys.argv[1:]:
        OUT.write_text(json.dumps({"schema_version": "vision-caution-camera-track-check-v1",
                                   "status": "diagnostic, not evidence: tracked vs logged positions on every run with processed frames",
                                   "tracker": "scripts/robotarium/camera_track.py", "unit": "runtime units (1 rt = 0.7 m)",
                                   "summary": summary, "runs": res}, indent=1) + "\n", encoding="utf-8")
        print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
