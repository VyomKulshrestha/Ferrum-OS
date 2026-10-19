#!/usr/bin/env python3
"""Read-only verifier for the real-telemetry studies rt1 and rt2 (no upstream data needed).

Checks the protocol -> selection -> result digest chain, the final-access ledgers (one registered
final read per dataset, after the selection freeze commit, plus labelled post-hoc reads only), and
recomputes every detector's event counts, recall, paired bootstrap intervals and registered gates
from the per-event outcomes stored in the result files. Writes real_telemetry_verification.json.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "docs/research"
OUT = R / "real_telemetry_verification.json"
BOOT_SEED = 51004


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha_candidates(path: Path) -> set[str]:
    raw = path.read_bytes()
    norm = raw.decode("utf-8").replace("\r\n", "\n")
    return {hashlib.sha256(v).hexdigest() for v in (raw, norm.encode(), norm.replace("\n", "\r\n").encode())}


def commit_time(path: str) -> datetime:
    out = subprocess.check_output(["git", "log", "--diff-filter=A", "--format=%cI", "--", path], cwd=ROOT, text=True).split()
    return datetime.fromisoformat(out[-1]).astimezone(timezone.utc)


def ledger(path: Path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def recheck_study(result, detectors, comparisons, level_primary, primary_pairs, budget, events_key):
    checks = {}
    for name, block in result[events_key].items():
        for d in detectors:
            found = [e["detected"] for e in block["per_event"][d]]
            s = block["detectors"][d]
            checks[f"{name}:{d}:counts"] = (len(found) == s["events"] and sum(found) == s["detected"]
                                            and abs(np.mean(found) - s["event_recall"]) < 1e-12)
        for key, (a, b, lv) in comparisons.items():
            fa = [e["detected"] for e in block["per_event"][a]]
            fb = [e["detected"] for e in block["per_event"][b]]
            redo = C.paired_event_bootstrap(fa, fb, reps=10_000, level=lv, seed=BOOT_SEED)
            stored = block["comparisons" if "comparisons" in block else "secondary"].get(key) or block.get("primary_comparisons", {}).get(key)
            checks[f"{name}:{key}:bootstrap"] = stored is not None and all(
                abs(redo[k] - stored[k]) < 1e-12 if not isinstance(redo[k], list) else
                max(abs(x - y) for x, y in zip(redo[k], stored[k])) < 1e-12 for k in redo)
    return checks


def main() -> None:
    checks, notes = {}, {}
    # ---------------- rt1 ----------------
    p1, s1, r1 = R / "real_telemetry_protocol_v1.json", R / "real_telemetry_selection_v1.json", R / "real_telemetry_result_v1.json"
    sel1, res1 = json.loads(s1.read_text(encoding="utf-8")), json.loads(r1.read_text(encoding="utf-8"))
    checks["rt1_selection_binds_protocol"] = sel1["protocol_sha256"] in text_sha_candidates(p1)
    checks["rt1_result_binds_selection"] = res1["selection_sha256"] in text_sha_candidates(s1)
    checks["rt1_selection_recorded_no_final_access"] = sel1["final_access_before_freeze"] is False
    led = ledger(R / "artifacts/real-telemetry-rt1/final_access.jsonl")
    finals = [e for e in led if e["reason"] == "registered final evaluation rt1"]
    checks["rt1_one_final_read_per_dataset"] = sorted(e["dataset"] for e in finals) == ["hai-22.04", "smd"]
    freeze_time = commit_time("docs/research/real_telemetry_selection_v1.json")
    checks["rt1_final_reads_after_selection_commit"] = all(datetime.fromisoformat(e["at"]) > freeze_time for e in finals)
    detectors1 = ["D0", "DR", "D1", "D2", "D3"]
    comps1 = {"D2_vs_D1": ("D1", "D2", 0.975), "D2_vs_D3": ("D3", "D2", 0.975), "D1_vs_D0": ("D0", "D1", 0.975),
              "D1_vs_DR": ("DR", "D1", 0.975)}
    checks.update({f"rt1:{k}": v for k, v in recheck_study(res1, detectors1, comps1, 0.975, None, None, "datasets").items()})
    for name, block in res1["datasets"].items():
        g = block["primary_gate"]
        redo = g["miss_reduction"] >= 0.20 and g["interval"][0] > 0 and g["false_episodes_per_day"] <= 2 * g["budget_per_day"]
        checks[f"rt1:{name}:primary_gate_recomputed"] = redo == g["passes"]
    checks["rt1_primary_rule_failed_as_reported"] = res1["primary_success_rule_passes"] is False
    notes["rt1_hai_D1"] = res1["datasets"]["hai-22.04"]["detectors"]["D1"]["detected"]
    # ---------------- rt2 (if present) ----------------
    r2 = R / "real_telemetry_result_rt2.json"
    if r2.exists():
        p2, s2 = R / "real_telemetry_protocol_rt2.json", R / "real_telemetry_selection_rt2.json"
        sel2, res2 = json.loads(s2.read_text(encoding="utf-8")), json.loads(r2.read_text(encoding="utf-8"))
        checks["rt2_selection_binds_protocol_and_amendment"] = (sel2["protocol_sha256"] in text_sha_candidates(p2)
                                                               and sel2["amendment_sha256"] in text_sha_candidates(R / "real_telemetry_protocol_rt2_amendment1.json"))
        checks["rt2_result_binds_selection"] = res2["selection_sha256"] in text_sha_candidates(s2)
        led2 = [e for e in ledger(R / "artifacts/real-telemetry-rt2/final_access.jsonl") if e["dataset"] in ("hai-21.03", "hai-23.05")]
        attempt1 = [e for e in led2 if e["reason"] == "registered final evaluation rt2"]
        finals2 = [e for e in led2 if e["reason"] == "registered final evaluation rt2 attempt 2 (amendment 2)"]
        failed = json.loads((R / "real_telemetry_rt2_failed_attempt1.json").read_text(encoding="utf-8"))
        checks["rt2_attempt1_retained_and_matches_ledger"] = attempt1 == failed["ledger_entries"]
        checks["rt2_one_attempt2_read_per_release"] = sorted(e["dataset"] for e in finals2) == ["hai-21.03", "hai-23.05"]
        checks["rt2_no_other_test_reads"] = len(led2) == len(attempt1) + len(finals2)
        t2 = commit_time("docs/research/real_telemetry_selection_rt2.json")
        t3 = commit_time("docs/research/real_telemetry_protocol_rt2_amendment2.json")
        checks["rt2_attempt1_after_selection_commit"] = all(datetime.fromisoformat(e["at"]) > t2 for e in attempt1)
        checks["rt2_attempt2_after_amendment2_commit"] = all(datetime.fromisoformat(e["at"]) > t3 for e in finals2)
        detectors2 = ["D0", "DR", "D1", "D2", "D3", "D2c"]
        comps2 = {"D1_vs_D0": ("D0", "D1", 0.9875), "D1_vs_DR": ("DR", "D1", 0.9875), "D2c_vs_D1": ("D1", "D2c", 0.95),
                  "D2_vs_D1": ("D1", "D2", 0.95), "D3_vs_D1": ("D1", "D3", 0.95), "D2c_vs_D3": ("D3", "D2c", 0.95)}
        checks.update({f"rt2:{k}": v for k, v in recheck_study(res2, detectors2, comps2, 0.9875, None, None, "releases").items()})
        for name, block in res2["releases"].items():
            prim = block["primary_comparisons"]
            redo = all(p["miss_reduction"] >= 0.20 and p["miss_reduction_interval"][0] > 0 for p in prim.values()) \
                and block["detectors"]["D1"]["false_episodes_per_day"] <= 2 * block["primary_gate"]["budget_per_day"]
            checks[f"rt2:{name}:primary_gate_recomputed"] = redo == block["primary_gate"]["passes"]
        checks["rt2_success_rule_recomputed"] = res2["primary_success_rule_passes"] == all(
            b["primary_gate"]["passes"] for b in res2["releases"].values())
    checks = {k: bool(v) for k, v in checks.items()}
    report = {"schema_version": "real-telemetry-verification-v1", "checks": checks, "check_count": len(checks),
              "overall_pass": all(checks.values()), "notes": notes}
    OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    failed = [k for k, v in checks.items() if not v]
    print(json.dumps({"checks": len(checks), "overall_pass": report["overall_pass"], "failed": failed}, indent=1))


if __name__ == "__main__":
    main()
