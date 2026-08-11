#!/usr/bin/env python3
"""Local-first neural acquisition, decoding and signed-intent gateway.

The default sources are deterministic synthetic and playback adapters. An
optional BrainFlow adapter is loaded only when that package is installed.
Raw samples remain on the host; FerrumOS receives only signed intent evidence.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import math
import os
import random
import socket
import struct
import sys
import time
import urllib.parse
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

WIRE_BYTES = 210
SIGNED_BYTES = 178
MAGIC = b"NIV1"
SCHEMA_VERSION = 1
KNOWN_ARTIFACT_MASK = 0x3F

PARADIGMS = {"ssvep": 0, "p300": 1, "motor-imagery": 2, "eog": 3, "emg": 4}
CLASSES = {"cancel": 0, "focus-left": 1, "focus-right": 2, "select": 3}
QUALITIES = {"good": 0, "degraded": 1, "reject": 2}
SCOPES = {"observe": 0, "navigate": 1, "safe-desktop": 2, "physical-goal": 3}
ARTIFACTS = {
    "blink": 1 << 0,
    "muscle": 1 << 1,
    "saturation": 1 << 2,
    "contact": 1 << 3,
    "motion": 1 << 4,
    "line-noise": 1 << 5,
}


class NeurodError(ValueError):
    """A validation or acquisition failure that must result in abstention."""


@dataclass(frozen=True)
class Sample:
    monotonic_ns: int
    channels_uv: tuple[float, ...]
    marker: int = 0


@dataclass(frozen=True)
class SignalHealth:
    quality: str
    artifact_flags: int
    rms_uv: float
    peak_uv: float
    flat_channel_count: int
    dropped_samples: int


@dataclass(frozen=True)
class DecodeResult:
    label: str | None
    posterior_permille: int
    margin_permille: int
    dwell_windows: int
    frequency_hz: float | None
    health: SignalHealth

    @property
    def abstained(self) -> bool:
        return self.label is None


class BoundedSampleBuffer:
    """Fixed-capacity buffer that counts overflow rather than growing memory."""

    def __init__(self, capacity: int, channel_count: int):
        if capacity < 2 or not 1 <= channel_count <= 32:
            raise NeurodError("invalid buffer shape")
        self.capacity = capacity
        self.channel_count = channel_count
        self._samples: deque[Sample] = deque(maxlen=capacity)
        self.dropped_samples = 0

    def append(self, sample: Sample) -> None:
        if len(sample.channels_uv) != self.channel_count:
            raise NeurodError("channel count changed within a session")
        if self._samples and sample.monotonic_ns <= self._samples[-1].monotonic_ns:
            raise NeurodError("sample clock is non-monotonic")
        if len(self._samples) == self.capacity:
            self.dropped_samples += 1
        self._samples.append(sample)

    def snapshot(self) -> tuple[Sample, ...]:
        return tuple(self._samples)

    def __len__(self) -> int:
        return len(self._samples)


class SyntheticBoard:
    """Deterministic SSVEP-like fixture source, never labelled as human EEG."""

    def __init__(self, sample_rate_hz: int = 250, channel_count: int = 8, seed: int = 42):
        if sample_rate_hz <= 0 or not 1 <= channel_count <= 32:
            raise NeurodError("invalid synthetic board configuration")
        self.sample_rate_hz = sample_rate_hz
        self.channel_count = channel_count
        self._rng = random.Random(seed)

    def acquire(
        self,
        seconds: float,
        stimulus_hz: float | None,
        start_ns: int = 1_000_000_000,
        noise_uv: float = 2.0,
        fault: str | None = None,
    ) -> list[Sample]:
        count = max(1, int(seconds * self.sample_rate_hz))
        step_ns = int(1_000_000_000 / self.sample_rate_hz)
        samples: list[Sample] = []
        for index in range(count):
            if fault == "dropout" and index % 7 == 0:
                continue
            t = index / self.sample_rate_hz
            channels = []
            for channel in range(self.channel_count):
                phase = channel * 0.07
                signal = 0.0 if stimulus_hz is None else 18.0 * math.sin(2 * math.pi * stimulus_hz * t + phase)
                harmonic = 0.0 if stimulus_hz is None else 5.0 * math.sin(4 * math.pi * stimulus_hz * t + phase)
                value = signal + harmonic + self._rng.gauss(0.0, noise_uv)
                if fault == "saturation" and index > count // 2:
                    value = 500.0
                elif fault == "blink" and count // 3 <= index < count // 3 + 8:
                    value += 220.0
                elif fault == "line-noise":
                    value += 35.0 * math.sin(2 * math.pi * 50.0 * t)
                channels.append(value)
            samples.append(Sample(start_ns + index * step_ns, tuple(channels)))
        return samples


class PlaybackBoard:
    """Strict CSV playback source: monotonic_ns,ch0,...,chN[,marker]."""

    def __init__(self, path: Path, channel_count: int):
        self.path = Path(path)
        self.channel_count = channel_count

    def acquire(self) -> list[Sample]:
        samples: list[Sample] = []
        with self.path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            expected = {"monotonic_ns", *(f"ch{i}" for i in range(self.channel_count))}
            if not reader.fieldnames or not expected.issubset(reader.fieldnames):
                raise NeurodError("playback CSV schema mismatch")
            for row in reader:
                samples.append(
                    Sample(
                        int(row["monotonic_ns"]),
                        tuple(float(row[f"ch{i}"]) for i in range(self.channel_count)),
                        int(row.get("marker") or 0),
                    )
                )
        if len(samples) < 2:
            raise NeurodError("playback requires at least two samples")
        for previous, current in zip(samples, samples[1:]):
            if current.monotonic_ns <= previous.monotonic_ns:
                raise NeurodError("playback clock is non-monotonic")
        return samples


class BrainFlowBoard:
    """Optional real-board adapter with an explicit dependency boundary."""

    def __init__(self, board_id: int, serial_port: str, channel_count: int):
        try:
            from brainflow.board_shim import BoardShim, BrainFlowInputParams  # type: ignore
        except ImportError as exc:
            raise NeurodError("BrainFlow is not installed; use synthetic/playback or install brainflow") from exc
        params = BrainFlowInputParams()
        params.serial_port = serial_port
        self._board = BoardShim(board_id, params)
        self._board_id = board_id
        self._board_shim = BoardShim
        self.channel_count = channel_count

    def acquire(self, seconds: float) -> list[Sample]:
        self._board.prepare_session()
        try:
            self._board.start_stream()
            time.sleep(seconds)
            data = self._board.get_board_data()
        finally:
            self._board.stop_stream()
            self._board.release_session()
        eeg_rows = self._board_shim.get_eeg_channels(self._board_id)[: self.channel_count]
        timestamp_row = self._board_shim.get_timestamp_channel(self._board_id)
        samples = []
        for column in range(data.shape[1]):
            channels = tuple(float(data[row][column]) for row in eeg_rows)
            samples.append(Sample(int(float(data[timestamp_row][column]) * 1e9), channels))
        return samples


def assess_signal(samples: Sequence[Sample], dropped_samples: int = 0) -> SignalHealth:
    if len(samples) < 8:
        return SignalHealth("reject", ARTIFACTS["contact"], 0.0, 0.0, 0, dropped_samples)
    intervals = [current.monotonic_ns - previous.monotonic_ns for previous, current in zip(samples, samples[1:])]
    ordered_intervals = sorted(intervals)
    median_interval = ordered_intervals[len(ordered_intervals) // 2]
    inferred_drops = 0
    if median_interval > 0:
        inferred_drops = sum(max(0, round(interval / median_interval) - 1) for interval in intervals)
    dropped_samples += inferred_drops
    values = [value for sample in samples for value in sample.channels_uv]
    rms = math.sqrt(sum(value * value for value in values) / len(values))
    peak = max(abs(value) for value in values)
    channel_count = len(samples[0].channels_uv)
    flat = 0
    for channel in range(channel_count):
        channel_values = [sample.channels_uv[channel] for sample in samples]
        mean = sum(channel_values) / len(channel_values)
        variance = sum((value - mean) ** 2 for value in channel_values) / len(channel_values)
        flat += variance < 0.25
    flags = 0
    if peak >= 400.0:
        flags |= ARTIFACTS["saturation"]
    elif peak >= 180.0:
        flags |= ARTIFACTS["blink"]
    if flat:
        flags |= ARTIFACTS["contact"]
    if dropped_samples:
        flags |= ARTIFACTS["contact"]
    if median_interval > 0:
        sample_rate_hz = 1_000_000_000 / median_interval
        aggregate = [sum(sample.channels_uv) / channel_count for sample in samples]
        aggregate_mean = sum(aggregate) / len(aggregate)
        centered = [value - aggregate_mean for value in aggregate]
        total_energy = sum(value * value for value in centered)
        sine = sum(value * math.sin(2 * math.pi * 50.0 * index / sample_rate_hz) for index, value in enumerate(centered))
        cosine = sum(value * math.cos(2 * math.pi * 50.0 * index / sample_rate_hz) for index, value in enumerate(centered))
        line_ratio = 2.0 * (sine * sine + cosine * cosine) / (len(centered) * total_energy) if total_energy else 0.0
        if line_ratio >= 0.45:
            flags |= ARTIFACTS["line-noise"]
    quality = "reject" if flags or rms < 0.5 or rms > 150.0 else "good"
    return SignalHealth(quality, flags, rms, peak, flat, dropped_samples)


class SsvepDecoder:
    """Registered classical frequency-projection baseline with abstention."""

    def __init__(
        self,
        sample_rate_hz: int,
        targets: dict[str, float] | None = None,
        minimum_posterior: float = 0.80,
        minimum_margin: float = 0.15,
        required_dwell_windows: int = 3,
    ):
        self.sample_rate_hz = sample_rate_hz
        self.targets = targets or {"focus-left": 8.0, "focus-right": 10.0, "select": 12.0, "cancel": 15.0}
        self.minimum_posterior = minimum_posterior
        self.minimum_margin = minimum_margin
        self.required_dwell_windows = required_dwell_windows
        self._last_label: str | None = None
        self._dwell = 0

    def decode(self, samples: Sequence[Sample], dropped_samples: int = 0) -> DecodeResult:
        health = assess_signal(samples, dropped_samples)
        if health.quality != "good":
            self._last_label = None
            self._dwell = 0
            return DecodeResult(None, 0, 0, 0, None, health)
        aggregate = [sum(sample.channels_uv) / len(sample.channels_uv) for sample in samples]
        mean = sum(aggregate) / len(aggregate)
        centered = [value - mean for value in aggregate]
        energies: dict[str, float] = {}
        for label, frequency in self.targets.items():
            sine = sum(value * math.sin(2 * math.pi * frequency * i / self.sample_rate_hz) for i, value in enumerate(centered))
            cosine = sum(value * math.cos(2 * math.pi * frequency * i / self.sample_rate_hz) for i, value in enumerate(centered))
            harmonic_sine = sum(value * math.sin(4 * math.pi * frequency * i / self.sample_rate_hz) for i, value in enumerate(centered))
            harmonic_cosine = sum(value * math.cos(4 * math.pi * frequency * i / self.sample_rate_hz) for i, value in enumerate(centered))
            energies[label] = sine * sine + cosine * cosine + 0.25 * (harmonic_sine * harmonic_sine + harmonic_cosine * harmonic_cosine)
        ranked = sorted(energies.items(), key=lambda item: item[1], reverse=True)
        total = sum(energies.values()) or 1.0
        label, best = ranked[0]
        second = ranked[1][1]
        posterior = best / total
        margin = (best - second) / total
        if label == self._last_label:
            self._dwell += 1
        else:
            self._last_label = label
            self._dwell = 1
        accepted = posterior >= self.minimum_posterior and margin >= self.minimum_margin and self._dwell >= self.required_dwell_windows
        return DecodeResult(
            label if accepted else None,
            min(1000, round(posterior * 1000)),
            min(1000, round(margin * 1000)),
            self._dwell,
            self.targets[label],
            health,
        )


def derive_session_material(pairing_token: bytes) -> tuple[bytes, bytes]:
    if len(pairing_token) < 16:
        raise NeurodError("pairing token must contain at least 16 bytes")
    key = hashlib.sha256(b"ferrum-neural-key-v1\0" + pairing_token).digest()
    session_id = hashlib.sha256(b"ferrum-neural-session-v1\0" + pairing_token).digest()[:16]
    return key, session_id


@dataclass(frozen=True)
class IntentEvidence:
    label: str
    scope: str
    sequence: int
    window_start_ns: int
    window_end_ns: int
    expires_at_ns: int
    session_id: bytes
    intent_id: bytes
    decoder_version: bytes
    calibration_id: bytes
    subject_key: bytes
    focus_revision: int
    state_revision: int
    posterior_permille: int
    margin_permille: int
    dwell_windows: int
    quality: str = "good"
    artifact_flags: int = 0
    paradigm: str = "ssvep"

    def validate(self) -> None:
        for value, size, name in (
            (self.session_id, 16, "session_id"),
            (self.intent_id, 16, "intent_id"),
            (self.decoder_version, 32, "decoder_version"),
            (self.calibration_id, 32, "calibration_id"),
            (self.subject_key, 16, "subject_key"),
        ):
            if len(value) != size or not any(value):
                raise NeurodError(f"invalid {name}")
        if self.label not in CLASSES or self.scope not in SCOPES or self.quality not in QUALITIES or self.paradigm not in PARADIGMS:
            raise NeurodError("unknown intent enum")
        if self.artifact_flags & ~KNOWN_ARTIFACT_MASK:
            raise NeurodError("unknown artifact flag")
        if not (0 <= self.posterior_permille <= 1000 and 0 <= self.margin_permille <= 1000):
            raise NeurodError("invalid probability")
        if not self.window_start_ns < self.window_end_ns < self.expires_at_ns:
            raise NeurodError("invalid intent time window")


def sign_intent(evidence: IntentEvidence, key: bytes) -> bytes:
    evidence.validate()
    if len(key) < 16:
        raise NeurodError("signing key is too short")
    wire = bytearray(WIRE_BYTES)
    wire[:4] = MAGIC
    struct.pack_into("<HBBBBHBBHHQQQQ", wire, 4, SCHEMA_VERSION, PARADIGMS[evidence.paradigm], CLASSES[evidence.label], QUALITIES[evidence.quality], SCOPES[evidence.scope], evidence.artifact_flags, evidence.dwell_windows, 0, evidence.posterior_permille, evidence.margin_permille, evidence.sequence, evidence.window_start_ns, evidence.window_end_ns, evidence.expires_at_ns)
    wire[50:66] = evidence.session_id
    wire[66:82] = evidence.intent_id
    wire[82:114] = evidence.decoder_version
    wire[114:146] = evidence.calibration_id
    wire[146:162] = evidence.subject_key
    struct.pack_into("<QQ", wire, 162, evidence.focus_revision, evidence.state_revision)
    wire[SIGNED_BYTES:] = hmac.new(key, wire[:SIGNED_BYTES], hashlib.sha256).digest()
    return bytes(wire)


class ConsentRecorder:
    """Writes a minimal BIDS-shaped local recording only with explicit consent."""

    def __init__(self, root: Path, subject_key: str, consent: bool):
        if not consent:
            raise NeurodError("recording requires --i-consent-to-local-recording")
        if not subject_key or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for character in subject_key):
            raise NeurodError("subject key must be a non-identifying alphanumeric pseudonym")
        self.root = Path(root)
        self.subject_key = subject_key

    def write(
        self,
        samples: Sequence[Sample],
        sample_rate_hz: int,
        events: Sequence[tuple[float, str]] = (),
        source_kind: str = "human",
    ) -> Path:
        if not samples:
            raise NeurodError("cannot record an empty session")
        if source_kind not in {"human", "synthetic", "playback"}:
            raise NeurodError("recording source must be human, synthetic, or playback")
        eeg_dir = self.root / f"sub-{self.subject_key}" / "eeg"
        eeg_dir.mkdir(parents=True, exist_ok=True)
        (self.root / "dataset_description.json").write_text(
            json.dumps({"Name": "FerrumOS local neural recording", "BIDSVersion": "1.9.0", "DatasetType": "raw"}, indent=2) + "\n",
            encoding="utf-8",
        )
        (self.root / "participants.tsv").write_text("participant_id\nsub-" + self.subject_key + "\n", encoding="utf-8")
        stem = f"sub-{self.subject_key}_task-ferrum_eeg"
        data_path = eeg_dir / f"{stem}.tsv"
        with data_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["monotonic_ns", *(f"ch{i}_uv" for i in range(len(samples[0].channels_uv))), "marker"])
            for sample in samples:
                writer.writerow([sample.monotonic_ns, *sample.channels_uv, sample.marker])
        (eeg_dir / f"{stem}.json").write_text(
            json.dumps(
                {
                    "SamplingFrequency": sample_rate_hz,
                    "PowerLineFrequency": 50,
                    "RecordingType": "continuous",
                    "FerrumSourceKind": source_kind,
                    "FerrumSynthetic": source_kind == "synthetic",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        with (eeg_dir / f"sub-{self.subject_key}_task-ferrum_events.tsv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["onset", "trial_type"])
            writer.writerows(events)
        return data_path


class JsonRpcWebSocket:
    """Small dependency-free WebSocket client for FerrumOS's local bridge."""

    def __init__(self, url: str, timeout_seconds: float = 5.0):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "ws" or not parsed.hostname:
            raise NeurodError("bridge URL must use ws:// with an explicit host")
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self.path = parsed.path or "/"
        self.timeout_seconds = timeout_seconds
        self._socket: socket.socket | None = None
        self._request_id = 0

    def connect(self) -> None:
        if self._socket is not None:
            raise NeurodError("bridge is already connected")
        stream = socket.create_connection((self.host, self.port), timeout=self.timeout_seconds)
        stream.settimeout(self.timeout_seconds)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        stream.sendall(request.encode("ascii"))
        response = self._receive_until(stream, b"\r\n\r\n", 16_384)
        header = response.decode("ascii", errors="strict")
        expected_accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if not header.startswith("HTTP/1.1 101 ") or f"Sec-WebSocket-Accept: {expected_accept}".lower() not in header.lower():
            stream.close()
            raise NeurodError("bridge WebSocket upgrade was rejected")
        self._socket = stream

    @staticmethod
    def _receive_until(stream: socket.socket, marker: bytes, maximum: int) -> bytes:
        received = bytearray()
        while marker not in received:
            chunk = stream.recv(4096)
            if not chunk:
                raise NeurodError("bridge closed during handshake")
            received.extend(chunk)
            if len(received) > maximum:
                raise NeurodError("bridge handshake exceeded size limit")
        return bytes(received)

    @staticmethod
    def encode_client_frame(payload: bytes, mask: bytes) -> bytes:
        if len(mask) != 4:
            raise NeurodError("WebSocket mask must be four bytes")
        length = len(payload)
        if length < 126:
            header = bytes((0x81, 0x80 | length))
        elif length <= 65_535:
            header = bytes((0x81, 0xFE)) + struct.pack(">H", length)
        else:
            header = bytes((0x81, 0xFF)) + struct.pack(">Q", length)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return header + mask + masked

    @staticmethod
    def _receive_exact(stream: socket.socket, count: int) -> bytes:
        result = bytearray()
        while len(result) < count:
            chunk = stream.recv(count - len(result))
            if not chunk:
                raise NeurodError("bridge disconnected")
            result.extend(chunk)
        return bytes(result)

    def _receive_frame(self) -> bytes:
        if self._socket is None:
            raise NeurodError("bridge is not connected")
        first, second = self._receive_exact(self._socket, 2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._receive_exact(self._socket, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._receive_exact(self._socket, 8))[0]
        if length > 1_048_576:
            raise NeurodError("bridge frame exceeded 1 MiB limit")
        mask = self._receive_exact(self._socket, 4) if masked else b""
        payload = self._receive_exact(self._socket, length)
        if masked:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        if opcode == 0x8:
            raise NeurodError("bridge closed the WebSocket")
        if opcode != 0x1 or not (first & 0x80):
            raise NeurodError("bridge returned an unsupported WebSocket frame")
        return payload

    def rpc(self, method: str, params: dict[str, object] | None = None) -> object:
        if self._socket is None:
            raise NeurodError("bridge is not connected")
        self._request_id += 1
        request: dict[str, object] = {"jsonrpc": "2.0", "method": method, "id": self._request_id}
        if params is not None:
            request["params"] = params
        payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
        self._socket.sendall(self.encode_client_frame(payload, os.urandom(4)))
        try:
            response = json.loads(self._receive_frame().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NeurodError("bridge returned invalid JSON") from exc
        if response.get("id") != self._request_id:
            raise NeurodError("bridge response id mismatch")
        if "error" in response:
            error = response["error"]
            message = error.get("message", "RPC failed") if isinstance(error, dict) else "RPC failed"
            raise NeurodError(f"bridge RPC error: {message}")
        if "result" not in response:
            raise NeurodError("bridge response omitted result")
        return response["result"]

    def close(self) -> None:
        stream = self._socket
        self._socket = None
        if stream is not None:
            try:
                stream.sendall(bytes((0x88, 0x80)) + b"\0\0\0\0")
            finally:
                stream.close()

    def __enter__(self) -> "JsonRpcWebSocket":
        self.connect()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


def build_intent_from_decode(
    result: DecodeResult,
    pairing_token: bytes,
    calibration_id: bytes,
    subject_key: bytes,
    sequence: int,
    focus_revision: int,
    state_revision: int,
    scope: str,
    window_start_ns: int,
    window_end_ns: int,
) -> bytes:
    if result.abstained:
        raise NeurodError("decoder abstained; no intent may be emitted")
    key, session_id = derive_session_material(pairing_token)
    evidence = IntentEvidence(
        label=result.label or "cancel",
        scope=scope,
        sequence=sequence,
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
        expires_at_ns=window_end_ns + 1_500_000_000,
        session_id=session_id,
        intent_id=hashlib.sha256(session_id + sequence.to_bytes(8, "little") + window_end_ns.to_bytes(8, "little")).digest()[:16],
        decoder_version=hashlib.sha256(b"ferrum-neurod-ssvep-v1").digest(),
        calibration_id=calibration_id,
        subject_key=subject_key,
        focus_revision=focus_revision,
        state_revision=state_revision,
        posterior_permille=result.posterior_permille,
        margin_permille=result.margin_permille,
        dwell_windows=result.dwell_windows,
        quality=result.health.quality,
        artifact_flags=result.health.artifact_flags,
    )
    return sign_intent(evidence, key)


def run_synthetic(args: argparse.Namespace) -> dict[str, object]:
    board = SyntheticBoard(args.sample_rate, args.channels, args.seed)
    decoder = SsvepDecoder(args.sample_rate, required_dwell_windows=args.dwell)
    result: DecodeResult | None = None
    samples: list[Sample] = []
    for window in range(args.windows):
        acquired = board.acquire(args.seconds, args.frequency, 1_000_000_000 + window * int(args.seconds * 1e9), args.noise, args.fault)
        buffer = BoundedSampleBuffer(max(8, int(args.seconds * args.sample_rate)), args.channels)
        for sample in acquired:
            buffer.append(sample)
        samples = list(buffer.snapshot())
        result = decoder.decode(samples, buffer.dropped_samples)
    assert result is not None
    output: dict[str, object] = {"source": "synthetic", "result": asdict(result), "sample_count": len(samples)}
    if not result.abstained and args.pairing_token:
        calibration_id = hashlib.sha256(args.calibration_id.encode()).digest()
        subject_key = hashlib.sha256(args.subject.encode()).digest()[:16]
        wire = build_intent_from_decode(
            result,
            args.pairing_token.encode(),
            calibration_id,
            subject_key,
            args.sequence,
            args.focus_revision,
            args.state_revision,
            args.scope,
            samples[0].monotonic_ns,
            samples[-1].monotonic_ns,
        )
        output["intent_hex"] = wire.hex()
        output["calibration_id_hex"] = calibration_id.hex()
        output["session_id_hex"] = derive_session_material(args.pairing_token.encode())[1].hex()
    return output


def run_bridge_synthetic(args: argparse.Namespace) -> dict[str, object]:
    """Pair, calibrate, wait for a local non-neural arm, then preview one intent."""

    token_text = args.pairing_token or os.environ.get("FERRUM_NEURAL_PAIRING_TOKEN", "")
    if len(token_text) != 32 or any(character not in "0123456789abcdefABCDEF" for character in token_text):
        raise NeurodError("set a 32-hex pairing token via --pairing-token or FERRUM_NEURAL_PAIRING_TOKEN")
    token = token_text.encode("ascii")
    calibration_id = hashlib.sha256(args.calibration_id.encode("utf-8")).digest()
    board = SyntheticBoard(args.sample_rate, args.channels, args.seed)
    decoder = SsvepDecoder(args.sample_rate, required_dwell_windows=args.dwell)
    result: DecodeResult | None = None
    for window in range(args.windows):
        samples = board.acquire(
            args.seconds,
            args.frequency,
            1_000_000_000 + window * int(args.seconds * 1e9),
            args.noise,
            args.fault,
        )
        result = decoder.decode(samples)
    assert result is not None
    if result.abstained:
        raise NeurodError("decoder abstained; nothing was sent to FerrumOS")

    with JsonRpcWebSocket(args.url, args.timeout) as bridge:
        paired = bridge.rpc("pair", {"token": token_text, "control_mode": args.control_mode})
        if not isinstance(paired, dict) or paired.get("authorized") is not True:
            raise NeurodError("bridge pairing did not authorize the session")
        bridge.rpc(
            "neural_calibrate",
            {
                "transport": "synthetic",
                "sample_rate_hz": args.sample_rate,
                "channel_count": args.channels,
                "calibration_id_hex": calibration_id.hex(),
            },
        )
        deadline = time.monotonic() + args.wait_for_arm
        print("neurod: calibrated; run 'heliox neural arm' at the FerrumOS console", file=sys.stderr)
        status: object = bridge.rpc("neural_status")
        while isinstance(status, dict) and status.get("state") != "armed_safe_ui" and time.monotonic() < deadline:
            time.sleep(0.2)
            status = bridge.rpc("neural_status")
        if not isinstance(status, dict) or status.get("state") != "armed_safe_ui":
            bridge.rpc("neural_disarm")
            raise NeurodError("timed out waiting for the local 'heliox neural arm' command")
        now_ns = int(status["monotonic_ns"])
        window_end_ns = max(2, now_ns - 10_000_000)
        wire = build_intent_from_decode(
            result,
            token,
            calibration_id,
            hashlib.sha256(args.subject.encode("utf-8")).digest()[:16],
            args.sequence,
            int(status["focus_revision"]),
            int(status["state_revision"]),
            args.scope,
            max(1, window_end_ns - min(1_000_000_000, int(args.seconds * 1e9))),
            window_end_ns,
        )
        preview = bridge.rpc("neural_intent_preview", {"intent_hex": wire.hex()})
        output: dict[str, object] = {
            "source": "synthetic",
            "synthetic_only": True,
            "result": asdict(result),
            "preview": preview,
            "committed": False,
        }
        if args.commit:
            output["commit"] = bridge.rpc("neural_intent_commit", {"intent_id": wire[66:82].hex()})
            output["committed"] = True
        else:
            bridge.rpc("neural_disarm")
        return output


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    subcommands = command.add_subparsers(dest="command", required=True)
    synthetic = subcommands.add_parser("synthetic", help="decode deterministic synthetic SSVEP fixtures")
    synthetic.add_argument("--frequency", type=float, default=12.0)
    synthetic.add_argument("--sample-rate", type=int, default=250)
    synthetic.add_argument("--channels", type=int, default=8)
    synthetic.add_argument("--seconds", type=float, default=1.0)
    synthetic.add_argument("--windows", type=int, default=3)
    synthetic.add_argument("--dwell", type=int, default=3)
    synthetic.add_argument("--noise", type=float, default=2.0)
    synthetic.add_argument("--fault", choices=["dropout", "saturation", "blink", "line-noise"])
    synthetic.add_argument("--seed", type=int, default=42)
    synthetic.add_argument("--pairing-token")
    synthetic.add_argument("--calibration-id", default="synthetic-calibration-v1")
    synthetic.add_argument("--subject", default="synthetic-fixture")
    synthetic.add_argument("--sequence", type=int, default=1)
    synthetic.add_argument("--focus-revision", type=int, default=0)
    synthetic.add_argument("--state-revision", type=int, default=0)
    synthetic.add_argument("--scope", choices=sorted(SCOPES), default="navigate")
    bridge = subcommands.add_parser(
        "bridge-synthetic",
        help="preview a synthetic fixture through the paired FerrumOS bridge",
    )
    bridge.add_argument("--url", default="ws://127.0.0.1:8785/")
    bridge.add_argument("--pairing-token", help="prefer FERRUM_NEURAL_PAIRING_TOKEN to avoid shell history")
    bridge.add_argument("--control-mode", choices=["exclusive", "cooperative"], default="exclusive")
    bridge.add_argument("--frequency", type=float, default=12.0)
    bridge.add_argument("--sample-rate", type=int, default=250)
    bridge.add_argument("--channels", type=int, default=8)
    bridge.add_argument("--seconds", type=float, default=1.0)
    bridge.add_argument("--windows", type=int, default=3)
    bridge.add_argument("--dwell", type=int, default=3)
    bridge.add_argument("--noise", type=float, default=2.0)
    bridge.add_argument("--fault", choices=["dropout", "saturation", "blink", "line-noise"])
    bridge.add_argument("--seed", type=int, default=42)
    bridge.add_argument("--calibration-id", default="synthetic-calibration-v1")
    bridge.add_argument("--subject", default="synthetic-fixture")
    bridge.add_argument("--sequence", type=int, default=1)
    bridge.add_argument("--scope", choices=sorted(SCOPES), default="navigate")
    bridge.add_argument("--wait-for-arm", type=float, default=30.0)
    bridge.add_argument("--timeout", type=float, default=5.0)
    bridge.add_argument("--commit", action="store_true", help="commit after preview; default is preview then disarm")
    return command


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "synthetic":
        print(json.dumps(run_synthetic(args), indent=2, sort_keys=True))
        return 0
    if args.command == "bridge-synthetic":
        print(json.dumps(run_bridge_synthetic(args), indent=2, sort_keys=True))
        return 0
    raise NeurodError("unknown command")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except NeurodError as error:
        print(json.dumps({"error": str(error), "abstained": True}))
        raise SystemExit(2)
