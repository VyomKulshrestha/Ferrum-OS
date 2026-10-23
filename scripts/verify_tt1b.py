#!/usr/bin/env python3
"""Verify the tt1b registered finals: registration before access, one tt1b access per dataset, frozen
files unchanged, gates recomputed from the stored result.

Writes docs/research/threshold_transfer_tt1b_verification.json; exits non-zero on any failure. Datasets
without a result yet (SWaT, WADI before they arrive) are listed as pending, not failed.
"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_data as D
import tt1b_final as B

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/threshold_transfer_tt1b_verification.json"
REASON = "tt1b final: registered replication"


def commit_time(path):
    out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%aI", "--", str(path)], cwd=ROOT,
                         capture_output=True, text=True, timeout=30).stdout.split()
    return datetime.datetime.fromisoformat(out[-1]) if out else None


def main():
    checks, pending = [], []
    add = lambda name, ok, detail="": checks.append({"check": name, "pass": bool(ok), "detail": detail})
    protocol = json.loads(B.PROTOCOL.read_text(encoding="utf-8"))
    frozen = protocol["frozen_file_sha256"]
    add("protocol lists a digest for every frozen file", set(frozen) == set(B.FROZEN_FILES))
    registered = commit_time(B.PROTOCOL.relative_to(ROOT))
    add("protocol is committed", registered is not None, str(registered))
    rows = [json.loads(line) for line in D.FINAL_LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    for ds in B.DATASETS:
        path = ROOT / "docs/research" / f"threshold_transfer_tt1b_result_{ds}.json"
        mine = [r for r in rows if r["dataset"] == ds and r["reason"].startswith(REASON)]
        if not path.exists() and not mine:
            pending.append(ds)
            continue
        add(f"{ds}: exactly one tt1b access", len(mine) == 1, f"{len(mine)} ledger rows")
        others = [r for r in rows if r["dataset"] == ds and not r["reason"].startswith(REASON)]
        add(f"{ds}: no other access, or post-hoc after the final",
            all(r["reason"].startswith("post-hoc") and mine and r["at"] > mine[0]["at"] for r in others),
            "; ".join(r["reason"] for r in others))
        if mine:
            at = datetime.datetime.fromisoformat(mine[0]["at"])
            add(f"{ds}: access after registration commit", registered is not None and at > registered,
                f"access {at.isoformat()} vs registration {registered}")
        add(f"{ds}: result file exists", path.exists())
        if path.exists():
            res = json.loads(path.read_text(encoding="utf-8"))
            add(f"{ds}: result ran with the registered frozen files", res.get("frozen_file_sha256") == frozen)
            add(f"{ds}: stored gates equal gates recomputed from the result", B.gates(res) == res.get("gates"))
    passed = all(c["pass"] for c in checks)
    OUT.write_text(json.dumps({"schema_version": "threshold-transfer-tt1b-verification", "passed": passed,
                               "pending_datasets": pending, "checks": checks}, indent=1) + "\n", encoding="utf-8")
    for c in checks:
        print(("PASS " if c["pass"] else "FAIL ") + c["check"] + (f"  ({c['detail']})" if c["detail"] else ""))
    print(f"{sum(c['pass'] for c in checks)}/{len(checks)} checks pass; pending: {pending}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
