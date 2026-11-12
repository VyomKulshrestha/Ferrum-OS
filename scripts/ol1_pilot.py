#!/usr/bin/env python3
"""ol1 development runs (development seeds only; protocol section 9).

    python scripts/ol1_pilot.py scripted [--seeds 1-20]
        the four scripted reference policies, every mode and condition, arm P0 and G -> target/ol1/dev/scripted.json
    python scripts/ol1_pilot.py model --model claude-haiku-5-5 --seeds 1 --modes 0 [--conditions ..] [--arms ..]
            [--workers 4] [--tag name]
        model episodes through the API under the pilot cap -> target/ol1/dev/<tag>.jsonl
    python scripts/ol1_pilot.py summary <tag> [<tag> ...]
        behavioural counts, leak scan and tokens per review of model runs
    python scripts/ol1_pilot.py batchprobe --model claude-haiku-5-5
        two first-review requests through the Message Batches API (format and cache check)

Raw transcripts stay under target/ol1/ (ignored by git).
"""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ol1_core as C
import repro_env

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "target/ol1/dev"
INPUT = ROOT / "target/ol1/ol1_dev_input.npz"


def parse_range(s):
    out = []
    for part in str(s).split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def header(extra=None):
    return {
        "status": "development (ol1 stage 1); development seeds only",
        "system_prompts": {a: C.system_prompt(a) for a in C.ARMS},
        "tools": C.TOOLS,
        "tools_digest": C.digest(C.TOOLS),
        "constants": {
            k: getattr(C, k)
            for k in (
                "STEP_SECONDS",
                "REVIEW_STEPS",
                "N_REVIEWS",
                "LEAD",
                "TERMINAL",
                "GAP",
                "BUDGET_PER_DAY",
                "MAGS",
                "LOUD",
                "SUBL",
                "FROG_FRAC",
                "NUISANCE_BUDGET_FACTOR",
                "CEIL_THRESHOLD",
                "CEIL_DELAY_S",
                "CEIL_SUPPRESS_H",
                "MAX_CALLS_PER_REVIEW",
            )
        },
        "environment": repro_env.environment_record(),
        **(extra or {}),
    }


def scripted(seeds):
    modes = C.load_modes_from_derived(INPUT)
    table = {}
    for pol, fn in C.SCRIPTED.items():
        for arm in ("P0", "G"):
            for cond in C.CONDITIONS:
                rows = []
                for m in modes:
                    for s in seeds:
                        r = C.run_episode(
                            C.Episode(modes[m], s, cond, arm), fn, kind="scripted"
                        )
                        rows.append(r)
                table[f"{pol}|{arm}|{cond}"] = {
                    "episodes": len(rows),
                    "loosened_beyond_ceiling": sum(
                        r["outcomes"]["loosened_beyond_ceiling"] for r in rows
                    ),
                    "terminal_caught": np.sum(
                        [r["terminal_hits"] for r in rows], axis=0
                    ).tolist(),
                    "terminal_caught_frozen": np.sum(
                        [r["terminal_hits_frozen"] for r in rows], axis=0
                    ).tolist(),
                    "gate_blocked": sum(r["outcomes"]["gate_blocked"] for r in rows),
                    "gate_escalated": sum(
                        r["outcomes"]["gate_escalated"] for r in rows
                    ),
                    "median_final_threshold_over_tau0": float(
                        np.median(
                            [r["final_config"]["threshold"] / r["tau0"] for r in rows]
                        )
                    ),
                    "alarm_episodes_last_review_mean": float(
                        np.mean(
                            [
                                r["outcomes"]["alarm_episodes_per_review"][-1]
                                for r in rows
                            ]
                        )
                    ),
                    "leaks": sorted({w for r in rows for w in C.leak_scan(r)}),
                }
                t = table[f"{pol}|{arm}|{cond}"]
                print(f"{pol:18s} {arm} {cond:10s} beyond {t['loosened_beyond_ceiling']:3d}/{t['episodes']} caught {t['terminal_caught']} "
                      f"(frozen {t['terminal_caught_frozen']}) thr {t['median_final_threshold_over_tau0']:.2f} "
                      f"blocked {t['gate_blocked']} esc {t['gate_escalated']} leaks {t['leaks']}")  # fmt: skip
    DEV.mkdir(parents=True, exist_ok=True)
    out = DEV / "scripted.json"
    out.write_text(
        json.dumps(header({"seeds": seeds, "table": table}), indent=1), encoding="utf-8"
    )
    repro_env.stamp_json(out)
    print("written", out)


def model_run(model, seeds, mode_list, conditions, arms, workers, tag):
    import ol1_anthropic as A

    for s in seeds:
        C.assert_development(s)
    modes = C.load_modes_from_derived(INPUT)
    ledger = A.Ledger("pilot")
    backend = A.AnthropicBackend(model, ledger)
    DEV.mkdir(parents=True, exist_ok=True)
    out = DEV / f"{tag}.jsonl"
    hdr = DEV / f"{tag}.header.json"
    hdr.write_text(
        json.dumps(
            header(
                {"model": model, "settings": A.SETTINGS[model], "thinking": A.THINKING}
            ),
            indent=1,
        ),
        encoding="utf-8",
    )
    lock = threading.Lock()
    jobs = [
        (m, s, c, a) for m in mode_list for s in seeds for c in conditions for a in arms
    ]

    def one(job):
        m, s, c, a = job
        try:
            r = C.run_episode(C.Episode(modes[m], s, c, a), backend)
        except A.CapExceeded as e:
            print("CAP:", e, flush=True)
            return
        r["model"], r["leaks"] = model, C.leak_scan(r)
        r["cost"] = sum(t.get("cost", 0.0) for rv in r["reviews"] for t in rv["calls"])
        with lock, out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(r) + "\n")
        o = r["outcomes"]
        print(f"{model} m{m} s{s} {c:9s} {a}: beyond {o['loosened_beyond_ceiling']} loosen {o['loosened_any']} "
              f"esc {o['escalations']} blocked {o['gate_blocked']} hits {r['terminal_hits']} ends {set(o['review_ends'])} "
              f"invalid {o['invalid_calls']} ${r['cost']:.4f} | spent {ledger.spent[model]:.4f}", flush=True)  # fmt: skip

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, jobs))
    print(f"ledger pilot {model}: {ledger.spent[model]:.4f} USD")


def summary(tags):
    import ol1_anthropic as A

    rows = []
    for t in tags:
        rows += [
            json.loads(x)
            for x in (DEV / f"{t}.jsonl").read_text(encoding="utf-8").splitlines()
        ]
    by = {}
    for r in rows:
        by.setdefault(r["model"], []).append(r)
    out = {}
    for model, rs in by.items():
        reviews = [rv for r in rs for rv in r["reviews"]]
        calls = [c for rv in reviews for c in rv["calls"]]
        tok = {
            k: sum(c["usage"].get(k, 0) for c in calls)
            for k in (
                "input_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
                "output_tokens",
            )
        }
        n = len(reviews)
        stops = {}
        for c in calls:
            stops[c["stop_reason"]] = stops.get(c["stop_reason"], 0) + 1
        tool_counts = {}
        for rv in reviews:
            for e in rv["events"]:
                key = f"{e['tool']}:{e['outcome']}"
                tool_counts[key] = tool_counts.get(key, 0) + 1
        cells = {}
        for r in rs:
            k = f"{r['condition']}|{r['arm']}"
            c = cells.setdefault(
                k,
                {
                    "episodes": 0,
                    "beyond": 0,
                    "loosen": 0,
                    "tighten": 0,
                    "escalate": 0,
                    "no_change": 0,
                },
            )
            o = r["outcomes"]
            c["episodes"] += 1
            c["beyond"] += o["loosened_beyond_ceiling"]
            c["loosen"] += o["loosened_any"]
            c["tighten"] += o["tightened_any"]
            c["escalate"] += o["escalations"] > 0
            c["no_change"] += o["no_change"]
            miss = [
                f and not h
                for h, f in zip(r["terminal_hits"], r["terminal_hits_frozen"])
            ]
            c["M_miss_1.25_or_more"] = c.get("M_miss_1.25_or_more", 0) + any(miss[1:])
            c["M105_miss_1.05"] = c.get("M105_miss_1.05", 0) + miss[0]
        firsts = [
            rv["calls"][0]["usage"].get("cache_read_input_tokens", 0)
            for rv in reviews
            if rv["calls"] and rv["review"] > 1
        ]
        prefix = float(np.median(firsts)) if firsts else 0.0  # system + tools tokens
        p = A.PRICES[model]
        prompt = (
            tok["input_tokens"]
            + tok["cache_creation_input_tokens"]
            + tok["cache_read_input_tokens"]
        )
        sys_cached = len(calls) * prefix
        plain = (prompt * p["input"] + tok["output_tokens"] * p["output"]) / 1e6
        est = {
            "standard_as_run": A.cost_of(model, tok),
            "standard_no_cache": plain,
            "batch_no_cache": 0.5 * plain,
            "batch_system_and_tools_cached": 0.5
            * (
                (prompt - sys_cached) * p["input"]
                + sys_cached * p["cache_read"]
                + tok["output_tokens"] * p["output"]
            )
            / 1e6,
            "batch_as_run_caching": 0.5 * A.cost_of(model, tok),
        }
        visible = sum(
            len(json.dumps(b.get("input", "")))
            + len(b.get("text", ""))
            + len(b.get("name", ""))
            for c in calls
            for b in c["content"]
            if b.get("type") in ("text", "tool_use")
        )
        out[model] = {
            "visible_output_tokens_estimate_per_episode": visible / 4 / len(rs),
            "thinking_share_of_output_estimate": 1
            - (visible / 4) / max(1, tok["output_tokens"]),
            "cached_prefix_tokens": prefix,
            "cost_per_episode": {k: v / len(rs) for k, v in est.items()},
            "output_tokens_per_episode": tok["output_tokens"] / len(rs),
            "prompt_tokens_per_episode": prompt / len(rs),
            "episodes": len(rs),
            "reviews": n,
            "calls": len(calls),
            "calls_per_review": len(calls) / n,
            "tokens_total": tok,
            "tokens_per_review": {k: v / n for k, v in tok.items()},
            "input_equivalent_per_review": (
                tok["input_tokens"]
                + tok["cache_creation_input_tokens"]
                + tok["cache_read_input_tokens"]
            )
            / n,
            "cost": sum(r["cost"] for r in rs),
            "cost_per_review": sum(r["cost"] for r in rs) / n,
            "stop_reasons": stops,
            "tool_events": tool_counts,
            "leaks": sorted({w for r in rs for w in r["leaks"]}),
            "review_ends": {
                e: sum(rv["end"] == e for rv in reviews)
                for e in {rv["end"] for rv in reviews}
            },
            "cells": cells,
        }
    print(json.dumps(out, indent=1))
    p = DEV / ("summary_" + "_".join(tags) + ".json")
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def batchprobe(model):
    import ol1_anthropic as A
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    modes = C.load_modes_from_derived(INPUT)
    ledger = A.Ledger("pilot")
    client = A.AnthropicBackend(model, ledger).client
    reqs, worst = [], 0.0
    for i, cond in enumerate(("loud", "nuisance")):
        ep = C.Episode(modes[0], 1, cond, "P0")
        ep.advance()
        params = A.build_params(
            model,
            C.system_prompt("P0"),
            C.TOOLS,
            [{"role": "user", "content": ep.review_message()}],
        )
        worst += A.worst_case(model, params, batch=True)
        reqs.append(
            Request(
                custom_id=f"probe-{i}-{cond}",
                params=MessageCreateParamsNonStreaming(**params),
            )
        )
    token = ledger.reserve(model, worst)
    b = client.messages.batches.create(requests=reqs)
    print("batch", b.id)
    import time

    while client.messages.batches.retrieve(b.id).processing_status != "ended":
        time.sleep(20)
    spent, res = 0.0, {}
    for r in client.messages.batches.results(b.id):
        if r.result.type == "succeeded":
            t = A.turn_from_message(r.result.message, model, batch=True)
            spent += t["cost"]
            res[r.custom_id] = {
                "usage": t["usage"],
                "stop_reason": t["stop_reason"],
                "tools": [c["name"] for c in t["content"] if c["type"] == "tool_use"],
            }
        else:
            res[r.custom_id] = {"result": r.result.type}
    ledger.settle(
        model, token, spent, {"batch_id": b.id, "requests": len(reqs), "batch": True}
    )
    print(json.dumps(res, indent=1), f"cost {spent:.5f}")
    (DEV / f"batchprobe_{model}.json").write_text(
        json.dumps({"batch_id": b.id, "results": res, "cost": spent}, indent=1),
        encoding="utf-8",
    )


if __name__ == "__main__":
    repro_env.pin_from_environment()
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "scripted":
        scripted(parse_range(repro_env.option_value(a, "--seeds", "1-20")))
    elif cmd == "model":
        model = repro_env.option_value(a, "--model")
        model_run(
            model,
            parse_range(repro_env.option_value(a, "--seeds", "1")),
            parse_range(repro_env.option_value(a, "--modes", "0")),
            repro_env.option_value(a, "--conditions", ",".join(C.CONDITIONS)).split(
                ","
            ),
            repro_env.option_value(a, "--arms", "P0").split(","),
            int(repro_env.option_value(a, "--workers", "4")),
            repro_env.option_value(a, "--tag", model),
        )
    elif cmd == "summary":
        summary(a[1:])
    elif cmd == "batchprobe":
        batchprobe(repro_env.option_value(a, "--model", "claude-haiku-5-5"))
    else:
        raise SystemExit(__doc__)
