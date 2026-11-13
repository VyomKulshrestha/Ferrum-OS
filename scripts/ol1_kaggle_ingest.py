#!/usr/bin/env python3
"""ol1 open-weight arm: turn OL1REC lines copied from a Kaggle notebook log into the episode records that
scripts/ol1_analysis.py reads. Exploratory arm (protocol and docs/research/operator_in_the_loop_ol1_notes.md).

    python scripts/ol1_kaggle_ingest.py --jobs target/ol1/kaggle/ol1_jobs_kaggle_sealed.npz \\
        --out target/ol1/kaggle/results/qwen3-8b LOG.txt [LOG2.txt ...]

Each input is text pasted from the notebook's log page; any line containing "OL1REC " counts (prefixes such as
timestamps are ignored, and an episode printed twice is kept once). The terminal outcomes (M(d) and the added
detection delay) are recomputed by replaying the final configuration on the episode's background windows from
the job file, exactly as the runner computes them. The "OL1DONE" line, when present, is checked against the
number of episodes. Writes <out>/episodes.jsonl.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ol1_core as C

TOOLS = {
    "thr": "set_threshold",
    "dly": "set_alarm_delay",
    "sup": "suppress_alarms",
    "rcl": "recalibrate_threshold",
    "exc": "exclude_channel",
    "rah": "read_alarm_history",
    "rss": "read_score_summary",
    "rcf": "read_configuration",
    "esc": "escalate_to_engineer",
    "cls": "close_review",
}


def parse_lines(texts):
    """(records keyed by episode, OL1DONE dicts) from log text."""
    recs, done = {}, []
    for text in texts:
        for line in text.splitlines():
            if "OL1REC " in line:
                body = line[line.index("OL1REC ") + 7 :].strip()
                r = json.loads(body)
                recs.setdefault((r["M"], r["m"], r["s"], r["c"], r["a"]), r)
            elif "OL1DONE " in line:
                done.append(json.loads(line[line.index("OL1DONE ") + 8 :].strip()))
    return recs, done


def episode_record(r, modes, windows, source) -> dict:
    """The analysis record of one OL1REC line, with the terminal outcomes recomputed by replay."""
    m, s = int(r["m"]), int(r["s"])
    ep = C.Episode(modes[m], s, r["c"], r["a"], source=source, windows=windows[(m, s)])
    thr, delay, mute, excl = r["f"]
    ep.cfg = {
        "threshold": thr,
        "delay_s": delay,
        "mute_until": int(mute),
        "excluded": bool(excl),
    }
    ep.carry = int(r["k"])
    o = r["o"]
    ends = [e for e, n in r["e"].items() for _ in range(n)]
    return {
        "model": r["M"],
        "mode": m,
        "seed": s,
        "condition": r["c"],
        "arm": r["a"],
        "tau0": ep.tau0,
        "initial_threshold": ep.thr0,
        "final_config": dict(ep.cfg),
        "terminal_hits": ep.terminal(),
        "terminal_hits_frozen": ep.terminal(ep.frozen_cfg()),
        "terminal_by_duration": ep.terminal_by_duration(),
        "terminal_by_duration_frozen": ep.terminal_by_duration(ep.frozen_cfg()),
        "added_delay_s": ep.added_delay_s(),
        "outcomes": {
            "loosened_beyond_ceiling": bool(o[0]),
            "first_beyond_ceiling_review": o[1],
            "loosened_any": bool(o[2]),
            "first_loosening_review": o[3],
            "tightened_any": bool(o[4]),
            "no_change": bool(o[5]),
            "escalations": r["n"][4],
            "gate_blocked": r["n"][2],
            "gate_escalated": r["n"][3],
            "invalid_calls": r["n"][1],
            "dials_applied": [TOOLS.get(t, t) for t in r["d"]],
            "tools_after_block": [TOOLS.get(t, t) for t in r["tb"]],
            "alarm_episodes_per_review": list(r["ap"]),
            "review_ends": ends,  # counts per kind; the order of reviews is not kept
        },
        "model_calls": r["n"][0],
        "changes": [[h[0], TOOLS.get(h[1], h[1]), h[2]] for h in r["h"]],
        "changes_total": r["hn"],
        "leaks": r.get("L", []),
        "source": "OL1REC",
    }


def ingest(texts, job_file):
    modes, windows, _, meta = C.load_job_input(job_file)
    recs, done = parse_lines(texts)
    out = [
        episode_record(r, modes, windows, meta.get("source", "dev"))
        for r in recs.values()
    ]
    return out, done


def main(argv):
    import repro_env

    if not argv:
        raise SystemExit(__doc__)
    jobs = Path(repro_env.option_value(argv, "--jobs"))
    out_dir = Path(repro_env.option_value(argv, "--out"))
    logs, i = [], 0
    while i < len(argv):
        if argv[i] in ("--jobs", "--out"):
            i += 2
            continue
        if not argv[i].startswith("--"):
            logs.append(argv[i])
        i += 1
    texts = [Path(p).read_text(encoding="utf-8", errors="replace") for p in logs]
    records, done = ingest(texts, jobs)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "episodes.jsonl").open("w", encoding="utf-8") as f:
        for r in sorted(
            records,
            key=lambda x: (x["model"], x["mode"], x["seed"], x["condition"], x["arm"]),
        ):
            f.write(json.dumps(r) + "\n")
    print(f"{len(records)} episodes written to {out_dir / 'episodes.jsonl'}")
    for d in done:
        n = sum(1 for r in records if r["model"] == d.get("model"))
        flag = "matches" if n == d.get("episodes") else "DOES NOT MATCH"
        print(f"OL1DONE {d.get('model')} shard {d.get('shard')}: {d.get('episodes')} episodes ({flag} {n} ingested), "
              f"results sha256 {d.get('results_sha256')}, {d.get('seconds')} s")  # fmt: skip
    return records


if __name__ == "__main__":
    main(sys.argv[1:])
