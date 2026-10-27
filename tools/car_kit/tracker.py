"""Overhead phone tracking of the car and the obstacle from coloured paper or tape markers.

No printer: two coloured squares on top of the car (front and rear, along its long axis),
one coloured object as the obstacle, four objects of one colour on the arena corners. The
phone looks down from a fixed mount; a homography from the four clicked corners maps image
pixels to floor metres, arena-centred (x along the near edge, y away from it). Markers sit
above the floor, so their floor-plane hit points are pushed away from the camera's nadir;
locate() scales them back by (camera_height - marker_height) / camera_height.

Colours are learned by clicking each marker once (median patch, Lab distance), as in
scripts/real_rig/phone_rig.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import threading
import time

import cv2
import numpy as np

CORNER_NAMES = ("near-left", "near-right", "far-right", "far-left")
MARKERS = ("front", "rear", "obstacle")
COLOUR_DIST = 28.0


@dataclass
class Calibration:
    corners_px: list[list[float]]          # image pixels, CORNER_NAMES order
    arena_w_m: float
    arena_h_m: float
    refs: dict[str, list[float]]           # BGR of each marker in MARKERS
    camera_height_m: float                 # lens above the floor (tape measure)
    marker_height_m: float = 0.07          # top of the car, where the front/rear squares are
    obstacle_height_m: float = 0.05        # top of the obstacle marker
    marker_sep_m: float = 0.10             # centre-to-centre, front to rear square
    axle_offset_m: float = 0.0             # wheel-axle midpoint ahead (+) of the squares' midpoint
    image_size: list[int] = field(default_factory=lambda: [640, 480])
    nadir_px: list[float] | None = None    # image point straight below the lens; default image centre

    def __post_init__(self) -> None:
        w, h = self.arena_w_m / 2, self.arena_h_m / 2
        floor = np.float32([[-w, -h], [w, -h], [w, h], [-w, h]])
        self.H = cv2.getPerspectiveTransform(np.float32(self.corners_px), floor)
        nadir = self.nadir_px or [self.image_size[0] / 2, self.image_size[1] / 2]
        self.nadir_xy = self.to_floor(nadir)
        poly = np.float32(self.corners_px)
        centre = poly.mean(0)
        self.roi_poly = (centre + 1.25 * (poly - centre)).astype(np.int32)   # arena plus a margin

    def to_floor(self, uv, height_m: float = 0.0) -> np.ndarray:
        p = cv2.perspectiveTransform(np.float32(uv).reshape(1, 1, 2), self.H).reshape(2).astype(np.float64)
        if height_m:
            p = self.nadir_xy + (p - self.nadir_xy) * (self.camera_height_m - height_m) / self.camera_height_m
        return p

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Calibration":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Scene:
    t: float
    robot: tuple[float, float, float] | None    # x, y (axle midpoint, metres), heading (rad)
    obstacle: tuple[float, float] | None
    reason: str = "ok"

    @property
    def ok(self) -> bool:
        return self.robot is not None


def sample_colour(frame, uv, r: int = 4) -> list[float]:
    u, v = int(round(uv[0])), int(round(uv[1]))
    patch = frame[max(v - r, 0):v + r + 1, max(u - r, 0):u + r + 1].reshape(-1, 3)
    return np.median(patch, 0).tolist()


class ColourTracker:
    def __init__(self, cal: Calibration, min_px: int = 12, colour_dist: float = COLOUR_DIST) -> None:
        self.cal = cal
        self.min_px = min_px
        self.colour_dist = colour_dist
        self.refs = {k: cv2.cvtColor(np.uint8(v).reshape(1, 1, 3), cv2.COLOR_BGR2LAB).reshape(3).astype(np.float32)
                     for k, v in cal.refs.items()}
        self._roi = None

    def _blob(self, lab, roi, name):
        d = np.linalg.norm(lab - self.refs[name], axis=2)
        mask = ((d < self.colour_dist) & roi).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, _, stats, cent = cv2.connectedComponentsWithStats(mask)
        if n <= 1:
            return None
        k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        return cent[k] if stats[k, cv2.CC_STAT_AREA] >= self.min_px else None

    def locate(self, frame, t: float | None = None) -> Scene:
        t = time.monotonic() if t is None else t
        if self._roi is None or self._roi.shape != frame.shape[:2]:
            roi = np.zeros(frame.shape[:2], np.uint8)
            cv2.fillPoly(roi, [self.cal.roi_poly], 1)
            self._roi = roi.astype(bool)
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.float32)
        uv = {k: self._blob(lab, self._roi, k) for k in MARKERS}
        obstacle = None
        if uv["obstacle"] is not None:
            obstacle = tuple(self.cal.to_floor(uv["obstacle"], self.cal.obstacle_height_m))
        if uv["front"] is None or uv["rear"] is None:
            return Scene(t, None, obstacle, "car markers not found")
        front = self.cal.to_floor(uv["front"], self.cal.marker_height_m)
        rear = self.cal.to_floor(uv["rear"], self.cal.marker_height_m)
        sep = float(np.hypot(*(front - rear)))
        if not 0.6 * self.cal.marker_sep_m <= sep <= 1.4 * self.cal.marker_sep_m:
            return Scene(t, None, obstacle, f"marker separation {sep:.3f} m implausible")
        theta = math.atan2(front[1] - rear[1], front[0] - rear[0])
        mid = (front + rear) / 2 + self.cal.axle_offset_m * np.array([math.cos(theta), math.sin(theta)])
        return Scene(t, (float(mid[0]), float(mid[1]), theta), obstacle)


class PhoneSource:
    """IP Webcam (Android, free): http://<phone-ip>:8080. A reader thread keeps only the newest
    frame of the MJPEG stream, so tracking never works from a buffered, seconds-old image."""

    def __init__(self, spec: str, max_age_s: float = 1.0) -> None:
        if spec.startswith("http") and "/video" not in spec:
            spec = spec.rstrip("/") + "/video"
        self.cap = cv2.VideoCapture(int(spec) if spec.isdigit() else spec)
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open camera stream {spec}")
        self.max_age_s = max_age_s
        self._frame, self._t = None, 0.0
        self._lock = threading.Lock()
        self._run = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        while self._run:
            ok, frame = self.cap.read()
            if ok:
                with self._lock:
                    self._frame, self._t = frame, time.monotonic()
            else:
                time.sleep(0.05)

    def read(self):
        with self._lock:
            frame, t = self._frame, self._t
        if frame is None or time.monotonic() - t > self.max_age_s:
            raise RuntimeError("no fresh frame from the phone")
        return frame

    def close(self) -> None:
        self._run = False
        self._thread.join(timeout=1.0)
        self.cap.release()
