#!/usr/bin/env python3
"""tw1c: Netdata's ML anomaly bit on the tw1c series (compressed run of the plan, section 2).

    python -I tools/tw1c/netdata_run.py prepare     write feed/series.bin, feed/series.json, series_info.json
    python -I tools/tw1c/netdata_run.py read        read the anomaly bit per series and the alert log

The feeder (tools/tw1c/netdata_feeder.py) runs in its own container in the network namespace of the
Netdata container and sends one statsd gauge value per series per second. The agent's API is on
127.0.0.1:19999.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import repro_env  # noqa: E402
import tw1c_signals as S  # noqa: E402

API = "http://127.0.0.1:19999"
INPUT = ROOT / "target/tw1c/input"
OUT = ROOT / "target/tw1c/netdata"
FEED = OUT / "feed"
HISTORY, CAMPAIGN, TAIL = 4000, 4000, 200
PREFIX = "tw1c_"


def get(path, **q):
    url = API + path + ("?" + urllib.parse.urlencode(q) if q else "")
    with urllib.request.urlopen(url, timeout=300) as r:
        return json.loads(r.read())


def prepare():
    FEED.mkdir(parents=True, exist_ok=True)
    setup = S.load_setup(INPUT / "tep_setup.json")
    rows, infos, metas = [], [], []
    for mode in range(7):
        p = S.load_placement(INPUT, setup, mode)
        X, info, meta = S.build(p, campaign=CAMPAIGN, history=HISTORY, tail=TAIL)
        rows.append(X)
        infos += info
        metas.append(meta)
    X = np.vstack(rows).astype("<f8")
    for i, r in enumerate(infos):
        r["row"] = i
    X.tofile(FEED / "series.bin")
    names = [PREFIX + r["name"] for r in infos]
    (FEED / "series.json").write_text(
        json.dumps({"names": names, "steps": int(X.shape[1])})
    )
    (OUT / "series_info.json").write_text(
        json.dumps({"series": infos, "placements": metas})
    )
    print("series", X.shape, "real time", round(X.shape[1] / 3600, 2), "h")


def chart_of(charts, name):
    """statsd turns the gauge `tw1c_<series>` into the chart `statsd_tw1c.<series>_gauge`."""
    cid = "statsd_" + name.replace(PREFIX, PREFIX[:-1] + ".", 1) + "_gauge"
    return cid if cid in charts else None


def read():
    info = json.loads((OUT / "series_info.json").read_text())["series"]
    prog = json.loads((FEED / "progress.json").read_text())
    start, steps = prog["start"], prog["steps"]
    X = np.fromfile(FEED / "series.bin").reshape(len(info), steps)
    charts = get("/api/v1/charts")["charts"]
    rows, raw = [], {}
    for r in info:
        name = PREFIX + r["name"]
        cid = chart_of(charts, name)
        if cid is None:
            rows.append({"name": r["name"], "status": "no chart"})
            continue
        # Netdata stamps a 1-second point with the end of its interval: step k sits at start + k + 1
        q = dict(
            chart=cid,
            after=start,
            before=start + steps + 1,
            points=steps + 1,
            group="max",
            format="json",
        )
        q["options"] = "seconds|anomaly-bit|null2zero"
        bit = get("/api/v1/data", **q)
        q["options"] = "seconds|null2zero"
        val = get("/api/v1/data", **q)
        bits = {int(t): v for t, *v in bit["data"]}
        vals = {int(t): v for t, *v in val["data"]}
        b = np.array(
            [max(bits.get(start + 1 + k, [0]) or [0]) for k in range(steps)], float
        )
        v = np.array(
            [(vals.get(start + 1 + k, [np.nan]) or [np.nan])[0] for k in range(steps)],
            float,
        )
        fed = X[r["row"]]
        row_fidelity = float(np.nanmax(np.abs(v - fed))) if len(v) else None
        raw[r["name"]] = {
            "chart": cid,
            "anomalous_steps": np.flatnonzero(b > 0).tolist(),
        }
        cs, ce = r["campaign_start"], r["campaign_end"]
        row = {
            k: r[k]
            for k in ("name", "mode", "campaign", "mag", "lead", "terminal_start")
        }
        row["chart"] = cid
        row["alarms_history"] = int((b[:cs] > 0).sum())
        row["alarms_campaign"] = int((b[cs:ce] > 0).sum())
        row["alarms_total"] = int((b > 0).sum())
        row["values_missing"] = int(np.isnan(v).sum())
        row["largest_stored_minus_fed"] = row_fidelity
        row["steps_off_by_more_than_0.01"] = int((np.abs(v - fed) > 0.01).sum())
        if r["terminal_start"] is not None:
            lo, hi = r["terminal_start"], r["terminal_start"] + r["terminal_len"]
            row["hit"] = bool((b[lo:hi] > 0).any())
            row["terminal_alarm_steps"] = int((b[lo:hi] > 0).sum())
        else:
            row["alarms_lead0_window"] = int((b[ce : ce + S.TERMINAL] > 0).sum())
            row["alarms_lead_window"] = int(
                (b[ce + 1000 : ce + 1000 + S.TERMINAL] > 0).sum()
            )
        rows.append(row)
    alarms = get("/api/v1/alarm_log", after=start)
    ml_alerts = [
        a for a in alarms if "ml" in a.get("name", "") or "anomal" in a.get("name", "")
    ]
    out = OUT / "result.json"
    out.write_text(json.dumps({"progress": prog, "rows": rows, "anomalies": raw, "ml_alert_log": ml_alerts}),
                   encoding="utf-8")  # fmt: skip
    repro_env.stamp_json(out)
    table = {}
    for c in S.CAMPAIGNS:
        cell = {}
        for lead in S.LEADS:
            cell[f"hit_lead{lead}"] = [
                sum(bool(x.get("hit")) for x in rows if x.get("campaign") == c and x.get("mag") == m and x.get("lead") == lead)
                for m in S.MAGS
            ]  # fmt: skip
        none = [
            x
            for x in rows
            if x.get("campaign") == c and x.get("mag") is None and "alarms_total" in x
        ]
        cell["no_step"] = [
            (x["alarms_campaign"], x["alarms_lead0_window"], x["alarms_lead_window"])
            for x in none
        ]
        table[c] = cell
    (OUT / "summary.json").write_text(json.dumps(table, indent=1))
    print(json.dumps(table, indent=1))
    print("charts missing:", sum(1 for x in rows if x.get("status")))


if __name__ == "__main__":
    repro_env.pin_from_environment()
    {"prepare": prepare, "read": read}[sys.argv[1]]()
