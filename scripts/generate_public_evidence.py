#!/usr/bin/env python3
"""Generate FerrumOS public capability and benchmark evidence from source data."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "docs" / "benchmarks"
RAW_DIR = BENCHMARK_DIR / "raw" / "2026-08-13"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def median(values: list[float]) -> float:
    return round(float(statistics.median(values)), 3)


def parse_capabilities() -> dict:
    world_model_path = ROOT / "userland" / "heliox-daemon" / "src" / "cognitive" / "world_model" / "mod.rs"
    mapper_path = ROOT / "userland" / "heliox-daemon" / "src" / "cognitive" / "tool_mapper.rs"
    world_model = world_model_path.read_text(encoding="utf-8")
    mapper = mapper_path.read_text(encoding="utf-8")

    names_match = re.search(r"pub const TOOL_NAMES: \[&str; \d+\] = \[(.*?)\];", world_model, re.S)
    if not names_match:
        raise RuntimeError("could not parse TOOL_NAMES")
    names = re.findall(r'"([a-z0-9_]+)"', names_match.group(1))

    tier_names = ["Observe", "Safe", "Network", "Modify", "Destructive"]
    function_match = re.search(r"fn tool_tier\(.*?match name \{(.*?)_ =>", mapper, re.S)
    if not function_match:
        raise RuntimeError("could not parse tool_tier")
    tiers: dict[str, int] = {}
    arm_pattern = re.compile(
        r'((?:"[a-z0-9_]+"\s*\|\s*)*"[a-z0-9_]+")\s*=>\s*PermissionTier::(\w+)',
        re.S,
    )
    for arm in arm_pattern.finditer(function_match.group(1)):
        tier_name = arm.group(2)
        if tier_name not in tier_names:
            raise RuntimeError(f"unknown permission tier {tier_name}")
        level = tier_names.index(tier_name)
        for name in re.findall(r'"([a-z0-9_]+)"', arm.group(1)):
            tiers[name] = level

    if len(names) != 41 or set(names) != set(tiers):
        raise RuntimeError(
            f"capability registry mismatch: {len(names)} names, {len(tiers)} tiered"
        )

    actions = []
    for name in names:
        tier = tiers[name]
        actions.append(
            {
                "name": name,
                "permission_tier": tier,
                "permission_tier_name": tier_names[tier].lower(),
                "operator_confirmation_required": tier >= 3,
                "world_model_previewed": True,
                "execution_boundary": "ring-3 daemon to capability-gated syscall",
                "verification": "registry and exhaustive QEMU command/bridge audits",
            }
        )

    return {
        "schema_version": 1,
        "project": "FerrumOS",
        "generated_from": [
            str(world_model_path.relative_to(ROOT)).replace("\\", "/"),
            str(mapper_path.relative_to(ROOT)).replace("\\", "/"),
        ],
        "platform": "bootable x86_64 research OS; documented QEMU/Bochs profile",
        "canonical_action_count": len(actions),
        "permission_tier_count": len(tier_names),
        "unknown_action_policy": "destructive tier; fail closed",
        "actions": actions,
        "claim_boundary": [
            "Catalog membership does not mean each action has an independent semantic postcondition verifier.",
            "Camera input is synthetic in the current release; broad physical-PC compatibility is not claimed.",
            "Neural physical intents remain proposal-only and cannot invoke an actuator adapter.",
        ],
    }


def aggregate_benchmarks() -> dict:
    manifest = load_json(RAW_DIR / "manifest.json")
    runtime_runs = [load_json(RAW_DIR / f"runtime-run-{index}.json") for index in range(1, 4)]
    queue_before = [
        load_json(RAW_DIR / f"concurrency-baseline-run-{index}.json") for index in range(1, 4)
    ]
    queue_after = [
        load_json(RAW_DIR / f"concurrency-optimized-run-{index}.json") for index in range(1, 4)
    ]
    neural = load_json(RAW_DIR / "neural-synthetic.json")
    paper = load_json(ROOT / "docs" / "research" / "world_model_paper_evaluation.json")
    training = load_json(ROOT / "docs" / "research" / "world_model_training_config.json")
    physical = load_json(ROOT / "docs" / "research" / "physical_world_model_evaluation.json")

    horizons = []
    for horizon in range(1, 6):
        rows = [run["horizons"][horizon - 1] for run in runtime_runs]
        means = [row["mean_microseconds"] for row in rows]
        horizons.append(
            {
                "horizon": horizon,
                "mean_microseconds_range": [min(means), max(means)],
                "median_run_mean_microseconds": median(means),
                "median_microseconds_across_runs": [row["median_microseconds"] for row in rows],
                "p95_microseconds_across_runs": [row["p95_microseconds"] for row in rows],
                "blocked_previews_each_run": [row["blocked_previews"] for row in rows],
            }
        )

    before_ms = [run["batch_wall_milliseconds"] for run in queue_before]
    after_ms = [run["batch_wall_milliseconds"] for run in queue_after]
    before_median = median(before_ms)
    after_median = median(after_ms)
    improvement = round((before_median - after_median) / before_median * 100.0, 2)

    full_pipeline = training["full_pipeline_seed_evaluation"]
    paper_combined = paper["baselines"]["rules_plus_jepa"]
    paper_mean = paper["baselines"]["rules_plus_mean_delta"]
    physical_combined = physical["safety"]["rules_plus_jepa"]

    summary = {
        "schema_version": 1,
        "snapshot_date": manifest["snapshot_date"],
        "environment": manifest["environment"],
        "paper_release": {
            "release_tag": "world-model-study-v1.0.0",
            "evidence_commit": "42ea7b8",
            "accepted_rows": paper["dataset_accounting"]["stages"][0]["rows"],
            "eligible_transitions": paper["dataset_accounting"]["stages"][3]["rows"],
            "episodes": paper["dataset_accounting"]["all_episodes"],
            "fixture_episodes": 500,
            "rules_plus_jepa_balanced_accuracy": paper_combined["balanced_accuracy"],
            "rules_plus_jepa_false_negative_rate": 1.0 - paper_combined["recall"],
            "rules_plus_jepa_false_positive_rate": 1.0 - paper_combined["specificity"],
            "rules_plus_mean_balanced_accuracy": paper_mean["balanced_accuracy"],
            "five_pipeline_balanced_accuracy_mean": full_pipeline[
                "combined_balanced_accuracy_mean"
            ],
            "claim_boundary": "Authored balanced safety fixture; no material JEPA safety advantage over the per-action mean baseline was established.",
        },
        "current_ring3_preview": {
            "source_commit": manifest["runtime_source_commit"],
            "runs": len(runtime_runs),
            "iterations_per_horizon_per_run": runtime_runs[0]["iterations_per_horizon"],
            "warmup_previews_per_run": runtime_runs[0]["warmup_previews"],
            "accelerator": runtime_runs[0]["accelerator"],
            "horizons": horizons,
            "model_load_milliseconds_range": [
                min(run["model_load"]["pit_elapsed_microseconds"] for run in runtime_runs) / 1000,
                max(run["model_load"]["pit_elapsed_microseconds"] for run in runtime_runs) / 1000,
            ],
            "heap_growth_bytes_each_run": [run["memory"]["heap_growth_bytes"] for run in runtime_runs],
            "scope": runtime_runs[0]["scope"],
        },
        "paired_preview_queue": {
            "baseline_source_commit": manifest["queue_baseline_source_commit"],
            "optimized_source_commit": manifest["queue_optimized_source_commit"],
            "requests_per_run": queue_before[0]["outstanding_requests"],
            "runs_each": len(queue_before),
            "baseline_batch_milliseconds": before_ms,
            "optimized_batch_milliseconds": after_ms,
            "baseline_median_batch_milliseconds": before_median,
            "optimized_median_batch_milliseconds": after_median,
            "median_improvement_percent": improvement,
            "optimized_median_milliseconds_per_serialized_request": round(
                after_median / queue_after[0]["outstanding_requests"], 3
            ),
            "responses_received_each_run": [run["responses_received"] for run in queue_after],
            "execution_records_added_each_run": [
                run["execution_dataset_records_added"] for run in queue_after
            ],
            "guest_fault_free_each_run": [run["guest_fault_free"] for run in queue_after],
            "limitation": queue_after[0]["limitation"],
        },
        "physical_simulator_jepa": {
            "episodes": physical["episodes"],
            "transitions": physical["transitions"],
            "rules_plus_jepa_balanced_accuracy": physical_combined["balanced_accuracy"],
            "false_negatives": physical_combined["fn"],
            "false_positives": physical_combined["fp"],
            "normalized_rollout_error": physical["normalized_rollout_error"],
            "validated_for_gating": physical["validated_for_gating"],
            "claim_boundary": "Deterministic simulator evidence; the artifact is permanently shadow-only and has no actuator authority.",
        },
        "neural_synthetic": {
            "signal_trials": neural["signal"]["trials"],
            "accepted_signal_accuracy": neural["signal"]["accepted_accuracy"],
            "artifact_trials": neural["artifact"]["trials"],
            "artifact_abstention_rate": neural["artifact"]["abstention_rate"],
            "no_control_windows": neural["no_control_soak"]["windows"],
            "emitted_intents": neural["no_control_soak"]["emitted_intents"],
            "passed": neural["passed"],
            "claim_boundary": neural["claim_boundary"],
        },
        "global_limitations": [
            "The paper, physical simulator, and neural synthetic evaluations use different protocols and are not directly comparable.",
            "No live EEG, human neural calibration, robot hardware-in-the-loop, or broad physical-PC benchmark is claimed.",
            "Ring-3 timing uses a virtualized 1 kHz PIT; provider, tool execution, and operator-confirmation latency are excluded.",
            "A passing benchmark is evidence for its named fixture and protocol, not formal safety proof.",
        ],
    }
    return summary


def percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def benchmark_markdown(summary: dict) -> str:
    paper = summary["paper_release"]
    runtime = summary["current_ring3_preview"]
    queue = summary["paired_preview_queue"]
    physical = summary["physical_simulator_jepa"]
    neural = summary["neural_synthetic"]
    runtime_rows = "\n".join(
        f"| H={row['horizon']} | {row['mean_microseconds_range'][0] / 1000:.2f}-{row['mean_microseconds_range'][1] / 1000:.2f} ms | "
        f"{row['median_run_mean_microseconds'] / 1000:.2f} ms | {max(row['p95_microseconds_across_runs']) / 1000:.2f} ms |"
        for row in runtime["horizons"]
    )
    return f"""# FerrumOS Benchmarks and Evidence Boundaries

This page is generated by `scripts/generate_public_evidence.py` from committed raw results and research artifacts. Run `python scripts/generate_public_evidence.py --check` to detect stale public claims.

## Evidence map

| Evidence | Result | What it does not prove |
| --- | --- | --- |
| Published OS world-model study | Rules + JEPA: {percent(paper['rules_plus_jepa_balanced_accuracy'])} balanced accuracy; rules + per-action mean: {percent(paper['rules_plus_mean_balanced_accuracy'])} | JEPA superiority, formal safety, or natural-use prevalence |
| Current Ring-3 preview | Three runs, 100 previews per H=1..5 per run; zero heap growth | Provider, action execution, or approval latency |
| Paired preview queue | 96/96 responses in every run; median batch {queue['optimized_median_batch_milliseconds'] / 1000:.3f} s after optimization | Parallel inference; the daemon intentionally serializes previews |
| Physical JEPA | {percent(physical['rules_plus_jepa_balanced_accuracy'])} balanced accuracy, {physical['false_negatives']} FN, {physical['false_positives']} FP | Real robot safety; the artifact is shadow-only |
| Neural decoder | {neural['signal_trials']}/{neural['signal_trials']} synthetic signals, {neural['artifact_trials']}/{neural['artifact_trials']} artifact abstentions, {neural['emitted_intents']} candidates in {neural['no_control_windows']:,} no-control windows | Live EEG accuracy, usability, or medical performance |

## Published world-model study

The frozen `world-model-study-v1.0.0` release accounts for {paper['accepted_rows']:,} rows from {paper['episodes']:,} episodes; {paper['eligible_transitions']:,} executed transitions enter episode-disjoint fitting/evaluation. On the authored balanced {paper['fixture_episodes']}-episode safety fixture, rules + JEPA reach {percent(paper['rules_plus_jepa_balanced_accuracy'])} balanced accuracy with {percent(paper['rules_plus_jepa_false_negative_rate'])} FNR and {percent(paper['rules_plus_jepa_false_positive_rate'])} FPR. Rules + a per-action mean reach {percent(paper['rules_plus_mean_balanced_accuracy'])}; the report therefore does not establish a material JEPA safety advantage. Five independently trained pipelines average {percent(paper['five_pipeline_balanced_accuracy_mean'])} balanced accuracy.

- [Technical report release](https://github.com/VyomKulshrestha/Ferrum-OS/releases/tag/world-model-study-v1.0.0)
- [Technical report DOI](https://doi.org/10.5281/zenodo.21829808)
- [Dataset DOI](https://doi.org/10.5281/zenodo.21829193)
- [Reproduction guide](research/WORLD_MODEL_PAPER_EVALUATION.md)

## Current Ring-3 preview latency

Environment: {summary['environment']['host_os']}, QEMU {summary['environment']['qemu_version']}, {runtime['accelerator']}, 512 MiB guest RAM. Each of three sequential runs performs 64 H=5 warmups and then 100 measured previews at each horizon.

| Horizon | Run-mean range | Median run mean | Worst recorded p95 |
| --- | ---: | ---: | ---: |
{runtime_rows}

Model loading was {runtime['model_load_milliseconds_range'][0]:.0f}-{runtime['model_load_milliseconds_range'][1]:.0f} ms. Heap growth was {set(runtime['heap_growth_bytes_each_run']).pop()} bytes in every run. PIT percentiles have 1 ms resolution; raw TSC cycles remain in the JSON files.

## Paired preview queue optimization

Three baseline runs at `{queue['baseline_source_commit'][:7]}` took {min(queue['baseline_batch_milliseconds']) / 1000:.3f}-{max(queue['baseline_batch_milliseconds']) / 1000:.3f} s for 96 outstanding requests. After replacing the connected-client ten-tick sleep with a one-tick cooperative cadence at `{queue['optimized_source_commit'][:7]}`, three runs took {min(queue['optimized_batch_milliseconds']) / 1000:.3f}-{max(queue['optimized_batch_milliseconds']) / 1000:.3f} s; median batch time improved {queue['median_improvement_percent']:.2f}%.

Every optimized run returned 96/96 correlated responses, produced zero execution-dataset records, remained deterministic across six action classes, and stayed guest-fault-free. This is queue responsiveness, not parallel inference.

## Post-paper physical and neural evidence

The physical JEPA uses {physical['transitions']:,} transitions from {physical['episodes']:,} deterministic simulator episodes. Rules + JEPA record {percent(physical['rules_plus_jepa_balanced_accuracy'])} balanced accuracy with {physical['false_negatives']} false negative and {physical['false_positives']} false positives. Its artifact is `validated_for_gating=false`; it cannot issue permits or invoke adapters.

The neural decoder evaluation is deterministic synthetic SSVEP evidence only: {neural['signal_trials']} accepted signal trials at {percent(neural['accepted_signal_accuracy'])} accuracy, {neural['artifact_trials']} artifact trials at {percent(neural['artifact_abstention_rate'])} abstention, and zero emitted candidates in {neural['no_control_windows']:,} no-control windows. OS commit still requires pairing, calibration, non-neural arming, a signed preview, and revision checks.

## Reproduce

```powershell
python scripts/verify_world_model_paper_evaluation.py
python scripts/verify_physical_world_model.py
python scripts/evaluate_neural_simulator.py --output target/neural.json
python -m unittest discover -s tools/neurod -p "test_*.py" -v
node scripts/benchmark_world_model_runtime.mjs --iterations 100
node scripts/verify_world_model_preview_concurrency.mjs
python scripts/generate_public_evidence.py --check
```

## Global limitations

""" + "\n".join(f"- {item}" for item in summary["global_limitations"]) + "\n"


def proof_markdown(summary: dict, capabilities: dict) -> str:
    paper = summary["paper_release"]
    queue = summary["paired_preview_queue"]
    physical = summary["physical_simulator_jepa"]
    neural = summary["neural_synthetic"]
    return f"""# FerrumOS Proof Center

FerrumOS is a bootable x86_64 Rust research OS with a deterministic kernel, a Ring-3 agent daemon, capability-gated syscalls, and a provider-independent predictive safety screen. This page links claims to reproducible evidence; it is not a formal safety certificate.

| Surface | Current evidence |
| --- | --- |
| Build | GitHub Actions builds the kernel and userland on Windows with the pinned Rust/LLVM setup |
| Agent actions | {capabilities['canonical_action_count']} canonical operations across {capabilities['permission_tier_count']} permission tiers; unknown tools fail closed |
| OS world model | Published fixture: {percent(paper['rules_plus_jepa_balanced_accuracy'])} rules + JEPA vs {percent(paper['rules_plus_mean_balanced_accuracy'])} rules + mean baseline |
| Ring-3 preview | Three H=1..5 runs, 100 measured previews per horizon, zero heap growth |
| Preview queue | 96/96 responses in every run; {queue['median_improvement_percent']:.2f}% median batch improvement after cadence optimization |
| Physical model | {percent(physical['rules_plus_jepa_balanced_accuracy'])} simulator balanced accuracy; permanently shadow-only |
| Neural input | {neural['signal_trials']} synthetic signals, {neural['artifact_trials']} artifact abstentions, zero candidates in {neural['no_control_windows']:,} no-control windows |

Read the [full benchmark protocol and limitations](docs/BENCHMARKS.md), [machine-readable benchmark summary](benchmarks.json), [capability catalog](capabilities.json), [architecture](docs/ARCHITECTURE.md), [security policy](SECURITY.md), and [published research release](https://github.com/VyomKulshrestha/Ferrum-OS/releases/tag/world-model-study-v1.0.0).

## Claim boundaries

- The current release targets a documented QEMU/Bochs device profile, not broad physical-PC compatibility.
- Camera frames are synthetic; physical camera, gaze, and gesture accuracy are not claimed.
- Neural results are synthetic software evidence, not live EEG or medical evidence.
- Physical-world results use a deterministic simulator; the learned artifact has no actuator authority.
- The published 500-episode safety fixture is authored and balanced; it is not natural-use prevalence.
- JEPA does not materially outperform the per-action mean safety baseline on the published fixture.
- Passing automated checks does not establish formal safety or independent replication.
"""


def write_or_check(path: Path, content: str, check: bool) -> bool:
    if check:
        actual = path.read_text(encoding="utf-8") if path.exists() else None
        if actual != content:
            print(f"STALE {path.relative_to(ROOT)}")
            return False
        print(f"PASS  {path.relative_to(ROOT)}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"WROTE {path.relative_to(ROOT)}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated artifacts are stale")
    args = parser.parse_args()
    capabilities = parse_capabilities()
    benchmarks = aggregate_benchmarks()
    outputs = {
        ROOT / "capabilities.json": dump_json(capabilities),
        ROOT / "benchmarks.json": dump_json(benchmarks),
        ROOT / "proof.md": proof_markdown(benchmarks, capabilities),
        ROOT / "docs" / "BENCHMARKS.md": benchmark_markdown(benchmarks),
    }
    passed = all(write_or_check(path, content, args.check) for path, content in outputs.items())
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
