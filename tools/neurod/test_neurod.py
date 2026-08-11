import csv
import hashlib
import hmac
import json
import struct
import tempfile
import unittest
from pathlib import Path

from neurod import (
    BoundedSampleBuffer,
    ConsentRecorder,
    IntentEvidence,
    JsonRpcWebSocket,
    NeurodError,
    PlaybackBoard,
    Sample,
    SsvepDecoder,
    SyntheticBoard,
    WIRE_BYTES,
    assess_signal,
    build_intent_from_decode,
    derive_session_material,
    sign_intent,
)


class NeurodTests(unittest.TestCase):
    def test_bounded_buffer_counts_overflow_and_rejects_clock_races(self):
        buffer = BoundedSampleBuffer(3, 2)
        for index in range(5):
            buffer.append(Sample(index + 1, (1.0, 2.0)))
        self.assertEqual(len(buffer), 3)
        self.assertEqual(buffer.dropped_samples, 2)
        with self.assertRaises(NeurodError):
            buffer.append(Sample(5, (1.0, 2.0)))

    def test_registered_ssvep_targets_decode_after_dwell(self):
        for label, frequency in {"focus-left": 8.0, "focus-right": 10.0, "select": 12.0, "cancel": 15.0}.items():
            board = SyntheticBoard(seed=7)
            decoder = SsvepDecoder(250)
            result = None
            for window in range(3):
                result = decoder.decode(board.acquire(1.0, frequency, 1_000_000_000 + window * 1_000_000_000))
            self.assertIsNotNone(result)
            self.assertEqual(result.label, label)
            self.assertGreaterEqual(result.posterior_permille, 800)

    def test_no_control_and_artifacts_abstain(self):
        for frequency, fault in ((None, None), (12.0, "saturation"), (12.0, "blink"), (12.0, "line-noise")):
            board = SyntheticBoard(seed=3)
            decoder = SsvepDecoder(250, required_dwell_windows=1)
            result = decoder.decode(board.acquire(1.0, frequency, fault=fault))
            self.assertTrue(result.abstained)

    def test_noise_cannot_accumulate_dwell_without_absolute_spectral_evidence(self):
        board = SyntheticBoard(seed=99173)
        decoder = SsvepDecoder(250)
        for window in range(500):
            result = decoder.decode(board.acquire(1.0, None, 1_000_000_000 + window * 1_000_000_000))
            self.assertTrue(result.abstained)
            self.assertEqual(result.dwell_windows, 0)

    def test_dropout_is_detected_and_forces_abstention(self):
        samples = SyntheticBoard(seed=2).acquire(1.0, 12.0, fault="dropout")
        gaps = [b.monotonic_ns - a.monotonic_ns for a, b in zip(samples, samples[1:])]
        self.assertGreater(max(gaps), min(gaps))
        result = SsvepDecoder(250, required_dwell_windows=1).decode(samples)
        self.assertTrue(result.abstained)
        self.assertGreater(result.health.dropped_samples, 0)

    def test_playback_schema_and_monotonicity_are_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["monotonic_ns", "ch0", "ch1", "marker"])
                writer.writerow([1, 1.0, 2.0, 0])
                writer.writerow([2, 1.5, 2.5, 1])
            self.assertEqual(len(PlaybackBoard(path, 2).acquire()), 2)
            path.write_text("monotonic_ns,ch0\n1,1\n", encoding="utf-8")
            with self.assertRaises(NeurodError):
                PlaybackBoard(path, 2).acquire()

    def test_wire_layout_signature_and_derivation_match_contract(self):
        token = b"0123456789abcdef0123456789abcdef"
        key, session_id = derive_session_material(token)
        evidence = IntentEvidence(
            "select", "navigate", 9, 100, 200, 300, session_id, bytes(range(16)),
            hashlib.sha256(b"decoder").digest(), hashlib.sha256(b"calibration").digest(),
            hashlib.sha256(b"subject").digest()[:16], 7, 11, 900, 300, 3,
        )
        wire = sign_intent(evidence, key)
        self.assertEqual(len(wire), WIRE_BYTES)
        self.assertEqual(wire[:4], b"NIV1")
        self.assertEqual(struct.unpack_from("<Q", wire, 18)[0], 9)
        self.assertEqual(wire[50:66], session_id)
        self.assertTrue(hmac.compare_digest(wire[178:], hmac.new(key, wire[:178], hashlib.sha256).digest()))

    def test_abstention_cannot_be_signed_as_an_intent(self):
        board = SyntheticBoard(seed=1)
        result = SsvepDecoder(250, required_dwell_windows=1).decode(board.acquire(1.0, None))
        with self.assertRaises(NeurodError):
            build_intent_from_decode(result, b"0123456789abcdef", b"c" * 32, b"s" * 16, 1, 0, 0, "navigate", 1, 2)

    def test_recording_is_consent_gated_and_pseudonymous(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(NeurodError):
                ConsentRecorder(Path(directory), "subject1", False)
            recorder = ConsentRecorder(Path(directory), "subject1", True)
            path = recorder.write(
                [Sample(1, (1.0, 2.0)), Sample(2, (2.0, 3.0))],
                250,
                [(0.0, "stimulus-12hz")],
                source_kind="synthetic",
            )
            self.assertTrue(path.exists())
            self.assertTrue((Path(directory) / "dataset_description.json").exists())
            sidecar = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(sidecar["FerrumSourceKind"], "synthetic")
            self.assertTrue(sidecar["FerrumSynthetic"])

    def test_websocket_client_frames_are_masked_and_bounded(self):
        payload = b'{"method":"neural_status"}'
        frame = JsonRpcWebSocket.encode_client_frame(payload, b"abcd")
        self.assertEqual(frame[0], 0x81)
        self.assertTrue(frame[1] & 0x80)
        length = frame[1] & 0x7F
        self.assertEqual(length, len(payload))
        self.assertEqual(frame[2:6], b"abcd")
        decoded = bytes(value ^ b"abcd"[index % 4] for index, value in enumerate(frame[6:]))
        self.assertEqual(decoded, payload)
        with self.assertRaises(NeurodError):
            JsonRpcWebSocket.encode_client_frame(payload, b"bad")

    def test_short_pairing_tokens_are_rejected(self):
        with self.assertRaises(NeurodError):
            derive_session_material(b"short")


if __name__ == "__main__":
    unittest.main()
