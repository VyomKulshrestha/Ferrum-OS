#!/usr/bin/env python3
"""Collect the round-3 thread-count measurements into docs/research/fi1_pipeline_round3.json.

Reads the comparison files under target/fi1-pipeline3/ (written by fi1_thread_compare.py,
fi1_thread_where.py, fi1_thread_incident.py and fi1_thread_crossdomain.py) and keeps, per study, the
runs, the largest relative change, every flip and the closest gate. Writes nothing else.

    python scripts/fi1_thread_compare.py robustness
    python scripts/fi1_thread_compare.py sweep
    python scripts/fi1_thread_compare.py os-world-model
    python scripts/fi1_pipeline_round3_summary.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "target" / "fi1-pipeline3"
OUT = ROOT / "docs" / "research" / "fi1_pipeline_round3.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def slim_gates(gates):
    return [
        {
            k: g[k]
            for k in (
                "name",
                "kind",
                "value",
                "op",
                "threshold",
                "passed",
                "margin",
                "relative_margin",
            )
        }
        for g in gates
    ]


def study_block(compare: dict | None) -> dict | None:
    if compare is None:
        return None
    runs = {}
    for label, row in compare["runs"].items():
        entry = {
            k: v for k, v in row.items() if k not in ("gates", "stored_gates", "run")
        }
        entry["gates"] = slim_gates(row["gates"])
        runs[label] = entry
    largest = max(
        (
            row["diff"]["largest_relative_change"]
            for label, row in compare["runs"].items()
            if label != "committed" and "diff" in row
        ),
        default=None,
    )
    return {
        **{k: v for k, v in compare.items() if k not in ("runs", "closest")},
        "largest_relative_change_any_run": largest,
        "closest_gate_per_name": {
            name: {
                k: g[k]
                for k in (
                    "run",
                    "value",
                    "op",
                    "threshold",
                    "passed",
                    "relative_margin",
                )
            }
            for name, g in compare["closest"].items()
        },
        "runs": runs,
    }


def main() -> None:
    summary = {
        "schema": "fi1-pipeline-round3-v1",
        "status": "exploratory; no committed result was recomputed in place or replaced",
        "machine": "24 logical CPUs; OpenBLAS 0.3.29 (Haswell kernel); NumPy 2.2.6; torch 2.6.0 CPU",
        "physical_jepa_robustness": study_block(load(WORK / "compare_robustness.json")),
        "physical_jepa_v3_sweep": study_block(load(WORK / "compare_sweep.json")),
        "os_world_model": study_block(load(WORK / "compare_os-world-model.json")),
        "where": {
            name: load(WORK / f"{name}.json")
            for name in ("where_1_4", "where_1_4_24")
            if (WORK / f"{name}.json").exists()
        },
        "incident_dynamics": {
            p.stem: {
                k: v
                for k, v in load(p).items()
                if k not in ("environment", "inference")
            }
            | {
                "inference_max_abs": {
                    k: max(v["max_abs_errors"], v["max_abs_scores"])
                    for k, v in load(p)["inference"].items()
                }
            }
            for p in sorted((WORK / "incident").glob("v*_t*.json"))
        },
        "cross_domain_archived_inference": {
            p.stem: {k: v for k, v in load(p).items() if k != "environment"}
            for p in sorted(WORK.glob("crossdomain_t*.json"))
        },
    }
    for key in list(summary["where"]):
        for item in (
            summary["where"][key].get("training", {}).get("comparisons", {}).values()
        ):
            trace = item["relative_weight_difference_by_checkpoint"]
            item["relative_weight_difference_by_checkpoint"] = trace[::4] + trace[-1:]
        summary["where"][key].pop("environment", None)
    OUT.write_text(
        json.dumps(summary, indent=1, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("wrote", OUT)


if __name__ == "__main__":
    main()
