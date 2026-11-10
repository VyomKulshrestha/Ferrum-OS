#!/usr/bin/env python3
"""Verifier for the tt1d registered study: recomputes every pooled number and gate from the per-run records
of the result file and checks the registration around it.

    python scripts/verify_tt1d.py

Checks: (1) the protocol is registered and the frozen files still match it; (2) the result's own frozen
digests equal the protocol's; (3) each dataset id appears in the access ledger exactly once (twice only
if the result says the run was resumed, and then the second entry must say so); (4) pooled real-event
tables, campaign tables and gates recomputed from the per-run records equal the stored ones; (5) every
ceiling rule detected at least what its static threshold detected, event by event; (6) the event and
placement counts match the per-run records; (7) the file roles of the attack-free runs used are the
registered ones. Writes docs/research/threshold_transfer_tt1d_verification.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_data as D
import tt1d_data as TD
import tt1d_final as M

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/threshold_transfer_tt1d_verification.json"


def same(a, b):
    """Deep equality with a float tolerance (the stored file went through JSON)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return a is b
        return a == b or abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def main():
    checks = []
    add = lambda name, ok, detail="": checks.append({"check": name, "pass": bool(ok), "detail": detail})
    protocol = json.loads(M.PROTOCOL.read_text(encoding="utf-8"))
    result = json.loads(M.RESULT.read_text(encoding="utf-8"))
    add("frozen files match the registration", not M.check_frozen(), str(M.check_frozen()))
    add("result digests equal the registered digests", result["frozen_file_sha256"] == protocol["frozen_file_sha256"])
    rows = [json.loads(line) for line in D.FINAL_LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    for dataset in TD.LEDGER_IDS:
        mine = [r for r in rows if r["dataset"] == dataset]
        expected = 2 if result.get("resumed") else 1
        ok = len(mine) == expected and (expected == 1 or "RESUME" in mine[-1]["reason"])
        add(f"ledger: {dataset} opened once", ok, f"{len(mine)} entries")
    again = M.assemble(result["modes"], "final")
    for key in ("real_events", "campaigns", "gates", "settings"):
        add(f"recomputed {key} equals stored", same(json.loads(json.dumps(again[key])), result[key]))
    worse = 0
    for mode in result["modes"]:
        for run in mode["attack_runs"]:
            sc = run["scores"]["D1"]
            for k in ("1.1", "1.25", "1.5"):
                worse += sum(1 for c, s in zip(sc[f"tracker_ceil_{k}"]["found"], sc[f"static_{k}"]["found"]) if s and not c)
            worse += sum(1 for c, s in zip(sc["spot_gr_ceil_1.25"]["found"], sc["static_1.25"]["found"]) if s and not c)
            worse += sum(1 for c, s in zip(sc["daily_ceil_1.25"]["found"], sc["static_1.25"]["found"]) if s and not c)
    add("no ceiling rule missed an event its static threshold caught", worse == 0, f"{worse} violations")
    n_events = sum(len(run["events"]) for mode in result["modes"] for run in mode["attack_runs"])
    add("event count matches the per-run records", n_events == result["real_events"]["D1"]["events"], str(n_events))
    n_runs = sum(len(mode["attack_runs"]) for mode in result["modes"])
    names = TD.attack_names()
    add("every attack run of the archive was scored", n_runs == sum(len(v) for v in names.values()), str(n_runs))
    roles = TD.clean_roles()
    used = {m["mode"]: [r["name"] for r in m["sealed_runs"]] for m in result["modes"]}
    add("sealed runs are the registered ones", all(used[m] == roles[m]["sealed"] for m in used))
    add("one placement per sealed run", result["campaigns"]["placements"] == sum(len(v) for v in used.values()))
    ok = all(c["pass"] for c in checks)
    OUT.write_text(json.dumps({"schema_version": "threshold-transfer-tt1d-verification", "overall_pass": ok,
                               "checks": checks, "gates": result["gates"]}, indent=1) + "\n", encoding="utf-8")
    for c in checks:
        print("PASS" if c["pass"] else "FAIL", c["check"], c["detail"])
    print("overall_pass", ok, f"({sum(c['pass'] for c in checks)} of {len(checks)})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
