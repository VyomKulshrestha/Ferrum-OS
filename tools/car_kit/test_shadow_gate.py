"""Shadow gate tests: tracked scenes -> FerrumOS car-arena gate verdicts (roadmap M1).

Needs the built gate (see tools/car_kit/shadow_gate.py); skipped otherwise.
  python -m unittest tools.car_kit.test_shadow_gate
"""

from __future__ import annotations

import unittest

from .mock_car import MockCarFirmware, MockOverheadCamera
from .shadow_gate import ArenaMeasurements, ShadowGate, find_gate
from .tracker import ColourTracker, Scene

ARENA = ArenaMeasurements(arena_w_m=1.0, arena_h_m=0.75, car_radius_m=0.09, obstacle_radius_m=0.04,
                          required_clearance_m=0.05, tracker_error_p99_m=0.015, max_speed_m_s=0.2,
                          latency_s=0.15, stop_s=0.10, max_step_m=0.10)


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


@unittest.skipIf(find_gate() is None, "tools/car_gate not built")
class ShadowGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.gate = ShadowGate(ARENA, clock=self.clock)
        self.addCleanup(self.gate.close)

    def scene(self, robot, obstacle=(0.25, 0.0)) -> Scene:
        return Scene(t=self.clock.t, robot=(robot[0], robot[1], 0.0), obstacle=obstacle)

    def test_policy_carries_the_measured_margin(self) -> None:
        p = self.gate.policy
        self.assertEqual((p.margin_mm, p.age_ticks, p.min_clearance_mm, p.step_mm), (65, 15, 215, 100))
        self.assertEqual(p.fence_mm, (-345, 345, -220, 220))

    def test_verdicts_for_short_long_outside_and_unseen_moves(self) -> None:
        self.assertIn("StaleActorPosition", self.gate.propose(1, (0.0, 0.0)).reasons)
        self.assertTrue(self.gate.observe(self.scene((-0.2, -0.1))))
        self.clock.t += 0.02
        self.assertTrue(self.gate.propose(2, (-0.15, -0.08)).allowed)
        self.assertEqual(self.gate.propose(3, (0.0, -0.1)).reasons, ("MoveStepTooLong",))
        self.assertIn("GeofenceViolation", self.gate.propose(4, (-0.2, 0.3)).reasons)

    def test_scene_without_the_obstacle_sends_nothing_and_motion_goes_stale(self) -> None:
        self.assertTrue(self.gate.observe(self.scene((-0.2, -0.1))))
        self.clock.t += 0.10
        self.assertFalse(self.gate.observe(Scene(t=self.clock.t, robot=(-0.2, -0.1, 0.0), obstacle=None)))
        self.assertFalse(self.gate.observe(Scene(t=self.clock.t, robot=None, obstacle=(0.25, 0.0), reason="no car")))
        self.clock.t += 0.10      # 0.20 s since the last real scene, limit 0.15 s
        verdict = self.gate.propose(1, (-0.18, -0.1))
        self.assertFalse(verdict.allowed)
        self.assertIn("StaleProximitySensor", verdict.reasons)
        self.assertIn("StaleActorPosition", verdict.reasons)


@unittest.skipIf(find_gate() is None, "tools/car_gate not built")
class EndToEndTests(unittest.TestCase):
    """Mock car -> rendered overhead image -> colour tracker -> FerrumOS gate."""

    def test_camera_tracked_car_is_judged_by_the_gate(self) -> None:
        car = MockCarFirmware("t0ken", obstacle=(0.25, 0.0))
        self.addCleanup(car.close)
        cam = MockOverheadCamera(car)
        tracker = ColourTracker(cam.operator_calibration())
        clock = Clock()
        gate = ShadowGate(ARENA, clock=clock)
        self.addCleanup(gate.close)

        def look(x: float, y: float) -> Scene:
            car.set_pose(x, y, 0.0)
            scene = tracker.locate(cam.read(), t=clock.t)
            self.assertTrue(scene.ok, scene.reason)
            self.assertIsNotNone(scene.obstacle)
            return scene

        # far from the obstacle (clearance ~0.37 m): a 6 cm step toward it is allowed
        self.assertTrue(gate.observe(look(-0.25, 0.0)))
        clock.t += 0.02
        self.assertTrue(gate.propose(1, (-0.19, 0.0)).allowed)

        # 0.25 m from its centre: clearance ~0.12 m, below the 0.215 m floor
        clock.t += 0.05
        self.assertTrue(gate.observe(look(0.0, 0.0)))
        clock.t += 0.02
        near = gate.propose(2, (0.02, 0.0))
        self.assertIn("UnsafeProximity", near.reasons)

        # the camera loses the car: nothing goes in, and motion blocks once the readings age out
        cam.hide_car = True
        clock.t += 0.05
        self.assertFalse(gate.observe(tracker.locate(cam.read(), t=clock.t)))
        clock.t += 0.20
        lost = gate.propose(3, (-0.02, 0.0))
        self.assertIn("StaleActorPosition", lost.reasons)

    def test_a_delayed_frame_reaches_the_gate_with_its_arrival_time(self) -> None:
        import time

        from .backend import CarKitBackend
        from .shadow_gate import GateError
        from .wire import UdpLink
        car = MockCarFirmware("t0ken", start=(-0.25, 0.0, 0.0), obstacle=(0.25, 0.0)).start()
        cam = MockOverheadCamera(car)

        class Delayed:                  # a phone frame that arrived 0.3 s ago: under the backend's
            def read_stamped(self):     # 0.4 s stall limit, over the gate's 0.15 s reading age
                return cam.read(), time.monotonic() - 0.3

            def read(self):
                return self.read_stamped()[0]

        backend = CarKitBackend(1, UdpLink("127.0.0.1", "t0ken", port=car.port),
                                ColourTracker(cam.operator_calibration()), Delayed())
        self.addCleanup(car.close)
        self.addCleanup(backend.close)
        gate = ShadowGate(ARENA)
        self.addCleanup(gate.close)
        scene = backend.observe()
        with self.assertRaisesRegex(GateError, "StaleObservation"):   # refused at ingest
            gate.observe(scene)
        verdict = gate.propose(1, (scene.robot[0] + 0.06, 0.0))
        self.assertFalse(verdict.allowed, verdict)


if __name__ == "__main__":
    unittest.main()
