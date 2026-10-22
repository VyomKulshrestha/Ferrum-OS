#!/usr/bin/env python3
"""Rendered-physics data for the FerrumOS vision world model (increment 1).

PyBullet is used as a 3D RENDERER (headless DIRECT, real camera/perspective/
lighting/occlusion) while the agent kinematics are integrated in numpy for full
control. The observation is therefore a genuine rendered image (the high-dim
regime where a neural world model earns its place), with known, controllable,
nonlinear dynamics (momentum + wall reflection) and geometry-based hazard labels.

Scene: dark floor, N static mid-gray box obstacles, a bright sphere agent, fixed
top-down grayscale camera. 5 discrete actions (stay, -x, +x, -y, +y) drive a
momentum-blended velocity. Per-step hazard = agent within MARGIN of an obstacle
or the bounds (imminent collision / out-of-bounds). Labels are for the caution
head / evaluation only; never model input.

collect(n_episodes, steps, size, seed) -> frames (N, steps+1, size, size) float32 [0,1],
                                          actions (N, steps) int64, hazards (N, steps+1) int8
Self-test: python scripts/vision_wm_pybullet_data.py
"""
from __future__ import annotations

import numpy as np

ACTIONS = np.array([[0, 0], [-1, 0], [1, 0], [0, -1], [0, 1]], np.float32)
BOUND = 2.2
AGENT_R = 0.22
BOX_HALF = 0.34
N_OBST = 2
MARGIN = 0.22
CAM_H = 5.4
VEL_DECAY, VEL_GAIN = 0.80, 0.085     # terminal speed ~0.42 units/frame


def _make_world():
    import pybullet as p
    p.connect(p.DIRECT)
    floor_c = p.createCollisionShape(p.GEOM_BOX, halfExtents=[BOUND + 1, BOUND + 1, 0.05])
    floor_v = p.createVisualShape(p.GEOM_BOX, halfExtents=[BOUND + 1, BOUND + 1, 0.05], rgbaColor=[0.10, 0.10, 0.10, 1])
    p.createMultiBody(0, floor_c, floor_v, [0, 0, -0.05])
    agent_v = p.createVisualShape(p.GEOM_SPHERE, radius=AGENT_R, rgbaColor=[1, 1, 1, 1])
    agent = p.createMultiBody(0, -1, agent_v, [0, 0, AGENT_R])
    obst = []
    for _ in range(N_OBST):
        vis = p.createVisualShape(p.GEOM_BOX, halfExtents=[BOX_HALF, BOX_HALF, BOX_HALF], rgbaColor=[0.55, 0.55, 0.55, 1])
        obst.append(p.createMultiBody(0, -1, vis, [10, 10, BOX_HALF]))
    view = p.computeViewMatrix([0, 0, CAM_H], [0, 0, 0], [0, 1, 0])
    proj = p.computeProjectionMatrixFOV(60, 1.0, 0.1, 12.0)
    return p, agent, obst, view, proj


def _render(p, size, view, proj):
    img = p.getCameraImage(size, size, view, proj, lightDirection=[0.2, 0.2, 1.0],
                           renderer=p.ER_TINY_RENDERER)[2]
    rgba = np.asarray(img, np.uint8).reshape(size, size, 4)
    return (rgba[:, :, :3].mean(2) / 255.0).astype(np.float32)


def collect(n_episodes=300, steps=20, size=48, seed=0):
    rng = np.random.default_rng(seed)
    P, agent, obst, view, proj = _make_world()
    frames = np.zeros((n_episodes, steps + 1, size, size), np.float32)
    actions = rng.integers(0, len(ACTIONS), (n_episodes, steps)).astype(np.int64)
    hazards = np.zeros((n_episodes, steps + 1), np.int8)

    def place_clear(existing, gap):
        pos = rng.uniform(-BOUND + 0.3, BOUND - 0.3, 2)
        for _ in range(200):
            if all(np.hypot(*(pos - e)) > gap for e in existing):
                break
            pos = rng.uniform(-BOUND + 0.3, BOUND - 0.3, 2)
        return pos.astype(np.float32)

    for e in range(n_episodes):
        ob = []
        for o in obst:
            xy = place_clear(ob, 1.0); ob.append(xy)
            P.resetBasePositionAndOrientation(o, [float(xy[0]), float(xy[1]), BOX_HALF], [0, 0, 0, 1])
        ob = np.array(ob, np.float32)
        pos = place_clear(list(ob), 1.1)
        vel = np.zeros(2, np.float32)

        def haz(pp):
            d_ob = min(float(np.hypot(*(pp - o)) - (AGENT_R + BOX_HALF)) for o in ob)
            return int(min(d_ob, BOUND - float(np.max(np.abs(pp)))) < MARGIN)

        def put_render(pp):
            P.resetBasePositionAndOrientation(agent, [float(pp[0]), float(pp[1]), AGENT_R], [0, 0, 0, 1])
            return _render(P, size, view, proj)

        frames[e, 0] = put_render(pos); hazards[e, 0] = haz(pos)
        for t in range(steps):
            vel = vel * VEL_DECAY + ACTIONS[actions[e, t]] * VEL_GAIN
            pos = pos + vel
            for d in (0, 1):
                if abs(pos[d]) > BOUND:
                    pos[d] = np.clip(pos[d], -BOUND, BOUND); vel[d] = -0.6 * vel[d]
            frames[e, t + 1] = put_render(pos); hazards[e, t + 1] = haz(pos)
    P.disconnect()
    return frames, actions, hazards


def _selftest():
    import time
    from pathlib import Path
    t0 = time.time()
    f, a, h = collect(n_episodes=8, steps=16, size=48, seed=1)
    print(f"frames {f.shape} actions {a.shape} hazards {h.shape} ({round(time.time()-t0,1)}s)")
    print(f"frame range [{f.min():.3f},{f.max():.3f}] mean {f.mean():.4f}")
    print(f"hazard rate {h.mean():.3f}  episodes with any hazard {int(h.any(1).sum())}/{len(h)}")
    print(f"mean |frame_t+1 - frame_t| = {np.abs(np.diff(f,axis=1)).mean():.4f}  (motion visible if >> 0.001)")
    thumb = f[0, 8][::4, ::4]
    print("sample frame (12x12, '#'=bright agent, ':'=obstacle):")
    for row in thumb:
        print("  " + "".join("#" if v > 0.6 else (":" if v > 0.3 else " ") for v in row))
    out = Path(r"C:\Users\marcu\AppData\Local\Temp\claude\C--Users-marcu-Videos-cursor-os-base\856620c1-b73d-4c7d-aa40-dcc0f33acbbc\scratchpad\vwm_sample.npy")
    np.save(out, f[0]); print("saved ->", out)


if __name__ == "__main__":
    _selftest()
