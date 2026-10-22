#!/usr/bin/env python3
"""Real-camera footage for the vision caution advisory: an Android phone over a tabletop.

No printer needed. A taped square (the runtime geofence |x|, |y| <= 1) with four bright
corner objects, a small coloured object as the robot and another as the obstacle. The
phone streams through the free IP Webcam app (http://<phone-ip>:8080); the laptop shows
the next FerrumOS runtime action as a ring on the live view, the operator moves the robot
by hand (stop-motion), and a frame is saved once the scene is still and nothing else (a
hand) is in view. One saved frame = one runtime step, as in the runtime-scene proxy.

Actions come from the proxy's own generator (vision_runtime_domain_render._draw_action:
runtime PhysicalAction kinds + features, half of the Moves heading for an episode goal).
Positions come from colour tracking on a top-down rectified view (homography from the
four clicked corners), in runtime units. Labels use the proxy's rules (moving and
clearance_next < 0.16, geofence margin_next < 0, first contact). The model input is the
rectified view, grey, 64x64, covering |x|, |y| <= 1.5 like the proxy camera.

Subcommands
  calibrate --source URL --session NAME   click 4 fence corners, capture the empty scene,
                                          click the robot and the obstacle to learn colours
  record --session NAME --seed S --episodes N   guided stop-motion recording
  build --session NAME                    write dataset.npz with the proxy's keys
  selftest                                end-to-end run on a synthetic phone + operator

Footage stays in target/real-rig/<session>/ (gitignored). Labels and inputs share one
camera; the caution target looks 1-3 steps ahead, which the model never sees.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import train_physical_world_model as simulator  # noqa: E402
import vision_runtime_domain_render as R  # noqa: E402

RIG = ROOT / "target/real-rig"
EXTENT, CANVAS, MODEL_SIZE = 1.5, 450, R.SIZE      # rectified view covers |x|,|y| <= 1.5 runtime units
PX = CANVAS / (2 * EXTENT)                          # canvas pixels per runtime unit
CORNERS_RT = np.float32([[-1, -1], [1, -1], [1, 1], [-1, 1]])
CORNER_NAMES = ("near-left", "near-right", "far-right", "far-left")
TOL, STILL_S, STILL_DIFF, FOREIGN_FRAC, COLOUR_DIST = 0.08, 0.8, 2.0, 0.004, 28.0


# --- geometry ----------------------------------------------------------------------------
def rt_to_canvas(xy):
    xy = np.asarray(xy, np.float64)
    return np.stack([(xy[..., 0] + EXTENT) * PX, (EXTENT - xy[..., 1]) * PX], -1)


def canvas_to_rt(uv):
    uv = np.asarray(uv, np.float64)
    return np.stack([uv[..., 0] / PX - EXTENT, EXTENT - uv[..., 1] / PX], -1)


def warp_matrix(corner_px):
    """Image pixels -> rectified canvas pixels, from the 4 clicked fence corners."""
    return cv2.getPerspectiveTransform(np.float32(corner_px), np.float32(rt_to_canvas(CORNERS_RT)))


def rectify(frame, W):
    return cv2.warpPerspective(frame, W, (CANVAS, CANVAS))


def model_frame(canvas_bgr):
    grey = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.resize(grey, (MODEL_SIZE, MODEL_SIZE), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


# --- tracking ----------------------------------------------------------------------------
def lab_of(bgr):
    return cv2.cvtColor(np.uint8(bgr).reshape(1, 1, 3), cv2.COLOR_BGR2LAB).reshape(3).astype(np.float32)


def sample_colour(canvas, uv, r=4):
    u, v = int(round(uv[0])), int(round(uv[1]))
    patch = canvas[max(v - r, 0):v + r + 1, max(u - r, 0):u + r + 1].reshape(-1, 3)
    return np.median(patch, 0).tolist()


def colour_mask(canvas, ref_bgr):
    lab = cv2.cvtColor(canvas, cv2.COLOR_BGR2LAB).astype(np.float32)
    d = np.linalg.norm(lab - lab_of(ref_bgr), axis=2)
    mask = (d < COLOUR_DIST).astype(np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def detect(canvas, ref_bgr, min_px=30):
    """Largest blob of the reference colour -> (runtime xy, mask) or (None, mask)."""
    mask = colour_mask(canvas, ref_bgr)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        return None, mask
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[k, cv2.CC_STAT_AREA] < min_px:
        return None, mask
    return canvas_to_rt(cent[k]), (lab == k).astype(np.uint8)


def touching(mask_a, mask_b):
    return bool((cv2.dilate(mask_a, np.ones((5, 5), np.uint8)) & mask_b).any())


def foreign_fraction(canvas, background, masks):
    diff = cv2.absdiff(cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY), cv2.cvtColor(background, cv2.COLOR_BGR2GRAY))
    keep = np.ones(diff.shape, np.uint8)
    for m in masks:
        keep &= 1 - cv2.dilate(m, np.ones((15, 15), np.uint8))
    return float(((diff > 35) & (keep > 0)).mean())


# --- sources -----------------------------------------------------------------------------
class PhoneSource:
    """IP Webcam: base URL http://<ip>:8080 (single JPEG per read from /shot.jpg).
    Anything else (a webcam index, an MJPEG URL) goes through cv2.VideoCapture."""

    def __init__(self, spec):
        self.url = None
        if spec.startswith("http") and "/video" not in spec:
            self.url = spec.rstrip("/") + ("" if spec.endswith(".jpg") else "/shot.jpg")
        else:
            self.cap = cv2.VideoCapture(int(spec) if spec.isdigit() else spec)

    def read(self):
        if self.url:
            with urllib.request.urlopen(self.url, timeout=3) as resp:
                buf = np.frombuffer(resp.read(), np.uint8)
            frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        else:
            ok, frame = self.cap.read()
            frame = frame if ok else None
        if frame is None:
            raise RuntimeError("no frame from the phone")
        return frame


class SyntheticSource:
    """Perspective view of a fake tabletop with an automatic operator, for the self-test."""

    ROBOT, OBST, CORNER, HAND = (40, 40, 220), (200, 120, 30), (0, 220, 255), (120, 160, 220)

    def __init__(self, seed=0):
        self.rng = np.random.default_rng(seed)
        self.size = (640, 480)
        dst = np.float32([[150, 420], [500, 430], [440, 120], [190, 110]])        # oblique fence image
        self.H = cv2.getPerspectiveTransform(np.float32(rt_to_canvas(CORNERS_RT)), dst)   # canvas -> image
        self.corner_px = dst
        self.robot, self.obst = np.array([5.0, 5.0]), np.array([-5.0, -5.0])     # off the table
        self.goal_robot = self.goal_obst = None
        self.hand_frames = 0
        self.t = 0

    def instruct(self, robot_target=None, obstacle_target=None):
        """The operator reads the instruction: moves objects (with hand in view for a while)."""
        if robot_target is not None:
            self.goal_robot = np.asarray(robot_target) + self.rng.normal(0, 0.02, 2)
        if obstacle_target is not None:
            self.goal_obst = np.asarray(obstacle_target) + self.rng.normal(0, 0.02, 2)
        self.hand_frames = int(self.rng.integers(2, 5))

    def read(self):
        self.t += 1
        if self.hand_frames > 0:
            self.hand_frames -= 1
            if self.hand_frames == 0:
                if self.goal_robot is not None:
                    self.robot, self.goal_robot = self.goal_robot, None
                if self.goal_obst is not None:
                    self.obst, self.goal_obst = self.goal_obst, None
        canvas = np.full((CANVAS, CANVAS, 3), (90, 100, 110), np.uint8)
        a, b = rt_to_canvas([-1, 1]).astype(int), rt_to_canvas([1, -1]).astype(int)
        cv2.rectangle(canvas, tuple(a), tuple(b), (235, 235, 235), 3)
        for c in CORNERS_RT:
            cv2.circle(canvas, tuple(rt_to_canvas(c).astype(int)), 9, self.CORNER, -1)
        half = int(0.08 * PX)
        for pos, col in ((self.obst, self.OBST), (self.robot, self.ROBOT)):
            u, v = rt_to_canvas(pos).astype(int)
            cv2.rectangle(canvas, (u - half, v - half), (u + half, v + half), col, -1)
        if self.hand_frames > 0:
            target = self.goal_robot if self.goal_robot is not None else self.robot
            u, v = rt_to_canvas(target).astype(int)
            cv2.ellipse(canvas, (u, v + 60), (35, 70), 0, 0, 360, self.HAND, -1)
        img = cv2.warpPerspective(canvas, self.H, self.size, borderValue=(60, 60, 60))
        noise = self.rng.normal(0, 3, img.shape)
        return np.clip(img + noise, 0, 255).astype(np.uint8)


# --- session ------------------------------------------------------------------------------
def session_dir(name):
    d = RIG / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def click_points(window, frame, prompts):
    pts = []
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, lambda ev, x, y, *_: pts.append((x, y)) if ev == cv2.EVENT_LBUTTONDOWN else None)
    while len(pts) < len(prompts):
        view = frame.copy()
        for p in pts:
            cv2.circle(view, p, 6, (0, 255, 0), 2)
        cv2.putText(view, prompts[len(pts)], (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.imshow(window, view)
        if cv2.waitKey(30) == 27:
            raise SystemExit("calibration cancelled")
    return pts


def wait_key(window, frame, text):
    while True:
        view = frame() if callable(frame) else frame
        view = view.copy()
        cv2.putText(view, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.imshow(window, view)
        if cv2.waitKey(50) == 32:
            return


def calibrate(source, name, fence_cm, headless=False):
    d = session_dir(name)
    frame = source.read()
    if headless:
        corners = source.corner_px.tolist()
    else:
        corners = click_points("calibrate", frame, [f"click fence corner {i + 1}/4: {n}" for i, n in enumerate(CORNER_NAMES)])
    W = warp_matrix(corners)
    if not headless:
        wait_key("calibrate", source.read, "remove robot + obstacle from view, then SPACE")
    background = rectify(source.read(), W)
    colours = {}
    for obj in ("robot", "obstacle"):
        if headless:
            pos = np.array([0.4, 0.0]) if obj == "robot" else np.array([-0.4, 0.0])
            source.instruct(**({"robot_target": pos} if obj == "robot" else {"obstacle_target": pos}))
            for _ in range(8):
                source.read()
            canvas = rectify(source.read(), W)
            uv = rt_to_canvas(source.robot if obj == "robot" else source.obst)
        else:
            wait_key("calibrate", source.read, f"place the {obj} inside the fence, then SPACE")
            canvas = rectify(source.read(), W)
            uv = click_points("calibrate", canvas, [f"click the {obj} (top-down view)"])[0]
        colours[obj] = sample_colour(canvas, uv)
    cv2.imwrite(str(d / "background.png"), background)
    meta = {"corners_px": [list(map(float, c)) for c in corners], "corner_order": CORNER_NAMES,
            "fence_cm": fence_cm, "cm_per_runtime_unit": fence_cm / 2.0, "colours_bgr": colours,
            "extent": EXTENT, "canvas": CANVAS, "model_size": MODEL_SIZE,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (d / "session.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if not headless:
        cv2.destroyAllWindows()
    print(f"calibrated session {name}: 1 runtime unit = {fence_cm / 2:.1f} cm; robot should be about "
          f"{0.16 * fence_cm / 2:.1f} cm wide")
    return meta


def load_session(name):
    d = RIG / name
    meta = json.loads((d / "session.json").read_text(encoding="utf-8"))
    return d, meta, warp_matrix(meta["corners_px"]), cv2.imread(str(d / "background.png"))


def observe(source, W, background, meta):
    frame = source.read()
    canvas = rectify(frame, W)
    rpos, rmask = detect(canvas, meta["colours_bgr"]["robot"])
    opos, omask = detect(canvas, meta["colours_bgr"]["obstacle"])
    foreign = foreign_fraction(canvas, background, [rmask, omask])
    return frame, canvas, rpos, opos, (rmask, omask), foreign


def capture_when_ready(source, W, background, meta, robot_goal, obstacle_goal, prompt, headless, blocked_ok):
    """Block until the scene is still, clear of hands, and the objects sit at their goals
    (or the operator presses B: 'blocked, cannot reach'). Returns the observation."""
    last, still_since = None, None
    while True:
        frame, canvas, rpos, opos, masks, foreign = observe(source, W, background, meta)
        grey = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY).astype(np.float32)
        moving = last is None or float(np.abs(grey - last).mean()) > STILL_DIFF
        last = grey
        now = time.time() if not headless else source.t * 0.3
        still_since = None if moving else (still_since or now)
        at_goal = (rpos is not None and opos is not None
                   and (robot_goal is None or np.hypot(*(rpos - robot_goal)) < TOL)
                   and (obstacle_goal is None or np.hypot(*(opos - obstacle_goal)) < TOL))
        key = -1
        if not headless:
            view = canvas.copy()
            for g, col in ((robot_goal, (0, 255, 0)), (obstacle_goal, (255, 0, 255))):
                if g is not None:
                    cv2.circle(view, tuple(rt_to_canvas(g).astype(int)), int(TOL * PX), col, 2)
            status = "hand/object in view" if foreign > FOREIGN_FRAC else ("hold still" if moving else "ok")
            cv2.putText(view, prompt, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
            cv2.putText(view, status + ("   [B] blocked  [Q] quit" if blocked_ok else "   [Q] quit"), (8, CANVAS - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.imshow("record", view)
            key = cv2.waitKey(30)
            if key in (ord("q"), 27):
                raise KeyboardInterrupt
        ready = (still_since is not None and now - still_since >= STILL_S and foreign <= FOREIGN_FRAC
                 and rpos is not None and opos is not None)
        if ready and (at_goal or (blocked_ok and key == ord("b"))):
            return frame, canvas, rpos, opos, masks


def record(source, name, seed, episodes, headless=False):
    d, meta, W, background = load_session(name)
    rng = np.random.default_rng(seed)
    out = d / f"seed{seed}"
    out.mkdir(exist_ok=True)
    for e in range(episodes):
        ep_file = out / f"episode{e:03d}.npz"
        robot = rng.uniform(-0.8, 0.8, 2)
        obstacle = rng.uniform(-0.9, 0.9, 2)
        while math.hypot(*(robot - obstacle)) < 0.45:
            obstacle = rng.uniform(-0.9, 0.9, 2)
        goal = (obstacle + rng.uniform(-0.3, 0.3, 2)) if rng.random() < 0.5 else rng.uniform(-1.15, 1.15, 2)
        if ep_file.exists():            # resume: the rng draws below must still happen in order
            for _ in range(R.STEPS):
                R._draw_action(rng, robot, goal)
            continue
        if headless:
            source.instruct(robot_target=robot, obstacle_target=obstacle)
        frame, canvas, rpos, opos, masks = capture_when_ready(
            source, W, background, meta, robot, obstacle, f"episode {e + 1}: place robot (green) + obstacle (pink)",
            headless, blocked_ok=False)
        frames, kinds, feats, rxy, oxy, contact, stamps = [frame], [], [], [rpos], [opos], [0], [time.time()]
        pos = rpos
        for t in range(R.STEPS):
            kind, f = R._draw_action(rng, pos, goal)
            kinds.append(kind)
            feats.append(f)
            target = None
            if kind == simulator.MOVE:
                target = pos + R.STEP_GAIN * f[:2]
                prompt = f"step {t + 1}/{R.STEPS}: MOVE robot to the green ring"
            else:
                prompt = f"step {t + 1}/{R.STEPS}: {simulator.ACTION_NAMES[kind].upper()} - leave everything still"
            if headless:
                source.instruct(robot_target=target if target is not None else pos)
            frame, canvas, rpos, opos, masks = capture_when_ready(
                source, W, background, meta, target if target is not None else pos, None, prompt, headless,
                blocked_ok=target is not None)
            frames.append(frame)
            rxy.append(rpos)
            oxy.append(opos)
            contact.append(int(touching(*masks)))
            stamps.append(time.time())
            pos = rpos
        ok, jpgs = zip(*[cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 92]) for fr in frames])
        np.savez_compressed(ep_file, jpeg=np.array([j.tobytes() for j in jpgs], dtype=object), kinds=np.array(kinds),
                            features=np.array(feats, np.float32), robot_xy=np.array(rxy, np.float32),
                            obstacle_xy=np.array(oxy, np.float32), contact=np.array(contact, np.int8),
                            start_robot=robot, start_obstacle=obstacle, goal=goal, stamps=np.array(stamps))
        print(f"saved {ep_file}", flush=True)
    if not headless:
        cv2.destroyAllWindows()


def build(name):
    """All recorded episodes -> dataset.npz with the keys of vision_runtime_domain_render.collect."""
    d, meta, W, _ = load_session(name)
    eps = sorted(d.glob("seed*/episode*.npz"))
    if not eps:
        raise SystemExit("no episodes recorded")
    out = {k: [] for k in ("frames", "kinds", "features", "hazards", "clearance", "margin", "contact", "robot_xy",
                           "obstacle_xy")}
    for p in eps:
        z = np.load(p, allow_pickle=True)
        frames = [model_frame(rectify(cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_COLOR), W)) for j in z["jpeg"]]
        rxy, oxy, kinds, feats = z["robot_xy"], z["obstacle_xy"], z["kinds"], z["features"]
        obst = oxy.mean(0)                       # the obstacle is parked for the whole episode
        clr = np.array([R.clearance(p_, obst) for p_ in rxy], np.float32)
        mar = np.array([R.margin(p_) for p_ in rxy], np.float32)
        con = z["contact"]
        haz = np.zeros(len(rxy), np.int8)
        for t in range(len(kinds)):
            moving = kinds[t] == simulator.MOVE and feats[t][2] > 0.1
            onset = con[t + 1] and not con[: t + 1].any()
            haz[t + 1] = int((moving and clr[t + 1] < R.CLEARANCE_HAZARD) or mar[t + 1] < 0 or onset)
        for k, v in (("frames", np.stack(frames)), ("kinds", kinds), ("features", feats), ("hazards", haz),
                     ("clearance", clr), ("margin", mar), ("contact", con), ("robot_xy", rxy), ("obstacle_xy", obst)):
            out[k].append(v)
    data = {k: np.stack(v) for k, v in out.items()}
    np.savez_compressed(d / "dataset.npz", **data, episode_files=np.array([str(p.relative_to(d)) for p in eps]))
    y = [data["hazards"][i, t + 1:t + 4].any() for i in range(len(eps)) for t in range(1, R.STEPS)]
    print(f"{len(eps)} episodes -> {d / 'dataset.npz'}; caution prevalence {np.mean(y):.3f}")
    return data


def selftest():
    import shutil
    name = "_selftest"
    shutil.rmtree(RIG / name, ignore_errors=True)
    src = SyntheticSource(seed=1)
    calibrate(src, name, fence_cm=60, headless=True)
    record(src, name, seed=5, episodes=3, headless=True)
    data = build(name)
    _, meta, W, _ = load_session(name)
    # tracking check: re-detect against the synthetic ground truth on a fresh placement
    errs = []
    for target in ([0.3, -0.5], [-0.7, 0.6], [0.9, 0.9]):
        src.instruct(robot_target=target)
        for _ in range(8):
            src.read()
        _, _, rpos, _, _, _ = observe(src, W, cv2.imread(str(RIG / name / "background.png")), meta)
        errs.append(float(np.hypot(*(rpos - src.robot))))
    assert data["frames"].shape == (3, R.STEPS + 1, MODEL_SIZE, MODEL_SIZE), data["frames"].shape
    assert max(errs) < 0.03, errs
    import vision_runtime_proxy_final as RP     # the registered harness reads this dataset as is
    idx = RP.decisions(data)
    assert len(idx["y"]) == 3 * (R.STEPS - 1) and idx["a10"].shape == (len(idx["y"]), 10)
    print(f"selftest OK: frames {data['frames'].shape}, tracking error max {max(errs):.4f} runtime units, "
          f"{len(idx['y'])} decisions readable by vision_runtime_proxy_final.decisions")
    shutil.rmtree(RIG / name, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("--source", required=True, help="IP Webcam base URL, e.g. http://192.168.1.23:8080")
    c.add_argument("--session", required=True)
    c.add_argument("--fence-cm", type=float, default=60.0)
    r = sub.add_parser("record")
    r.add_argument("--source", required=True)
    r.add_argument("--session", required=True)
    r.add_argument("--seed", type=int, required=True)
    r.add_argument("--episodes", type=int, default=10)
    b = sub.add_parser("build")
    b.add_argument("--session", required=True)
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "calibrate":
        calibrate(PhoneSource(a.source), a.session, a.fence_cm)
    elif a.cmd == "record":
        try:
            record(PhoneSource(a.source), a.session, a.seed, a.episodes)
        except KeyboardInterrupt:
            print("stopped; finished episodes are saved and the next run resumes after them")
    elif a.cmd == "build":
        build(a.session)
    else:
        selftest()


if __name__ == "__main__":
    main()
