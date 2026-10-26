#!/usr/bin/env python3
"""Runtime-scene proxy footage for the vision caution advisory. Branch work, not main.

FerrumOS has no real robot, camera or hardware-in-the-loop rig, so footage of "the
deployment domain" cannot be recorded. The closest domain that exists is the runtime's
own registered PyBullet world (topology pybullet-direct-box-robot-obstacle-v1, used by
scripts/run_physical_jepa_pybullet_integration.py). This script films that world from
a fixed overhead camera. It is still simulation, and every result built on it is a
runtime-scene PROXY, not real footage.

Physics and commands: the UNMODIFIED tools.physical_sim_bridge.bridge.PyBulletBackend
(box robot + static box obstacle, half-extent 0.08 m, DIRECT, 1/240 s; move_to drives
the robot for 240 substeps = one runtime step; stop zeroes its velocity). A Move with
features (dx, dy, speed) is issued exactly as the integration does: target = current
position + 0.32 * (dx, dy) m. The other five kinds (inspect, diagnose, approve, repair,
verify) have no base motion in the runtime, so the robot stays put for that step.

Rendering: a SEPARATE DIRECT client mirrors the robot and obstacle poses read back from
the backend after every step, so the backend's world is never touched. The mirror adds
a floor shaded lighter inside the geofence (|x|, |y| <= 1 m) than outside it, which
makes the fence visible to the camera.

Actions: real runtime PhysicalAction encodings, the 7 kinds of
train_physical_world_model.ACTION_NAMES with 3 features in [-1, 1]
(Move: [dx, dy, speed]; inspect/diagnose/repair/verify: [intensity, 0, 0];
approve/stop: zeros). Half of the Move steps head for a per-episode goal (often near the
obstacle, sometimes past the fence); the rest use the runtime's own action_features draw.

Labels (evaluation only, never model input): the camera-visible terms of
train_physical_world_model.is_dangerous evaluated on the PyBullet world after each step:
  moving and clearance_next < 0.16   (clearance = centre distance - 0.16, as state_for_case)
  or geofence margin_next < 0        (margin = 1 - max(|x|, |y|))
  or a robot-obstacle contact first detected during the step (backend.collision_detected).
Humans, battery, link, e-stop and approval hazards are invisible to a camera and out of
scope.

collect(n_episodes, seed, steps=12, size=64) -> dict of arrays:
    frames (N, steps+1, size, size) float32 in [0,1], kinds (N, steps) int64,
    features (N, steps, 3) float32, hazards (N, steps+1) int8, clearance and margin
    (N, steps+1), contact (N, steps+1) int8, robot_xy (N, steps+1, 2), obstacle_xy (N, 2)
Self-test: python scripts/vision_runtime_domain_render.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import train_physical_world_model as simulator  # noqa: E402
from tools.physical_sim_bridge.bridge import PyBulletBackend  # noqa: E402
from tools.physical_sim_bridge.protocol import BridgeCommand  # noqa: E402

STEPS, SIZE = 12, 64
FENCE, HALF, STEP_GAIN = 1.0, 0.08, 0.32
CLEARANCE_HAZARD = 0.16
# runtime kind mix: motion-heavy, every kind present
KIND_P = np.array([0.60, 0.06, 0.06, 0.06, 0.06, 0.06, 0.10])
P_GOAL = 0.5
EYE, FOV = [0.0, 0.0, 2.6], 60.0
GREY = {"outside": 0.14, "inside": 0.34, "obstacle": 0.60, "robot": 0.95}
# "arena" look: the Georgia Tech Robotarium as it appears in rectified real frames (medians
# measured on spent runs 201/202/401/402/501): one bright floor inside and outside the fence,
# a darker projected fence line, a darker projected disc under the parked obstacle, and two
# identical near-black robots. Rendered flat (ambient light only) so pixels equal these values.
ARENA = {"floor": 0.65, "fence": 0.47, "disc": 0.53, "robot": 0.03, "fence_w": 0.03, "disc_r": 0.129}
TOPOLOGY = "pybullet-direct-box-robot-obstacle-v1"


def clearance(robot_xy, obstacle_xy):
    """Runtime definition (run_physical_jepa_pybullet_integration.state_for_case)."""
    return float(np.clip(math.hypot(robot_xy[0] - obstacle_xy[0], robot_xy[1] - obstacle_xy[1]) - 0.16, 0.0, 1.0))


def margin(robot_xy):
    return float(1.0 - max(abs(robot_xy[0]), abs(robot_xy[1])))


def runtime_action_vector(kind, features):
    """The runtime model's own action encoding: 7-way one-hot + the 3 raw features."""
    v = np.zeros(simulator.ACTION_COUNT + simulator.ACTION_FEATURE_SIZE, np.float32)
    v[int(kind)] = 1.0
    v[simulator.ACTION_COUNT:] = features
    return v


def lossy_sim_action(kind, features):
    """The rejected alternative: project a runtime action onto the v1 head's 5 sim impulses
    (stay, -x, +x, -y, +y). Moves keep only their dominant axis; every other kind is 'stay'."""
    if int(kind) != simulator.MOVE or features[2] <= 0.1:
        return 0
    dx, dy = float(features[0]), float(features[1])
    if abs(dx) >= abs(dy):
        return 2 if dx > 0 else 1
    return 4 if dy > 0 else 3


class _Mirror:
    """Render-only DIRECT client that copies poses from the physics backend."""

    def __init__(self, size, look="proxy"):
        import pybullet as p
        self.p, self.size, self.look = p, size, look
        self.cid = p.connect(p.DIRECT)
        self.disc = None
        box = lambda half, g: p.createVisualShape(p.GEOM_BOX, halfExtents=half, rgbaColor=[g, g, g, 1],
                                                 physicsClientId=self.cid)
        body = lambda shape, xyz: p.createMultiBody(0, -1, shape, xyz, physicsClientId=self.cid)
        if look == "arena":
            a, w = ARENA, ARENA["fence_w"] / 2
            body(box([3.0, 3.0, 0.01], a["floor"]), [0, 0, -0.012])
            for xy, half in (([0, FENCE], [FENCE + w, w, 0.002]), ([0, -FENCE], [FENCE + w, w, 0.002]),
                             ([FENCE, 0], [w, FENCE + w, 0.002]), ([-FENCE, 0], [w, FENCE + w, 0.002])):
                body(box(half, a["fence"]), [xy[0], xy[1], 0.0])
            disc = p.createVisualShape(p.GEOM_CYLINDER, radius=a["disc_r"], length=0.002,
                                       rgbaColor=[a["disc"]] * 3 + [1], physicsClientId=self.cid)
            self.disc = body(disc, [10, 10, 0.003])
            robot_g = obstacle_g = a["robot"]
        elif look == "proxy":
            body(box([3.0, 3.0, 0.01], GREY["outside"]), [0, 0, -0.012])
            body(box([FENCE, FENCE, 0.01], GREY["inside"]), [0, 0, -0.01])
            robot_g, obstacle_g = GREY["robot"], GREY["obstacle"]
        else:
            raise ValueError(f"unknown look {look!r}")
        self.robot = body(box([HALF] * 3, robot_g), [0, 0, HALF])
        self.obstacle = body(box([HALF] * 3, obstacle_g), [0, 0, HALF])
        self.view = p.computeViewMatrix(EYE, [0, 0, 0], [0, 1, 0], physicsClientId=self.cid)
        self.proj = p.computeProjectionMatrixFOV(FOV, 1.0, 0.1, 6.0, physicsClientId=self.cid)

    def render(self, backend):
        p, b = self.p, backend
        for src, dst in ((b._robot, self.robot), (b._obstacle, self.obstacle)):
            pos, orn = b._p.getBasePositionAndOrientation(src, physicsClientId=b._client)
            p.resetBasePositionAndOrientation(dst, pos, orn, physicsClientId=self.cid)
            if dst == self.obstacle and self.disc is not None:
                p.resetBasePositionAndOrientation(self.disc, [pos[0], pos[1], 0.003], [0, 0, 0, 1],
                                                  physicsClientId=self.cid)
        light = ({"lightAmbientCoeff": 1.0, "lightDiffuseCoeff": 0.0, "lightSpecularCoeff": 0.0}
                 if self.look == "arena" else {})
        img = p.getCameraImage(self.size, self.size, self.view, self.proj, lightDirection=[0.3, 0.2, 1.0],
                               renderer=p.ER_TINY_RENDERER, physicsClientId=self.cid, **light)[2]
        rgba = np.asarray(img, np.uint8).reshape(self.size, self.size, 4)
        return (rgba[:, :, :3].mean(2) / 255.0).astype(np.float32)

    def close(self):
        self.p.disconnect(self.cid)


def _command(backend, kind, target, seq):
    return BridgeCommand(run_id=backend.run_id, command_id=seq, idempotency_key=seq, adapter_id=1, endpoint_id=1,
                         session_epoch=1, kind=kind,
                         arguments=(int(round(target[0] * 1000)), int(round(target[1] * 1000)), 0),
                         issued_at_tick=seq, deadline_tick=seq + 1, expected_policy_revision=1,
                         expected_twin_event_id=seq, confirmation_kind="not_required", confirmation_id=0,
                         authority="ferrum_routed_command_v1")   # simulator-only, as the integration issues it


def _robot_xy(backend):
    pos, _ = backend._p.getBasePositionAndOrientation(backend._robot, physicsClientId=backend._client)
    return float(pos[0]), float(pos[1])


def _draw_action(rng, pos, goal):
    kind = int(rng.choice(simulator.ACTION_COUNT, p=KIND_P))
    if kind == simulator.MOVE and rng.random() < P_GOAL:
        d = np.asarray(goal) - np.asarray(pos)
        n = float(np.hypot(*d))
        step = d / max(n, 1e-6) * min(1.0, n / STEP_GAIN) * rng.uniform(0.6, 1.0)
        step = np.clip(step + rng.normal(0, 0.15, 2), -1, 1)
        return kind, np.array([step[0], step[1], rng.uniform(0.1, 1.0)], np.float32)
    return kind, simulator.action_features(rng, kind)


def collect(n_episodes, seed, steps=STEPS, size=SIZE, look="proxy"):
    rng = np.random.default_rng(seed)
    backend = PyBulletBackend(run_id=7000 + int(seed) % 1000, source_clock_id=71)
    mirror = _Mirror(size, look)
    frames = np.zeros((n_episodes, steps + 1, size, size), np.float32)
    kinds = np.zeros((n_episodes, steps), np.int64)
    feats = np.zeros((n_episodes, steps, 3), np.float32)
    hazards = np.zeros((n_episodes, steps + 1), np.int8)
    clr = np.zeros((n_episodes, steps + 1), np.float32)
    mar = np.zeros((n_episodes, steps + 1), np.float32)
    rxy = np.zeros((n_episodes, steps + 1, 2), np.float32)
    con = np.zeros((n_episodes, steps + 1), np.int8)
    oxy = np.zeros((n_episodes, 2), np.float32)
    seq = 0
    try:
        for e in range(n_episodes):
            robot = rng.uniform(-0.8, 0.8, 2)
            obstacle = rng.uniform(-0.9, 0.9, 2)
            while math.hypot(*(robot - obstacle)) < 0.45:
                obstacle = rng.uniform(-0.9, 0.9, 2)
            goal = (obstacle + rng.uniform(-0.3, 0.3, 2)) if rng.random() < 0.5 else rng.uniform(-1.15, 1.15, 2)
            backend.reset_scene(tuple(robot.tolist()), tuple(obstacle.tolist()))
            oxy[e] = obstacle
            backend.poll_observation()
            pos = _robot_xy(backend)
            frames[e, 0] = mirror.render(backend)
            clr[e, 0], mar[e, 0], rxy[e, 0] = clearance(pos, obstacle), margin(pos), pos
            for t in range(steps):
                kind, f = _draw_action(rng, pos, goal)
                kinds[e, t], feats[e, t] = kind, f
                collided_before = backend.collision_detected
                if kind == simulator.MOVE:
                    seq += 1
                    target = (pos[0] + STEP_GAIN * float(f[0]), pos[1] + STEP_GAIN * float(f[1]))
                    backend.submit_command(_command(backend, "move_to", target, seq))
                elif kind == simulator.STOP:
                    seq += 1
                    backend.submit_command(_command(backend, "stop", pos, seq))
                while backend.poll_observation() is not None:
                    pass
                pos = _robot_xy(backend)
                frames[e, t + 1] = mirror.render(backend)
                clr[e, t + 1], mar[e, t + 1], rxy[e, t + 1] = clearance(pos, obstacle), margin(pos), pos
                moving = kind == simulator.MOVE and f[2] > 0.1
                contact = backend.collision_detected and not collided_before
                con[e, t + 1] = int(contact)
                hazards[e, t + 1] = int((moving and clr[e, t + 1] < CLEARANCE_HAZARD) or mar[e, t + 1] < 0 or contact)
    finally:
        mirror.close()
        backend._p.disconnect(backend._client)
    return {"frames": frames, "kinds": kinds, "features": feats, "hazards": hazards, "clearance": clr,
            "margin": mar, "contact": con, "robot_xy": rxy, "obstacle_xy": oxy}


def _selftest():
    import time
    t0 = time.time()
    d = collect(40, seed=5)
    f, k, h, c, m = d["frames"], d["kinds"], d["hazards"], d["clearance"], d["margin"]
    print(f"frames {f.shape} ({round(time.time() - t0, 1)}s)  range [{f.min():.3f},{f.max():.3f}]")
    print(f"kind mix {np.bincount(k.ravel(), minlength=7) / k.size}")
    print(f"per-step hazard rate {h[:, 1:].mean():.3f}; episodes with any hazard {int(h.any(1).sum())}/{len(h)}")
    y = np.array([h[e, t + 1:t + 4].any() for e in range(len(h)) for t in range(1, STEPS)])
    print(f"caution-label prevalence (H=3) {y.mean():.3f}")
    print(f"min clearance {c.min():.3f}, min margin {m.min():.3f}; motion |dframe| {np.abs(np.diff(f, axis=1)).mean():.4f}")
    thumb = f[0, 6][::4, ::4]
    for row in thumb:
        print("  " + "".join("#" if v > 0.8 else ("o" if v > 0.5 else ("." if v > 0.25 else " ")) for v in row))


if __name__ == "__main__":
    _selftest()
