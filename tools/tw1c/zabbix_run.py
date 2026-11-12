#!/usr/bin/env python3
"""tw1c: Zabbix trend functions (baselinedev, baselinewma, trendstl) on the tw1c series.

Plan: docs/research/thresholds_in_the_wild_tw1c_signal_plan.md, section 3. The containers are started by
hand; the frontend API is on 127.0.0.1:8080. Standard library only (plus numpy for the series).

    python -I tools/tw1c/zabbix_run.py setup      change the Admin password, create host and items
    python -I tools/tw1c/zabbix_run.py push       send the hourly means with their timestamps
    python -I tools/tw1c/zabbix_run.py triggers   create triggers and calculated items for the next hour
    python -I tools/tw1c/zabbix_run.py read       read trigger values, events, calculated values, trends

State: target/tw1c/zabbix/state.json (item ids, anchor hour, shifts); results: target/tw1c/zabbix/read_<n>.json.
The Admin password is generated once and kept in target/tw1c/zabbix/api_password (never printed).

Time: one step is 3.6 s, so an hour is 1,000 steps. These functions read hourly averages only, so each
series is sent as one value per hour (the mean of its 1,000 steps) at the middle of the hour. Every series
is placed so that its terminal hour is the same absolute hour: the hour that ends one hour before the last
full hour at push time. The extra hour after it is sent so that the terminal hour's trend is flushed.
"""

from __future__ import annotations

import json
import secrets
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import repro_env  # noqa: E402
import tw1c_signals as S  # noqa: E402

API = "http://127.0.0.1:8080/api_jsonrpc.php"
INPUT = ROOT / "target/tw1c/input"
OUT = ROOT / "target/tw1c/zabbix"
STATE = OUT / "state.json"
HOUR_STEPS = 1000
HISTORY = 264 * HOUR_STEPS  # 11 days
CAMPAIGN = 24 * HOUR_STEPS
HOST = "tw1c"
FUNCS = ("bdev", "bwma", "stl")


class Api:
    def __init__(self, token=None):
        self.token, self.n = token, 0

    def __call__(self, method, params):
        self.n += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params, "id": self.n}
        headers = {"Content-Type": "application/json-rpc"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(API, json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=600) as r:
            res = json.loads(r.read())
        if "error" in res:
            raise RuntimeError(f"{method}: {res['error']}")
        return res["result"]


def login():
    pw = (OUT / "api_password").read_text().strip()
    api = Api()
    api.token = api("user.login", {"username": "Admin", "password": pw})
    return api


def state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save(st):
    STATE.write_text(json.dumps(st), encoding="utf-8")


def all_series():
    """Hourly means of every series, with its description; the terminal hour index of each."""
    setup = S.load_setup(INPUT / "tep_setup.json")
    out = []
    for mode in range(7):
        p = S.load_placement(INPUT, setup, mode)
        for terminal in (S.TERMINAL, HOUR_STEPS):
            X, info, meta = S.build(
                p, campaign=CAMPAIGN, history=HISTORY, tail=1000, terminal=terminal
            )
            for r in info:
                if terminal == HOUR_STEPS and r["mag"] is None:
                    continue  # the same as the 167-step build
                lead = r["lead"] or 0
                h_term = (HISTORY + CAMPAIGN + lead) // HOUR_STEPS
                hours = (
                    h_term + 2
                )  # up to and including the extra hour after the terminal hour
                x = X[r["row"]][: hours * HOUR_STEPS].reshape(hours, HOUR_STEPS)
                out.append(
                    {
                        **{
                            k: r[k]
                            for k in (
                                "name",
                                "mode",
                                "campaign",
                                "mag",
                                "lead",
                                "terminal_len",
                            )
                        },
                        "h_term": h_term,
                        "hourly": x.mean(axis=1).tolist(),
                        "tau0": meta["tau0"],
                    }
                )
    return out


def setup():
    OUT.mkdir(parents=True, exist_ok=True)
    pwfile = OUT / "api_password"
    api = Api()
    if not pwfile.exists():
        new = secrets.token_urlsafe(24)
        api.token = api("user.login", {"username": "Admin", "password": "zabbix"})
        uid = api("user.get", {"filter": {"username": "Admin"}, "output": ["userid"]})[
            0
        ]["userid"]
        api("user.update", {"userid": uid, "current_passwd": "zabbix", "passwd": new})
        pwfile.write_text(new)
    api = login()
    st = state()
    if "hostid" not in st:
        gid = api("hostgroup.create", {"name": "tw1c"})["groupids"][0]
        st["hostid"] = api("host.create", {"host": HOST, "groups": [{"groupid": gid}]})[
            "hostids"
        ][0]
        save(st)
    series = all_series()
    have = {
        i["key_"]: i["itemid"]
        for i in api(
            "item.get", {"hostids": st["hostid"], "output": ["itemid", "key_"]}
        )
    }
    new = [
        {
            "hostid": st["hostid"],
            "name": s["name"],
            "key_": f"s[{s['name']}]",
            "type": 2,
            "value_type": 0,
            "history": "31d",
            "trends": "365d",
        }
        for s in series
        if f"s[{s['name']}]" not in have
    ]
    for i in range(0, len(new), 200):
        api("item.create", new[i : i + 200])
    items = {
        i["key_"]: i["itemid"]
        for i in api(
            "item.get", {"hostids": st["hostid"], "output": ["itemid", "key_"]}
        )
    }
    st["items"] = {s["name"]: items[f"s[{s['name']}]"] for s in series}
    save(st)
    print("items", len(st["items"]))


def push():
    st = state()
    api = login()
    series = all_series()
    now = time.time()
    last_full = int(now // 3600) * 3600  # start of the current hour
    term_start = last_full - 2 * 3600  # terminal hour [term_start, term_start + 1 h)
    st["anchor"] = {"pushed_at": now, "terminal_hour_start": term_start}
    batch, sent = [], 0
    for s in series:
        iid = st["items"][s["name"]]
        for h, v in enumerate(s["hourly"]):
            clock = term_start + (h - s["h_term"]) * 3600 + 1800
            batch.append(
                {"itemid": iid, "clock": int(clock), "ns": 0, "value": round(v, 9)}
            )
            if len(batch) >= 5000:
                res = api("history.push", batch)
                bad = [d for d in res.get("data", []) if "error" in d]
                if bad:
                    raise RuntimeError(f"push errors: {bad[:3]}")
                sent += len(batch)
                batch = []
    if batch:
        api("history.push", batch)
        sent += len(batch)
    st["pushed"] = sent
    save(st)
    print(
        "pushed",
        sent,
        "terminal hour starts",
        time.strftime("%Y-%m-%d %H:%M", time.gmtime(term_start)),
        "UTC",
    )


def expressions(name, shift):
    k = f"/{HOST}/s[{name}]"
    sh = f"now/h-{shift}h"
    return {
        "bdev": f'baselinedev({k},1h:{sh},"d",10)>3',
        "bwma": f'trendavg({k},1h:{sh})>1.2*baselinewma({k},1h:{sh},"d",3)',
        "stl": f"trendstl({k},100h:{sh},1h,2h)>0",
    }


def triggers():
    """Shift N so that, at the next hour boundary, 1h:now/h-Nh is the terminal hour; N+1 the hour before."""
    st = state()
    api = login()
    now = time.time()
    nxt = (int(now // 3600) + 1) * 3600
    if nxt - now < 600:
        nxt += 3600
    shift = (nxt - st["anchor"]["terminal_hour_start"]) // 3600 - 1
    st["eval"] = {"boundary": nxt, "shift_terminal": shift, "created_at": now}
    new, calc = [], []
    for name in st["items"]:
        for tag, n in (("term", shift), ("before", shift + 1)):
            for f, e in expressions(name, n).items():
                new.append(
                    {
                        "description": f"tw1c {f} {tag} {name}",
                        "expression": e,
                        "priority": 2,
                        "tags": [{"tag": "f", "value": f}, {"tag": "at", "value": tag}],
                    }
                )
        k, sh = f"/{HOST}/s[{name}]", f"now/h-{shift}h"
        for f, formula in (
            ("bdev", f'baselinedev({k},1h:{sh},"d",10)'),
            ("bwma", f'baselinewma({k},1h:{sh},"d",3)'),
            ("avg", f"trendavg({k},1h:{sh})"),
            ("stl", f"trendstl({k},100h:{sh},1h,2h)"),
        ):
            calc.append(
                {
                    "hostid": st["hostid"],
                    "name": f"c {f} {name}",
                    "key_": f"c.{f}[{name}]",
                    "type": 15,
                    "value_type": 0,
                    "params": formula,
                    "delay": "10m",
                }
            )
    for i in range(0, len(new), 300):
        api("trigger.create", new[i : i + 300])
    for i in range(0, len(calc), 300):
        api("item.create", calc[i : i + 300])
    save(st)
    print("triggers", len(new), "calculated items", len(calc), "shift", shift,
          "evaluate after", time.strftime("%H:%M", time.gmtime(nxt)), "UTC")  # fmt: skip


def read():
    st = state()
    api = login()
    trig = api(
        "trigger.get",
        {
            "hostids": st["hostid"],
            "output": [
                "triggerid",
                "description",
                "value",
                "state",
                "error",
                "lastchange",
            ],
            "limit": 100000,
        },
    )
    calc = api(
        "item.get",
        {
            "hostids": st["hostid"],
            "search": {"key_": "c."},
            "output": ["itemid", "key_", "lastvalue", "lastclock", "state", "error"],
        },
    )
    events = api(
        "event.get",
        {
            "hostids": st["hostid"],
            "output": ["eventid", "objectid", "clock", "value", "name"],
            "limit": 100000,
        },
    )
    ids = list(st["items"].values())
    trends = api(
        "trend.get",
        {
            "itemids": ids,
            "time_from": st["anchor"]["terminal_hour_start"] - 3 * 3600,
            "output": ["itemid", "clock", "num", "value_avg"],
            "limit": 100000,
        },
    )
    n = len(list(OUT.glob("read_*.json")))
    path = OUT / f"read_{n}.json"
    out = {"read_at": time.time(), "eval": st.get("eval"), "anchor": st.get("anchor"),
           "triggers": trig, "calculated": calc, "events": events, "trends_recent": trends}  # fmt: skip
    path.write_text(json.dumps(out), encoding="utf-8")
    repro_env.stamp_json(path)
    states = {}
    for t in trig:
        states[(t["state"], t["value"])] = states.get((t["state"], t["value"]), 0) + 1
    print("written", path, "trigger (state, value) counts", states)


if __name__ == "__main__":
    repro_env.pin_from_environment()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"setup": setup, "push": push, "triggers": triggers, "read": read}.get(
        cmd, lambda: (_ for _ in ()).throw(SystemExit(__doc__))
    )()
