"""Backend-neutral bridge for scripted, Gazebo/ROS 2, Webots, and HIL sessions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
from typing import Any, Protocol

from .protocol import BridgeAck, BridgeCommand, BridgeHello, BridgeObservation, ProtocolError


MAX_SEEN_COMMANDS = 4_096


class BridgeError(RuntimeError):
    """The bridge session violated identity, ordering, or delivery rules."""


class BridgeRejected(BridgeError):
    """A command was deterministically rejected before backend delivery."""


class BridgeDeliveryUncertain(BridgeError):
    """The backend may have received a command but did not acknowledge it."""


class SimulatorBackend(Protocol):
    def poll_observation(self) -> BridgeObservation | None: ...

    def submit_command(self, command: BridgeCommand) -> dict[str, Any]: ...

    def close(self) -> None: ...


class ScriptedBackend:
    def __init__(self, observations: list[BridgeObservation] | None = None) -> None:
        self._observations = deque(observations or [])
        self.commands: list[BridgeCommand] = []

    def poll_observation(self) -> BridgeObservation | None:
        return self._observations.popleft() if self._observations else None

    def submit_command(self, command: BridgeCommand) -> dict[str, Any]:
        self.commands.append(command)
        return {"command_id": command.command_id, "executed": True, "reason": "simulated"}

    def close(self) -> None:
        self._observations.clear()


class ActuatorDisabledBackend:
    """HIL boundary that records commands but cannot energize an actuator."""

    def __init__(self, wrapped: SimulatorBackend) -> None:
        self.wrapped = wrapped
        self.commands: list[BridgeCommand] = []

    def poll_observation(self) -> BridgeObservation | None:
        return self.wrapped.poll_observation()

    def submit_command(self, command: BridgeCommand) -> dict[str, Any]:
        self.commands.append(command)
        return {
            "command_id": command.command_id,
            "executed": False,
            "reason": "actuator_disabled_hil",
        }

    def close(self) -> None:
        self.wrapped.close()


class GazeboRos2Backend:
    """Optional ROS 2 JSON-envelope connector for Gazebo-facing topics."""

    def __init__(
        self,
        observation_topic: str = "/ferrum/observations",
        command_topic: str = "/ferrum/commands",
    ) -> None:
        try:
            import rclpy
            from std_msgs.msg import String
        except ImportError as error:
            raise BridgeError("Gazebo ROS 2 backend requires rclpy and std_msgs") from error
        self._rclpy = rclpy
        self._string_type = String
        self._queue: deque[BridgeObservation] = deque()
        rclpy.init(args=None)
        self._node = rclpy.create_node("ferrum_physical_sim_bridge")
        self._publisher = self._node.create_publisher(String, command_topic, 10)
        self._subscription = self._node.create_subscription(
            String,
            observation_topic,
            self._on_observation,
            10,
        )

    def _on_observation(self, message: Any) -> None:
        self._queue.append(BridgeObservation.parse(message.data))

    def poll_observation(self) -> BridgeObservation | None:
        self._rclpy.spin_once(self._node, timeout_sec=0.0)
        return self._queue.popleft() if self._queue else None

    def submit_command(self, command: BridgeCommand) -> dict[str, Any]:
        message = self._string_type()
        message.data = command.to_wire().decode("ascii").strip()
        self._publisher.publish(message)
        return {"command_id": command.command_id, "executed": True, "reason": "published_ros2"}

    def close(self) -> None:
        self._node.destroy_node()
        self._rclpy.shutdown()


class WebotsBackend:
    """Optional Webots Receiver/Emitter connector using canonical JSON lines."""

    def __init__(self, receiver_name: str = "ferrum_rx", emitter_name: str = "ferrum_tx") -> None:
        try:
            from controller import Robot
        except ImportError as error:
            raise BridgeError("Webots backend requires the Webots controller module") from error
        self._robot = Robot()
        self._receiver = self._robot.getDevice(receiver_name)
        self._emitter = self._robot.getDevice(emitter_name)
        if self._receiver is None or self._emitter is None:
            raise BridgeError("Webots world does not expose the Ferrum Receiver/Emitter")
        self._receiver.enable(int(self._robot.getBasicTimeStep()))

    def poll_observation(self) -> BridgeObservation | None:
        if self._receiver.getQueueLength() == 0:
            self._robot.step(0)
            return None
        data = bytes(self._receiver.getBytes())
        self._receiver.nextPacket()
        return BridgeObservation.parse(data)

    def submit_command(self, command: BridgeCommand) -> dict[str, Any]:
        self._emitter.send(command.to_wire())
        return {"command_id": command.command_id, "executed": True, "reason": "sent_webots"}

    def close(self) -> None:
        self._receiver.disable()


@dataclass
class BridgeSession:
    hello: BridgeHello
    backend: SimulatorBackend

    def __post_init__(self) -> None:
        if self.hello.actuator_enabled and isinstance(self.backend, ActuatorDisabledBackend):
            raise BridgeError("hello claims actuator authority while HIL backend disables it")
        self._last_sequence: dict[int, int] = {}
        self._clock_by_adapter: dict[int, int] = {}
        self._seen_commands: set[int] = set()
        self._closed = False

    def poll(self) -> BridgeObservation | None:
        if self._closed:
            raise BridgeError("bridge session is closed")
        try:
            observation = self.backend.poll_observation()
        except Exception as error:
            self._closed = True
            raise BridgeError("simulator backend disconnected") from error
        if observation is None:
            return None
        if observation.run_id != self.hello.run_id:
            raise BridgeError("observation run identity changed")
        if observation.simulator_epoch != self.hello.simulator_epoch:
            raise BridgeError("observation simulator epoch changed")
        previous = self._last_sequence.get(observation.adapter_id, 0)
        if observation.sequence <= previous:
            raise BridgeError("observation sequence replayed or reordered")
        clock = self._clock_by_adapter.setdefault(
            observation.adapter_id, observation.source_clock_id
        )
        if clock != observation.source_clock_id:
            raise BridgeError("observation source clock changed within the session")
        self._last_sequence[observation.adapter_id] = observation.sequence
        return observation

    def submit(self, command: BridgeCommand, current_tick: int) -> dict[str, Any]:
        if self._closed:
            raise BridgeRejected("bridge session is closed")
        if command.run_id != self.hello.run_id:
            raise BridgeRejected("command run identity does not match the bridge session")
        if current_tick > command.deadline_tick:
            raise BridgeRejected("command expired before backend delivery")
        if command.idempotency_key in self._seen_commands:
            raise BridgeRejected("duplicate command idempotency key")
        if len(self._seen_commands) >= MAX_SEEN_COMMANDS:
            raise BridgeRejected("command replay journal is full")
        self._seen_commands.add(command.idempotency_key)
        try:
            return self.backend.submit_command(command)
        except Exception as error:
            # The backend may have received the command before raising. Retain
            # the idempotency claim and force external reconciliation.
            raise BridgeDeliveryUncertain("backend delivery is uncertain") from error

    def close(self) -> None:
        if not self._closed:
            self.backend.close()
            self._closed = True


@dataclass
class BridgePump:
    """Canonical byte boundary used by a vsock/network gateway.

    The pump deliberately has no socket ownership. Ferrum's host runner can use
    vsock, TCP, or a test pipe without changing validation or session state.
    """

    session: BridgeSession

    def hello_bytes(self) -> bytes:
        return self.session.hello.to_wire()

    def poll_bytes(self) -> bytes | None:
        observation = self.session.poll()
        return observation.to_wire() if observation is not None else None

    def submit_bytes(self, raw: bytes | str, current_tick: int) -> bytes:
        command = BridgeCommand.parse(raw)
        try:
            result = self.session.submit(command, current_tick)
            executed = bool(result.get("executed", False))
            state = "accepted" if executed else "actuator_disabled"
            reason = str(result.get("reason", "backend_acknowledged"))[:128]
        except BridgeRejected as error:
            state = "rejected"
            reason = str(error)[:128]
        except BridgeDeliveryUncertain:
            # The session keeps the idempotency claim. The caller must reconcile
            # rather than retry an action that may have reached the backend.
            state = "uncertain"
            reason = "backend_delivery_uncertain"
        return BridgeAck(
            run_id=self.session.hello.run_id,
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            state=state,
            observed_at_tick=current_tick,
            reason_code=reason,
        ).to_wire()


def parse_backend_observation(raw: str) -> BridgeObservation:
    """Helper used by ROS/Webots plugins before a message reaches a session."""
    try:
        return BridgeObservation.parse(raw)
    except (ProtocolError, json.JSONDecodeError) as error:
        raise BridgeError("backend emitted an invalid observation") from error
