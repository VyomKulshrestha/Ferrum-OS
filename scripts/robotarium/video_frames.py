#!/usr/bin/env python3
"""Turn a Robotarium FerrumOS run (video + logged poses) into per-step camera frames.

1. Time sync. The video's motion energy (frame differences inside the arena) is matched
   to the logged robot speed: a global line (video time of iteration 0 + iteration rate),
   then a local offset per window of iterations, interpolated. The testbed's control loop
   runs about 1% slow with +-0.2 s jitter, so one line is not enough.
2. Camera fit. Only frames from the middle of each step's 0.7 s hold are used (both robots
   still, so sync jitter cannot move them). Each frame with two dark robot blobs gives both
   possible blob-to-robot pairings; a RANSAC homography keeps the consistent ones, then a
   plane homography plus one radial lens term (about the image centre) is fitted by robust
   least squares together with the body offset (the logged pose sits behind the visible
   body centre along the heading; the testbed's collision check uses 0.025 m), every frame
   is re-paired under it and the fit repeated. (OpenCV's full
   camera model was tried first: from one plane it traded focal length against distortion
   and diverged.) Poses are robot-top points, so the fitted plane is the robots' top
   surface, not the floor.
3. Frames. For every runtime step, the frame in the middle of the hold is rectified to a
   top-down view covering runtime |x|, |y| <= 1.5 (the proxy camera's framing), grey,
   64x64, plus a 256x256 copy for inspection.

Writes <run>/frames.npz (dataset keys of vision_runtime_domain_render.collect, runtime
units, contact all zero), <run>/camera.json and <run>/contact_sheet.jpg.

Usage: python scripts/robotarium/video_frames.py target/robotarium/runs/seed101
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import least_squares

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import label_robotarium_log as L  # noqa: E402

EVERY = 2                      # analyse every 2nd video frame for sync and fitting
HALF = 0.5                     # analysis resolution (960x540)
BLOB_AREA = (200, 1600)        # robot blob area at half resolution
EXTENT_RT, MODEL_SIZE, INSPECT_SIZE = 1.5, 64, 256


def read_video(path):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    greys, idx, i = [], [], 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % EVERY == 0:
            _, f = cap.retrieve()
            greys.append(cv2.cvtColor(cv2.resize(f, None, fx=HALF, fy=HALF, interpolation=cv2.INTER_AREA),
                                      cv2.COLOR_BGR2GRAY))
            idx.append(i)
        i += 1
    return np.stack(greys), np.array(idx), fps


def arena_mask(greys):
    med = np.median(greys[:: max(1, len(greys) // 200)], 0).astype(np.uint8)
    m = (med > 110).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    return cv2.erode((lab == k).astype(np.uint8), np.ones((25, 25), np.uint8))


def sync(greys, frame_idx, fps, traj, dt, window=900):
    mask = arena_mask(greys).astype(bool)
    energy = np.array([0.0] + [float(np.abs(greys[i].astype(np.int16) - greys[i - 1])[mask].mean())
                               for i in range(1, len(greys))])
    t_video = frame_idx / fps
    speed = np.r_[0.0, np.abs(np.diff(traj[:, [1, 2, 4, 5]], axis=0)).sum(1)]
    speed = np.convolve(speed, np.ones(5) / 5, "same")
    e = (energy - energy.mean()) / (energy.std() + 1e-9)

    def corr(t_it, sl=slice(None)):
        w = (t_video >= t_it[sl][0]) & (t_video <= t_it[sl][-1])
        sp = np.interp(t_video[w], t_it[sl], speed[sl])
        return float(np.corrcoef(e[w], sp)[0, 1]) if sp.std() > 0 else -2.0

    its = np.arange(len(traj))
    best = (-2.0, 0.0, 1.0)
    for rate in np.arange(0.98, 1.02 + 1e-9, 0.002):
        for t0 in np.arange(0.0, max(1.0, t_video[-1] - its[-1] * dt * rate) + 1e-9, 0.04):
            r = corr(t0 + its * dt * rate)
            if r > best[0]:
                best = (r, float(t0), float(rate))
    line = best[1] + its * dt * best[2]
    knots_it, knots_t, knot_corr = [], [], []
    shifts = np.arange(-1.0, 1.0 + 1e-9, 0.04)
    for start in range(0, len(traj) - window // 2, window):
        sl = slice(start, min(start + window, len(traj)))
        rs = [corr(line + d, sl) for d in shifts]
        k = int(np.argmax(rs))
        mid = (sl.start + sl.stop - 1) / 2
        knots_it.append(mid)
        knots_t.append(float(np.interp(mid, its, line)) + float(shifts[k]))
        knot_corr.append(rs[k])
    t_of_it = np.interp(its, knots_it, knots_t)
    lo, hi = its < knots_it[0], its > knots_it[-1]        # ends: continue along the global rate
    t_of_it[lo] = knots_t[0] - (knots_it[0] - its[lo]) * dt * best[2]
    t_of_it[hi] = knots_t[-1] + (its[hi] - knots_it[-1]) * dt * best[2]
    return {"corr": best[0], "t0_s": best[1], "rate": best[2], "knot_corr_median": float(np.median(knot_corr)),
            "knots_it": knots_it, "knots_t": knots_t, "t_of_it": t_of_it, "mask": mask}


def blobs(grey, mask):
    m = ((grey < 70) & mask).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))      # rejoin a fragmented board
    n, _, st, cen = cv2.connectedComponentsWithStats(m)
    return [cen[i] / HALF for i in range(1, n) if BLOB_AREA[0] <= st[i, cv2.CC_STAT_AREA] <= BLOB_AREA[1]]


def project(cam, xy):
    """Arena metres (robot-top plane) -> image pixels: a plane homography, then one radial
    lens term about the image centre (pixel radius in units of 1000 px)."""
    H = np.append(np.asarray(cam["h"], np.float64), 1.0).reshape(3, 3)
    c = np.asarray(cam["centre"], np.float64)
    p = np.c_[np.asarray(xy, np.float64), np.ones(len(xy))] @ H.T
    d = (p[:, :2] / p[:, 2:3] - c) / 1000.0
    return c + d * (1.0 + cam["k1"] * (d ** 2).sum(1, keepdims=True)) * 1000.0


def body_points(poses, offset):
    """Logged poses (x, y, heading) -> the visible body centre, `offset` metres ahead along
    the heading (the testbed's own collision check uses 0.025 m)."""
    poses = np.asarray(poses, np.float64)
    return poses[:, :2] + offset * np.c_[np.cos(poses[:, 2]), np.sin(poses[:, 2])]


def _fit(src, dst, cam):
    """src: logged poses (x, y, heading); fits homography, k1 and the body offset."""
    def resid(v):
        return (project({"h": v[:8], "k1": v[8], "centre": cam["centre"]}, body_points(src, v[9])) - dst).ravel()
    x0 = np.r_[cam["h"], cam["k1"], cam["body_offset_m"]]
    r = least_squares(resid, x0, loss="soft_l1", f_scale=4.0)
    return {"h": r.x[:8].tolist(), "k1": float(r.x[8]), "body_offset_m": float(r.x[9]), "centre": cam["centre"]}


def fit_camera(greys, frame_idx, fps, steps, col, hold_its, s, size, traj):
    t_video = frame_idx / fps
    frames = []
    for e in range(steps.shape[0]):
        for k in range(steps.shape[1]):
            it_end = int(steps[e, k, col["it_end"]])
            t_lo, t_hi = s["t_of_it"][it_end - 2 * hold_its + 3], s["t_of_it"][it_end - 3]
            r0 = traj[it_end - 1, 1:4]                    # (x, y, heading) of both robots during the hold
            r1 = traj[it_end - 1, 4:7]
            for j in np.flatnonzero((t_video >= t_lo) & (t_video <= t_hi)):
                b = blobs(greys[j], s["mask"])
                if len(b) == 2:
                    frames.append((r0, r1, np.array(b[0]), np.array(b[1])))
    src = np.array([p for r0, r1, _, _ in frames for p in (r0, r1, r0, r1)], np.float64)
    dst = np.array([p for _, _, b0, b1 in frames for p in (b0, b1, b1, b0)], np.float64)
    H, inl = cv2.findHomography(body_points(src, 0.025), dst, cv2.RANSAC, 15.0)
    inl = inl.ravel().astype(bool)
    cam = _fit(src[inl], dst[inl], {"h": (H / H[2, 2]).ravel()[:8].tolist(), "k1": 0.0, "body_offset_m": 0.025,
                                     "centre": [size[0] / 2, size[1] / 2]})
    for _ in range(3):                               # re-pair every frame under the current model, refit
        keep_s, keep_d = [], []
        for r0, r1, b0, b1 in frames:
            pr = project(cam, body_points(np.array([r0, r1]), cam["body_offset_m"]))
            straight = max(np.hypot(*(pr[0] - b0)), np.hypot(*(pr[1] - b1)))
            swapped = max(np.hypot(*(pr[0] - b1)), np.hypot(*(pr[1] - b0)))
            if min(straight, swapped) < 12.0:
                keep_s += [r0, r1]
                keep_d += [b0, b1] if straight <= swapped else [b1, b0]
        keep_s, keep_d = np.array(keep_s), np.array(keep_d)
        cam = _fit(keep_s, keep_d, cam)
    err = np.hypot(*(project(cam, body_points(keep_s, cam["body_offset_m"])) - keep_d).T)
    c = project(cam, np.array([[0.05, 0.0], [-0.05, 0.0]]))
    px_per_m = float(np.hypot(*(c[0] - c[1])) / 0.1)
    cam.update({"model": "plane homography + one radial term about the image centre",
                "hold_frames_with_two_blobs": len(frames), "hold_frames_paired": int(len(keep_s) // 2),
                "median_err_px": float(np.median(err)), "p90_err_px": float(np.quantile(err, 0.9)),
                "median_err_m": float(np.median(err) / px_per_m), "px_per_m": px_per_m,
                "pose_extent_m": [float(np.abs(keep_s[:, 0]).max()), float(np.abs(keep_s[:, 1]).max())]})
    return cam


def rectifier(cam, scale, out):
    """Maps for cv2.remap: output top-down pixel -> source image pixel."""
    half = EXTENT_RT * scale                                     # arena metres
    u = (np.arange(out) + 0.5) / out * 2 * half - half
    xx, yy = np.meshgrid(u, -u)
    p = project(cam, np.c_[xx.ravel(), yy.ravel()])
    return p[:, 0].reshape(out, out).astype(np.float32), p[:, 1].reshape(out, out).astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    a = ap.parse_args()
    run = Path(a.run)
    meta = json.loads((run / "ferrum_meta.txt").read_text(encoding="utf-8"))
    traj = np.load(run / "ferrum_traj.npy")
    steps = np.load(run / "ferrum_steps.npy").reshape(meta["episodes"], meta["steps"], -1)
    col = {c: i for i, c in enumerate(meta["step_columns"])}
    dt, scale = meta["time_step_s"], meta["scale"]
    hold_its = int(meta["hold_s"] / dt / 2)
    video = run / "experiment_video.mp4"
    greys, frame_idx, fps = read_video(video)
    print(f"video: {len(greys)} analysed frames at {fps / EVERY:.1f} fps", flush=True)
    s = sync(greys, frame_idx, fps, traj, dt)
    print(f"sync: iteration 0 at video {s['t0_s']:.2f} s, rate {s['rate']:.4f}, global corr {s['corr']:.3f}, "
          f"window corr median {s['knot_corr_median']:.3f} over {len(s['knots_it'])} windows", flush=True)
    cap = cv2.VideoCapture(str(video))
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cam = fit_camera(greys, frame_idx, fps, steps, col, hold_its, s, size, traj)
    print(f"camera: {cam['hold_frames_paired']}/{cam['hold_frames_with_two_blobs']} hold frames paired, reprojection "
          f"median {cam['median_err_px']:.1f} px (p90 {cam['p90_err_px']:.1f}) = {cam['median_err_m'] * 100:.1f} cm; "
          f"k1={cam['k1']:.4f}, body offset {cam['body_offset_m'] * 100:.1f} cm, {cam['px_per_m']:.0f} px/m", flush=True)

    lab = L.label(run)
    t_of = lambda it: float(s["t_of_it"][it])
    maps = rectifier(cam, scale, MODEL_SIZE), rectifier(cam, scale, INSPECT_SIZE)
    n_ep, n_st = meta["episodes"], meta["steps"]
    frames = np.zeros((n_ep, n_st + 1, MODEL_SIZE, MODEL_SIZE), np.float32)
    inspect = np.zeros((n_ep, n_st + 1, INSPECT_SIZE, INSPECT_SIZE), np.uint8)
    times = np.zeros((n_ep, n_st + 1))
    for e in range(n_ep):
        its = [int(steps[e, 0, col["it_start"]])] + [int(steps[e, k, col["it_end"]]) - hold_its for k in range(n_st)]
        for k, it in enumerate(its):
            cap.set(cv2.CAP_PROP_POS_MSEC, t_of(it) * 1000.0)
            ok, f = cap.read()
            if not ok:
                raise RuntimeError(f"no video frame at {t_of(it):.2f} s")
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            frames[e, k] = cv2.remap(g, *maps[0], cv2.INTER_AREA).astype(np.float32) / 255.0
            inspect[e, k] = cv2.remap(g, *maps[1], cv2.INTER_LINEAR)
            times[e, k] = t_of(it)
    robot_xy, obstacle_xy = lab["robot_xy"], lab["obstacle_xy"]          # body centres, runtime units
    clearance = np.concatenate([np.clip(np.hypot(*(robot_xy[:, :1] - obstacle_xy[:, None]).transpose(2, 0, 1)) - 0.16,
                                        0, 1), lab["clearance"]], 1).astype(np.float32)
    margin = (1.0 - np.abs(robot_xy).max(2)).astype(np.float32)
    np.savez_compressed(run / "frames.npz", frames=frames, kinds=steps[:, :, col["kind"]].astype(np.int64),
                        features=steps[:, :, [col["f0"], col["f1"], col["f2"]]].astype(np.float32),
                        hazards=lab["hazards"], clearance=clearance, margin=margin,
                        contact=np.zeros_like(lab["hazards"]), robot_xy=robot_xy, obstacle_xy=obstacle_xy,
                        video_time_s=times, inspect=inspect)
    (run / "camera.json").write_text(json.dumps({"sync": {k: v for k, v in s.items() if k not in ("mask", "t_of_it")},
                                                 "camera": cam, "video_fps": fps, "video_size": size,
                                                 "rectified_extent_runtime": EXTENT_RT}, indent=1), encoding="utf-8")
    sheet = np.vstack([np.hstack(list(inspect[e, ::2])) for e in range(min(4, n_ep))])
    cv2.imwrite(str(run / "contact_sheet.jpg"), sheet)
    print(f"wrote {run / 'frames.npz'} ({n_ep}x{n_st + 1} frames), camera.json, contact_sheet.jpg")


if __name__ == "__main__":
    main()
