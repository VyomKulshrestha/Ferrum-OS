# Vision world model — sim-to-real and advisory integration (increment 3)

Branch work (`vision-world-model`), NOT main. Design/scoping. The vision world model is validated only in **rendered simulation**; nothing below is a real-hardware or field claim. This note states the sim-to-real gap honestly and scopes a bounded, authority-boundaried advisory integration — it does not implement runtime integration.

## What is proven, and where
- Increment 2 (`vision_world_model_result_v2.json`), registered single-open final on sealed scenes: the GPU vision model's caution head reaches AUC-PR 0.817 / recall 0.714 at a 10% false-alarm rate, vs a linear pixel probe's 0.173 (recall gap +0.542, CI [0.515, 0.568]); it also wins frame prediction (0.285 vs ridge 0.353). Gates G1+G2 pass.
- Increment 3 hard/occluded scenes (`vision_world_model_result_v3_hard.json`): the occlusion stress test of the same claim.
- All of this is on **pybullet-rendered frames with numpy kinematics and perfect geometric hazard labels**. That is the ceiling of the current evidence.

## Sim-to-real gap (honest)
The rendered setup is unrealistic in ways that would not transfer to a real camera:
1. **Perfect labels.** Hazard labels come from exact geometry. Real deployment has no ground-truth "hazard within H"; labels must come from recorded incidents/near-misses or a conservative proxy, which are noisier and rarer.
2. **Clean, static rendering.** No sensor noise, motion blur, exposure/white-balance changes, rolling shutter, compression artifacts, lighting variation, or background clutter. A model trained on clean renders typically collapses on real frames.
3. **Known, simple kinematics.** Momentum + wall reflection in 2D. Real dynamics have friction, 3D motion, multiple interacting agents, and actuation lag.
4. **Single fixed camera, single scene family.** One viewpoint, one obstacle distribution. Real cameras move, and scenes vary.
5. **In-distribution evaluation.** The sealed final is a fresh *seed* of the *same* generator — a within-distribution test, not a new environment or a real site.

### What closing the gap would require (not done here)
- **Domain randomization** at train time: randomize lighting, textures, camera pose, noise, object counts/shapes, and dynamics, so the model does not overfit the clean renderer.
- **Real benign footage** for calibration: set the caution threshold on recorded *normal* operation from the actual camera, with the conservative half-budget margin (the cycle-2b lesson), since false-alarm rate is a property of real benign data, not sim.
- **A registered real evaluation**: a sealed set of *real* recordings with incident labels, opened once — the sim result does not substitute for it. Until then, no real-world recall claim is made.
- **Pretrained visual encoder** (DINOv2 / V-JEPA) as a frozen backbone to improve transfer from clean sim to varied real frames (increment-3 follow-up; gated on a reliable model-weight download — unreliable on this network without Cloudflare WARP).

## Advisory integration path (bounded, authority-boundaried)
If and only if a real evaluation later holds up, a vision caution signal could enter the FerrumOS/Heliox runtime as an **advisory** input, with the same authority boundary as `physical_hai_v1` ("advisory diagnostic only; no permit, block, approval, adapter or actuation authority"):

- **Placement.** A separate inference daemon loads the frozen caution model, runs on the camera stream, and emits a calibrated caution score + a boolean "caution raised" at the conservative threshold. It publishes to the same advisory channel the state world model uses; it is one input the operator/UI sees, never a control output.
- **Non-authority.** The deterministic authority gate remains the sole decision-maker. The vision caution never grants, blocks, or defers a permission; at most it annotates/logs and can prompt a human. This preserves the "prediction is not permission" invariant.
- **Fail-safe, not fail-open.** If the model is unavailable, times out, or its input is degraded (e.g., camera obscured), the daemon emits "no confident caution" **and logs the degradation** — it never emits "safe". Downstream treats missing caution as missing information, not as an all-clear.
- **Compute budget.** Inference is a single forward pass of a ~6M-param CNN at 48–64 px — well under the 8 GB / one-CUDA-job limit; it runs sequentially with any other GPU job, or on CPU at low frame rates.
- **Calibration discipline at deploy.** Threshold calibrated on real benign footage to a false-alarm budget with the conservative margin; recalibrated on drift; the budget and realized false-alarm rate are logged.
- **Registration before integration.** No integration ships without: (a) a real, sealed, single-open evaluation passing pre-registered gates, and (b) a written authority-boundary statement in the daemon, mirroring the physical_hai_v1 claim boundary.

## Status / next
- Implemented + validated in sim: increments 1–2 (and 3 hard scenes).
- Not implemented: domain randomization, real-data evaluation, pretrained encoder, runtime daemon. Those are the ordered next steps, each gated on the previous. The runtime daemon is the LAST step and only after a real registered evaluation.

## Update 2026-10-22: what increment 4 actually is
Since this note: domain randomization and a shift ablation (options c and follow-up), a pretrained DINOv2 encoder (option b, then a sealed confirmation under amendment 3), and a first real-footage evaluation on CCD dashcam video (a different domain) have been done. Increment 4 was built in the bounded form this note allows *without* the real same-domain evaluation:

- **Host-side only.** `tools/vision_caution/` (modelled on `tools/neurod/`) scores the sealed-evaluated `FERRUM_VISION_CAUTION_V1` head (`docs/research/artifacts/vision-caution-v1/selected_caution_head.npz`). Nothing in `userland/` (the `no_std` guest, the physical runtime, the authority gate) is changed or reads it. In particular the score is never passed as a `PhysicalPrediction`, which still carries fail-closed block influence.
- **Off by default** (`FERRUM_VISION_CAUTION=advisory` to enable), log/telemetry output only, statuses `caution_raised` / `no_caution_raised` / `no_confident_caution` with no "safe" status, and every doubt abstains.
- **Verified** by `tools/vision_caution/test_vision_caution.py` (fail-safe paths, no route to authority, encoder equivalence with the research implementation, end-to-end agreement with the evaluated pipeline) and `scripts/verify_vision_caution_advisory.py` (artifact bound to the sealed result, protected deployed artifacts unchanged, no wiring in guest/gate code).
- **Still not qualified for live use.** Promotion beyond advisory logging requires a sealed, single-open evaluation on real footage of the deployment domain itself; see `docs/research/vision_caution_integration_protocol_v1.json`.
