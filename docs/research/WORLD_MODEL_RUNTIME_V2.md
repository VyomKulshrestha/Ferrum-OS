# FerrumOS world-model runtime refinement v2

This is a post-publication runtime checkpoint. It does not replace or rewrite the evidence for `world-model-study-v1.0.0`; that study's encoder, transition model, and manifest are preserved under `docs/research/artifacts/world-model-study-v1.0.0/`.

## Selection protocol

The released 512-hidden-unit transition checkpoint was warm-started for 300 additional epochs at learning rate 0.005. The loss increased the relative weight of the seven deterministic/core state dimensions. Candidate choice used only the episode-disjoint validation partition and the pre-existing composite objective:

```text
normalized macro-tool error + normalized core-state error + normalized H=3 rollout error
```

The boundary sweep selected core weight 128. Weight 64 scored 0.0765383, weight 128 scored 0.0765112, and weight 256 worsened to 0.0769659. The untouched test partition was opened only after selection.

## Untouched-test result

| Metric | Study checkpoint | Runtime v2 | Relative change |
|---|---:|---:|---:|
| One-step normalized error | 1.6752% | 1.3645% | -18.55% |
| Macro-tool normalized error | 1.7080% | 1.2517% | -26.72% |
| Core-state normalized error | 3.8053% | 3.4007% | -10.63% |
| H=3 rollout normalized error | 3.8672% | 3.7751% | -2.38% |
| H=5 rollout normalized error | 4.0283% | 4.0362% | +0.20% |

The geometric ratio across the five promotion metrics is 0.8780. No metric exceeds the preregistered 2% regression tolerance.

## Safety fixture

The authored 500-episode safety fixture was evaluated after model selection. Rules plus JEPA reached 81.8% balanced accuracy with 50 false negatives and 41 false positives, compared with 81.4%, 52, and 41 for the study checkpoint. The combined system added 53 dangerous catches over rules alone and lost no deterministic catch. This remains an authored-fixture result, not natural-use or independently annotated evidence.

## Runtime check

A fresh WHPX-backed appliance run measured 100 previews at every horizon from H=1 through H=5. Median guest-PIT latency was 1-2 ms, p95 was 2 ms, both learned files loaded, and no heap growth or guest fault was observed. Virtualized timing is environment-specific and excludes provider latency, tool execution, and confirmation.

## Artifacts

- Runtime transition: `appliance/world-model/model_learned.bin` (`f6bf2e502aa9d8abeeba47b81205468f02ec54203f4f39931d6ea42359cf0dc8`)
- Full metrics: `world_model_runtime_v2_metrics.json`
- Promotion decision: `world_model_runtime_v2_selection.json`
- Sweep summary: `world_model_runtime_v2_sweep.json`
- Safety aggregate and predictions: `world_model_runtime_v2_safety.json`, `world_model_runtime_v2_safety_predictions.csv`
- In-guest benchmark: `world_model_runtime_v2_benchmark.json`

The JEPA representation and provider-independent action encoding are unchanged. This refinement improves the FWM2 transition predictor; deterministic rules and capability enforcement retain authority.
