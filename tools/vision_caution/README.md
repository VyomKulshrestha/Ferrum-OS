# vision_caution — advisory vision caution (host side)

Given the last two camera frames and a proposed action, it reports the probability that a
camera-visible hazard (obstacle proximity, geofence exit or contact) occurs within the
next 3 steps. The model is a sealed-evaluated caution head over the official DINOv2-small
encoder.

**Authority:** advisory diagnostic only; no permit, block, approval, adapter or actuation
authority. That is the same boundary as `physical_hai_v1`. The record goes to logs and
telemetry. It is never a bridge or runtime command, it is never passed to the physical
runtime as a `PhysicalPrediction`, and nothing in the guest (`userland/`) reads it. The
deterministic authority gate remains the only decision-maker.

**Off by default.** Inference runs only with `FERRUM_VISION_CAUTION=advisory`, or with
`VisionCaution(enabled=True)`.

## Artifacts

| artifact | frames | proposed action | evaluated on | scope |
|---|---|---|---|---|
| `vision-caution-v2` (default) | 64x64 grey | runtime `PhysicalAction`: `(kind, features)` | runtime-scene proxy, sealed seed 790: AUC-PR 0.685, recall 0.464 at FPR 0.057 | `docs/research/vision_caution_integration_protocol_v2.json` |
| `vision-caution-v1` | 48x48 grey | sim impulse, int 0..4 | rendered hard scene, sealed seed 781 | `docs/research/vision_caution_integration_protocol_v1.json` |

The v2 action input is the runtime model's own encoding (one-hot over the 7 kinds plus the
3 features), so no mapping is needed. A projection onto v1's five impulses cost recall on
the sealed test (registered secondary S1).

**Not qualified for live use or real cameras.** The runtime-scene proxy is the runtime's
own PyBullet world filmed from a fixed overhead camera: simulation, not real footage.
FerrumOS has no real robot or camera yet. On real robots (Georgia Tech Robotarium, registered
study, sealed seeds 301-306) the v2 head FAILED: AUC-PR 0.279 against a 0.220 base rate, no
better than the action-only control, and its simulation threshold raised alarms on 90% of
hazard-free steps (`docs/research/vision_caution_robotarium_result_v1.json`; exploratory
diagnosis in `_diagnosis_v1.json`). Real-footage evidence in another domain is in
`docs/research/vision_world_model_ccd_result_v1.json`; it does not qualify either head.

## Statuses

| status | meaning |
|---|---|
| `caution_raised` | logit above the threshold calibrated to the chosen false-alarm budget |
| `no_caution_raised` | below it; **not** a statement that the action is safe |
| `no_confident_caution` | abstained; `degradation` gives the reason |

There is no "safe" status. Every failure abstains and never raises: disabled,
missing/altered/non-finite artifact, encoder digest mismatch, invalid, obscured, stale or
out-of-order frames, an action outside the artifact's action space (for v2, the runtime's
own `InvalidAction` rule: finite features within [-1, 1]), a timeout, or a non-finite output.

## Use

```python
from vision_caution import VisionCaution
vc = VisionCaution(enabled=True, log=print)           # v2; log receives one JSON line per call
rec = vc.assess((frame_prev, frame_cur), proposed_action=("move", (0.5, -0.2, 0.8)), frame_ids=(41, 42))
rec.status, rec.caution_probability, rec.degradation

from vision_caution import V1_ARTIFACT                # the older sim-action head, by path
VisionCaution(V1_ARTIFACT, enabled=True).assess((f48_prev, f48_cur), proposed_action=2, frame_ids=(1, 2))
```

The DINOv2 weights must already be in the Hugging Face cache; the advisory never downloads
at runtime.

## Verify

```
python -m unittest discover -s tools/vision_caution -p "test_*.py"
python scripts/verify_vision_caution_advisory.py            # static, numpy only, both artifacts
python scripts/verify_vision_caution_advisory.py --replay   # re-derives both 5% thresholds (slow)
```
