#!/usr/bin/env python3
"""tw1c: per-product tables from the result files under target/tw1c/ (counts over the seven placements).

    python -I tools/tw1c/summarize.py opensearch|netdata

Prints, per campaign, the terminal steps caught at 1.05 / 1.25 / 1.5 / 2 tau0 at lead 0 and after the lead,
and for the series without a terminal step the placements with alarms in the campaign and in the two
terminal windows.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import tw1c_signals as S  # noqa: E402

T = ROOT / "target/tw1c"


def rows(product):
    if product == "opensearch":
        out = []
        for p in sorted((T / "opensearch").glob("mode*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("stage") == "done":
                out += d["rows"]
        return out
    return [
        r
        for r in json.loads((T / product / "result.json").read_text())["rows"]
        if "alarms_total" in r
    ]


def table(rs, key="hit"):
    out = {}
    for c in S.CAMPAIGNS:
        cell = {}
        for lead in S.LEADS:
            cell[f"lead{lead}"] = [
                sum(bool(r.get(key)) for r in rs if r["campaign"] == c and r["mag"] == m and r["lead"] == lead)
                for m in S.MAGS
            ]  # fmt: skip
        none = [r for r in rs if r["campaign"] == c and r["mag"] is None]
        cell["no_step_placements"] = len(none)
        cell["no_step_alarm_in_campaign"] = sum(r["alarms_campaign"] > 0 for r in none)
        cell["no_step_alarm_steps_in_campaign"] = [r["alarms_campaign"] for r in none]
        cell["no_step_alarm_lead0_window"] = sum(
            r["alarms_lead0_window"] > 0 for r in none
        )
        cell["no_step_alarm_lead_window"] = sum(
            r["alarms_lead_window"] > 0 for r in none
        )
        cell["no_step_alarm_history"] = sum(r["alarms_history"] > 0 for r in none)
        out[c] = cell
    return out


if __name__ == "__main__":
    product = sys.argv[1]
    rs = rows(product)
    res = {"series": len(rs), "hit": table(rs)}
    if product == "opensearch":
        res["hit_monitor_default"] = table(rs, "hit_monitor_default")
    print(json.dumps(res, indent=1))
