"""UDP JSON protocol between the host backend and the ESP32 car firmware.

One datagram per message, canonical JSON, exact key sets in both directions. The car
answers every authenticated command with a status datagram carrying the same sequence
number. Delivery is not guaranteed (UDP), so safety does not depend on it: every drive
command carries a time-to-live and the firmware stops the wheels when it expires, and a
pressed bump switch latches the wheels off until the host sends clear_bump.

Keep this file and firmware/ferrum_car/ferrum_car.ino in sync.
"""

from __future__ import annotations

import json
import socket
from typing import Any

PORT = 4210
MAX_PWM = 255
MAX_TTL_MS = 500
MAX_DATAGRAM = 512
OPS = {"drive", "stop", "clear_bump", "ping"}
COMMAND_KEYS = {"drive": {"op", "seq", "tok", "l", "r", "ttl_ms"}}
STATUS_KEYS = {"seq", "ack", "bump", "latched", "l", "r", "up_ms"}


class WireError(ValueError):
    """A datagram is malformed or outside the registered ranges."""


def _int(value: Any, name: str, lo: int, hi: int) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise WireError(f"{name} outside [{lo}, {hi}]")
    return value


def encode_command(op: str, seq: int, token: str, l: int = 0, r: int = 0, ttl_ms: int = 0) -> bytes:
    if op not in OPS:
        raise WireError(f"unknown op {op!r}")
    value: dict[str, Any] = {"op": op, "seq": _int(seq, "seq", 0, 2**31 - 1), "tok": token}
    if op == "drive":
        value.update(l=_int(l, "l", -MAX_PWM, MAX_PWM), r=_int(r, "r", -MAX_PWM, MAX_PWM),
                     ttl_ms=_int(ttl_ms, "ttl_ms", 1, MAX_TTL_MS))
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def decode_command(raw: bytes) -> dict[str, Any]:
    """Firmware-side parse (used by the mock car): exact keys per op."""
    value = _object(raw)
    op = value.get("op")
    if op not in OPS:
        raise WireError("unknown op")
    if set(value) != COMMAND_KEYS.get(op, {"op", "seq", "tok"}):
        raise WireError("command keys mismatch")
    _int(value["seq"], "seq", 0, 2**31 - 1)
    if not isinstance(value["tok"], str):
        raise WireError("token is not a string")
    if op == "drive":
        _int(value["l"], "l", -MAX_PWM, MAX_PWM)
        _int(value["r"], "r", -MAX_PWM, MAX_PWM)
        _int(value["ttl_ms"], "ttl_ms", 1, MAX_TTL_MS)
    return value


def encode_status(seq: int, ack: str, bump: bool, latched: bool, l: int, r: int, up_ms: int) -> bytes:
    value = {"seq": seq, "ack": ack, "bump": int(bump), "latched": int(latched), "l": l, "r": r, "up_ms": up_ms}
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def decode_status(raw: bytes) -> dict[str, Any]:
    value = _object(raw)
    if set(value) != STATUS_KEYS:
        raise WireError("status keys mismatch")
    if value["ack"] not in OPS:
        raise WireError("status acknowledges an unknown op")
    _int(value["seq"], "seq", 0, 2**31 - 1)
    _int(value["bump"], "bump", 0, 1)
    _int(value["latched"], "latched", 0, 1)
    _int(value["l"], "l", -MAX_PWM, MAX_PWM)
    _int(value["r"], "r", -MAX_PWM, MAX_PWM)
    _int(value["up_ms"], "up_ms", 0, 2**63 - 1)
    return value


def _object(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_DATAGRAM:
        raise WireError("datagram too long")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WireError("datagram is not ASCII JSON") from error
    if not isinstance(value, dict):
        raise WireError("datagram root must be an object")
    return value


class UdpLink:
    """Host side: send one command, wait briefly for the status with the same seq."""

    def __init__(self, host: str, token: str, port: int = PORT, timeout_s: float = 0.15) -> None:
        self.addr = (host, port)
        self.token = token
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout_s)
        self.seq = 0
        self.last_status: dict[str, Any] | None = None

    def send(self, op: str, l: int = 0, r: int = 0, ttl_ms: int = 0) -> dict[str, Any] | None:
        """Status dict, or None when no valid answer arrived in time (the command may still have landed)."""
        self.seq += 1
        self.sock.sendto(encode_command(op, self.seq, self.token, l, r, ttl_ms), self.addr)
        while True:
            try:
                raw, _ = self.sock.recvfrom(MAX_DATAGRAM + 1)
            except (socket.timeout, ConnectionResetError):
                return None
            try:
                status = decode_status(raw)
            except WireError:
                continue
            if status["seq"] == self.seq:
                self.last_status = status
                return status

    def drive(self, l: int, r: int, ttl_ms: int) -> dict[str, Any] | None:
        return self.send("drive", l, r, ttl_ms)

    def stop(self) -> dict[str, Any] | None:
        return self.send("stop")

    def clear_bump(self) -> dict[str, Any] | None:
        return self.send("clear_bump")

    def ping(self) -> dict[str, Any] | None:
        return self.send("ping")

    def close(self) -> None:
        self.sock.close()
