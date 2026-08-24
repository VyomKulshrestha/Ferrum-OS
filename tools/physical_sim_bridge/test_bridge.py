from __future__ import annotations

from dataclasses import replace
import unittest

from tools.physical_sim_bridge.bridge import (
    ActuatorDisabledBackend,
    BridgeError,
    BridgePump,
    BridgeSession,
    GazeboRos2Backend,
    PyBulletBackend,
    ScriptedBackend,
    WebotsBackend,
)
from tools.physical_sim_bridge.protocol import (
    BridgeAck,
    BridgeCommand,
    BridgeHello,
    BridgeObservation,
    ProtocolError,
    decode_message,
)


def hello(*, actuator_enabled: bool = False) -> BridgeHello:
    return BridgeHello(7, 3, "scripted", 9, "ab" * 32, actuator_enabled)


def observation(sequence: int = 1) -> BridgeObservation:
    return BridgeObservation(
        run_id=7,
        simulator_epoch=3,
        adapter_id=1,
        endpoint_id=2,
        session_epoch=4,
        sequence=sequence,
        observed_at_tick=10 + sequence,
        source_clock_id=9,
        clock_uncertainty_ticks=0,
        frame_id=sequence,
        expires_at_tick=30,
        evidence_class="simulated",
        fault_manifest_id=0,
        fault_code=0,
        payload={
            "type": "sensor",
            "sensor_id": 11,
            "site_id": 1,
            "asset_id": None,
            "kind": "proximity_millimeters",
            "value": 900,
            "quality_permille": 1000,
            "observed_at_tick": 10 + sequence,
        },
    )


def command(key: int = 5) -> BridgeCommand:
    return BridgeCommand(
        run_id=7,
        command_id=4,
        idempotency_key=key,
        adapter_id=1,
        endpoint_id=2,
        session_epoch=4,
        kind="move_to",
        arguments=(100, 200, 0),
        issued_at_tick=10,
        deadline_tick=20,
        expected_policy_revision=2,
        expected_twin_event_id=8,
        confirmation_kind="local_human",
        confirmation_id=6,
        authority="ferrum_routed_command_v1",
    )


class ProtocolTests(unittest.TestCase):
    def test_hello_observation_and_command_round_trip_canonically(self) -> None:
        self.assertEqual(BridgeHello.parse(hello().to_wire()), hello())
        self.assertEqual(
            BridgeObservation.parse(observation().to_wire()), observation()
        )
        self.assertEqual(BridgeCommand.parse(command().to_wire()), command())
        self.assertEqual(command().to_wire(), command().to_wire())
        ack = BridgeAck(7, 4, 5, "accepted", 20, "simulated")
        self.assertEqual(BridgeAck.parse(ack.to_wire()), ack)

    def test_unknown_fields_nonfinite_numbers_and_boolean_ids_fail(self) -> None:
        value = decode_message(hello().to_wire())
        value["unknown"] = 1
        with self.assertRaises(ProtocolError):
            BridgeHello.parse(__import__("json").dumps(value))
        with self.assertRaises(ProtocolError):
            decode_message('{"value":NaN}')
        value = decode_message(observation().to_wire())
        value["adapter_id"] = True
        with self.assertRaises(ProtocolError):
            BridgeObservation.parse(__import__("json").dumps(value))

    def test_payload_clock_and_fault_provenance_are_consistent(self) -> None:
        value = decode_message(observation().to_wire())
        value["payload"]["observed_at_tick"] = 999
        with self.assertRaises(ProtocolError):
            BridgeObservation.parse(__import__("json").dumps(value))
        value = decode_message(observation().to_wire())
        value["fault_code"] = 2
        with self.assertRaises(ProtocolError):
            BridgeObservation.parse(__import__("json").dumps(value))

    def test_command_requires_routed_authority_and_consistent_confirmation(
        self,
    ) -> None:
        value = decode_message(command().to_wire())
        value["authority"] = "provider_output"
        with self.assertRaises(ProtocolError):
            BridgeCommand.parse(__import__("json").dumps(value))
        value = decode_message(command().to_wire())
        value["confirmation_kind"] = "not_required"
        with self.assertRaises(ProtocolError):
            BridgeCommand.parse(__import__("json").dumps(value))


class BridgeSessionTests(unittest.TestCase):
    def test_sequence_clock_and_run_identity_are_session_bound(self) -> None:
        backend = ScriptedBackend([observation(1), observation(2)])
        session = BridgeSession(hello(), backend)
        self.assertEqual(session.poll(), observation(1))
        self.assertEqual(session.poll(), observation(2))

        replay = BridgeSession(
            hello(), ScriptedBackend([observation(1), observation(1)])
        )
        replay.poll()
        with self.assertRaises(BridgeError):
            replay.poll()

        changed_clock = replace(observation(2), source_clock_id=10)
        clock = BridgeSession(hello(), ScriptedBackend([observation(1), changed_clock]))
        clock.poll()
        with self.assertRaises(BridgeError):
            clock.poll()

        wrong_run = replace(observation(), run_id=8)
        with self.assertRaises(BridgeError):
            BridgeSession(hello(), ScriptedBackend([wrong_run])).poll()

    def test_command_delivery_is_deadline_and_idempotency_bounded(self) -> None:
        backend = ScriptedBackend()
        session = BridgeSession(hello(), backend)
        self.assertTrue(session.submit(command(), 20)["executed"])
        with self.assertRaises(BridgeError):
            session.submit(command(), 20)
        with self.assertRaises(BridgeError):
            BridgeSession(hello(), ScriptedBackend()).submit(command(), 21)
        with self.assertRaises(BridgeError):
            BridgeSession(hello(), ScriptedBackend()).submit(
                replace(command(), run_id=8), 20
            )

    def test_hil_backend_records_but_never_executes(self) -> None:
        backend = ActuatorDisabledBackend(ScriptedBackend())
        session = BridgeSession(hello(), backend)
        result = session.submit(command(), 20)
        self.assertFalse(result["executed"])
        self.assertEqual(result["reason"], "actuator_disabled_hil")
        self.assertEqual(backend.commands, [command()])
        with self.assertRaises(BridgeError):
            BridgeSession(hello(actuator_enabled=True), backend)

    def test_optional_backends_fail_explicitly_when_dependencies_are_absent(
        self,
    ) -> None:
        try:
            GazeboRos2Backend()
        except BridgeError as error:
            self.assertIn("rclpy", str(error))
        try:
            WebotsBackend()
        except BridgeError as error:
            self.assertIn("Webots", str(error))

    def test_pybullet_direct_executes_only_a_simulated_command(self) -> None:
        backend = PyBulletBackend(run_id=7, simulator_epoch=3, source_clock_id=9)
        session = BridgeSession(
            BridgeHello(7, 3, "pybullet", 9, "ab" * 32, False), backend
        )
        try:
            first = session.poll()
            self.assertEqual(first.evidence_class, "simulated")
            result = session.submit(command(), 20)
            self.assertTrue(result["executed"])
            self.assertEqual(result["reason"], "pybullet_direct_simulation")
            self.assertIsNotNone(session.poll())
        finally:
            session.close()

    def test_transport_neutral_pump_uses_only_canonical_bytes(self) -> None:
        pump = BridgePump(BridgeSession(hello(), ScriptedBackend([observation()])))
        self.assertEqual(BridgeHello.parse(pump.hello_bytes()), hello())
        self.assertEqual(BridgeObservation.parse(pump.poll_bytes()), observation())
        ack = BridgeAck.parse(pump.submit_bytes(command().to_wire(), 20))
        self.assertEqual(ack.state, "accepted")
        self.assertEqual(ack.idempotency_key, command().idempotency_key)

    def test_uncertain_delivery_is_acknowledged_without_retry_authority(self) -> None:
        class FailingBackend(ScriptedBackend):
            def submit_command(self, value: BridgeCommand) -> dict[str, object]:
                raise RuntimeError("lost acknowledgement")

        pump = BridgePump(BridgeSession(hello(), FailingBackend()))
        ack = BridgeAck.parse(pump.submit_bytes(command().to_wire(), 20))
        self.assertEqual(ack.state, "uncertain")
        duplicate = BridgeAck.parse(pump.submit_bytes(command().to_wire(), 20))
        self.assertEqual(duplicate.state, "rejected")

        class PublishOnlyBackend(ScriptedBackend):
            def submit_command(self, value: BridgeCommand) -> dict[str, object]:
                return {
                    "command_id": value.command_id,
                    "executed": False,
                    "delivery_state": "uncertain",
                    "reason": "published_without_execution_ack",
                }

        publish_only = BridgePump(BridgeSession(hello(), PublishOnlyBackend()))
        ack = BridgeAck.parse(publish_only.submit_bytes(command(8).to_wire(), 20))
        self.assertEqual(ack.state, "uncertain")
        duplicate = BridgeAck.parse(publish_only.submit_bytes(command(8).to_wire(), 20))
        self.assertEqual(duplicate.state, "rejected")

    def test_closed_or_crashed_simulator_cannot_receive_new_authority(self) -> None:
        pump = BridgePump(BridgeSession(hello(), ScriptedBackend()))
        pump.session.close()
        ack = BridgeAck.parse(pump.submit_bytes(command().to_wire(), 20))
        self.assertEqual(ack.state, "rejected")
        with self.assertRaises(BridgeError):
            pump.poll_bytes()

        class CrashedBackend(ScriptedBackend):
            def poll_observation(self) -> BridgeObservation | None:
                raise RuntimeError("simulator stopped")

        crashed = BridgePump(BridgeSession(hello(), CrashedBackend()))
        with self.assertRaises(BridgeError):
            crashed.poll_bytes()
        self.assertEqual(
            BridgeAck.parse(crashed.submit_bytes(command(7).to_wire(), 20)).state,
            "rejected",
        )


if __name__ == "__main__":
    unittest.main()
