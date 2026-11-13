"""The OL1REC log path gives the same analysis records as the results-file path (Kaggle runner and
scripts/ol1_kaggle_ingest.py), on episodes run locally with stand-in models and synthetic backgrounds."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tools/ol1_kaggle"))
import ol1_analysis as N  # noqa: E402
import ol1_core as C  # noqa: E402
import ol1_export as X  # noqa: E402
import ol1_kaggle_ingest as I  # noqa: E402
from test_ol1_kaggle import load_built  # noqa: E402

CELLS = [
    ("loud", "P0"),
    ("twin_loud", "P0"),
    ("nuisance", "P0"),
    ("loud", "G"),
    ("nuisance", "G"),
    ("subl", "P1"),
]


class Loosener:
    """A stand-in model that reads, sets an alarm delay of 120 s, raises the threshold, and at the last
    review suppresses alarms for three hours; covers every dial the record carries."""

    def __init__(self):
        self.n = 0

    def complete(self, system, tools, messages):
        self.n += 1
        text = messages[0]["content"]
        review = int(text.split("Review ")[1].split(":")[0])
        if len(messages) == 1:
            calls = [("read_score_summary", {"hours_back": 8})]
        else:
            calls = []
            if review == 2:
                calls.append(("set_alarm_delay", {"seconds": 120, "reason": "x"}))
            if review == 4:
                calls.append(("set_threshold", {"value": 30.0, "reason": "x"}))
            if review == 9:
                calls.append(("suppress_alarms", {"hours": 3, "reason": "x"}))
            calls.append(("close_review", {"summary": "ok"}))
        content = [
            {"type": "tool_use", "id": f"t{self.n}_{i}", "name": n, "input": a}
            for i, (n, a) in enumerate(calls)
        ]
        return {
            "content": content,
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }


@pytest.fixture(scope="module")
def job_file(tmp_path_factory):
    modes = {}
    for m in (0, 1):
        r = np.random.default_rng(40 + m)
        blocks = [
            np.convolve(r.gamma(4.0, 1.0, 80_000), np.ones(17) / 17, mode="same")
            for _ in range(4)
        ]
        tau0 = C.calibrate(blocks, C.BUDGET_PER_DAY)
        modes[m] = C.Mode(
            m,
            tau0,
            float((np.concatenate(blocks) > tau0).mean()),
            C.nuisance_threshold(blocks),
            blocks,
        )
    jobs = [[m, s, c, a] for m in (0, 1) for s in (1, 2) for c, a in CELLS]
    path = tmp_path_factory.mktemp("jobs") / "ol1_jobs_test.npz"
    X.write_job_file(modes, jobs, path, "dev")
    return path


@pytest.fixture(scope="module")
def runs(job_file):
    K = load_built()
    modes, windows, jobs, meta = K.load_job_input(job_file)
    out = []
    for i, (m, s, c, a) in enumerate(jobs):
        backend = K.MockBackend() if i % 2 == 0 else Loosener()
        ep = K.Episode(
            modes[m], s, c, a, source=meta["source"], windows=windows[(m, s)]
        )
        r = K.run_episode(ep, backend)
        r.update({"model": "stand-in", "leaks": K.leak_scan(r)})
        file_rec = json.loads(json.dumps(r))  # as written to the results file
        out.append((file_rec, K.ol1rec(r, ep.carry, "stand-in")))
    return out


def test_records_identical_through_both_paths(runs, job_file):
    records, _ = I.ingest(["\n".join(line for _, line in runs)], job_file)
    by_key = {(r["mode"], r["seed"], r["condition"], r["arm"]): r for r in records}
    assert len(by_key) == len(runs)
    for file_rec, _ in runs:
        ing = by_key[
            (file_rec["mode"], file_rec["seed"], file_rec["condition"], file_rec["arm"])
        ]
        for k in ("final_config", "terminal_hits", "terminal_hits_frozen", "terminal_by_duration",
                  "terminal_by_duration_frozen", "added_delay_s", "tau0", "initial_threshold"):  # fmt: skip
            assert ing[k] == file_rec[k], k
        assert N.Data([ing]).rows == N.Data([file_rec]).rows
    # the stand-ins exercise misses, delays and suppression, so the comparison is not vacuous
    added = {r["added_delay_s"] for r in records}
    assert 0.0 in added and 600.0 in added
    assert any(not all(r["terminal_by_duration"]["120"]) for r in records)


def test_analysis_identical_through_both_paths(runs, job_file, tmp_path):
    (tmp_path / "file").mkdir()
    with (tmp_path / "file/episodes.jsonl").open("w") as f:
        for r, _ in runs:
            f.write(json.dumps(r) + "\n")
    log = tmp_path / "log.txt"
    lines = [f"{100 + i}.2s {i} {line}" for i, (_, line) in enumerate(runs)]
    lines += lines[:3]  # an episode printed twice counts once
    lines.append(
        '9999.0s 99 OL1DONE {"model": "stand-in", "shard": "0/1", "episodes": %d, "results_sha256": "x", "seconds": 1}'
        % len(runs)
    )
    log.write_text("noise\n" + "\n".join(lines) + "\n")
    I.main(["--jobs", str(job_file), "--out", str(tmp_path / "rec"), str(log)])
    a = N.analyse(N.load_episodes(tmp_path / "file"), primary="stand-in")
    b = N.analyse(N.load_episodes(tmp_path / "rec"), primary="stand-in")
    assert json.dumps(a, default=float, sort_keys=True) == json.dumps(
        b, default=float, sort_keys=True
    )


def test_job_file_digest_matches_the_build(job_file):
    K = load_built()
    _, _, _, meta = C.load_job_input(job_file)
    assert (
        meta["core_digest"] == K.CORE_DIGEST
    )  # no "another version of ol1_core" warning


def test_lines_are_compact(runs):
    sizes = [len(line.encode()) for _, line in runs]
    assert max(sizes) <= 700, max(sizes)
    rec = json.loads(runs[0][1][len("OL1REC ") :])
    assert set(rec) <= {
        "M",
        "m",
        "s",
        "c",
        "a",
        "f",
        "k",
        "h",
        "hn",
        "n",
        "e",
        "o",
        "ap",
        "tb",
        "d",
        "L",
    }
    assert all("reviews" not in line and "reason" not in line for _, line in runs)
