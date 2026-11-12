#!/usr/bin/env python3
"""Collect round 2 of the fi1 monitor workstream into docs/research/fi1_monitor_round2.json (EXPLORATORY).

Reads the round-2 selection table and verdicts, the round-2 check table and verdicts (a second use of the check set),
round 1's stored baseline check numbers, and the check ledger. Computes nothing new beyond means of stored numbers.

    python scripts/fi1_monitor_collect_r2.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "target/real-telemetry/fi1/monitor/results"
LEDGER = ROOT / "target/real-telemetry/fi1/monitor/check_ledger.jsonl"
OUT = ROOT / "docs/research/fi1_monitor_round2.json"

KEEP = (
    "events",
    "detected",
    "onset_detected",
    "onset_recall",
    "any_recall",
    "chance_onset_recall",
    "onset_recall_net_of_chance",
    "unlabelled_alarm_share",
    "fa_per_day",
    "fa_ratio_to_budget",
    "sealed_fa_ratio_to_budget",
    "average_precision",
    "median_seconds_to_first_alarm",
    "median_episode_seconds",
    "first",
    "follower",
    "unlabelled_share_outside_range",
    "alarm_share_inside_range",
    "events_starting_inside_range",
    "onset_recall_inside_range",
    "tau",
)


def load(name):
    return json.loads((RES / name).read_text(encoding="utf-8"))


def trim(table):
    return {
        m: {ds: {k: r[k] for k in KEEP if k in r} for ds, r in rows.items()}
        for m, rows in table.items()
    }


def mean_net(rows):
    v = [
        r["onset_recall_net_of_chance"]
        for r in rows.values()
        if r.get("onset_recall_net_of_chance") is not None
    ]
    return float(np.mean(v)) if v else None


def main():
    sel = load("selection_table_r2.json")
    selv = load("selection_verdicts_r2.json")
    chk = load("check_table_r2.json")
    chkv = load("check_verdicts_r2.json")
    r1 = load("check_table.json")
    ledger = [
        json.loads(line)
        for line in LEDGER.read_text(encoding="utf-8").splitlines()
        if line
    ]
    out = {
        "study": "fi1 workstream A, monitor round 2 (EXPLORATORY; check results are a second use of the check set)",
        "plan": "docs/research/ferrumos_improvement_fi1_plan.md, note 'monitor round 2 and the second use of the check set'",
        "report": "docs/research/fi1_reports/monitor_round2.md",
        "selection_rule_commit": "60d8f91",
        "benchmark_additions_commit": "aea4022",
        "selection_outcome_commit": "3f42ee3",
        "threads": "OMP, OpenBLAS, MKL = 2; no refit in round 2 (LightGBM not run); no GPU",
        "selection": {
            "baseline": selv["baseline"],
            "candidates": selv["candidates"],
            "table": trim(sel),
        },
        "check": {
            "baseline_round1": {
                ds: {k: r1["d1"][ds][k] for k in KEEP if k in r1["d1"][ds]}
                for ds in r1["d1"]
            },
            "baseline_round2_rescore": trim({"d1": chk["d1"]})["d1"],
            "candidates": trim({k: v for k, v in chk.items() if k != "d1"}),
            "verdicts": chkv["verdicts"],
            "baseline_summary": chkv["baseline"],
            "mean_onset_net_of_chance_stream_datasets": {
                m: mean_net(rows) for m, rows in chk.items()
            },
            "round1_best": {
                m: r1[m]
                and {
                    ds: {
                        k: r1[m][ds][k]
                        for k in (
                            "onset_detected",
                            "events",
                            "onset_recall",
                            "unlabelled_alarm_share",
                        )
                    }
                    for ds in r1[m]
                }
                for m in ("mad+second", "second")
            },
        },
        "check_ledger": ledger,
    }
    OUT.write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print("wrote", OUT.relative_to(ROOT))
    for m, v in out["check"]["mean_onset_net_of_chance_stream_datasets"].items():
        print(m, round(v, 4))


if __name__ == "__main__":
    main()
