# World-model runtime and failure evaluation

This evaluation measures the release gate inside the real ring-3 Heliox daemon. It does not substitute host-side Python timing for deployment timing and it does not dispatch benchmark actions.

## Runtime

The guest ran a 64-preview H=5 warmup followed by 100 previews at each horizon. Time comes from the guest's 1 kHz PIT; raw virtual TSC cycles are retained in the JSON evidence but are not converted to time because WHPX's virtual TSC was not a reliable wall-time clock.

| Horizon | Mean | Median | p95 | Maximum |
|---:|---:|---:|---:|---:|
| 1 | 1.35 ms | 1 ms | 2 ms | 3 ms |
| 2 | 1.44 ms | 1 ms | 2 ms | 3 ms |
| 3 | 1.45 ms | 1 ms | 2 ms | 3 ms |
| 4 | 1.53 ms | 1 ms | 2 ms | 3 ms |
| 5 | 1.59 ms | 2 ms | 2 ms | 2 ms |

The 193,229-parameter encoder and transition pair loaded in 30 ms by the same guest timer. The 129,344-byte encoder and 643,616-byte transition were both active. Heap usage was 664,832 bytes before and after the 500 measured previews, for zero observed growth. Percentiles have 1 ms resolution and apply only to this 512 MiB WHPX/QEMU run; provider latency, tool execution, and operator confirmation are out of scope.

## Concurrent outstanding requests

One WebSocket connection submitted 96 previews without waiting between sends, spanning six action classes. FerrumOS returned 96/96 responses with the correct IDs in 20.142 seconds of host wall time. Repeated identical requests produced identical decisions, no execution dataset record was emitted, both learned components were loaded, and the guest remained fault-free.

The daemon intentionally serializes inference; this experiment tests multiple outstanding requests, framing, response correlation, and state isolation, not parallel neural execution. During this test, the old 100 ms connected-client sleep exposed a throughput bottleneck. The bridge now uses a 10 ms cooperative cadence while connected, retains the 100 ms idle cadence, and retries partial WebSocket sends until the entire frame is transmitted.

## Failure injection

Five artifact conditions were exercised:

1. valid encoder and transition;
2. both learned artifacts missing;
3. valid-shape artifacts containing non-finite weights;
4. transition metadata claiming forbidden policy-only kernel-upgrade coverage; and
5. a collapsed constant-state JEPA training trial.

All checks passed. Valid artifacts loaded and the learned path ran. Missing, non-finite, and forbidden-coverage artifacts did not disable deterministic safety: a self-delete or unsafe upgrade remained blocked. The collapsed training trial preserved diagnostic metrics but emitted no promotable encoder or encoded corpus.

Machine-readable evidence is in `world_model_runtime_benchmark.json`, `world_model_concurrency.json`, and `world_model_failure_modes.json` in this directory.
