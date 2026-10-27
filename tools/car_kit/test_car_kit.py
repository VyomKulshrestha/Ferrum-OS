from __future__ import annotations

from dataclasses import replace
import math
import threading
import time
import unittest

from tools.physical_sim_bridge.bridge import BridgeError, BridgeSession
from tools.physical_sim_bridge.protocol import BridgeCommand, BridgeHello, BridgeObservation

from tools.car_kit.backend import CarKitBackend
from tools.car_kit.mock_car import MockCarFirmware, MockOverheadCamera
from tools.car_kit.tracker import ColourTracker
from tools.car_kit.wire import UdpLink, WireError, decode_command, decode_status, encode_command, encode_status

TOKEN = "t0k-test"


def command(kind: str = "move_to", x_mm: int = 0, y_mm: int = 0, key: int = 1) -> BridgeCommand:
    return BridgeCommand(
        run_id=7, command_id=key, idempotency_key=key, adapter_id=1, endpoint_id=1, session_epoch=1,
        kind=kind, arguments=(x_mm, y_mm, 0), issued_at_tick=0, deadline_tick=10**9,
        expected_policy_revision=1, expected_twin_event_id=1, confirmation_kind="local_human",
        confirmation_id=1, authority="ferrum_routed_command_v1",
    )


class Rig:
    def __init__(self, start=(-0.25, 0.0, 0.0), obstacle=(0.3, 0.25), **backend_kw) -> None:
        self.car = MockCarFirmware(TOKEN, start=start, obstacle=obstacle).start()
        self.cam = MockOverheadCamera(self.car)
        self.cal = self.cam.operator_calibration()
        self.link = UdpLink("127.0.0.1", TOKEN, port=self.car.port)
        self.backend = CarKitBackend(7, self.link, ColourTracker(self.cal), self.cam, **backend_kw)

    def close(self) -> None:
        self.backend.close()
        self.car.close()

    def wait_still(self, timeout: float = 1.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.car.speed == 0.0:
                return True
            time.sleep(0.02)
        return False


class WireTests(unittest.TestCase):
    def test_round_trip_and_strict_parsing(self) -> None:
        raw = encode_command("drive", 3, TOKEN, -120, 200, 250)
        self.assertEqual(decode_command(raw)["r"], 200)
        status = decode_status(encode_status(3, "drive", False, True, 0, 0, 99))
        self.assertEqual(status["latched"], 1)
        for bad in (b'{"op":"drive","seq":1,"tok":"x","l":0,"r":0,"ttl_ms":0}',      # TTL must be >= 1 ms
                    b'{"op":"drive","seq":1,"tok":"x","l":300,"r":0,"ttl_ms":50}',   # PWM range
                    b'{"op":"stop","seq":1,"tok":"x","extra":1}',                     # exact keys
                    b'{"op":"reboot","seq":1,"tok":"x"}'):
            with self.assertRaises(WireError):
                decode_command(bad)
        with self.assertRaises(WireError):
            encode_command("drive", 1, TOKEN, 0, 0, 501)                             # TTL cap
        with self.assertRaises(WireError):
            decode_status(b'{"seq":1,"ack":"drive","bump":0,"l":0,"r":0,"up_ms":1}')

    def test_wrong_token_gets_no_answer(self) -> None:
        car = MockCarFirmware(TOKEN).start()
        wrong, right = UdpLink("127.0.0.1", "wrong", port=car.port), UdpLink("127.0.0.1", TOKEN, port=car.port)
        try:
            self.assertIsNone(wrong.drive(200, 200, 300))
            self.assertEqual(car.drive_packets, 0)
            self.assertIsNotNone(right.ping())
        finally:
            wrong.close()
            right.close()
            car.close()


class TrackerTests(unittest.TestCase):
    def test_pose_accuracy_and_parallax_correction(self) -> None:
        car = MockCarFirmware(TOKEN)
        self.addCleanup(car.close)
        cam = MockOverheadCamera(car)
        cal = cam.operator_calibration()
        tracked, flat = ColourTracker(cal), ColourTracker(replace(cal, marker_height_m=0.0))
        errs, flat_errs = [], []
        for x, y, th in ((0.35, 0.25, 1.0), (-0.4, -0.28, -2.0), (0.0, 0.0, 3.0), (0.4, -0.3, 0.5)):
            car.set_pose(x, y, th)
            frame = cam.read()
            scene = tracked.locate(frame)
            self.assertTrue(scene.ok, scene.reason)
            errs.append(math.hypot(scene.robot[0] - x, scene.robot[1] - y))
            flat_errs.append(math.hypot(flat.locate(frame).robot[0] - x, flat.locate(frame).robot[1] - y))
            self.assertLess(abs((scene.robot[2] - th + math.pi) % (2 * math.pi) - math.pi), math.radians(4))
        self.assertLess(max(errs), 0.015)
        self.assertLess(sum(errs), sum(flat_errs) / 2)      # markers 7 cm up: correction matters

    def test_hidden_car_is_not_reported(self) -> None:
        car = MockCarFirmware(TOKEN)
        self.addCleanup(car.close)
        cam = MockOverheadCamera(car)
        tracker = ColourTracker(cam.operator_calibration())
        cam.hide_car = True
        scene = tracker.locate(cam.read())
        self.assertFalse(scene.ok)
        self.assertIsNotNone(scene.obstacle)


class BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rig = Rig()
        self.addCleanup(self.rig.close)

    def test_move_to_reaches_target_through_a_bridge_session(self) -> None:
        session = BridgeSession(BridgeHello(7, 1, "car_kit", 1, "ab" * 32, actuator_enabled=True), self.rig.backend)
        result = session.submit(command(x_mm=200, y_mm=-150), current_tick=0)
        self.assertEqual(result["reason"], "car_reached_target")
        self.assertEqual(result["delivery_state"], "accepted")
        x, y, _ = self.rig.car.pose()
        self.assertLess(math.hypot(x - 0.2, y + 0.15), 0.05)
        obs = session.poll()
        self.assertEqual(obs.evidence_class, "hardware_in_loop")
        self.assertEqual(BridgeObservation.parse(obs.to_wire()), obs)
        self.assertLess(math.hypot(obs.payload["x_mm"] / 1000 - x, obs.payload["y_mm"] / 1000 - y), 0.02)
        self.assertEqual(obs.payload["state"], "available")
        self.assertTrue(self.rig.wait_still())

    def test_target_outside_arena_sends_nothing(self) -> None:
        result = self.rig.backend.submit_command(command(x_mm=900, y_mm=0))
        self.assertEqual(result["delivery_state"], "rejected")
        self.assertFalse(result["executed"])
        self.assertEqual(self.rig.car.drive_packets, 0)

    def test_stop_and_unsupported_kinds(self) -> None:
        self.assertEqual(self.rig.backend.submit_command(command("stop"))["reason"], "car_stopped")
        self.assertEqual(self.rig.backend.submit_command(command("set_output"))["delivery_state"], "uncertain")

    def test_ttl_stops_the_car_when_the_host_goes_silent(self) -> None:
        self.rig.link.drive(200, 200, 200)
        time.sleep(0.08)
        self.assertGreater(self.rig.car.speed, 0.0)
        self.assertTrue(self.rig.wait_still(0.5))

    def test_link_loss_ends_the_move_and_the_car_stops_itself(self) -> None:
        threading.Timer(0.4, setattr, (self.rig.car, "drop_rate", 1.0)).start()
        result = self.rig.backend.submit_command(command(x_mm=350, y_mm=250))
        self.assertEqual(result["reason"], "car_link_lost")
        self.assertEqual(result["delivery_state"], "uncertain")
        self.assertTrue(self.rig.wait_still(0.6))

    def test_tracking_loss_ends_the_move(self) -> None:
        threading.Timer(0.4, setattr, (self.rig.cam, "hide_car", True)).start()
        result = self.rig.backend.submit_command(command(x_mm=350, y_mm=250))
        self.assertEqual(result["reason"], "car_tracking_lost")
        self.assertTrue(self.rig.wait_still(0.6))
        self.assertIsNone(self.rig.backend.poll_observation())     # no position the camera did not see


class BumpTests(unittest.TestCase):
    def test_bump_latches_until_reset_scene_rearms(self) -> None:
        rig = Rig(start=(-0.3, 0.0, 0.0), obstacle=(0.05, 0.0))
        self.addCleanup(rig.close)
        result = rig.backend.submit_command(command(x_mm=300, y_mm=0))
        self.assertEqual(result["reason"], "car_bump_stop")
        self.assertTrue(rig.backend.collision_detected)
        self.assertEqual(rig.backend.poll_observation().payload["state"], "emergency_stop")
        before = rig.car.pose()
        self.assertEqual(rig.backend.submit_command(command(x_mm=300, y_mm=0, key=2))["reason"], "car_bump_stop")
        self.assertLess(math.dist(before[:2], rig.car.pose()[:2]), 0.005)      # latched: no motion
        with self.assertRaises(BridgeError):
            rig.backend.reset_scene((-0.3, -0.2), (0.3, 0.25))                # obstacle not moved yet
        rig.car.obstacle = (0.3, 0.25)                                         # operator moves it
        rig.backend.reset_scene((-0.3, -0.2), (0.3, 0.25))
        self.assertFalse(rig.backend.collision_detected)
        x, y, _ = rig.car.pose()
        self.assertLess(math.hypot(x + 0.3, y + 0.2), 0.05)
        self.assertEqual(rig.backend.poll_observation().payload["state"], "available")


if __name__ == "__main__":
    unittest.main()
