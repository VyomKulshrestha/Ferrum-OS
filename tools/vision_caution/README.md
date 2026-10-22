# vision_caution — advisory vision caution (host side)

Increment 4 of the vision world model. Given the last two camera frames and a proposed
action, it reports the probability that a hazard (contact or out-of-bounds) occurs within
the next 3 steps. The model is the sealed-evaluated `FERRUM_VISION_CAUTION_V1` head over
the official DINOv2-small encoder.

**Authority:** advisory diagnostic only; no permit, block, approval, adapter or actuation
authority. That is the same boundary as `physical_hai_v1`. The record goes to logs and
telemetry. It is never a bridge or runtime command, it is never passed to the physical
runtime as a `PhysicalPrediction`, and nothing in the guest (`userland/`) reads it. The
deterministic authority gate remains the only decision-maker.

**Off by default.** Inference runs only with `FERRUM_VISION_CAUTION=advisory`, or with
`VisionCaution(enabled=True)`.

**Not qualified for live use.** It is validated only on rendered pybullet scenes (hard
scene, clean look, the five-action sim action space). Real-footage evidence is in
`docs/research/vision_world_model_ccd_result_v1.json`, a different domain that does not
qualify this head. Promotion conditions are in
`docs/research/vision_caution_integration_protocol_v1.json`.

## Statuses

| status | meaning |
|---|---|
| `caution_raised` | logit above the threshold calibrated to the chosen false-alarm budget |
| `no_caution_raised` | below it; **not** a statement that the action is safe |
| `no_confident_caution` | abstained; `degradation` gives the reason |

There is no "safe" status. Every failure abstains and never raises: disabled,
missing/altered/non-finite artifact, encoder digest mismatch, invalid, obscured, stale or
out-of-order frames, an unknown action, a timeout, or a non-finite output.

## Use

```python
from vision_caution import VisionCaution
vc = VisionCaution(enabled=True, log=print)           # log receives one JSON line per call
rec = vc.assess((frame_prev, frame_cur), proposed_action=2, frame_ids=(41, 42))
rec.status, rec.caution_probability, rec.degradation
```

Frames are 48x48 float greyscale in [0, 1]. The DINOv2 weights must already be in the
Hugging Face cache; the advisory never downloads at runtime.

## Verify

```
python -m unittest discover -s tools/vision_caution -p "test_*.py"
python scripts/verify_vision_caution_advisory.py            # static, numpy only
python scripts/verify_vision_caution_advisory.py --replay   # re-derives the 5% threshold (slow)
```
