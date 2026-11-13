#!/usr/bin/env python3
"""tw1c: Zabbix trigger outcomes from one read file (target/tw1c/zabbix/read_<n>.json).

    python -I tools/tw1c/zabbix_summary.py <n>

Counts, per function, campaign and terminal length, the placements whose trigger was PROBLEM for the
terminal hour ("term") and for the hour before it ("before"), and the calculated values of the functions
for the terminal hour.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import tw1c_signals as S  # noqa: E402

OUT = ROOT / "target/tw1c/zabbix"
NAME = re.compile(
    r"p(\d)_(control|frog_hold|frog|loud|subl)_(none|m\d{3})(?:_l(\d+))?(?:_t(\d+))?$"
)


def parse(name):
    m = NAME.match(name)
    mode, camp, mag, lead, tlen = m.groups()
    return {
        "mode": int(mode),
        "campaign": camp,
        "mag": None if mag == "none" else int(mag[1:]) / 100,
        "lead": None if lead is None else int(lead),
        "terminal_len": 0 if mag == "none" else int(tlen or S.TERMINAL),
    }


def main(n):
    d = json.loads((OUT / f"read_{n}.json").read_text(encoding="utf-8"))
    trig = {}
    for t in d["triggers"]:
        _, f, at, name = t["description"].split(" ", 3)
        trig[(f, at, name)] = (t["value"] == "1", t["state"], t["error"])
    calc = {}
    for c in d["calculated"]:
        f, name = re.match(r"c\.(\w+)\[(.+)\]", c["key_"]).groups()
        calc[(f, name)] = (
            float(c["lastvalue"]) if c["lastvalue"] not in ("", None) else None
        )
    names = sorted({k[2] for k in trig})
    unknown = sum(1 for v in trig.values() if v[1] != "0")
    table = {}
    for f in ("bdev", "bwma", "stl"):
        for at in ("term", "before"):
            for tlen in (S.TERMINAL, 1000):
                for c in S.CAMPAIGNS:
                    cell = {}
                    for lead in S.LEADS:
                        cell[f"lead{lead}"] = [
                            sum(
                                trig[(f, at, nm)][0]
                                for nm in names
                                if (p := parse(nm))["campaign"] == c
                                and p["mag"] == m
                                and p["lead"] == lead
                                and p["terminal_len"] == tlen
                            )
                            for m in S.MAGS
                        ]
                    cell["no_step"] = sum(
                        trig[(f, at, nm)][0]
                        for nm in names
                        if (p := parse(nm))["campaign"] == c and p["mag"] is None
                    )
                    table[f"{f} {at} t{tlen} {c}"] = cell
    values = {
        nm: {f: calc.get((f, nm)) for f in ("bdev", "bwma", "avg", "stl")}
        for nm in names
    }
    out = {"read": n, "eval": d.get("eval"), "read_at": d.get("read_at"), "triggers_not_normal": unknown,
           "problem_events": len(d["events"]), "table": table, "terminal_hour_values": values}  # fmt: skip
    (OUT / f"summary_read_{n}.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8"
    )
    for k, v in table.items():
        print(f"{k:32s} lead0 {v['lead0']} lead {v['lead1000']} no-step {v['no_step']}")
    print("triggers not in normal state:", unknown, "problem events:", len(d["events"]))


if __name__ == "__main__":
    main(int(sys.argv[1]))
