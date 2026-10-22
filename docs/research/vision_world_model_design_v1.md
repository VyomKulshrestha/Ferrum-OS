# Vision world model for FerrumOS — design & scope (v1)

Status: **design + increment-1 build**. Development only. Advisory diagnostic; no permit/block/actuation authority. Nothing frozen (Physical JEPA v5, incident-dynamics v2–v4, physical_hai_v1/v2, rt1/rt2) is touched or retrained.

## Why this, why now
On FerrumOS's engineered state/telemetry **vectors**, ridge/GBR beat GPU neural world models — shown twice on-device: physical domain (`physical_jepa_gpu_devtrial_v1.json`, neural ~15× worse) and 86-channel HAI (`real_telemetry_hai_forecast_jepa_vs_ridge.json`, neural 19–30% worse). On **raw pixels**, the opposite holds: a GPU CNN cut dynamic-region error 59% below a linear model (`pixel_world_model_gpu_v1.json`). So the only honest reason to spend GPU/neural on a FerrumOS world model is a **vision** observation space. This design moves from that toy pixel world to a rendered-physics scene with a deployable-relevant job: an advisory **caution signal** from pixels.

## Objective
A vision world model that, from a camera observation and the agent's action, (a) predicts near-future observations (world-model rollout) and (b) emits a calibrated **hazard-imminent** caution score (collision / out-of-bounds within H steps), good enough to be an advisory gate the way `physical_hai_v1` is advisory-only. Deployable target: the Heliox/FerrumOS runtime that already loads a CPU world-model artifact; a vision model would be an added, clearly-bounded advisory input, not a replacement for the deterministic authority gate.

## Non-goals
- Not a replacement for the deterministic authority gate or the deployed v5 state model.
- Not a real-hardware or field-incident claim; rendered simulation only (sim-to-real is future work).
- No actuation/permit/block authority. Advisory scores only.

## Data (increment 1): rendered physics scenes
- **Simulator**: PyBullet headless (`DIRECT`, CPU raster), already installed and verified rendering 48×48.
- **Scene**: a bounded plane with 1–2 static box obstacles; a mobile agent (sphere) driven by 5 discrete actions (stay, ±x, ±y impulse). Fixed top-down camera, grayscale `size×size`.
- **Labels**: per-step `hazard` = agent in contact/overlap with an obstacle or wall (from `getContactPoints` / margin). Used only for the caution head and evaluation, never fed as input.
- **Split**: by scene/seed into train / held-out eval; a sealed final-seed set opened once for the registered number (single-open discipline, like the physical protocols).

## Models
- **Baselines (non-neural / trivial)**: persistence (next = current); ridge-on-pixels for frame prediction; for hazard, a logistic/linear probe on raw pixels + action. These are the "does neural earn its place" bar.
- **Vision world model (GPU)**: small CNN encoder → latent; action-conditioned predictor → next latent; a decoder/delta head for pixel rollout; a **hazard head** predicting P(hazard within H). JEPA-style latent objective optional; the pixel experiment showed loss must up-weight changed pixels (plain MSE collapses to copy).
- **Optional richer encoder (later increment, network permitting)**: a frozen pretrained vision encoder (DINOv2-small / V-JEPA) per the repo's `world_model_safety_literature.md` Direction 3. Gated on reliable HF download (WARP may be needed); not required for increment 1.

## Evaluation
- **World-model quality**: closed-loop rollout MAE (H1..H10), dynamic-region MAE, vs persistence/ridge. (The pixel demo's metrics, on rendered scenes.)
- **Caution quality**: hazard-event recall at a fixed false-alarm budget (episodes/hour), detection lead time (how many steps before contact), AUC-PR — vs the linear pixel probe and vs a state-oracle upper bound.
- **Discipline**: registered protocol, ledgered single final open on the sealed seeds, retain negatives, report all baselines, record code + artifact digests. No tuning on the final set.

## Compute plan (RTX 4060, 8 GB, one CUDA job at a time)
- 48–64 px, small CNN (~1–3M params) fits 8 GB easily; batch 128–256. AMP only if needed. Keep rendering (CPU) and training (GPU) sequential. Expected minutes per training run.

## Milestones
1. **Increment 1 (now)**: pybullet data pipeline (scenes + hazard labels) → CNN vision world model + hazard head on GPU → honest eval vs persistence/ridge/linear-probe. Deliver `scripts/vision_wm_*.py` + `docs/research/vision_world_model_result_v1.json`.
2. Increment 2: registered protocol with sealed final seeds; calibration + single final open; conservative caution-budget calibration (the cycle-2b margin lesson).
3. Increment 3: richer encoder (pretrained) and/or multi-object/occlusion scenes; sim-to-real discussion.
4. Increment 4 (only if 1–3 hold up): a bounded, advisory integration path into the runtime, authority-boundaried like physical_hai_v1.

## Risks / honest caveats
- Rendered sim ≠ real cameras; any result is sim evidence only.
- Plain pixel MSE collapses to copy — must up-weight motion (shown).
- A linear pixel probe may already catch easy, slow hazards; the neural model must beat it on the hard/fast/occluded cases to earn its place. If it doesn't, that is a reportable negative.
- Pretrained-encoder downloads are unreliable on this network without WARP.
