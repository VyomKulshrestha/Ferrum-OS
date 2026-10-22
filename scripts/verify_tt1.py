#!/usr/bin/env python3
"""Verify the tt1 registered finals: registration before access, single access per dataset, frozen
files unchanged, gates recomputed from the stored result, detection-v2 run under amendment 2.

Writes docs/research/threshold_transfer_tt1_verification.json and exits non-zero on any failure.
"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_data as D
import tt1_final as F

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/threshold_transfer_tt1_verification.json"
DV2_WINDOW = {d: F.STREAMS[d]["detection_v2_window"] for d in F.STREAMS}


def commit_time(path):
    """Author time of the first commit that added the file (the registration commit)."""
    out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%aI", "--", str(path)], cwd=ROOT,
                         capture_output=True, text=True, timeout=30).stdout.split()
    return datetime.datetime.fromisoformat(out[-1]) if out else None


def main():
    checks = []
    add = lambda name, ok, detail="": checks.append({"check": name, "pass": bool(ok), "detail": detail})
    protocol = json.loads(F.PROTOCOL.read_text(encoding="utf-8"))
    frozen = protocol["frozen_file_sha256"]
    add("protocol lists a digest for every frozen file", set(frozen) == set(F.FROZEN_FILES))
    registered = commit_time(F.PROTOCOL.relative_to(ROOT))
    add("protocol is committed", registered is not None, str(registered))
    rows = [json.loads(line) for line in D.FINAL_LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    for ds in F.DATASETS:
        mine = [r for r in rows if r["dataset"] == ds]
        add(f"{ds}: exactly one final access", len(mine) == 1, f"{len(mine)} ledger rows")
        if mine:
            add(f"{ds}: access is the tt1 shared final", mine[0]["reason"].startswith("tt1 shared final"), mine[0]["reason"])
            at = datetime.datetime.fromisoformat(mine[0]["at"])
            add(f"{ds}: access after registration commit", registered is not None and at > registered,
                f"access {at.isoformat()} vs registration {registered}")
        path = ROOT / "docs/research" / f"threshold_transfer_tt1_result_{ds}.json"
        add(f"{ds}: result file exists", path.exists())
        if not path.exists():
            continue
        res = json.loads(path.read_text(encoding="utf-8"))
        add(f"{ds}: result ran with the registered frozen files", res.get("frozen_file_sha256") == frozen)
        if ds == "hai-20.07":
            again = F.primary_gates(res)
            add("hai-20.07: stored gates equal gates recomputed from the result", again == res.get("gates"))
        if ds in F.STREAMS:
            dv = ROOT / "docs/research" / f"real_telemetry_detection_v2_result_{ds}.json"
            add(f"{ds}: detection-v2 result exists", dv.exists())
            if dv.exists():
                dres = json.loads(dv.read_text(encoding="utf-8"))
                add(f"{ds}: detection-v2 ran inside the shared final", bool(dres.get("shared_final")))
                add(f"{ds}: detection-v2 window per amendment 2", dres.get("window") == DV2_WINDOW[ds],
                    f"window {dres.get('window')}")
    passed = all(c["pass"] for c in checks)
    OUT.write_text(json.dumps({"schema_version": "threshold-transfer-tt1-verification", "passed": passed,
                               "checks": checks}, indent=1) + "\n", encoding="utf-8")
    for c in checks:
        print(("PASS " if c["pass"] else "FAIL ") + c["check"] + (f"  ({c['detail']})" if c["detail"] else ""))
    print(f"{sum(c['pass'] for c in checks)}/{len(checks)} checks pass")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
