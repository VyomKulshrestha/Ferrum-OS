"""Check the tracker-memory and daily-memory propositions against the recorded threshold trajectories.

Reads only the paper pack's figure data (figure_data/threshold_trajectories.csv) and the registered
calibration parameters (p, eta, tau0) from the result files. No raw dataset is opened.

Proposition 1 (tracker memory). With q_{t+1} = q_t + eta (1[s_t > q_t] - p), every exceedance step raises
q by eta (1 - p) and every other step lowers it by eta p, so a rise built by E exceedance steps takes
E (1 - p) / p quiet steps to undo. The ratio does not depend on eta.
Check: between two recorded rows the change in q must equal eta (E - n p) for an integer E in [0, n],
where n is the number of steps between the rows.

Proposition 2 (daily memory). Daily recalibration sets the next day's threshold to the (1 - p) quantile
of the last day, so an attack that keeps the score above a level a for more than p N steps of a day
(N steps per day) lifts the next day's threshold to at least a.

Output: docs/research/threshold_transfer_tt1_memory_check.json
"""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "docs" / "research" / "paper" / "tt1_paper_pack"
OUT = ROOT / "docs" / "research" / "threshold_transfer_tt1_memory_check.json"

SETTINGS = {
    # dataset: (result file, path to thresholds, steps between rows, steps per day, step length in s)
    "hai-20.07": ("threshold_transfer_tt1_result_hai-20.07.json", ("thresholds",), 60, 86400, 1),
    "batadal": ("threshold_transfer_tt1b_result_batadal.json", ("scores", "D1", "thresholds"), 1, 96, 900),
}


def load_params(name, path):
    d = json.loads((PACK / "results" / name).read_text(encoding="utf-8"))
    for k in path:
        d = d[k]
    return d


def main():
    rows = defaultdict(list)
    with open(PACK / "figure_data" / "threshold_trajectories.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[(r["dataset"], r["stream"])].append(r)

    report = {}
    for ds, (fname, path, n, spd, step_s) in SETTINGS.items():
        th = load_params(fname, path)
        p, eta, tau0 = th["p"], th["eta"], th["tau0"]
        ratio = (1 - p) / p
        out = {"p": p, "eta": eta, "tau0": tau0, "steps_between_rows": n,
               "recovery_steps_per_exceedance_step": ratio,
               "recovery_hours_per_exceedance_minute": ratio * 60 / 3600 if step_s == 1 else None,
               "recovery_hours_per_exceedance_step": ratio * step_s / 3600,
               "decay_per_day_in_tau0": eta * p * (86400 / step_s) / tau0,
               "daily_steps_above_level_to_lift_next_day": p * spd,
               "streams": {}}
        for (d, stream), rs in sorted(rows.items()):
            if d != ds:
                continue
            q = [float(r["tau_tracker"]) for r in rs]
            qs = [float(r["tau_tracker_slow"]) for r in rs]
            worst, worst_slow, exceed, exceed_slow = 0.0, 0.0, 0, 0
            for a, b, a2, b2 in zip(q, q[1:], qs, qs[1:]):
                e = (b - a) / eta + n * p             # exceedance steps between the rows, must be an integer
                e2 = (b2 - a2) / (eta / 10) + n * p
                worst = max(worst, abs(e - round(e)))
                worst_slow = max(worst_slow, abs(e2 - round(e2)))
                exceed += round(e)
                exceed_slow += round(e2)
            steps = (len(q) - 1) * n
            above = [i for i, v in enumerate(q) if v > 2 * tau0]
            # longest run of rows with the tracker above 2 tau0 and no attack label in the row
            run, best = 0, 0
            for r, v in zip(rs, q):
                run = run + 1 if (v > 2 * tau0 and r["attack"] == "0") else 0
                best = max(best, run)
            out["streams"][stream] = {
                "rows": len(q),
                "max_integrality_error_tracker": worst,
                "max_integrality_error_tracker_slow": worst_slow,
                "exceedance_steps_tracker": exceed,
                "exceedance_steps_tracker_slow": exceed_slow,
                "steps": steps,
                "final_tracker_over_tau0": q[-1] / tau0,
                "max_tracker_over_tau0": max(q) / tau0,
                "predicted_days_to_return_from_final": (q[-1] - tau0) / (eta * p) * step_s / 86400,
                "share_of_rows_above_2tau0": len(above) / len(q),
                "longest_attack_free_stretch_above_2tau0_hours": best * n * step_s / 3600,
            }
        report[ds] = out
    report["note"] = ("post-hoc analysis of the recorded trajectories (figure data); no raw data opened. "
                      "An integrality error near 0 means every recorded change of the tracker is an exact "
                      "multiple of the Proposition 1 steps.")
    OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
