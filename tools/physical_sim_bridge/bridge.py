"""Backend-neutral bridge for scripted, physics-simulator, and HIL sessions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
from typing import Any, Protocol

from .protocol import (
    BridgeAck,
    BridgeCommand,
    BridgeHello,
    BridgeObservation,
    ProtocolError,
)


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
        return {
            "command_id": command.command_id,
            "executed": True,
            "delivery_state": "accepted",
            "reason": "simulated",
        }

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
            "delivery_state": "actuator_disabled",
            "reason": "actuator_disabled_hil",
        }

    def close(self) -> None:
        self.wrapped.close()


class PyBulletBackend:
    """Headless PyBullet DIRECT backend for independently executed simulation."""

    def __init__(
        self,
        run_id: int,
        simulator_epoch: int = 1,
        source_clock_id: int = 1,
    ) -> None:
        try:
            import pybullet
        except ImportError as error:
            raise BridgeError("PyBullet backend requires pybullet") from error
        self._p = pybullet
        self._client = pybullet.connect(pybullet.DIRECT)
        if self._client < 0:
            raise BridgeError("PyBullet DIRECT connection failed")
        self.run_id = run_id
        self.simulator_epoch = simulator_epoch
        self.source_clock_id = source_clock_id
        self._sequence = 0
        self._tick = 0
        self._queue: deque[BridgeObservation] = deque()
        self._robot = -1
        self._obstacle = -1
        self.collision_detected = False
        self.commands: list[BridgeCommand] = []
        self.reset_scene((0.0, 0.0), (0.5, 0.0))

    def reset_scene(
        self,
        robot_xy: tuple[float, float],
        obstacle_xy: tuple[float, float],
    ) -> None:
        p = self._p
        p.resetSimulation(physicsClientId=self._client)
        p.setTimeStep(1.0 / 240.0, physicsClientId=self._client)
        robot_shape = p.createCollisionShape(
            p.GEOM_BOX, halfExtents=[0.08, 0.08, 0.08], physicsClientId=self._client
        )
        obstacle_shape = p.createCollisionShape(
            p.GEOM_BOX, halfExtents=[0.08, 0.08, 0.08], physicsClientId=self._client
        )
        self._robot = p.createMultiBody(
            baseMass=1.0,
            baseCollisionShapeIndex=robot_shape,
            basePosition=[robot_xy[0], robot_xy[1], 0.08],
            physicsClientId=self._client,
        )
        self._obstacle = p.createMultiBody(
            baseMass=0.0,
            baseCollisionShapeIndex=obstacle_shape,
            basePosition=[obstacle_xy[0], obstacle_xy[1], 0.08],
            physicsClientId=self._client,
        )
        self.collision_detected = False
        self._queue.clear()
        self._emit_actor_observation()

    def _emit_actor_observation(self) -> None:
        position, _ = self._p.getBasePositionAndOrientation(
            self._robot, physicsClientId=self._client
        )
        self._sequence += 1
        self._queue.append(
            BridgeObservation(
                run_id=self.run_id,
                simulator_epoch=self.simulator_epoch,
                adapter_id=1,
                endpoint_id=1,
                session_epoch=1,
                sequence=self._sequence,
                observed_at_tick=self._tick,
                source_clock_id=self.source_clock_id,
                clock_uncertainty_ticks=0,
                frame_id=self._sequence,
                expires_at_tick=self._tick + 240,
                evidence_class="simulated",
                fault_manifest_id=0,
                fault_code=0,
                payload={
                    "type": "actor",
                    "actor_id": 1,
                    "zone_id": 1,
                    "x_mm": int(round(position[0] * 1000)),
                    "y_mm": int(round(position[1] * 1000)),
                    "z_mm": int(round(position[2] * 1000)),
                    "battery_permille": 1000,
                    "load_permille": 0,
                    "state": "available",
                },
            )
        )

    def poll_observation(self) -> BridgeObservation | None:
        return self._queue.popleft() if self._queue else None

    def submit_command(self, command: BridgeCommand) -> dict[str, Any]:
        self.commands.append(command)
        if command.kind == "stop":
            self._p.resetBaseVelocity(
                self._robot, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], self._client
            )
        elif command.kind == "move_to":
            position, _ = self._p.getBasePositionAndOrientation(
                self._robot, physicsClientId=self._client
            )
            target = (command.arguments[0] / 1000.0, command.arguments[1] / 1000.0)
            velocity = [target[0] - position[0], target[1] - position[1], 0.0]
            self._p.resetBaseVelocity(
                self._robot, linearVelocity=velocity, physicsClientId=self._client
            )
            for _ in range(240):
                self._p.stepSimulation(physicsClientId=self._client)
                self._tick += 1
                if self._p.getContactPoints(
                    self._robot, self._obstacle, physicsClientId=self._client
                ):
                    self.collision_detected = True
            self._p.resetBaseVelocity(
                self._robot, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], self._client
            )
        else:
            return {
                "command_id": command.command_id,
                "executed": False,
                "delivery_state": "uncertain",
                "reason": "unsupported_pybullet_command",
            }
        self._emit_actor_observation()
        return {
            "command_id": command.command_id,
            "executed": True,
            "delivery_state": "accepted",
            "reason": "pybullet_direct_simulation",
        }

    def close(self) -> None:
        if self._client >= 0:
            self._p.disconnect(self._client)
            self._client = -1


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
            raise BridgeError(
                "Gazebo ROS 2 backend requires rclpy and std_msgs"
            ) from error
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
        return {
            "command_id": command.command_id,
            "executed": False,
            "delivery_state": "uncertain",
            "reason": "published_ros2_without_execution_ack",
        }

    def close(self) -> None:
        self._node.destroy_node()
        self._rclpy.shutdown()


class WebotsBackend:
    """Optional Webots Receiver/Emitter connector using canonical JSON lines."""

    def __init__(
        self, receiver_name: str = "ferrum_rx", emitter_name: str = "ferrum_tx"
    ) -> None:
        try:
            from controller import Robot
        except ImportError as error:
            raise BridgeError(
                "Webots backend requires the Webots controller module"
            ) from error
        self._robot = Robot()
        self._receiver = self._robot.getDevice(receiver_name)
        self._emitter = self._robot.getDevice(emitter_name)
        if self._receiver is None or self._emitter is None:
            raise BridgeError(
                "Webots world does not expose the Ferrum Receiver/Emitter"
            )
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
        return {
            "command_id": command.command_id,
            "executed": False,
            "delivery_state": "uncertain",
            "reason": "sent_webots_without_execution_ack",
        }

    def close(self) -> None:
        self._receiver.disable()


@dataclass
class BridgeSession:
    hello: BridgeHello
    backend: SimulatorBackend

    def __post_init__(self) -> None:
        if self.hello.actuator_enabled and isinstance(
            self.backend, ActuatorDisabledBackend
        ):
            raise BridgeError(
                "hello claims actuator authority while HIL backend disables it"
            )
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
            raise BridgeRejected(
                "command run identity does not match the bridge session"
            )
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
            state = str(result.get("delivery_state", ""))
            if state not in {"accepted", "actuator_disabled", "uncertain"}:
                state = "uncertain"
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
