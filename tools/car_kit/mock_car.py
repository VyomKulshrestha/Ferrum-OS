"""Simulated car + overhead phone for testing the car-kit software before the kit arrives.

MockCarFirmware speaks the real UDP protocol (wire.py) with the firmware's semantics:
drive commands expire after ttl_ms, a closed bump switch latches the wheels off until
clear_bump (which fails while the switch is still pressed), wrong tokens get no answer.
Underneath is a differential-drive car with a motor deadband and mismatched wheels, so
the host has to close the loop. MockOverheadCamera renders the scene through a slightly
tilted pinhole camera, markers at their real heights (parallax included), with noise.
"""

from __future__ import annotations

import math
import socket
import threading
import time

import cv2
import numpy as np

from .tracker import Calibration, sample_colour
from .wire import MAX_DATAGRAM, WireError, decode_command, encode_status

ARENA_W, ARENA_H = 1.0, 0.75
WHEEL_BASE, MAX_SPEED, TRUE_DEADBAND = 0.12, 0.45, 95
BUMPER_AHEAD, BODY_RADIUS, OBSTACLE_R = 0.10, 0.06, 0.05
FRONT_AHEAD, REAR_BEHIND, MARKER_HALF = 0.07, 0.03, 0.02     # marker centres vs the axle midpoint
CAR_TOP, OBSTACLE_TOP = 0.07, 0.05
MAX_DRIVE_PWM = 200                                         # firmware cap


class MockCarFirmware:
    def __init__(self, token: str, start=(-0.25, 0.0, 0.0), obstacle=(0.25, 0.0),
                 gains=(1.0, 0.9), drop_rate: float = 0.0, seed: int = 0) -> None:
        self.token = token
        self.x, self.y, self.theta = start
        self.obstacle = obstacle
        self.gains = gains
        self.drop_rate = drop_rate
        self.rng = np.random.default_rng(seed)
        self.lock = threading.Lock()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.l = self.r = 0
        self.deadline = 0.0
        self.latched = False
        self.drive_packets = 0
        self.speed = 0.0
        self._t0 = time.monotonic()
        self._run = False

    # --- the firmware's loop() ---------------------------------------------------------------
    def bump_pressed(self) -> bool:
        if self.obstacle is None:
            return False
        ox, oy = self.obstacle
        bx, by = self.x + BUMPER_AHEAD * math.cos(self.theta), self.y + BUMPER_AHEAD * math.sin(self.theta)
        return math.hypot(bx - ox, by - oy) < OBSTACLE_R or math.hypot(self.x - ox, self.y - oy) < OBSTACLE_R + BODY_RADIUS

    def _wheel_speed(self, pwm: int, gain: float) -> float:
        if abs(pwm) <= TRUE_DEADBAND:
            return 0.0
        return math.copysign(gain * MAX_SPEED * (abs(pwm) - TRUE_DEADBAND) / (255 - TRUE_DEADBAND), pwm)

    def _physics(self) -> None:
        last = time.monotonic()
        while self._run:
            time.sleep(0.005)
            now = time.monotonic()
            dt, last = now - last, now
            with self.lock:
                if self.bump_pressed():
                    self.latched = True
                if self.latched or now > self.deadline:
                    self.l = self.r = 0
                vl, vr = self._wheel_speed(self.l, self.gains[0]), self._wheel_speed(self.r, self.gains[1])
                v, w = (vl + vr) / 2, (vr - vl) / WHEEL_BASE
                self.theta += w * dt
                self.x += v * math.cos(self.theta) * dt
                self.y += v * math.sin(self.theta) * dt
                self.speed = abs(v) + abs(w) * WHEEL_BASE / 2

    def _server(self) -> None:
        while self._run:
            try:
                raw, addr = self.sock.recvfrom(MAX_DATAGRAM + 1)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                return
            try:
                cmd = decode_command(raw)
            except WireError:
                continue
            if cmd["tok"] != self.token or self.rng.random() < self.drop_rate:
                continue
            with self.lock:
                op = cmd["op"]
                if op == "drive":
                    self.drive_packets += 1
                    if not self.latched:
                        self.l = max(-MAX_DRIVE_PWM, min(MAX_DRIVE_PWM, cmd["l"]))
                        self.r = max(-MAX_DRIVE_PWM, min(MAX_DRIVE_PWM, cmd["r"]))
                        self.deadline = time.monotonic() + cmd["ttl_ms"] / 1000.0
                elif op == "stop":
                    self.l = self.r = 0
                    self.deadline = 0.0
                elif op == "clear_bump" and not self.bump_pressed():
                    self.latched = False
                status = encode_status(cmd["seq"], op, self.bump_pressed(), self.latched, self.l, self.r,
                                       int((time.monotonic() - self._t0) * 1000))
            if self.rng.random() >= self.drop_rate:
                self.sock.sendto(status, addr)

    def start(self) -> "MockCarFirmware":
        self._run = True
        self._threads = [threading.Thread(target=f, daemon=True) for f in (self._physics, self._server)]
        for t in self._threads:
            t.start()
        return self

    def close(self) -> None:
        self._run = False
        for t in getattr(self, "_threads", []):
            t.join(timeout=1.0)
        self.sock.close()

    def pose(self) -> tuple[float, float, float]:
        with self.lock:
            return self.x, self.y, self.theta

    def set_pose(self, x: float, y: float, theta: float) -> None:
        with self.lock:
            self.x, self.y, self.theta = x, y, theta


class MockOverheadCamera:
    """Phone on a clamp arm ~0.85 m up, a few degrees off vertical, 640x480."""

    FLOOR, ROOM, CORNER = (175, 175, 170), (70, 75, 80), (60, 170, 60)
    BODY, FRONT, REAR, OBST = (45, 45, 45), (40, 40, 210), (200, 110, 30), (40, 200, 230)

    def __init__(self, car: MockCarFirmware, seed: int = 0, camera_xyz=(0.03, -0.02, 0.85),
                 tilt_deg=(4.0, -3.0, 10.0), f_px: float = 430.0, size=(640, 480)) -> None:
        self.car = car
        self.rng = np.random.default_rng(seed)
        self.size = size
        self.C = np.array(camera_xyz, np.float64)
        a, b, c = np.radians(tilt_deg)
        rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
        ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
        rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
        base = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], np.float64)   # looking straight down, far edge up
        self.R = rx @ ry @ rz @ base
        self.K = np.array([[f_px, 0, size[0] / 2], [0, f_px, size[1] / 2], [0, 0, 1]])
        self.hide_car = False

    def project(self, pts) -> np.ndarray:
        X = (np.atleast_2d(np.asarray(pts, np.float64)) - self.C) @ self.R.T
        uv = X @ self.K.T
        return uv[:, :2] / uv[:, 2:3]

    def _square(self, cx, cy, half, z, theta=0.0):
        c, s = math.cos(theta), math.sin(theta)
        pts = [(cx + c * dx - s * dy, cy + s * dx + c * dy, z) for dx, dy in ((-half, -half), (half, -half), (half, half), (-half, half))]
        return np.int32(np.round(self.project(pts)))

    def corners(self):
        w, h = ARENA_W / 2, ARENA_H / 2
        return [(-w, -h), (w, -h), (w, h), (-w, h)]        # tracker.CORNER_NAMES order

    def read(self):
        x, y, th = self.car.pose()
        img = np.full((self.size[1], self.size[0], 3), self.ROOM, np.uint8)
        w, h = ARENA_W / 2 + 0.06, ARENA_H / 2 + 0.06
        cv2.fillPoly(img, [np.int32(np.round(self.project([(-w, -h, 0), (w, -h, 0), (w, h, 0), (-w, h, 0)])))], self.FLOOR)
        for cx, cy in self.corners():
            cv2.fillPoly(img, [self._square(cx, cy, 0.025, 0.0)], self.CORNER)
        if self.car.obstacle is not None:
            ox, oy = self.car.obstacle
            ring = [(ox + OBSTACLE_R * math.cos(a), oy + OBSTACLE_R * math.sin(a), OBSTACLE_TOP) for a in np.linspace(0, 2 * math.pi, 24, endpoint=False)]
            cv2.fillPoly(img, [np.int32(np.round(self.project(ring)))], self.OBST)
        if not self.hide_car:
            ux, uy = math.cos(th), math.sin(th)
            cv2.fillPoly(img, [self._square(x + 0.02 * ux, y + 0.02 * uy, 0.07, CAR_TOP - 0.01, th)], self.BODY)
            cv2.fillPoly(img, [self._square(x + FRONT_AHEAD * ux, y + FRONT_AHEAD * uy, MARKER_HALF, CAR_TOP, th)], self.FRONT)
            cv2.fillPoly(img, [self._square(x - REAR_BEHIND * ux, y - REAR_BEHIND * uy, MARKER_HALF, CAR_TOP, th)], self.REAR)
        gain = self.rng.uniform(0.92, 1.08)
        noisy = img.astype(np.float32) * gain + self.rng.normal(0, 3, img.shape)
        return np.clip(noisy, 0, 255).astype(np.uint8)

    def operator_calibration(self, click_noise_px: float = 1.0, tape_error_m: float = 0.01) -> Calibration:
        """What the calibrate command would record: clicked corners and markers, a taped height."""
        corners = self.project([(cx, cy, 0.0) for cx, cy in self.corners()]) + self.rng.normal(0, click_noise_px, (4, 2))
        frame = self.read()
        x, y, th = self.car.pose()
        ux, uy = math.cos(th), math.sin(th)
        at = {"front": (x + FRONT_AHEAD * ux, y + FRONT_AHEAD * uy, CAR_TOP),
              "rear": (x - REAR_BEHIND * ux, y - REAR_BEHIND * uy, CAR_TOP),
              "obstacle": (*self.car.obstacle, OBSTACLE_TOP)}
        refs = {k: sample_colour(frame, self.project([p])[0]) for k, p in at.items()}
        return Calibration(corners_px=corners.tolist(), arena_w_m=ARENA_W, arena_h_m=ARENA_H, refs=refs,
                           camera_height_m=float(self.C[2] + tape_error_m), marker_height_m=CAR_TOP,
                           obstacle_height_m=OBSTACLE_TOP, marker_sep_m=FRONT_AHEAD + REAR_BEHIND,
                           axle_offset_m=-(FRONT_AHEAD - REAR_BEHIND) / 2, image_size=list(self.size))
