"""FerrumOS runtime actions on real Robotarium robots (Georgia Tech). Upload this file as is.

Robot 0 plays the FerrumOS robot and robot 1 a parked obstacle. Each episode runs 12
runtime steps; each step draws a runtime PhysicalAction (move, inspect, diagnose, approve,
repair, verify, stop with 3 features in [-1, 1]) from the same generator as the FerrumOS
runtime-scene proxy (scripts/vision_runtime_domain_render.py). A Move drives robot 0 to
position + 0.32 * (dx, dy) runtime metres; Stop and the five task kinds hold still.

Scale: 1 runtime metre = SCALE arena metres, so the runtime geofence |x|, |y| <= 1 is a
1.4 m square projected on the floor and the runtime's 16 cm robot is 11.2 cm, about a
GRITSbot. Hazards are labelled offline from the logged poses (scripts/robotarium/
label_robotarium_log.py), never in this file.

Robotarium rules this script respects: no two robots within 0.135 m (offset centres) and
no robot outside the arena. A local safety layer keeps robot 0's centre >= D_MIN from the
obstacle and its targets inside a safe box, so the experiment never approaches the
testbed's collision check; real contact is therefore never recorded.

Outputs (saved in the working directory, returned through the Robotarium web interface):
  ferrum_steps.npy  one row per runtime step, columns STEP_COLUMNS
  ferrum_traj.npy   one row per control iteration, columns TRAJ_COLUMNS
  ferrum_meta.txt   JSON with the seed, scale, timing and column names
Edit SEED for each submission. Needs only numpy and the rps package.
"""
import json

import numpy as np
import rps.robotarium as robotarium
from rps.utilities.barrier_certificates import create_uni_barrier_certificate_with_boundary
from rps.utilities.controllers import create_si_position_controller
from rps.utilities.transformations import create_si_to_uni_dynamics, create_si_to_uni_mapping

SEED = 101
N_EPISODES = 8                         # ~490 s incl. resets; the testbed allows 600 s
STEPS = 12
SCALE = 0.7
STEP_GAIN = 0.32                       # runtime metres per unit of dx, dy
FENCE = 1.0 * SCALE                    # projected geofence half-width (arena metres)
SAFE_X, SAFE_Y = 1.40, 0.82            # targets are clamped inside this box
D_MIN = 0.20                           # robot 0 centre never closer than this to the obstacle
OBS_MARK_R = 0.09                      # projected dark disc under the parked obstacle (visual identity)
DRIVE_S, HOLD_S = 3.0, 0.7             # per step: drive (at most), then hold still
RESET_TIMEOUT_S = 25.0
RESET_HOLD_S = 1.0                     # still, after the obstacle disc moves, before frame 0
KIND_NAMES = ("move", "inspect", "diagnose", "approve", "repair", "verify", "stop")
MOVE, STOP = 0, 6
KIND_P = np.array([0.60, 0.06, 0.06, 0.06, 0.06, 0.06, 0.10])
P_GOAL = 0.5
STEP_COLUMNS = ["episode", "step", "kind", "f0", "f1", "f2", "target_x", "target_y", "it_start", "it_end",
                "r0x_start", "r0y_start", "r0th_start", "r0x_end", "r0y_end", "r0th_end", "obs_x", "obs_y",
                "min_centre_dist"]
TRAJ_COLUMNS = ["it", "r0x", "r0y", "r0th", "r1x", "r1y", "r1th", "episode", "step"]


def action_features(rng, kind):
    """Same draws as train_physical_world_model.action_features."""
    if kind == MOVE:
        return np.array([rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0.1, 1)], np.float32)
    if kind in (1, 2, 4, 5):
        return np.array([rng.uniform(0.2, 1), 0, 0], np.float32)
    return np.zeros(3, np.float32)


def draw_action(rng, pos_rt, goal_rt):
    """Same policy as vision_runtime_domain_render._draw_action, in runtime units."""
    kind = int(rng.choice(len(KIND_NAMES), p=KIND_P))
    if kind == MOVE and rng.random() < P_GOAL:
        d = np.asarray(goal_rt) - np.asarray(pos_rt)
        n = float(np.hypot(*d))
        step = d / max(n, 1e-6) * min(1.0, n / STEP_GAIN) * rng.uniform(0.6, 1.0)
        step = np.clip(step + rng.normal(0, 0.15, 2), -1, 1)
        return kind, np.array([step[0], step[1], rng.uniform(0.1, 1.0)], np.float32)
    return kind, action_features(rng, kind)


def safe_velocity(v, pos, obs):
    """Remove any velocity component that would bring robot 0 inside D_MIN of the obstacle
    or outside the safe box. v, pos, obs are 2-vectors (single-integrator, arena metres)."""
    d = pos - obs
    dist = float(np.hypot(*d))
    if dist < D_MIN + 0.03:
        u = d / max(dist, 1e-6)
        toward = -float(v @ u)
        if toward > 0:
            v = v + toward * u
        if dist < D_MIN:
            v = v + 0.05 * u
    for k, lim in ((0, SAFE_X + 0.05), (1, SAFE_Y + 0.05)):
        if pos[k] > lim and v[k] > 0 or pos[k] < -lim and v[k] < 0:
            v[k] = 0.0
    return v


def limit_wheels(dxu, r):
    """Scale each robot's (v, w) so neither wheel exceeds 90% of the motor limit (keeps the
    testbed's actuator-limit warning at zero, so real motion matches the simulator)."""
    rad = getattr(r, "WHEEL_RADIUS", 0.016)
    base = getattr(r, "BASE_LENGTH", 0.11)
    wmax = 0.9 * getattr(r, "MAX_WHEEL_VELOCITY", 0.2 / 0.016)
    left = (dxu[0] - dxu[1] * base / 2) / rad
    right = (dxu[0] + dxu[1] * base / 2) / rad
    over = np.maximum(np.maximum(np.abs(left), np.abs(right)) / wmax, 1.0)
    return dxu / over


def main():
    rng = np.random.default_rng(SEED)
    starts = []
    for _ in range(N_EPISODES):
        robot = rng.uniform(-0.8, 0.8, 2)
        obstacle = rng.uniform(-0.9, 0.9, 2)
        while np.hypot(*(robot - obstacle)) < 0.45:
            obstacle = rng.uniform(-0.9, 0.9, 2)
        goal = (obstacle + rng.uniform(-0.3, 0.3, 2)) if rng.random() < 0.5 else rng.uniform(-1.15, 1.15, 2)
        starts.append((robot * SCALE, obstacle * SCALE, goal))

    init = np.array([[starts[0][0][0], starts[0][1][0]], [starts[0][0][1], starts[0][1][1]], [0.0, 0.0]])
    r = robotarium.Robotarium(number_of_robots=2, show_figure=True, initial_conditions=init, sim_in_real_time=True)
    dt = r.TIME_STEP
    obs_marker = None
    if r.show_figure:   # the figure is projected onto the bright floor, so black = darker (white was invisible)
        from matplotlib.patches import Circle
        ax = r._axes_handle
        ax.plot([-FENCE, FENCE, FENCE, -FENCE, -FENCE], [-FENCE, -FENCE, FENCE, FENCE, -FENCE], "-",
                color="black", linewidth=10, zorder=0)
        obs_marker = Circle((10.0, 10.0), OBS_MARK_R, color="black", zorder=0)   # moved under robot 1 per episode
        ax.add_patch(obs_marker)

    si_ctrl = create_si_position_controller(x_velocity_gain=1.0, y_velocity_gain=1.0, velocity_magnitude_limit=0.15)
    si_to_uni = create_si_to_uni_dynamics(linear_velocity_gain=1.0)
    _, uni_to_si = create_si_to_uni_mapping()
    reset_barrier = create_uni_barrier_certificate_with_boundary()
    steps, traj = [], []
    it = 0

    def tick(dxu, episode, step):
        nonlocal it
        r.set_velocities(np.arange(2), limit_wheels(dxu, r))
        r.step()
        it += 1
        x = r.get_poses()
        traj.append([it, *x[:, 0], *x[:, 1], episode, step])
        return x

    x = r.get_poses()
    for e, (robot0, obstacle, goal_rt) in enumerate(starts):
        # reset: both robots drive to the episode's start (barrier-protected, not labelled)
        target = np.column_stack([robot0, obstacle])
        for _ in range(int(RESET_TIMEOUT_S / dt)):
            xi = uni_to_si(x)
            if np.all(np.hypot(*(xi - target)) < 0.03):
                break
            dxu = reset_barrier(si_to_uni(si_ctrl(xi, target), x), x)
            x = tick(dxu, e, -1)
        x = tick(np.zeros((2, 2)), e, -1)
        obs = x[:2, 1].copy()
        if obs_marker is not None:
            obs_marker.center = (float(obs[0]), float(obs[1]))
        for _ in range(int(RESET_HOLD_S / dt)):       # let the projector redraw the disc before step 0
            x = tick(np.zeros((2, 2)), e, -1)
        for s in range(STEPS):
            pos = x[:2, 0].copy()
            kind, f = draw_action(rng, pos / SCALE, goal_rt)
            tgt = pos.copy()
            if kind == MOVE and f[2] > 0.1:
                tgt = pos + SCALE * STEP_GAIN * f[:2]
                tgt = np.clip(tgt, [-SAFE_X, -SAFE_Y], [SAFE_X, SAFE_Y])
            it_start, start_pose, min_d = it, x[:, 0].copy(), float(np.hypot(*(pos - obs)))
            for k in range(int((DRIVE_S + HOLD_S) / dt)):
                cur = x[:2, 0]
                v = np.zeros(2)
                if k < int(DRIVE_S / dt) and np.hypot(*(tgt - cur)) > 0.02:
                    v = si_ctrl(cur.reshape(2, 1), tgt.reshape(2, 1))[:, 0]
                v = safe_velocity(v, cur, obs)
                dxi = np.column_stack([v, np.zeros(2)])
                dxu = si_to_uni(dxi, x) if np.any(v) else np.zeros((2, 2))
                dxu[:, 1] = 0.0
                x = tick(dxu, e, s)
                min_d = min(min_d, float(np.hypot(*(x[:2, 0] - x[:2, 1]))))
            steps.append([e, s, kind, *f, *tgt, it_start, it, *start_pose, *x[:, 0], *obs, min_d])

    np.save("ferrum_steps.npy", np.asarray(steps, np.float64))
    np.save("ferrum_traj.npy", np.asarray(traj, np.float64))
    with open("ferrum_meta.txt", "w") as fh:
        json.dump({"seed": SEED, "episodes": N_EPISODES, "steps": STEPS, "scale": SCALE, "fence_half_width_m": FENCE,
                   "reset_hold_s": RESET_HOLD_S,
                   "d_min_m": D_MIN, "drive_s": DRIVE_S, "hold_s": HOLD_S, "time_step_s": dt,
                   "kind_names": KIND_NAMES, "step_columns": STEP_COLUMNS, "traj_columns": TRAJ_COLUMNS}, fh)
    print(f"ferrum: {len(steps)} steps in {N_EPISODES} episodes, {it} iterations (~{it * dt:.0f} s)")
    r.debug()


main()
