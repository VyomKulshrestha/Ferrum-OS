"""Real 2WD ESP32 car as a physical_sim_bridge backend.

Same surface as PyBulletBackend (reset_scene, submit_command move_to/stop,
poll_observation, close), so a BridgeSession can drive the car instead of the simulator.
Pose comes from the overhead phone tracker; wheel commands go to the firmware over UDP.
move_to is closed-loop: turn toward the target, drive with proportional steering, stop
within tolerance_m. Observations are evidence_class "hardware_in_loop".

Safety lives below this class too. The firmware stops the wheels when a drive command's
time-to-live runs out (so a crashed host, lost Wi-Fi or a stalled tracker all end in a
stop) and latches them off when a bump switch closes. This class adds a target geofence,
a stop when the car leaves the arena or tracking is lost, and a per-move timeout. It has
no authority of its own: FerrumOS decides whether a command is issued at all.
"""

from __future__ import annotations

from collections import deque
import json
import math
from pathlib import Path
import time
from typing import Any, Callable

from tools.physical_sim_bridge.bridge import BridgeError
from tools.physical_sim_bridge.protocol import BridgeCommand, BridgeObservation

from .tracker import ColourTracker, Scene
from .wire import MAX_PWM, MAX_TTL_MS, UdpLink

TICK_HZ = 240                      # bridge ticks per second, as PyBulletBackend's 1/240 s step


class CarKitBackend:
    def __init__(
        self,
        run_id: int,
        link: UdpLink,
        tracker: ColourTracker,
        source: Any,
        simulator_epoch: int = 1,
        source_clock_id: int = 1,
        tolerance_m: float = 0.03,
        arena_margin_m: float = 0.05,
        move_timeout_s: float = 8.0,
        control_hz: float = 15.0,
        stale_s: float = 0.4,
        deadband_pwm: int = 110,
        max_pwm: int = 200,
        turn_pwm: int = 150,
        turn_in_place_rad: float = math.radians(35),
        k_steer: float = 1.2,
        slow_radius_m: float = 0.15,
        battery_permille: int = 1_000,     # not measured: the ESP32-CAM's free pins are ADC2, unusable with Wi-Fi on
        log_path: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.run_id = run_id
        self.simulator_epoch = simulator_epoch
        self.source_clock_id = source_clock_id
        self.link, self.tracker, self.source = link, tracker, source
        self.tolerance_m, self.arena_margin_m = tolerance_m, arena_margin_m
        self.move_timeout_s, self.period_s, self.stale_s = move_timeout_s, 1.0 / control_hz, stale_s
        self.deadband_pwm, self.max_pwm, self.turn_pwm = deadband_pwm, min(max_pwm, MAX_PWM), turn_pwm
        self.turn_in_place_rad, self.k_steer, self.slow_radius_m = turn_in_place_rad, k_steer, slow_radius_m
        self.ttl_ms = min(MAX_TTL_MS, int(3000 * self.period_s))     # three missed periods -> the car stops itself
        self.battery_permille = battery_permille
        self.clock, self.sleep = clock, sleep
        self.half_w = tracker.cal.arena_w_m / 2
        self.half_h = tracker.cal.arena_h_m / 2
        self._t0 = clock()
        self._sequence = 0
        self._queue: deque[BridgeObservation] = deque()
        self._log = open(log_path, "a", encoding="utf-8") if log_path else None
        self.collision_detected = False
        self.link_ok = True
        self.last_scene: Scene | None = None
        self.commands: list[BridgeCommand] = []

    # --- time, logging, observations -----------------------------------------------------
    def tick(self) -> int:
        return int((self.clock() - self._t0) * TICK_HZ)

    def _record(self, event: str, **fields: Any) -> None:
        if self._log:
            self._log.write(json.dumps({"t": round(self.clock() - self._t0, 4), "event": event, **fields}) + "\n")

    def observe(self) -> Scene | None:
        """One fresh tracked frame (None if the camera has nothing)."""
        try:
            frame = self.source.read()
        except Exception as error:   # camera dropped: treated as tracking lost by the caller
            self._record("camera_error", error=str(error)[:120])
            return None
        scene = self.tracker.locate(frame, self.clock())
        self.last_scene = scene
        self._record("scene", robot=scene.robot, obstacle=scene.obstacle, reason=scene.reason)
        return scene

    def _state(self) -> str:
        status = self.link.last_status
        if not self.link_ok:
            return "offline"
        if status is not None and status["latched"]:
            return "emergency_stop"
        return "available"

    def _emit_actor_observation(self) -> None:
        scene = self.observe()
        if scene is None or not scene.ok:
            return    # never report a position the camera did not just see
        tick = self.tick()
        self._sequence += 1
        self._queue.append(BridgeObservation(
            run_id=self.run_id, simulator_epoch=self.simulator_epoch, adapter_id=1, endpoint_id=1,
            session_epoch=1, sequence=self._sequence, observed_at_tick=tick,
            source_clock_id=self.source_clock_id, clock_uncertainty_ticks=int(self.stale_s * TICK_HZ),
            frame_id=self._sequence, expires_at_tick=tick + TICK_HZ, evidence_class="hardware_in_loop",
            fault_manifest_id=0, fault_code=0,
            payload={"type": "actor", "actor_id": 1, "zone_id": 1,
                     "x_mm": int(round(scene.robot[0] * 1000)), "y_mm": int(round(scene.robot[1] * 1000)),
                     "z_mm": 0, "battery_permille": self.battery_permille, "load_permille": 0,
                     "state": self._state()},
        ))

    def poll_observation(self) -> BridgeObservation | None:
        return self._queue.popleft() if self._queue else None

    # --- motion -------------------------------------------------------------------------
    def inside(self, x: float, y: float, margin: float = 0.0) -> bool:
        return abs(x) <= self.half_w - margin and abs(y) <= self.half_h - margin

    def _pwm(self, u: float) -> int:
        """Normalised wheel effort [-1, 1] -> PWM above the motors' stiction deadband."""
        if abs(u) < 0.02:
            return 0
        u = max(-1.0, min(1.0, u))
        return int(math.copysign(self.deadband_pwm + abs(u) * (self.max_pwm - self.deadband_pwm), u))

    def _wheels(self, x, y, theta, tx, ty) -> tuple[int, int]:
        dist = math.hypot(tx - x, ty - y)
        err = (math.atan2(ty - y, tx - x) - theta + math.pi) % (2 * math.pi) - math.pi
        if abs(err) > self.turn_in_place_rad:
            s = 1 if err > 0 else -1                   # positive error = target to the left
            return -s * self.turn_pwm, s * self.turn_pwm
        v = min(1.0, dist / self.slow_radius_m)
        w = self.k_steer * err
        return self._pwm(v - w), self._pwm(v + w)

    def stop_car(self) -> dict[str, Any] | None:
        for _ in range(3):              # UDP: retry; the TTL stops the wheels regardless
            status = self.link.stop()
            if status is not None:
                self.link_ok = True
                return status
        self.link_ok = False
        return None

    def drive_to(self, tx: float, ty: float) -> str:
        """Closed-loop move; returns why it ended. Always leaves the wheels commanded off."""
        start, last_seen, link_misses = self.clock(), self.clock(), 0
        reason = "timeout"
        while True:
            t_loop = self.clock()
            if t_loop - start > self.move_timeout_s:
                break
            scene = self.observe()
            if scene is None or not scene.ok:
                if t_loop - last_seen > self.stale_s:
                    reason = "tracking_lost"
                    break
                self.link.stop()        # hold still until the car is seen again
                self.sleep(self.period_s)
                continue
            last_seen = t_loop
            x, y, theta = scene.robot
            if not self.inside(x, y):
                reason = "left_arena"
                break
            if math.hypot(tx - x, ty - y) <= self.tolerance_m:
                reason = "reached_target"
                break
            l, r = self._wheels(x, y, theta, tx, ty)
            status = self.link.drive(l, r, self.ttl_ms)
            self._record("drive", l=l, r=r, status=status)
            if status is None:
                link_misses += 1
                if link_misses >= 3:
                    reason = "link_lost"
                    break
            else:
                link_misses = 0
                self.link_ok = True
                if status["latched"]:
                    reason = "bump_stop"
                    break
            self.sleep(max(0.0, self.period_s - (self.clock() - t_loop)))
        status = self.stop_car()
        if reason == "link_lost":
            self.link_ok = False
        if status is not None and status["latched"]:
            reason = "bump_stop"
        if reason == "bump_stop":
            self.collision_detected = True
        self._record("move_end", target=[tx, ty], reason=reason)
        return reason

    # --- PyBulletBackend surface ------------------------------------------------------------
    def reset_scene(self, robot_xy: tuple[float, float], obstacle_xy: tuple[float, float],
                    obstacle_tolerance_m: float = 0.05) -> None:
        """A real car cannot teleport: the operator places the obstacle (checked here), then the
        car drives itself to robot_xy. Re-arms a latched bump switch (the operator has looked)."""
        scene = self.observe()
        if scene is None or scene.obstacle is None:
            raise BridgeError("reset_scene: the camera does not see the obstacle")
        ox, oy = scene.obstacle
        if math.hypot(ox - obstacle_xy[0], oy - obstacle_xy[1]) > obstacle_tolerance_m:
            raise BridgeError(f"reset_scene: place the obstacle at {obstacle_xy} (seen at {ox:.3f}, {oy:.3f})")
        if not self.inside(*robot_xy, self.arena_margin_m):
            raise BridgeError("reset_scene: robot start lies outside the arena")
        if self.link.clear_bump() is None:
            raise BridgeError("reset_scene: the car does not answer")
        self.collision_detected = False
        self._queue.clear()
        reason = self.drive_to(*robot_xy)
        if reason != "reached_target":
            raise BridgeError(f"reset_scene: could not reach the start ({reason})")
        self.collision_detected = False
        self._emit_actor_observation()

    def submit_command(self, command: BridgeCommand) -> dict[str, Any]:
        self.commands.append(command)
        self._record("command", kind=command.kind, arguments=list(command.arguments), command_id=command.command_id)
        if command.kind == "stop":
            ok = self.stop_car() is not None
            self._emit_actor_observation()
            return {"command_id": command.command_id, "executed": ok,
                    "delivery_state": "accepted" if ok else "uncertain",
                    "reason": "car_stopped" if ok else "car_did_not_acknowledge_stop"}
        if command.kind != "move_to":
            return {"command_id": command.command_id, "executed": False,
                    "delivery_state": "uncertain", "reason": "unsupported_car_kit_command"}
        tx, ty = command.arguments[0] / 1000.0, command.arguments[1] / 1000.0
        if not self.inside(tx, ty, self.arena_margin_m):
            # nothing was sent; BridgePump reports this as uncertain, the conservative reading
            return {"command_id": command.command_id, "executed": False,
                    "delivery_state": "rejected", "reason": "target_outside_arena"}
        reason = self.drive_to(tx, ty)
        self._emit_actor_observation()
        certain = reason in {"reached_target", "timeout", "bump_stop", "left_arena"} and self.link_ok
        return {"command_id": command.command_id, "executed": certain,
                "delivery_state": "accepted" if certain else "uncertain", "reason": f"car_{reason}"}

    def close(self) -> None:
        try:
            self.stop_car()
        finally:
            self.link.close()
            if hasattr(self.source, "close"):
                self.source.close()
            if self._log:
                self._log.close()
                self._log = None
