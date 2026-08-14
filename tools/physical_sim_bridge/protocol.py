"""Strict JSON-line protocol shared by physics backends and Ferrum gateways."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Mapping


SCHEMA_VERSION = 1
MAX_MESSAGE_BYTES = 65_536
MAX_U64 = (1 << 64) - 1
MIN_I64 = -(1 << 63)
MAX_I64 = (1 << 63) - 1

EVIDENCE_CLASSES = {"simulated", "recorded_playback", "hardware_in_loop"}
COMMAND_KINDS = {
    "read_sensor",
    "set_output",
    "move_to",
    "stop",
    "display_instruction",
    "acknowledge",
}
ACK_STATES = {"accepted", "actuator_disabled", "uncertain", "rejected"}
SENSOR_KINDS = {
    "temperature_millicelsius",
    "vibration_micrometers_per_second",
    "pressure_pascal",
    "proximity_millimeters",
    "current_milliamp",
    "battery_permille",
}
ACTOR_STATES = {"available", "busy", "offline", "emergency_stop"}
ASSET_STATES = {"operational", "degraded", "offline", "maintenance"}


class ProtocolError(ValueError):
    """The peer supplied a malformed, ambiguous, or out-of-policy message."""


def encode_message(value: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise ProtocolError("message is not canonical JSON") from error
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message exceeds the bridge limit")
    return encoded + b"\n"


def decode_message(line: bytes | str) -> dict[str, Any]:
    raw = line.encode("utf-8") if isinstance(line, str) else line
    if len(raw) > MAX_MESSAGE_BYTES + 1:
        raise ProtocolError("message exceeds the bridge limit")
    try:
        text = raw.decode("utf-8").strip()
        value = json.loads(text, parse_constant=_reject_nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError("message is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ProtocolError("message root must be an object")
    _reject_nonfinite_tree(value)
    return value


def _reject_nonfinite(value: str) -> None:
    raise ProtocolError(f"non-finite number is forbidden: {value}")


def _reject_nonfinite_tree(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ProtocolError("non-finite number is forbidden")
    if isinstance(value, dict):
        for child in value.values():
            _reject_nonfinite_tree(child)
    elif isinstance(value, list):
        for child in value:
            _reject_nonfinite_tree(child)


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ProtocolError(
            f"{name} keys mismatch: missing={missing}, unknown={unknown}"
        )


def _integer(value: Any, name: str, minimum: int = 0, maximum: int = MAX_U64) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise ProtocolError(f"{name} is outside the registered integer range")
    return value


def _text(value: Any, name: str, allowed: set[str] | None = None) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ProtocolError(f"{name} is not a bounded string")
    if allowed is not None and value not in allowed:
        raise ProtocolError(f"{name} is not registered")
    return value


def _sha256(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ProtocolError(f"{name} is not a lowercase SHA-256 digest")
    return text


@dataclass(frozen=True)
class BridgeHello:
    run_id: int
    simulator_epoch: int
    backend: str
    source_clock_id: int
    topology_sha256: str
    actuator_enabled: bool = False

    @classmethod
    def parse(cls, line: bytes | str) -> "BridgeHello":
        value = decode_message(line)
        _exact_keys(
            value,
            {
                "type",
                "schema_version",
                "run_id",
                "simulator_epoch",
                "backend",
                "source_clock_id",
                "topology_sha256",
                "actuator_enabled",
            },
            "hello",
        )
        if value["type"] != "hello" or value["schema_version"] != SCHEMA_VERSION:
            raise ProtocolError("unsupported hello schema")
        if type(value["actuator_enabled"]) is not bool:
            raise ProtocolError("actuator_enabled must be boolean")
        return cls(
            run_id=_integer(value["run_id"], "run_id", 1),
            simulator_epoch=_integer(value["simulator_epoch"], "simulator_epoch", 1),
            backend=_text(
                value["backend"], "backend", {"scripted", "gazebo_ros2", "webots"}
            ),
            source_clock_id=_integer(value["source_clock_id"], "source_clock_id", 1),
            topology_sha256=_sha256(value["topology_sha256"], "topology_sha256"),
            actuator_enabled=value["actuator_enabled"],
        )

    def to_wire(self) -> bytes:
        return encode_message(
            {
                "type": "hello",
                "schema_version": SCHEMA_VERSION,
                "run_id": self.run_id,
                "simulator_epoch": self.simulator_epoch,
                "backend": self.backend,
                "source_clock_id": self.source_clock_id,
                "topology_sha256": self.topology_sha256,
                "actuator_enabled": self.actuator_enabled,
            }
        )


@dataclass(frozen=True)
class BridgeObservation:
    run_id: int
    simulator_epoch: int
    adapter_id: int
    endpoint_id: int
    session_epoch: int
    sequence: int
    observed_at_tick: int
    source_clock_id: int
    clock_uncertainty_ticks: int
    frame_id: int
    expires_at_tick: int
    evidence_class: str
    fault_manifest_id: int
    fault_code: int
    payload: dict[str, Any]

    @classmethod
    def parse(cls, line: bytes | str) -> "BridgeObservation":
        value = decode_message(line)
        _exact_keys(
            value,
            {
                "type",
                "schema_version",
                "run_id",
                "simulator_epoch",
                "adapter_id",
                "endpoint_id",
                "session_epoch",
                "sequence",
                "observed_at_tick",
                "source_clock_id",
                "clock_uncertainty_ticks",
                "frame_id",
                "expires_at_tick",
                "evidence_class",
                "fault_manifest_id",
                "fault_code",
                "payload",
            },
            "observation",
        )
        if value["type"] != "observation" or value["schema_version"] != SCHEMA_VERSION:
            raise ProtocolError("unsupported observation schema")
        payload = _validate_payload(value["payload"], value["observed_at_tick"])
        observation = cls(
            run_id=_integer(value["run_id"], "run_id", 1),
            simulator_epoch=_integer(value["simulator_epoch"], "simulator_epoch", 1),
            adapter_id=_integer(value["adapter_id"], "adapter_id", 1),
            endpoint_id=_integer(value["endpoint_id"], "endpoint_id", 1),
            session_epoch=_integer(value["session_epoch"], "session_epoch", 1),
            sequence=_integer(value["sequence"], "sequence", 1),
            observed_at_tick=_integer(value["observed_at_tick"], "observed_at_tick"),
            source_clock_id=_integer(value["source_clock_id"], "source_clock_id", 1),
            clock_uncertainty_ticks=_integer(
                value["clock_uncertainty_ticks"], "clock_uncertainty_ticks"
            ),
            frame_id=_integer(value["frame_id"], "frame_id", 1),
            expires_at_tick=_integer(value["expires_at_tick"], "expires_at_tick", 1),
            evidence_class=_text(
                value["evidence_class"], "evidence_class", EVIDENCE_CLASSES
            ),
            fault_manifest_id=_integer(value["fault_manifest_id"], "fault_manifest_id"),
            fault_code=_integer(value["fault_code"], "fault_code", 0, (1 << 32) - 1),
            payload=payload,
        )
        if observation.expires_at_tick < observation.observed_at_tick:
            raise ProtocolError("observation expires before it was observed")
        if (observation.fault_manifest_id == 0) != (observation.fault_code == 0):
            raise ProtocolError(
                "fault manifest and code must both be present or absent"
            )
        return observation

    def to_wire(self) -> bytes:
        return encode_message(
            {
                "type": "observation",
                "schema_version": SCHEMA_VERSION,
                **self.__dict__,
            }
        )


@dataclass(frozen=True)
class BridgeCommand:
    run_id: int
    command_id: int
    idempotency_key: int
    adapter_id: int
    endpoint_id: int
    session_epoch: int
    kind: str
    arguments: tuple[int, int, int]
    issued_at_tick: int
    deadline_tick: int
    expected_policy_revision: int
    expected_twin_event_id: int
    confirmation_kind: str
    confirmation_id: int
    authority: str

    @classmethod
    def parse(cls, line: bytes | str) -> "BridgeCommand":
        value = decode_message(line)
        _exact_keys(
            value,
            {
                "type",
                "schema_version",
                "run_id",
                "command_id",
                "idempotency_key",
                "adapter_id",
                "endpoint_id",
                "session_epoch",
                "kind",
                "arguments",
                "issued_at_tick",
                "deadline_tick",
                "expected_policy_revision",
                "expected_twin_event_id",
                "confirmation_kind",
                "confirmation_id",
                "authority",
            },
            "command",
        )
        if value["type"] != "command" or value["schema_version"] != SCHEMA_VERSION:
            raise ProtocolError("unsupported command schema")
        if value["authority"] != "ferrum_routed_command_v1":
            raise ProtocolError("command does not carry Ferrum routing authority")
        arguments = value["arguments"]
        if not isinstance(arguments, list) or len(arguments) != 3:
            raise ProtocolError("command requires exactly three bounded arguments")
        parsed_arguments = tuple(
            _integer(argument, f"arguments[{index}]", MIN_I64, MAX_I64)
            for index, argument in enumerate(arguments)
        )
        issued_at_tick = _integer(value["issued_at_tick"], "issued_at_tick")
        deadline_tick = _integer(value["deadline_tick"], "deadline_tick", 1)
        if issued_at_tick > deadline_tick:
            raise ProtocolError("command deadline precedes issuance")
        confirmation_kind = _text(
            value["confirmation_kind"],
            "confirmation_kind",
            {"not_required", "local_human", "external_supervisor"},
        )
        confirmation_id = _integer(value["confirmation_id"], "confirmation_id")
        if (confirmation_kind == "not_required") != (confirmation_id == 0):
            raise ProtocolError("confirmation provenance is inconsistent")
        return cls(
            run_id=_integer(value["run_id"], "run_id", 1),
            command_id=_integer(value["command_id"], "command_id", 1),
            idempotency_key=_integer(value["idempotency_key"], "idempotency_key", 1),
            adapter_id=_integer(value["adapter_id"], "adapter_id", 1),
            endpoint_id=_integer(value["endpoint_id"], "endpoint_id", 1),
            session_epoch=_integer(value["session_epoch"], "session_epoch", 1),
            kind=_text(value["kind"], "kind", COMMAND_KINDS),
            arguments=parsed_arguments,  # type: ignore[arg-type]
            issued_at_tick=issued_at_tick,
            deadline_tick=deadline_tick,
            expected_policy_revision=_integer(
                value["expected_policy_revision"], "expected_policy_revision"
            ),
            expected_twin_event_id=_integer(
                value["expected_twin_event_id"], "expected_twin_event_id"
            ),
            confirmation_kind=confirmation_kind,
            confirmation_id=confirmation_id,
            authority=value["authority"],
        )

    def to_wire(self) -> bytes:
        return encode_message(
            {
                "type": "command",
                "schema_version": SCHEMA_VERSION,
                **{
                    key: value
                    for key, value in self.__dict__.items()
                    if key != "arguments"
                },
                "arguments": list(self.arguments),
            }
        )


@dataclass(frozen=True)
class BridgeAck:
    run_id: int
    command_id: int
    idempotency_key: int
    state: str
    observed_at_tick: int
    reason_code: str

    @classmethod
    def parse(cls, line: bytes | str) -> "BridgeAck":
        value = decode_message(line)
        _exact_keys(
            value,
            {
                "type",
                "schema_version",
                "run_id",
                "command_id",
                "idempotency_key",
                "state",
                "observed_at_tick",
                "reason_code",
            },
            "acknowledgement",
        )
        if value["type"] != "ack" or value["schema_version"] != SCHEMA_VERSION:
            raise ProtocolError("unsupported acknowledgement schema")
        return cls(
            run_id=_integer(value["run_id"], "run_id", 1),
            command_id=_integer(value["command_id"], "command_id", 1),
            idempotency_key=_integer(value["idempotency_key"], "idempotency_key", 1),
            state=_text(value["state"], "state", ACK_STATES),
            observed_at_tick=_integer(value["observed_at_tick"], "observed_at_tick"),
            reason_code=_text(value["reason_code"], "reason_code"),
        )

    def to_wire(self) -> bytes:
        return encode_message(
            {
                "type": "ack",
                "schema_version": SCHEMA_VERSION,
                **self.__dict__,
            }
        )


def _validate_payload(value: Any, observed_at_tick: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("payload must be an object")
    payload_type = _text(value.get("type"), "payload.type")
    if payload_type == "sensor":
        _exact_keys(
            value,
            {
                "type",
                "sensor_id",
                "site_id",
                "asset_id",
                "kind",
                "value",
                "quality_permille",
                "observed_at_tick",
            },
            "sensor payload",
        )
        _integer(value["sensor_id"], "sensor_id", 1)
        _integer(value["site_id"], "site_id", 1)
        if value["asset_id"] is not None:
            _integer(value["asset_id"], "asset_id", 1)
        _text(value["kind"], "sensor.kind", SENSOR_KINDS)
        _integer(value["value"], "sensor.value", MIN_I64, MAX_I64)
        _integer(value["quality_permille"], "quality_permille", 0, 1_000)
        _integer(value["observed_at_tick"], "payload.observed_at_tick")
    elif payload_type == "actor":
        _exact_keys(
            value,
            {
                "type",
                "actor_id",
                "zone_id",
                "x_mm",
                "y_mm",
                "z_mm",
                "battery_permille",
                "load_permille",
                "state",
            },
            "actor payload",
        )
        _integer(value["actor_id"], "actor_id", 1)
        _integer(value["zone_id"], "zone_id")
        for axis in ("x_mm", "y_mm", "z_mm"):
            _integer(value[axis], axis, MIN_I64, MAX_I64)
        _integer(value["battery_permille"], "battery_permille", 0, 1_000)
        _integer(value["load_permille"], "load_permille", 0, 1_000)
        _text(value["state"], "actor.state", ACTOR_STATES)
    elif payload_type == "asset":
        _exact_keys(
            value,
            {"type", "asset_id", "zone_id", "x_mm", "y_mm", "z_mm", "state"},
            "asset payload",
        )
        _integer(value["asset_id"], "asset_id", 1)
        _integer(value["zone_id"], "zone_id")
        for axis in ("x_mm", "y_mm", "z_mm"):
            _integer(value[axis], axis, MIN_I64, MAX_I64)
        _text(value["state"], "asset.state", ASSET_STATES)
    elif payload_type == "occupancy":
        _exact_keys(
            value,
            {"type", "site_id", "zone_id", "humans", "robots", "observed_at_tick"},
            "occupancy payload",
        )
        _integer(value["site_id"], "site_id", 1)
        _integer(value["zone_id"], "zone_id")
        _integer(value["humans"], "humans", 0, (1 << 16) - 1)
        _integer(value["robots"], "robots", 0, (1 << 16) - 1)
        _integer(value["observed_at_tick"], "payload.observed_at_tick")
    elif payload_type == "emergency_stop":
        _exact_keys(value, {"type", "actor_id", "reason_code"}, "emergency payload")
        _integer(value["actor_id"], "actor_id", 1)
        _integer(value["reason_code"], "reason_code", 1, (1 << 32) - 1)
    else:
        raise ProtocolError("payload type is not registered")
    if "observed_at_tick" in value and value["observed_at_tick"] != observed_at_tick:
        raise ProtocolError("payload and envelope observation clocks differ")
    return dict(value)
