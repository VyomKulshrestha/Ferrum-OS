#!/usr/bin/env python3
"""Host-side, advisory-only vision caution for FerrumOS (vision world model, increment 4).

Turns the last two camera frames and a proposed action into an advisory caution record
for logs and telemetry: P(hazard within the next 3 steps) from the frozen
FERRUM_VISION_CAUTION_V1 head over the official DINOv2-small encoder.

Authority boundary (identical to physical_hai_v1): advisory diagnostic only; no permit,
block, approval, adapter or actuation authority. The record is never a runtime or bridge
command, and there is no "safe" status: anything doubtful (disabled, missing or altered
artifact, encoder digest mismatch, invalid, obscured, stale or out-of-order frames, an
unknown action, a timeout or a non-finite output) yields "no_confident_caution" with the
reason in `degradation`.

Off by default: inference runs only when FERRUM_VISION_CAUTION=advisory (or enabled=True).
Qualified only for the rendered pybullet hard scene (clean look, sim action space); not
qualified for live use. See docs/research/vision_caution_integration_protocol_v1.json.

Numpy-only for loading and validation; torch is imported on first inference.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np

SCHEMA = "FERRUM_VISION_CAUTION_V1"
RECORD_SCHEMA = "ferrum_vision_caution_advisory_v1"
AUTHORITY = "advisory diagnostic only; no permit, block, approval, adapter or actuation authority"
STATUSES = ("caution_raised", "no_caution_raised", "no_confident_caution")
ENABLE_ENV = "FERRUM_VISION_CAUTION"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT = ROOT / "docs/research/artifacts/vision-caution-v1/selected_caution_head.npz"
FRAME_SIZE, N_ACTIONS, OBSCURED_STD = 48, 5, 1e-3
HEAD_SHAPES = {"red.weight": (64, 768, 1, 1), "red.bias": (64,), "act.weight": (32, 5), "act.bias": (32,),
               "mlp.0.weight": (128, 1056), "mlp.0.bias": (128,), "mlp.2.weight": (1, 128), "mlp.2.bias": (1,)}
IMAGENET_MEAN, IMAGENET_STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)


class VisionCautionError(ValueError):
    """A validation or inference failure; callers only ever see it as no_confident_caution."""


@dataclass(frozen=True)
class VisionCautionAdvisory:
    status: str
    caution_probability: float | None
    caution_logit: float | None
    threshold_logit: float | None
    budget: str | None
    horizon_steps: int
    frame_ids: tuple[int, int] | None
    model_sha256: str | None
    degradation: str | None
    latency_ms: float | None = None
    authority: str = AUTHORITY

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        if self.authority != AUTHORITY:
            raise ValueError("the authority boundary cannot be changed")
        if self.status == "no_confident_caution" and self.caution_probability is not None:
            raise ValueError("an abstention carries no probability")

    def to_json(self) -> str:
        return json.dumps({"schema": RECORD_SCHEMA, **asdict(self)}, sort_keys=True)


def load_artifact(path=DEFAULT_ARTIFACT, expected_sha256: str | None = None) -> dict:
    """Validate and load the frozen head. Raises VisionCautionError with a short reason."""
    p = Path(path)
    if not p.is_file():
        raise VisionCautionError("artifact_missing")
    raw = p.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise VisionCautionError("artifact_digest_mismatch")
    try:
        with np.load(io.BytesIO(raw), allow_pickle=False) as z:
            meta = json.loads(str(z["metadata"]))
            weights = {k[len("head."):]: np.array(z[k], np.float32) for k in z.files if k.startswith("head.")}
    except Exception as exc:  # malformed archive
        raise VisionCautionError("artifact_unreadable") from exc
    if meta.get("schema") != SCHEMA:
        raise VisionCautionError("artifact_schema")
    if meta.get("authority") != AUTHORITY:
        raise VisionCautionError("artifact_authority_boundary")
    if {k: v.shape for k, v in weights.items()} != HEAD_SHAPES:
        raise VisionCautionError("artifact_shapes")
    if not all(np.isfinite(v).all() for v in weights.values()):
        raise VisionCautionError("artifact_nonfinite")
    try:
        thresholds = {k: float(v) for k, v in meta["thresholds_logit"].items()}
        platt = (float(meta["platt"]["coef"]), float(meta["platt"]["intercept"]))
        encoder_sha = str(meta["encoder"]["weights_sha256"])
        horizon = int(meta["horizon_steps"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VisionCautionError("artifact_metadata") from exc
    if not all(math.isfinite(v) for v in (*thresholds.values(), *platt)) or platt[0] <= 0:
        raise VisionCautionError("artifact_calibration")
    if meta.get("frame_stack") != 2 or len(meta.get("action_space", {}).get("actions", [])) != N_ACTIONS:
        raise VisionCautionError("artifact_interface")
    return {"meta": meta, "weights": weights, "sha256": sha, "thresholds": thresholds,
            "platt": platt, "encoder_sha256": encoder_sha, "horizon_steps": horizon}


class VisionCaution:
    """Advisory caution scorer. Construction never raises; failures surface as abstentions."""

    def __init__(self, artifact=DEFAULT_ARTIFACT, expected_sha256: str | None = None, budget: str = "fpr_0.05",
                 enabled: bool | None = None, timeout_s: float = 5.0, device: str = "cpu",
                 log: Callable[[str], None] | None = None):
        self.enabled = (os.environ.get(ENABLE_ENV) == "advisory") if enabled is None else bool(enabled)
        self.budget, self.timeout_s, self.device, self.log = budget, timeout_s, device, log
        self._encoder = self._head = None
        self._last_frame_id: int | None = None
        try:
            self._art = load_artifact(artifact, expected_sha256)
            if budget not in self._art["thresholds"]:
                raise VisionCautionError("unknown_budget")
            self._failure = None
        except VisionCautionError as exc:
            self._art, self._failure = None, str(exc)

    # -- public ---------------------------------------------------------------------------
    def assess(self, frames, proposed_action: int, frame_ids: tuple[int, int]) -> VisionCautionAdvisory:
        start = time.perf_counter()
        try:
            ids = self._check_inputs(frames, proposed_action, frame_ids)
            logit = self._infer(frames, int(proposed_action))
            latency = (time.perf_counter() - start) * 1000.0
            if latency > self.timeout_s * 1000.0:
                raise VisionCautionError("timeout")
            if not math.isfinite(logit):
                raise VisionCautionError("nonfinite_output")
        except VisionCautionError as exc:
            return self._emit(self._abstain(frame_ids, str(exc), start))
        except Exception as exc:  # never let an internal error look like an all-clear
            return self._emit(self._abstain(frame_ids, f"internal_error:{type(exc).__name__}", start))
        self._last_frame_id = ids[1]
        a, b = self._art["platt"]
        thr = self._art["thresholds"][self.budget]
        return self._emit(VisionCautionAdvisory(
            status="caution_raised" if logit > thr else "no_caution_raised",
            caution_probability=1.0 / (1.0 + math.exp(-(a * logit + b))), caution_logit=logit,
            threshold_logit=thr, budget=self.budget, horizon_steps=self._art["horizon_steps"], frame_ids=ids,
            model_sha256=self._art["sha256"], degradation=None, latency_ms=round(latency, 3)))

    # -- internals ------------------------------------------------------------------------
    def _abstain(self, frame_ids, reason, start) -> VisionCautionAdvisory:
        ids = tuple(frame_ids) if isinstance(frame_ids, (tuple, list)) and len(frame_ids) == 2 else None
        return VisionCautionAdvisory(
            status="no_confident_caution", caution_probability=None, caution_logit=None, threshold_logit=None,
            budget=self.budget, horizon_steps=3, frame_ids=ids,
            model_sha256=self._art["sha256"] if self._art else None, degradation=reason,
            latency_ms=round((time.perf_counter() - start) * 1000.0, 3))

    def _emit(self, record: VisionCautionAdvisory) -> VisionCautionAdvisory:
        if self.log is not None:
            self.log(record.to_json())
        return record

    def _check_inputs(self, frames, action, frame_ids) -> tuple[int, int]:
        if not self.enabled:
            raise VisionCautionError("disabled_by_default")
        if self._failure:
            raise VisionCautionError(self._failure)
        if not (isinstance(frame_ids, (tuple, list)) and len(frame_ids) == 2
                and all(isinstance(i, (int, np.integer)) for i in frame_ids)):
            raise VisionCautionError("frame_ids_invalid")
        prev_id, cur_id = int(frame_ids[0]), int(frame_ids[1])
        if cur_id <= prev_id:
            raise VisionCautionError("frames_out_of_order")
        if self._last_frame_id is not None and cur_id <= self._last_frame_id:
            raise VisionCautionError("frames_stale")
        if not (isinstance(frames, (tuple, list)) and len(frames) == 2):
            raise VisionCautionError("frame_count")
        for f in frames:
            f = np.asarray(f)
            if f.shape != (FRAME_SIZE, FRAME_SIZE) or not np.issubdtype(f.dtype, np.floating):
                raise VisionCautionError("frame_shape_or_dtype")
            if not np.isfinite(f).all() or f.min() < 0.0 or f.max() > 1.0:
                raise VisionCautionError("frame_values")
            if float(f.std()) < OBSCURED_STD:
                raise VisionCautionError("frame_obscured")
        if not isinstance(action, (int, np.integer)) or not 0 <= int(action) < N_ACTIONS:
            raise VisionCautionError("action_out_of_space")
        return prev_id, cur_id

    def _load_models(self):
        import torch
        import torch.nn as nn
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file

        from dinov2_small import DinoV2Small

        try:
            wpath = hf_hub_download("facebook/dinov2-small", "model.safetensors", local_files_only=True)
        except Exception as exc:
            raise VisionCautionError("encoder_unavailable") from exc
        if hashlib.sha256(Path(wpath).read_bytes()).hexdigest() != self._art["encoder_sha256"]:
            raise VisionCautionError("encoder_digest_mismatch")
        enc = DinoV2Small()
        enc.load_state_dict(load_file(wpath), strict=True)
        head = nn.ModuleDict({"red": nn.Conv2d(768, 64, 1), "act": nn.Linear(N_ACTIONS, 32),
                              "mlp": nn.Sequential(nn.Linear(1056, 128), nn.GELU(), nn.Linear(128, 1))})
        head.load_state_dict({k: torch.from_numpy(v) for k, v in self._art["weights"].items()}, strict=True)
        self._encoder, self._head = enc.eval().to(self.device), head.eval().to(self.device)

    def _infer(self, frames, action: int) -> float:
        import torch
        import torch.nn.functional as F

        if self._encoder is None:
            self._load_models()
        mean = torch.tensor(IMAGENET_MEAN, device=self.device).view(1, 3, 1, 1)
        std = torch.tensor(IMAGENET_STD, device=self.device).view(1, 3, 1, 1)
        with torch.no_grad():
            x = torch.from_numpy(np.stack([np.asarray(f, np.float32) for f in frames])[:, None]).to(self.device)
            x = F.interpolate(x.repeat(1, 3, 1, 1), size=(224, 224), mode="bilinear", align_corners=False)
            feats = F.adaptive_avg_pool2d(self._encoder((x - mean) / std), 4).half().float()   # as evaluated
            stacked = torch.cat([feats[0:1], feats[1:2]], 1)
            onehot = torch.zeros(1, N_ACTIONS, device=self.device)
            onehot[0, action] = 1.0
            z = F.gelu(self._head["red"](stacked)).flatten(1)
            return float(self._head["mlp"](torch.cat([z, F.gelu(self._head["act"](onehot))], 1))[0, 0])


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate the vision caution artifact (advisory only).")
    ap.add_argument("--artifact", default=str(DEFAULT_ARTIFACT))
    ap.add_argument("--expected-sha256")
    a = ap.parse_args()
    try:
        art = load_artifact(a.artifact, a.expected_sha256)
    except VisionCautionError as exc:
        raise SystemExit(f"artifact rejected: {exc}")
    print(json.dumps({"schema": art["meta"]["schema"], "sha256": art["sha256"], "authority": art["meta"]["authority"],
                      "thresholds_logit": art["thresholds"], "qualified_for": art["meta"].get("qualified_for")}, indent=1))


if __name__ == "__main__":
    main()
