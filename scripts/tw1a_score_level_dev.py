#!/usr/bin/env python3
"""tw1a (exploratory): shipped score-level targets on the Tennessee Eastman score cache of the tt1f round.
No dataset is opened. Plan: docs/research/thresholds_in_the_wild_tw1a_dev_plan.md with amendment 1.

Run with the tw1 environment (river, PySAD, libspot), after scripts/tw1a_export_setup.py:

    python -I scripts/tw1a_score_level_dev.py versions
    python -I scripts/tw1a_score_level_dev.py mode <m> [full|young]    one mode  -> target/tw1/tw1a_mode<m>_<history>.json
    python -I scripts/tw1a_score_level_dev.py mode <m> <history> <name part> <guard>
            rerun, inside an existing part file, the targets whose name contains the part;
            the uncapped attacker stops at <guard> times tau0 (amendment 3)
    python -I scripts/tw1a_score_level_dev.py merge                    summary   -> target/tw1/tw1a_summary.json

Result files stay under target/tw1/ and are not committed (see the plan).
"""

from __future__ import annotations

import json
import math
import sys
import time
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tw1_adapters as A

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "target/real-telemetry/tt1f"
OUT = ROOT / "target/tw1"
SETUP = (
    json.loads((OUT / "tep_setup.json").read_text(encoding="utf-8"))
    if (OUT / "tep_setup.json").exists()
    else None
)
YOUNG = 24000  # one day of calibration scores
SHIFTS = 200  # circular shifts of the alarm sequence for the chance reference
MODES = ("control", "frog", "loud", "subl", "frog_cap", "subl_cap")


class Disagreement(RuntimeError):
    pass


def episodes(alarm, gap):
    """threshold_rules._episodes: alarm steps no more than gap quiet steps apart form one episode."""
    idx = np.flatnonzero(alarm)
    if not len(idx):
        return []
    breaks = np.flatnonzero(np.diff(idx) > gap + 1)
    starts = np.concatenate([[idx[0]], idx[breaks + 1]])
    ends = np.concatenate([idx[breaks], [idx[-1]]]) + 1
    return list(zip(starts.tolist(), ends.tolist()))


def check(t, x, tau, alarm, stats):
    stats["checked"] += 1
    if alarm == t.expected(x, tau):
        return
    rel = abs(x - tau) / max(abs(tau), 1e-12) if math.isfinite(tau) else math.inf
    if rel <= t.eps:
        stats["in_band"] += 1
        stats["largest_in_band"] = max(stats["largest_in_band"], rel)
        return
    raise Disagreement(f"{t.name}: score {x!r}, reading {tau!r}, target alarm {alarm}")


def probe(t, tau, stats):
    """The target's decision, on copies, for scores just above and just below the reading."""
    d = max(10 * t.eps, 1e-6) * max(abs(tau), 1e-9)
    for p, want in ((tau + d, True), (tau - d, False)):
        if t.clone().step(p) != want:
            raise Disagreement(
                f"{t.name}: probe {p!r} against reading {tau!r} should alarm = {want}"
            )
        stats["probes"] += 1


def step(t, x, i, stats, tau=None):
    """One score through the target, with the consistency check on the plan's schedule."""
    if t.closed_loop and (tau is not None or i < 2000 or i % 100 == 0):
        if tau is None:
            tau = t.tau()
        if t.copyable and math.isfinite(tau) and (i < 200 or i % 1000 == 0):
            probe(t, tau, stats)
        alarm = t.step(x)
        check(t, x, tau, alarm, stats)
        return alarm
    return t.step(x)


def feed(t, xs, stats, offset=0):
    alarm = np.zeros(len(xs), bool)
    for i, x in enumerate(xs):
        x = float(x)
        if math.isfinite(x):
            alarm[i] = step(t, x, offset + i, stats)
        else:
            stats["skipped_not_finite"] += 1
    return alarm


def terminal(t, s, start, K, tau0, stats):
    hits = []
    for mag in K["mags"]:
        u, hit = t.clone(), False
        for j in range(K["terminal"]):
            x = float(s[start + j])
            if math.isfinite(x):
                hit |= bool(u.step(max(x, mag * tau0)))
        hits.append(hit)
    return hits


def reading(t, tau0):
    if not t.closed_loop:
        return None
    v = t.tau()
    return v / tau0 if math.isfinite(v) else None


def campaign(t, s, end, mode, K, tau0, stats, guard=None):
    """One campaign on a target that stands at the start of the campaign window; the tt1d placement."""
    c_start, c_end = end - K["lead"] - K["campaign"], end - K["lead"]
    alarm = np.zeros(K["campaign"], bool)
    cap, injected = K["loud"][2] * tau0, 0.0
    for i in range(c_start, c_end):
        x = float(s[i])
        if not math.isfinite(x):
            continue
        k, tau, lift = i - c_start, None, None
        if mode in ("frog", "frog_cap"):
            tau = t.tau()
            lift = K["frog_frac"] * (tau if math.isfinite(tau) else tau0)
        elif mode == "loud":
            if k % K["loud"][0] < K["loud"][1]:
                lift = K["loud"][2] * tau0
        elif mode in ("subl", "subl_cap") and k % K["subl"][0] < K["subl"][1]:
            tau = t.tau()
            lift = K["subl"][2] * (tau if math.isfinite(tau) else tau0)
        if lift is not None:
            if mode.endswith(
                "_cap"
            ):  # amendment 2: an attacker whose score never exceeds the loud level
                lift = min(lift, cap)
            elif guard is not None:
                # amendment 3: a rerun stops the uncapped attacker at a fixed multiple of tau0
                lift = min(lift, guard * tau0)
            if lift > x:
                x, injected = lift, max(injected, lift)
        alarm[k] = step(t, x, i, stats, tau)
    out = {
        "largest_injected_over_tau0": injected / tau0,
        "alarm_steps": int(alarm.sum()),
        "alarm_episodes": len(episodes(alarm, K["gap"])),
        "reading_at_campaign_end": reading(t, tau0),
        "hits_lead0": terminal(t, s, c_end, K, tau0, stats),
    }
    lead_alarm = feed(t, s[c_end:end], stats, c_end)
    out.update(
        {
            "reading_at_terminal": reading(t, tau0),
            "hits": terminal(t, s, end, K, tau0, stats),
        }
    )
    return out, alarm, lead_alarm


def chance(alarm, events, rng):
    """Mean number of events with an alarm inside when the alarm sequence is shifted circularly (tt1f)."""
    if not events or not alarm.any():
        return 0.0
    n = len(alarm)
    shifts = rng.integers(1, n, SHIFTS)
    # np.roll(alarm, k)[a:b] holds alarm[(a - k) % n : (b - k) % n], wrapped; counted with a cumulative sum
    # (fi1: same value as rolling the array per shift, without the per-shift copy)
    cum = np.concatenate([[0], np.cumsum(alarm, dtype=np.int64)])
    total = 0
    for a, b, _ in events:
        lo, hi = (a - shifts) % n, (b - shifts) % n
        inside = np.where(hi <= lo, cum[n] - cum[lo] + cum[hi], cum[hi] - cum[lo])
        total += int((inside > 0).sum())
    return total / SHIFTS


def chance_rng(mode, name, run):
    """fi1 audit: one generator per (mode, target, attack run), so a target's chance reference does not depend
    on which targets ran before it (an `only` rerun reproduces the full run)."""
    return np.random.default_rng(
        [20261111, int(mode), zlib.crc32(name.encode()), zlib.crc32(run.encode())]
    )


def run_mode(mode, history, only=None, guard=None):
    K, M = SETUP["constants"], SETUP["modes"][str(mode)]
    z = np.load(CACHE / f"mode_{mode}.npz")
    tau0, pooled = M["tau0"], z["pooled"]
    hist = pooled if history == "full" else pooled[-YOUNG:]
    out = {
        "mode": mode,
        "history": history,
        "history_steps": int(len(hist)),
        "tau0": tau0,
        "versions": A.versions(),
        "targets": {},
    }
    part = OUT / f"tw1a_mode{mode}_{history}.json"
    if only and part.exists():
        out = json.loads(part.read_text(encoding="utf-8"))
    for make in A.documented(tau0):
        t0 = time.time()
        warm = make()
        if only and only not in warm.name:
            continue
        stats = {
            "checked": 0,
            "in_band": 0,
            "largest_in_band": 0.0,
            "probes": 0,
            "skipped_not_finite": 0,
        }
        row = {
            "doc": warm.doc,
            "closed_loop": warm.closed_loop,
            "uncapped_guard_over_tau0": guard,
            "sealed": [],
            "attack": [],
        }
        try:
            hist_alarm = feed(warm, hist, stats)
            row["history_alarm_share"] = float(hist_alarm.mean())
            row["reading_after_history"] = reading(warm, tau0)
            for run in M["sealed"]:
                s, end = z["sealed::" + run["name"]], run["terminal_start"]
                c_start = end - K["lead"] - K["campaign"]
                t = warm.clone()
                before = feed(t, s[:c_start], stats)
                cell = {"name": run["name"], "campaigns": {}}
                for c in MODES if warm.closed_loop else ("control", "loud"):
                    u = t.clone()
                    res, during, lead = campaign(u, s, end, c, K, tau0, stats, guard)
                    if c == "control":
                        after = feed(u, s[end:], stats, end)
                        whole = np.concatenate([before, during, lead, after])
                        cell["false_alarm_episodes"] = len(episodes(whole, K["gap"]))
                        cell["alarm_share"] = float(whole.mean())
                        cell["steps"] = int(len(whole))
                    cell["campaigns"][c] = res
                row["sealed"].append(cell)
            for run in M["attack"]:
                s = z["attack::" + run["name"]]
                alarm = feed(warm.clone(), s, stats)
                lab = np.zeros(len(s), bool)
                for a, b, _ in run["events"]:
                    lab[a:b] = True
                eps = episodes(alarm, K["gap"])
                starts = np.zeros(len(s), bool)
                for a, _ in eps:
                    starts[a] = True
                idx = np.flatnonzero(alarm)
                row["attack"].append(
                    {
                        "name": run["name"],
                        "type": run["type"],
                        "found": [bool(alarm[a:b].any()) for a, b, _ in run["events"]],
                        "onset": [bool(starts[a:b].any()) for a, b, _ in run["events"]],
                        "chance_found": chance(
                            alarm,
                            run["events"],
                            chance_rng(mode, warm.name, run["name"]),
                        ),
                        "fa": int(sum(1 for a, b in eps if not lab[a:b].any())),
                        "alarm_unlabelled": int((alarm & ~lab).sum()),
                        "unlabelled_steps": int((~lab).sum()),
                        "alarm_in_events": int((alarm & lab).sum()),
                        "event_steps": int(lab.sum()),
                        "last_alarm": int(idx[-1]) if len(idx) else None,
                    }
                )
            row["status"] = "run"
        except Disagreement as e:
            row["status"] = f"stopped: {e}"
        row["consistency"], row["seconds"] = stats, round(time.time() - t0)
        out["targets"][warm.name] = row
        print(
            f"mode {mode} {history}: {warm.name[:60]} {row['status'][:60]} {row['seconds']} s",
            flush=True,
        )
        OUT.mkdir(parents=True, exist_ok=True)
        part.write_text(json.dumps(out), encoding="utf-8")
    print("written", part)


def merge():
    K = SETUP["constants"]
    parts = sorted(OUT.glob("tw1a_mode*_*.json"))
    summary = {"status": "exploratory (tw1a); Tennessee Eastman score cache; no dataset opened", "parts": [p.name for p in parts],
               "magnitudes_over_tau0": K["mags"], "histories": {}}  # fmt: skip
    for history in ("full", "young"):
        docs = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in parts
            if p.name.endswith(f"_{history}.json")
        ]
        if not docs:
            continue
        table = {}
        for name in docs[0]["targets"]:
            rows = [d["targets"][name] for d in docs if name in d["targets"]]
            if any(r["status"] != "run" for r in rows):
                table[name] = {
                    "status": [r["status"] for r in rows if r["status"] != "run"][0]
                }
                continue
            sealed = [c for r in rows for c in r["sealed"]]
            attack = [a for r in rows for a in r["attack"]]
            first = [(a["found"][0], a["onset"][0]) for a in attack if a["found"]]
            foll = [
                (f, o) for a in attack for f, o in zip(a["found"][1:], a["onset"][1:])
            ]
            days = sum(c["steps"] for c in sealed) / K["spd"]
            entry = {
                "modes": len(rows),
                "placements": len(sealed),
                "sealed_false_alarm_ratio_to_budget": sum(
                    c["false_alarm_episodes"] for c in sealed
                )
                / days
                / K["budget"],
                "sealed_alarm_share": float(
                    np.mean([c["alarm_share"] for c in sealed])
                ),
                "first": {
                    "events": len(first),
                    "detected": sum(f for f, _ in first),
                    "onset": sum(o for _, o in first),
                },
                "follower": {
                    "events": len(foll),
                    "detected": sum(f for f, _ in foll),
                    "onset": sum(o for _, o in foll),
                },
                "events": sum(len(a["found"]) for a in attack),
                "chance_detected": float(sum(a["chance_found"] for a in attack)),
                "alarm_share_inside_events": sum(a["alarm_in_events"] for a in attack)
                / max(1, sum(a["event_steps"] for a in attack)),
                "alarm_share_unlabelled": sum(a["alarm_unlabelled"] for a in attack)
                / max(1, sum(a["unlabelled_steps"] for a in attack)),
                "campaigns": {},
                "consistency": {
                    k: sum(r["consistency"][k] for r in rows)
                    for k in ("checked", "in_band", "probes", "skipped_not_finite")
                },
                "per_mode": {},
            }
            for c in MODES:
                cells = [x["campaigns"][c] for x in sealed if c in x["campaigns"]]
                if not cells:
                    continue
                ends = [
                    x["reading_at_campaign_end"]
                    for x in cells
                    if x["reading_at_campaign_end"] is not None
                ]
                entry["campaigns"][c] = {
                    "caught_after_lead": [
                        int(sum(x["hits"][k] for x in cells))
                        for k in range(len(K["mags"]))
                    ],
                    "caught_at_lead0": [
                        int(sum(x["hits_lead0"][k] for x in cells))
                        for k in range(len(K["mags"]))
                    ],
                    "silent_placements": int(sum(x["alarm_steps"] == 0 for x in cells)),
                    "median_alarm_steps": float(
                        np.median([x["alarm_steps"] for x in cells])
                    ),
                    "median_reading_at_campaign_end": float(np.median(ends))
                    if ends
                    else None,
                    "median_largest_injected_over_tau0": float(
                        np.median([x["largest_injected_over_tau0"] for x in cells])
                    ),
                }
            for d in docs:
                r = d["targets"][name]
                entry["per_mode"][str(d["mode"])] = {
                    c: {"lead": [int(sum(x["campaigns"][c]["hits"][k] for x in r["sealed"])) for k in range(len(K["mags"]))],
                        "lead0": [int(sum(x["campaigns"][c]["hits_lead0"][k] for x in r["sealed"])) for k in range(len(K["mags"]))]}
                    for c in MODES if c in r["sealed"][0]["campaigns"]
                }  # fmt: skip
            table[name] = entry
        summary["histories"][history] = table
    (OUT / "tw1a_summary.json").write_text(
        json.dumps(summary, indent=1) + "\n", encoding="utf-8"
    )
    for history, table in summary["histories"].items():
        print(f"== history {history}")
        for name, v in table.items():
            if "status" in v:
                print(f"{name[:52]:52s} {v['status'][:90]}")
                continue
            line = f"{name[:52]:52s} FA x{v['sealed_false_alarm_ratio_to_budget']:8.2f} first {v['first']['detected']:3d}/{v['first']['onset']:3d} foll {v['follower']['detected']:3d}/{v['follower']['onset']:3d} chance {v['chance_detected']:5.1f}"
            for c in MODES:
                if c in v["campaigns"]:
                    line += f" | {c} {v['campaigns'][c]['caught_at_lead0']} {v['campaigns'][c]['caught_after_lead']}"
            print(line)
    print("written", OUT / "tw1a_summary.json")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "versions":
        print(json.dumps(A.versions(), indent=1))
    elif cmd == "mode":
        run_mode(
            int(sys.argv[2]),
            sys.argv[3] if len(sys.argv) > 3 else "full",
            sys.argv[4] if len(sys.argv) > 4 else None,
            float(sys.argv[5]) if len(sys.argv) > 5 else None,
        )
    elif cmd == "merge":
        merge()
    else:
        raise SystemExit(__doc__)
