#!/usr/bin/env python3
"""fi1 workstream A: collect every number of round 1 into docs/research/fi1_monitor_round1.json.

Reads target/real-telemetry/fi1/monitor/{results,diagnosis.json,check_ledger.jsonl}; computes nothing new.

    python scripts/fi1_monitor_collect.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "target/real-telemetry/fi1/monitor"
OUT = ROOT / "docs/research/fi1_monitor_round1.json"


def load(name):
    p = WORK / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def strip(diag):
    """The diagnosis without the long per-recording lists."""
    out = {}
    for unit, d in (diag or {}).items():
        d = dict(d)
        loro = d.get("calibration_loro") or {}
        recs = loro.get("recordings", [])
        d["calibration_loro"] = {
            "tau_max_over_min": loro.get("tau_max_over_min"),
            "recordings": len(recs),
            "worst_fa_ratio_on_other_recordings": max(
                (r["fa_ratio_on_others_max"] or 0) for r in recs
            )
            if recs
            else None,
        }
        sc = d.get("scales") or {}
        rec = sc.get("recordings", [])
        d["scales"] = {
            "attack_free_recordings": len(rec),
            "attack_free_max_channel_std_ratio": max(
                r["std_ratio_h1"]["max"] for r in rec
            )
            if rec
            else None,
            "test_unlabelled_std_ratio_h1": sc.get("test_unlabelled_std_ratio_h1"),
            "test_unlabelled_mean_over_sig_h1": sc.get(
                "test_unlabelled_mean_over_sig_h1"
            ),
        }
        out[unit] = d
    return out


def main():
    ledger = WORK / "check_ledger.jsonl"
    doc = {
        "schema_version": "fi1-monitor-round1",
        "status": "exploratory; every dataset is spent (plan docs/research/ferrumos_improvement_fi1_plan.md)",
        "reproduction": {
            "registered": load("results/registered.json"),
            "tep_registered_scores_through_harness": load(
                "results/reproduce_tep_cache.json"
            ),
        },
        "selection": {
            "table": load("results/selection_table.json"),
            "verdicts": load("results/selection_verdicts.json"),
        },
        "diagnosis": strip(load("diagnosis.json")),
        "check": {
            "table": load("results/check_table.json"),
            "verdicts": load("results/check_verdicts.json"),
            "ledger": [
                json.loads(x)
                for x in ledger.read_text(encoding="utf-8").splitlines()
                if x
            ]
            if ledger.exists()
            else [],
        },
    }
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
