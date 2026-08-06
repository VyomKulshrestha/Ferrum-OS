# Natural-use world-model evaluation protocol

## Purpose and claim boundary

This protocol measures the operational cost and labelled safety performance of
the FerrumOS gate on naturally proposed actions. It is separate from the
balanced authored stress fixture and the QEMU safe-only replay. Until two
independent annotators complete adjudication, natural-use logs may report only
action volume, gate alerts, confirmation outcomes, action mix, and latency—not
precision, recall, or dangerous-action prevalence.

## Privacy-bounded collection

Every canonical dispatch emits `world-model-telemetry-v1` with a tick, action
name, allow/block decision, risk, lookahead, raw guest TSC cycle counts,
execution/success flags, and confirmation status. It intentionally excludes:

- prompts, goals, arguments, paths, hosts, and user text;
- provider and model identity;
- tool output and screen/audio content;
- account or device identifiers.

Collect one serial log per session and parse it with:

```text
python scripts/collect_world_model_natural_telemetry.py session-*.log \
  --jsonl-out target/natural-use/telemetry.jsonl \
  --summary-out target/natural-use/summary.json
```

TSC values are not converted to time by this collector. Use the calibrated
in-guest benchmark for microsecond latency claims.

## Sampling target

The preregistered target is at least seven days, 20 distinct task families,
1,000 proposed actions, and 100 actions from destructive or resource-changing
classes where operationally safe to observe. Report sessions and action counts
even if the target is not met. Do not supplement sparse natural danger cases
with authored cases while calling the result natural prevalence.

## Outcomes

Report total proposed actions, blocks per 1,000 actions, confirmations by
status, successful executions, action mix, median/p95 calibrated gate latency,
task completion, abandoned tasks, human overrides, and independently
adjudicated TP/FN/FP/TN. A task-level companion sheet may contain task outcome
and elapsed time but must use the telemetry `item_id` rather than raw user text.

## Human adjudication

Use `WORLD_MODEL_LABELING_RUBRIC.md` and the annotation-pack scripts. Annotators
must not see model/rule decisions, risk scores, provider identity, or each
other's labels. Report raw agreement, Cohen's kappa, uncertain rate, all
disagreements, adjudication procedure, and final confusion matrices.

## Stopping and disclosure rules

- Never report precision/recall from unlabelled telemetry.
- Preserve failed and abandoned tasks in the denominator.
- Report missing sessions, collector failures, and operator exclusions.
- Stop destructive testing before real user or non-disposable data is at risk.
- Treat deployment results as workload-specific, not as a formal guarantee.
