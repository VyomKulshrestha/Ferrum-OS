#!/usr/bin/env python3
"""Verifier for the tt1d registered study: recomputes every pooled number and gate from the per-run records
of a result file and checks the registration around it.

    python scripts/verify_tt1d.py tep59
    python scripts/verify_tt1d.py provics

Checks: (1) the protocol is registered and the frozen files still match it; (2) the result's own frozen
digests equal the protocol's; (3) each ledger id of the dataset appears in the access ledger exactly once
(twice only if the result says the run was resumed, and then the second entry must say so); (4) pooled
real-event tables, campaign tables, gates and settings recomputed from the per-run records equal the
stored ones; (5) no ceiling rule missed an event its static threshold caught; (6) event and placement
counts match the per-run records; (7) dataset-specific coverage: every attack run of the Tennessee
Eastman archive was scored and the sealed runs are the registered ones; every ProvICS ground-truth row is
either scored or counted as unobserved. Writes docs/research/threshold_transfer_tt1d_verification_<dataset>.json.
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


def same(a, b):
    """Deep equality with a float tolerance (the stored file went through JSON)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or isinstance(a, (str, bool)) or isinstance(b, (str, bool)):
            return a is b or a == b
        return a == b or abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def main():
    name = sys.argv[1]
    S = M.SETUPS[name]
    checks = []
    add = lambda label, ok, detail="": checks.append({"check": label, "pass": bool(ok), "detail": detail})
    protocol = json.loads(M.PROTOCOL.read_text(encoding="utf-8"))
    result = json.loads(M.result_path(name).read_text(encoding="utf-8"))
    add("frozen files match the registration", not M.check_frozen(), str(M.check_frozen()))
    add("result digests equal the registered digests", result["frozen_file_sha256"] == protocol["frozen_file_sha256"])
    rows = [json.loads(line) for line in D.FINAL_LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    for dataset in S.ledger_ids:
        mine = [r for r in rows if r["dataset"] == dataset]
        expected = 2 if result.get("resumed") else 1
        ok = len(mine) == expected and (expected == 1 or "RESUME" in mine[-1]["reason"])
        add(f"ledger: {dataset} opened once", ok, f"{len(mine)} entries")
    again = json.loads(json.dumps(M.assemble(S, result["units"], "final")))
    for key in ("real_events", "campaigns", "gates", "settings"):
        add(f"recomputed {key} equals stored", same(again[key], result[key]))
    worse = 0
    for unit in result["units"]:
        for run in unit["attack_runs"]:
            sc = run["scores"]["D1"]
            for k in ("1.1", "1.25", "1.5"):
                worse += sum(1 for c, s in zip(sc[f"tracker_ceil_{k}"]["found"], sc[f"static_{k}"]["found"]) if s and not c)
            for r in ("spot_gr_ceil_1.25", "daily_ceil_1.25"):
                worse += sum(1 for c, s in zip(sc[r]["found"], sc["static_1.25"]["found"]) if s and not c)
    add("no ceiling rule missed an event its static threshold caught", worse == 0, f"{worse} violations")
    n_events = sum(len(run["events"]) for unit in result["units"] for run in unit["attack_runs"])
    add("event count matches the per-run records", n_events == result["real_events"]["D1"]["events"], str(n_events))
    n_place = sum(len(run["campaigns"]) for unit in result["units"] for run in unit["sealed_runs"])
    add("placement count matches the per-run records", n_place == result["campaigns"]["placements"], str(n_place))
    if name == "tep59":
        n_runs = sum(len(unit["attack_runs"]) for unit in result["units"])
        add("every attack run of the archive was scored", n_runs == sum(len(v) for v in TD.attack_names().values()), str(n_runs))
        roles = TD.clean_roles()
        used = {int(unit["unit"].split("_")[1]): [r["name"] for r in unit["sealed_runs"]] for unit in result["units"]}
        add("sealed runs are the registered ones", all(used[m] == roles[m]["sealed"] for m in TD.MODES))
        add("one placement per sealed run", all(len(r["campaigns"]) == 1 for unit in result["units"] for r in unit["sealed_runs"]))
    else:
        run = result["units"][0]["attack_runs"][0]
        add("32 ground-truth rows are scored or counted as unobserved", len(run["events"]) + run["unobserved_events"] == 32,
            f"{len(run['events'])} scored, {run['unobserved_events']} unobserved")
        add("six placements on the sealed stream", n_place == M.PROVICS_PLACEMENTS)
    ok = all(c["pass"] for c in checks)
    out = ROOT / "docs/research" / f"threshold_transfer_tt1d_verification_{name}.json"
    out.write_text(json.dumps({"schema_version": "threshold-transfer-tt1d-verification", "dataset": name, "overall_pass": ok,
                               "checks": checks, "gates": result["gates"]}, indent=1) + "\n", encoding="utf-8")
    for c in checks:
        print("PASS" if c["pass"] else "FAIL", c["check"], c["detail"])
    print("overall_pass", ok, f"({sum(c['pass'] for c in checks)} of {len(checks)})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
