#!/usr/bin/env python3
"""tw1c: OpenSearch anomaly detection, historical analysis of the tw1c series (one detector per mode).

Plan: docs/research/thresholds_in_the_wild_tw1c_signal_plan.md, section 1. The container is started by
hand (see the plan); this driver talks to it on 127.0.0.1:9200 with the standard library only.

    python -I tools/tw1c/opensearch_run.py mode <m>      index, detect, read, clean up one mode
    python -I tools/tw1c/opensearch_run.py merge         merge per-mode results into one summary

Every stage writes target/tw1c/opensearch/mode<m>.json; a mode that is already complete is skipped, so the
driver can be rerun after an interruption.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import repro_env  # noqa: E402
import tw1c_signals as S  # noqa: E402

URL = "http://127.0.0.1:9200"
INPUT = ROOT / "target/tw1c/input"
OUT = ROOT / "target/tw1c/opensearch"
T0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
MINUTE = 60_000
HISTORY, CAMPAIGN, TAIL = 8000, 24000, 200
AD = "/_plugins/_anomaly_detection"


def call(method, path, body=None, ndjson=None, timeout=600):
    data = None
    headers = {}
    if ndjson is not None:
        data, headers["Content-Type"] = ndjson.encode(), "application/x-ndjson"
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: {e.code} {e.read()[:800]!r}") from None


def index_name(mode):
    return f"tw1c-series-m{mode}"


def load(mode):
    setup = S.load_setup(INPUT / "tep_setup.json")
    p = S.load_placement(INPUT, setup, mode)
    return S.build(p, campaign=CAMPAIGN, history=HISTORY, tail=TAIL)


def ingest(mode, X, info):
    idx = index_name(mode)
    try:
        call("DELETE", "/" + idx)
    except RuntimeError:
        pass
    call(
        "PUT",
        "/" + idx,
        {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "refresh_interval": "-1",
            },
            "mappings": {
                "properties": {
                    "timestamp": {"type": "date", "format": "epoch_millis"},
                    "series": {"type": "keyword"},
                    "value": {"type": "double"},
                }
            },
        },
    )
    batch, n = [], 0
    for r in info:
        row, name = X[r["row"]], r["name"]
        for t, v in enumerate(row):
            batch.append('{"index":{}}')
            batch.append(
                json.dumps(
                    {"timestamp": T0 + t * MINUTE, "series": name, "value": float(v)}
                )
            )
            if len(batch) >= 40000:
                res = call("POST", f"/{idx}/_bulk", ndjson="\n".join(batch) + "\n")
                if res.get("errors"):
                    raise RuntimeError("bulk errors")
                n += len(batch) // 2
                batch = []
    if batch:
        res = call("POST", f"/{idx}/_bulk", ndjson="\n".join(batch) + "\n")
        if res.get("errors"):
            raise RuntimeError("bulk errors")
        n += len(batch) // 2
    call("POST", f"/{idx}/_refresh")
    count = call("GET", f"/{idx}/_count")["count"]
    if count != n or n != X.size:
        raise RuntimeError(f"indexed {count} of {X.size}")
    return n


def detector(mode):
    body = {
        "name": f"tw1c-m{mode}",
        "description": "tw1c exploratory, synthetic timestamps",
        "time_field": "timestamp",
        "indices": [index_name(mode)],
        "feature_attributes": [
            {
                "feature_name": "value_max",
                "feature_enabled": True,
                "aggregation_query": {"value_max": {"max": {"field": "value"}}},
            }
        ],
        "detection_interval": {"period": {"interval": 1, "unit": "Minutes"}},
        "window_delay": {"period": {"interval": 0, "unit": "Minutes"}},
        "category_field": ["series"],
    }
    return call("POST", AD + "/detectors", body)


def run_task(det_id, steps):
    call(
        "POST",
        f"{AD}/detectors/{det_id}/_start",
        {"start_time": T0, "end_time": T0 + steps * MINUTE},
    )
    t0, last = time.time(), None
    while True:
        time.sleep(20)
        d = call("GET", f"{AD}/detectors/{det_id}?task=true")
        task = d.get("historical_analysis_task") or {}
        state = (task.get("state"), round(task.get("task_progress") or 0, 3))
        if state != last:
            print(f"  {int(time.time() - t0)} s {state}", flush=True)
            last = state
        if task.get("state") in ("FINISHED", "FAILED", "STOPPED"):
            return task, d


def read(det_id, task_id, info):
    """Per series: every interval with a grade above zero, and the number of results the task wrote."""
    out = {}
    for r in info:
        q = {
            "bool": {
                "filter": [
                    {"term": {"detector_id": det_id}},
                    {"term": {"task_id": task_id}},
                    {
                        "nested": {
                            "path": "entity",
                            "query": {"term": {"entity.value": r["name"]}},
                        }
                    },
                ]
            }
        }
        total = call(
            "POST",
            f"{AD}/detectors/results/_search",
            {"size": 0, "query": q, "track_total_hits": True},
        )
        q["bool"]["filter"].append({"range": {"anomaly_grade": {"gt": 0}}})
        hits, after = [], None
        while True:
            body = {
                "size": 5000,
                "query": q,
                "sort": [{"data_start_time": "asc"}],
                "_source": ["data_start_time", "anomaly_grade", "confidence"],
            }
            if after:
                body["search_after"] = after
            res = call("POST", f"{AD}/detectors/results/_search", body)["hits"]["hits"]
            if not res:
                break
            for h in res:
                s = h["_source"]
                hits.append(
                    [
                        (s["data_start_time"] - T0) // MINUTE,
                        s["anomaly_grade"],
                        s.get("confidence"),
                    ]
                )
            after = res[-1]["sort"]
        out[r["name"]] = {
            "results": total["hits"]["total"]["value"],
            "anomalies": hits,
        }
    return out


def outcome(info, res):
    """Hits on the terminal window and alarms during the campaign, from the plugin's own grades."""
    rows = []
    for r in info:
        a = res[r["name"]]["anomalies"]
        steps = [t for t, g, _ in a if g > 0]
        strong = [t for t, g, c in a if g > 0.7 and (c or 0) > 0.7]

        def inside(ts, lo, hi):
            return sum(lo <= t < hi for t in ts)

        cs, ce = r["campaign_start"], r["campaign_end"]
        row = {k: r[k] for k in ("name", "campaign", "mag", "lead", "terminal_start")}
        row["results_written"] = res[r["name"]]["results"]
        row["alarms_history"] = inside(steps, 0, cs)
        row["alarms_campaign"] = inside(steps, cs, ce)
        row["alarms_total"] = len(steps)
        if r["terminal_start"] is not None:
            lo, hi = r["terminal_start"], r["terminal_start"] + r["terminal_len"]
            row["hit"] = inside(steps, lo, hi) > 0
            row["hit_monitor_default"] = inside(strong, lo, hi) > 0
            row["max_grade_terminal"] = max(
                [g for t, g, _ in a if lo <= t < hi], default=0.0
            )
        else:
            # the windows a terminal step would occupy, for the series without one
            row["alarms_lead0_window"] = inside(steps, ce, ce + S.TERMINAL)
            row["alarms_lead_window"] = inside(steps, ce + 1000, ce + 1000 + S.TERMINAL)
        rows.append(row)
    return rows


def mode_run(mode):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"mode{mode}.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if state.get("stage") == "done":
        print("mode", mode, "already done")
        return
    X, info, meta = load(mode)
    state.update({"mode": mode, "meta": meta, "series": len(info)})
    t = time.time()
    state["indexed"] = ingest(mode, X, info)
    state["index_seconds"] = round(time.time() - t)
    print(
        f"mode {mode}: indexed {state['indexed']} in {state['index_seconds']} s",
        flush=True,
    )
    det = detector(mode)
    det_id = det["_id"]
    state["detector"] = {"id": det_id, "as_created": det.get("anomaly_detector")}
    t = time.time()
    task, full = run_task(det_id, X.shape[1])
    state["task"] = task
    state["detector"]["as_run"] = full.get("anomaly_detector")
    state["task_seconds"] = round(time.time() - t)
    if task.get("state") != "FINISHED":
        state["stage"] = "failed"
        path.write_text(json.dumps(state), encoding="utf-8")
        raise SystemExit(f"task ended {task.get('state')}: {task.get('error')}")
    res = read(det_id, task["task_id"], info)
    state["rows"] = outcome(info, res)
    state["anomalies"] = {k: v["anomalies"] for k, v in res.items()}
    state["stage"] = "done"
    path.write_text(json.dumps(state), encoding="utf-8")
    repro_env.stamp_json(path)
    # clean up: results of this detector, the detector and the index
    call(
        "POST",
        "/.opendistro-anomaly-results*/_delete_by_query?conflicts=proceed",
        {"query": {"term": {"detector_id": det_id}}},
        timeout=1800,
    )
    call("DELETE", f"{AD}/detectors/{det_id}")
    call("DELETE", "/" + index_name(mode))
    print("written", path, flush=True)


def merge():
    rows = []
    for p in sorted(OUT.glob("mode*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("stage") == "done":
            rows += d["rows"]
    table = {}
    for c in S.CAMPAIGNS:
        cell = {}
        for lead in S.LEADS:
            for key in ("hit", "hit_monitor_default"):
                cell[f"{key}_lead{lead}"] = [
                    sum(
                        r[key]
                        for r in rows
                        if r["campaign"] == c and r["mag"] == m and r["lead"] == lead
                    )
                    for m in S.MAGS
                ]
        none = [r for r in rows if r["campaign"] == c and r["mag"] is None]
        cell["no_step_alarms_campaign"] = [r["alarms_campaign"] for r in none]
        cell["no_step_alarms_lead0_window"] = sum(
            r["alarms_lead0_window"] > 0 for r in none
        )
        cell["no_step_alarms_lead_window"] = sum(
            r["alarms_lead_window"] > 0 for r in none
        )
        cell["placements"] = len(none)
        table[c] = cell
    out = OUT / "summary.json"
    out.write_text(
        json.dumps({"magnitudes": S.MAGS, "campaigns": table}, indent=1),
        encoding="utf-8",
    )
    repro_env.stamp_json(out)
    print(json.dumps(table, indent=1))


if __name__ == "__main__":
    repro_env.pin_from_environment()
    if len(sys.argv) > 2 and sys.argv[1] == "mode":
        mode_run(int(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == "merge":
        merge()
    else:
        raise SystemExit(__doc__)
