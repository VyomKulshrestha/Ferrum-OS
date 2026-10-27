"""Bring-up commands for the car kit (python -m tools.car_kit <command> --help).

  selftest                          the whole pipeline against the simulated car and phone
  calibrate --source URL ...        click 4 arena corners, the front/rear squares, the obstacle
  track --source URL                print tracked poses (check the markers before driving)
  ping --car IP --token T           firmware alive? bump state?
  wheels --car IP --token T         each wheel briefly, car lifted off the ground
  goto --car IP --token T --source URL --x X --y Y
                                    one closed-loop move without FerrumOS in the loop (same
                                    geofence, TTL and bump latch); real runs go through a
                                    BridgeSession instead
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import cv2

from .tracker import CORNER_NAMES, MARKERS, Calibration, ColourTracker, PhoneSource, sample_colour
from .wire import UdpLink

OUT = Path("target/car-kit")


def click_points(frame, prompts):
    points = []
    window = "car-kit calibrate"

    def on_mouse(event, u, v, *_):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < len(prompts):
            points.append((u, v))

    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)
    while len(points) < len(prompts):
        view = frame.copy()
        for u, v in points:
            cv2.circle(view, (u, v), 5, (0, 0, 255), 2)
        cv2.putText(view, f"click: {prompts[len(points)]}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imshow(window, view)
        if cv2.waitKey(30) == 27:
            raise SystemExit("cancelled")
    cv2.destroyWindow(window)
    return points


def calibrate(args):
    source = PhoneSource(args.source)
    time.sleep(1.0)
    frame = source.read()
    prompts = [f"{c} corner" for c in CORNER_NAMES] + [f"{m} marker" for m in MARKERS]
    points = json.loads(args.points) if args.points else click_points(frame, prompts)
    cal = Calibration(corners_px=[list(map(float, p)) for p in points[:4]], arena_w_m=args.arena_w, arena_h_m=args.arena_h,
                      refs={m: sample_colour(frame, points[4 + i]) for i, m in enumerate(MARKERS)},
                      camera_height_m=args.camera_height, marker_height_m=args.marker_height,
                      obstacle_height_m=args.obstacle_height, marker_sep_m=args.marker_sep,
                      axle_offset_m=args.axle_offset, image_size=[frame.shape[1], frame.shape[0]])
    cal.save(Path(args.cal))
    cv2.imwrite(str(Path(args.cal).with_suffix(".jpg")), frame)
    print("saved", args.cal, "->", ColourTracker(cal).locate(frame))
    source.close()


def track(args):
    source = PhoneSource(args.source)
    tracker = ColourTracker(Calibration.load(args.cal))
    try:
        while True:
            try:
                scene = tracker.locate(source.read())
                print(scene.robot and tuple(round(v, 3) for v in scene.robot), scene.obstacle and tuple(round(v, 3) for v in scene.obstacle), scene.reason)
            except RuntimeError as error:
                print(error)
            time.sleep(0.2)
    except KeyboardInterrupt:
        source.close()


def wheels(args):
    link = UdpLink(args.car, args.token)
    for name, l, r in (("left forward", 140, 0), ("left reverse", -140, 0), ("right forward", 0, 140), ("right reverse", 0, -140)):
        print(name)
        end = time.monotonic() + 0.8
        while time.monotonic() < end:
            link.drive(l, r, 200)
            time.sleep(0.05)
        link.stop()
        time.sleep(0.6)
    link.close()


def goto(args):
    from .backend import CarKitBackend
    link = UdpLink(args.car, args.token)
    backend = CarKitBackend(1, link, ColourTracker(Calibration.load(args.cal)), PhoneSource(args.source),
                            log_path=OUT / "goto_log.jsonl")
    try:
        if not backend.inside(args.x, args.y, backend.arena_margin_m):
            raise SystemExit("target outside the arena")
        print(backend.drive_to(args.x, args.y), backend.last_scene)
    finally:
        backend.close()


def selftest(_args):
    import unittest
    suite = unittest.defaultTestLoader.loadTestsFromName("tools.car_kit.test_car_kit")
    sys.exit(0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1)


def main():
    ap = argparse.ArgumentParser(prog="python -m tools.car_kit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("--source", required=True, help="http://<phone-ip>:8080 (IP Webcam)")
    c.add_argument("--arena-w", type=float, required=True, help="metres, along the near edge")
    c.add_argument("--arena-h", type=float, required=True)
    c.add_argument("--camera-height", type=float, required=True, help="lens above the floor, metres")
    c.add_argument("--marker-height", type=float, default=0.07)
    c.add_argument("--obstacle-height", type=float, default=0.05)
    c.add_argument("--marker-sep", type=float, default=0.10)
    c.add_argument("--axle-offset", type=float, default=0.0)
    c.add_argument("--points", help="JSON list of 7 [u, v] instead of clicking")
    for name in ("track", "goto"):
        s = sub.add_parser(name)
        s.add_argument("--source", required=True)
    for name in ("ping", "wheels", "goto"):
        s = sub.choices[name] if name in sub.choices else sub.add_parser(name)
        s.add_argument("--car", required=True, help="car IP printed on the serial monitor")
        s.add_argument("--token", required=True)
    sub.choices["goto"].add_argument("--x", type=float, required=True)
    sub.choices["goto"].add_argument("--y", type=float, required=True)
    sub.add_parser("selftest")
    for s in sub.choices.values():
        if s.prog.split()[-1] != "selftest":
            s.add_argument("--cal", default=str(OUT / "calibration.json"))
    args = ap.parse_args()
    if args.cmd == "ping":
        print(UdpLink(args.car, args.token).ping() or "no answer (IP, token, same Wi-Fi?)")
        return
    {"calibrate": calibrate, "track": track, "wheels": wheels, "goto": goto, "selftest": selftest}[args.cmd](args)


if __name__ == "__main__":
    main()
