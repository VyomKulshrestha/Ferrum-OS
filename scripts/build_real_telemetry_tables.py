#!/usr/bin/env python3
"""Generate the report's real-telemetry tables from the retained result files (no hand-typed values)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "docs/research"
NAMES = {"D0": "Persistence residual (D0)", "DR": "Bound and gradient check (DR)", "D1": "World-model residual, normal-only (D1)",
         "D2": "Incident-informed classifier (D2)", "D3": "Generic-noise classifier (D3)", "D2c": "D2 at D1's alarm fraction (D2c)"}


def load(name):
    return json.loads((R / name).read_text(encoding="utf-8"))


def pct(x):
    return f"{100 * x:.1f}%"


def interval(c, baseline_recall=None):
    """Recall difference in percentage points with its interval, then the relative miss reduction
    (undefined, shown as n/a, when the reference detector missed nothing)."""
    lo, hi = c["recall_difference_interval"]
    miss = "n/a" if baseline_recall is not None and baseline_recall >= 1.0 else f"{100 * c['miss_reduction']:+.0f}%"
    return f"{100 * c['recall_difference']:+.1f} [{100 * lo:+.1f}, {100 * hi:+.1f}]; {miss}"


def table_rt1():
    r = load("real_telemetry_result_v1.json")["datasets"]
    h, s = r["hai-22.04"]["detectors"], r["smd"]["detectors"]
    rows = ["| Detector | HAI attacks found | HAI false episodes/day | HAI AUC-PR | SMD incidents found | SMD false episodes/day | SMD normal minutes alarmed |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    for d in ("D0", "DR", "D1", "D2", "D3"):
        rows.append(f"| {NAMES[d]} | {h[d]['detected']}/{h[d]['events']} ({pct(h[d]['event_recall'])}) | {h[d]['false_episodes_per_day']:.2f} | "
                    f"{h[d]['auc_pr']:.3f} | {s[d]['detected']}/{s[d]['events']} ({pct(s[d]['event_recall'])}) | "
                    f"{s[d]['false_episodes_per_day']:.2f} | {pct(s[d]['normal_step_alarm_rate'])} |")
    return "\n".join(rows)


def table_rt1_comparisons():
    r = load("real_telemetry_result_v1.json")["datasets"]
    rows = ["| Comparison | HAI 22.04: recall points [97.5% interval]; miss reduction | SMD: recall points [97.5% interval]; miss reduction |",
            "|---|---:|---:|"]
    for key, label in (("D2_vs_D1", "D2 versus D1 (registered primary)"), ("D2_vs_D3", "D2 versus D3 (specificity)"),
                       ("D1_vs_D0", "D1 versus D0"), ("D1_vs_DR", "D1 versus DR")):
        rows.append(f"| {label} | {interval(r['hai-22.04']['comparisons'][key])} | {interval(r['smd']['comparisons'][key])} |")
    return "\n".join(rows)


def table_posthoc():
    p = load("real_telemetry_posthoc_rt1.json")["matched_rate"]
    rows = ["| False episodes per day (matched on test) | D0 | DR | D1 | D2 | D3 |", "|---|---:|---:|---:|---:|---:|"]
    for rate in ("0.5", "1.0", "2.0"):
        rows.append(f"| {rate} | " + " | ".join(f"{p[rate][d]['detected']}/{p[rate][d]['events']}" for d in ("D0", "DR", "D1", "D2", "D3")) + " |")
    return "\n".join(rows)


def table_rt2():
    r = load("real_telemetry_result_rt2.json")["releases"]
    a, b = r["hai-21.03"]["detectors"], r["hai-23.05"]["detectors"]
    rows = ["| Detector | HAI 21.03 attacks found | False episodes/day | HAI 23.05 attacks found | False episodes/day |",
            "|---|---:|---:|---:|---:|"]
    for d in ("D0", "DR", "D1", "D2", "D3", "D2c"):
        rows.append(f"| {NAMES[d]} | {a[d]['detected']}/{a[d]['events']} ({pct(a[d]['event_recall'])}) | {a[d]['false_episodes_per_day']:.2f} | "
                    f"{b[d]['detected']}/{b[d]['events']} ({pct(b[d]['event_recall'])}) | {b[d]['false_episodes_per_day']:.2f} |")
    return "\n".join(rows)


def table_rt2_comparisons():
    r = load("real_telemetry_result_rt2.json")["releases"]
    rows = ["| Comparison | Interval | HAI 21.03: recall points [interval]; miss reduction | HAI 23.05: recall points [interval]; miss reduction |", "|---|---|---:|---:|"]
    base = lambda rel, key: r[rel]["detectors"][key.split("_vs_")[1]]["event_recall"]
    for key, label, lv in (("D1_vs_D0", "D1 versus D0 (primary)", "98.75%"), ("D1_vs_DR", "D1 versus DR (primary)", "98.75%")):
        rows.append(f"| {label} | {lv} | {interval(r['hai-21.03']['primary_comparisons'][key], base('hai-21.03', key))} | "
                    f"{interval(r['hai-23.05']['primary_comparisons'][key], base('hai-23.05', key))} |")
    for key, label in (("D2c_vs_D1", "D2c versus D1"), ("D2_vs_D1", "D2 versus D1"), ("D3_vs_D1", "D3 versus D1"), ("D2c_vs_D3", "D2c versus D3")):
        rows.append(f"| {label} | 95% | {interval(r['hai-21.03']['secondary'][key], base('hai-21.03', key))} | "
                    f"{interval(r['hai-23.05']['secondary'][key], base('hai-23.05', key))} |")
    return "\n".join(rows)


if __name__ == "__main__":
    for fn in (table_rt1, table_rt1_comparisons, table_posthoc):
        print(fn())
        print()
    if (R / "real_telemetry_result_rt2.json").exists():
        print(table_rt2())
        print()
        print(table_rt2_comparisons())
