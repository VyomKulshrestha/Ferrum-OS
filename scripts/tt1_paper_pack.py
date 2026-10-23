#!/usr/bin/env python3
"""Build the paper pack for "Thresholds That Travel" (docs/research/paper/tt1_paper_pack/).

  tables        plot-ready CSVs assembled from the committed result JSONs (no data access)
  trajectories  per-rule threshold paths over the HAI 20.07 and BATADAL test streams for figures.
                Both datasets were opened by their registered finals; this recomputation is ledgered
                as post-hoc, uses the registered pipelines unchanged, and records whether tau0 matches
                the registered result.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_detect as R
import threshold_rules_ext as E
import threshold_transfer_dev as X
import tt1_data as TD
import tt1_final as F
import tt1b_final as B

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/research"
PACK = DOCS / "paper/tt1_paper_pack"
FIG = PACK / "figure_data"
TRAJ_RULES = ["frozen", "daily", "tracker", "tracker_slow", "one_sided:none", "spot", "spot_mle", "dspot"]


def load(name):
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


def write(name, rows, cols):
    FIG.mkdir(parents=True, exist_ok=True)
    with (FIG / name).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()})
    print("wrote", FIG / name, len(rows), "rows")


def ci(paired, rule):
    b = paired.get(f"{rule}_vs_frozen") or {}
    iv = b.get("recall_difference_interval") or [None, None]
    return b.get("recall_difference"), iv[0], iv[1]


def tables():
    rows = []

    def add(dataset, status, score, rules, paired, source, recall_key="recall"):
        for r, m in rules.items():
            d, lo, hi = (None, None, None) if r == "frozen" else ci(paired, r)
            rows.append({"dataset": dataset, "status": status, "score": score, "rule": r,
                         "events": m.get("events", m.get("anomalous")), "detected": m.get("detected"),
                         "recall": m.get(recall_key), "diff_vs_frozen": d, "ci_low": lo, "ci_high": hi,
                         "fa_per_day": m.get("fa_per_day"), "fa_ratio_to_budget": m.get("ratio_to_budget", m.get("fa_ratio_to_budget")),
                         "fpr": m.get("fpr"), "median_onset_inflation": m.get("median_onset_inflation", m.get("median_inflation_at_anomalies")),
                         "recall_close": m.get("recall_close"), "n_close": m.get("n_close"),
                         "recall_isolated": m.get("recall_isolated"), "n_isolated": m.get("n_isolated"), "source": source})

    for ds in ("hai-20.07", "hygrid-ics"):
        res = load(f"threshold_transfer_tt1_result_{ds}.json")
        add(ds, "registered tt1", "D1", res["real_events"]["rules"], res["real_events"]["paired"],
            f"threshold_transfer_tt1_result_{ds}.json")
    vor = load("threshold_transfer_tt1_result_voraus-ad.json")
    add("voraus-ad", "registered tt1", "D1", vor["rules"], vor["paired"], "threshold_transfer_tt1_result_voraus-ad.json", "tpr")
    bat = load("threshold_transfer_tt1b_result_batadal.json")
    for key, s in bat["scores"].items():
        add("batadal", "registered tt1b", key, s["real_events"]["rules"], s["real_events"]["paired"],
            "threshold_transfer_tt1b_result_batadal.json")
    dev = load("threshold_transfer_tt1b_dev_v1.json")
    for rel, v in dev["releases"].items():
        for key, s in v["scores"].items():
            paired = {f"{r}_vs_frozen": m["vs_frozen"] for r, m in s["rules"].items() if "vs_frozen" in m}
            add(rel, "exploratory (spent data)", key, s["rules"], paired, "threshold_transfer_tt1b_dev_v1.json")
    post = load("threshold_transfer_tt1b_posthoc_v1.json")
    for ds, v in post["datasets"].items():
        for key, s in v["scores"].items():
            rules = s["rules"]
            paired = {f"{r}_vs_frozen": m["vs_frozen"] for r, m in rules.items() if "vs_frozen" in m}
            add(ds, "post-hoc (after finals)", key, rules, paired, "threshold_transfer_tt1b_posthoc_v1.json",
                "tpr" if ds == "voraus-ad" else "recall")
    write("recall_and_false_alarms_by_rule.csv", rows,
          ["dataset", "status", "score", "rule", "events", "detected", "recall", "diff_vs_frozen", "ci_low", "ci_high",
           "fa_per_day", "fa_ratio_to_budget", "fpr", "median_onset_inflation", "recall_close", "n_close",
           "recall_isolated", "n_isolated", "source"])

    camp = []
    v3 = load("threshold_transfer_dev_v3.json")
    for rel, v in v3["releases"].items():
        for r, m in v["E4_pulse_campaign"]["rules"].items():
            camp.append({"campaign": "E4 supra-threshold pulses", "dataset": rel, "status": "exploratory (normal data)",
                         "rule": r, "placements": v["E4_pulse_campaign"]["placements_used"],
                         "terminal_after": m["terminal_detected_after_campaign"], "terminal_control": m["terminal_detected_control"],
                         "median_inflation": m["median_threshold_inflation"], "source": "threshold_transfer_dev_v3.json"})
    att = load("threshold_transfer_tt1b_attacks_dev_v1.json")
    for rel, v in att["releases"].items():
        for kind, label in (("E4", "E4 supra-threshold pulses"), ("E6", "E6 sub-alarm pulses")):
            for r, m in v[kind]["rules"].items():
                if kind == "E4" and r not in ("spot", "dspot"):
                    continue                        # tt1 rules come from threshold_transfer_dev_v3.json above
                camp.append({"campaign": label, "dataset": rel, "status": "exploratory (normal data)", "rule": r,
                             "placements": v[kind]["placements_used"], "terminal_after": m["terminal_after_campaign"],
                             "terminal_control": m["terminal_control"], "median_inflation": m["median_inflation"],
                             "source": "threshold_transfer_tt1b_attacks_dev_v1.json"})
    h = load("threshold_transfer_tt1_result_hai-20.07.json")["E4_pulse_campaign"]
    for r, m in h["rules"].items():
        camp.append({"campaign": "E4 supra-threshold pulses", "dataset": "hai-20.07", "status": "registered tt1 (G1)", "rule": r,
                     "placements": h["placements_used"], "terminal_after": m["terminal_detected_after_campaign"],
                     "terminal_control": m["terminal_detected_control"], "median_inflation": m["median_threshold_inflation"],
                     "source": "threshold_transfer_tt1_result_hai-20.07.json"})
    frog = load("threshold_transfer_tt1b_frog_dev_v1.json")
    for rel, v in frog["releases"].items():
        for k, rules in v["variants"].items():
            for r, m in rules.items():
                camp.append({"campaign": f"score-level frog {k}", "dataset": rel, "status": "exploratory (normal data)", "rule": r,
                             "placements": 10, "terminal_after": m["terminal_after_campaign"], "terminal_control": m["terminal_control"],
                             "median_inflation": m["median_inflation"], "source": "threshold_transfer_tt1b_frog_dev_v1.json"})
    for key in ("D1", "D0"):
        fr = bat["scores"][key]["frog"]
        for k, rules in fr["variants"].items():
            for r, m in rules.items():
                camp.append({"campaign": f"score-level frog {k} ({key})", "dataset": "batadal", "status": "registered tt1b (H3 is 24h, D1)",
                             "rule": r, "placements": fr["placements_used"], "terminal_after": m["terminal_after_campaign"],
                             "terminal_control": m["terminal_control"], "median_inflation": m["median_inflation"],
                             "source": "threshold_transfer_tt1b_result_batadal.json"})
    phys = load("threshold_transfer_tt1b_physfrog_dev_v1.json")
    for rel, v in phys["releases"].items():
        for r, m in v["rules"].items():
            camp.append({"campaign": "physical frog (sensor-noise spoofing, 6h)", "dataset": rel, "status": "exploratory (normal data)",
                         "rule": r, "placements": v["placements_used"], "terminal_after": m["terminal_after_campaign"],
                         "terminal_control": m["terminal_control"], "median_inflation": m["median_inflation"],
                         "source": "threshold_transfer_tt1b_physfrog_dev_v1.json"})
    write("attack_campaigns.csv", camp, ["campaign", "dataset", "status", "rule", "placements", "terminal_after",
                                         "terminal_control", "median_inflation", "source"])


def trajectories():
    out_rows, checks = [], {}
    # HAI 20.07: the registered tt1 pipeline (fit 60 / scale 20 / calibration 20 %), D1, 1 Hz
    t0 = time.time()
    segs, cols = F.normal_data("hai-20.07")
    kx, ku = F.varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=1000)
    scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
    cal = [s[np.isfinite(s)] for s in (X.d1(scorer, z, v) for z, v in pack(parts["calib"]))]
    tau0 = R.calibrate(cal, X.GAP, X.BUDGET, X.STEPS_PER_DAY)
    pooled = np.concatenate(cal)
    cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
    reg = load("threshold_transfer_tt1_result_hai-20.07.json")["thresholds"]["tau0"]
    checks["hai-20.07"] = {"tau0_recomputed": cfg["tau0"], "tau0_registered": reg, "relative_difference": abs(cfg["tau0"] - reg) / reg}
    raw = TD.hai2007_test("post-hoc analysis after the registered tt1 final: threshold trajectories for paper figures")[0]
    for k, (x, u, y) in enumerate(raw):
        z, v = pack([(x[:, kx], u[:, ku])])[0]
        s = X.d1(scorer, z, v)
        s = np.where(np.isfinite(s), s, -np.inf)
        taus = {r: E.apply_rule(r, s, cfg, pooled, X.STEPS_PER_DAY, X.GAP, 3600, labels=y)[0] for r in TRAJ_RULES}
        for m in range(0, len(s) - 59, 60):           # one row per minute: max score, label, thresholds at the minute's end
            sl = slice(m, m + 60)
            row = {"dataset": "hai-20.07", "stream": f"test{k + 1}", "t": m // 60, "unit": "minute",
                   "attack": int(y[sl].max()), "score_max": float(np.max(s[sl])) if np.isfinite(np.max(s[sl])) else None,
                   "tau0": cfg["tau0"]}
            row.update({f"tau_{r}": float(taus[r][m + 59]) for r in TRAJ_RULES})
            out_rows.append(row)
    print("hai-20.07 trajectories", round(time.time() - t0), "s", flush=True)
    # BATADAL: the registered tt1b pipeline, D1, 15-minute grid, full resolution
    ds = B.DATASETS["batadal"]
    segs, cols = ds["train"]()
    kx, ku = F.varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=max(200, 4 * ds["window"]))
    scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
    cal = [s[np.isfinite(s)] for s in (B.smoothed(scorer, z, v, "D1", ds["window"]) for z, v in pack(parts["calib"]))]
    tau0 = R.calibrate(cal, ds["gap"], ds["budget"], ds["steps_per_day"])
    pooled = np.concatenate(cal)
    cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
    reg = load("threshold_transfer_tt1b_result_batadal.json")["scores"]["D1"]["thresholds"]["tau0"]
    checks["batadal"] = {"tau0_recomputed": cfg["tau0"], "tau0_registered": reg, "relative_difference": abs(cfg["tau0"] - reg) / reg}
    raw, _ = ds["test"]("post-hoc analysis after the registered tt1b final: threshold trajectories for paper figures")
    for k, (x, u, y) in enumerate(raw):
        z, v = pack([(x[:, kx], u[:, ku])])[0]
        s = B.smoothed(scorer, z, v, "D1", ds["window"])
        s = np.where(np.isfinite(s), s, -np.inf)
        taus = {r: E.apply_rule(r, s, cfg, pooled, ds["steps_per_day"], ds["gap"], ds["depth"], labels=y)[0] for r in TRAJ_RULES}
        for i in range(len(s)):
            row = {"dataset": "batadal", "stream": f"test_dataset_{k + 1}", "t": i, "unit": "15 min",
                   "attack": int(y[i]), "score_max": float(s[i]) if np.isfinite(s[i]) else None, "tau0": cfg["tau0"]}
            row.update({f"tau_{r}": float(taus[r][i]) for r in TRAJ_RULES})
            out_rows.append(row)
    write("threshold_trajectories.csv", out_rows,
          ["dataset", "stream", "t", "unit", "attack", "score_max", "tau0"] + [f"tau_{r}" for r in TRAJ_RULES])
    (FIG / "trajectory_consistency.json").write_text(json.dumps(checks, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(checks, indent=1))


if __name__ == "__main__":
    {"tables": tables, "trajectories": trajectories}[sys.argv[1]]()
