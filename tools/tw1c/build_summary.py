#!/usr/bin/env python3
"""tw1c: collect the per-product result tables into target/tw1c/tw1c_summary.json.

python -I tools/tw1c/build_summary.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import repro_env  # noqa: E402

T = ROOT / "target/tw1c"


def load(path):
    p = T / path
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main():
    out = {
        "status": "exploratory (tw1c); Tennessee Eastman score cache; no dataset opened",
        "plan": "docs/research/thresholds_in_the_wild_tw1c_signal_plan.md (b7660df, amendments 1 and 2)",
        "magnitudes_over_tau0": [1.05, 1.25, 1.5, 2.0],
        "count_unit": "placements of 7 whose product alarm fired in the terminal window",
        "products": {
            "opensearch": {
                "env": load("opensearch/env.json"),
                "tables": load("opensearch/summary_table.json"),
                "read_from_product": "anomaly_grade > 0 per interval, results index",
            },
            "netdata": {
                "env": load("netdata/env.json"),
                "tables": load("netdata/summary_table.json"),
                "read_from_product": "per-dimension anomaly bit per second, /api/v1/data",
                "compressed": "training window 1 h, train every 1 h; campaign 4,000 s",
            },
            "zabbix": {
                "before_terminal_hour": load("zabbix/summary_read_3.json"),
                "terminal_hour": load("zabbix/summary_read_4.json"),
                "read_from_product": "trigger value after the server's hourly evaluation; calculated items",
            },
        },
        "libraries": {
            "streamad": {
                "versions": (load("streamad/work/out/tw1a_mode0_full.json") or {}).get(
                    "versions"
                ),
                "summary": load("streamad/work/out/tw1a_summary.json"),
            },
            "htm.core": {
                "versions": load("htm/work/out/versions.json"),
                "summary": load("htm/work/out/tw1a_summary.json"),
            },
        },
    }
    for k in ("opensearch", "netdata", "zabbix"):
        for sub in ("terminal_hour", "before_terminal_hour"):
            v = out["products"][k].get(sub)
            if v:
                v.pop("terminal_hour_values", None)
    path = T / "tw1c_summary.json"
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    repro_env.stamp_json(path)
    print("written", path)


if __name__ == "__main__":
    repro_env.pin_from_environment()
    main()
