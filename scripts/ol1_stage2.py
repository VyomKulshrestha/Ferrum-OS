#!/usr/bin/env python3
"""ol1 stage 2: the registered run of the Claude grids (protocol sections 8 and 13).

    python scripts/ol1_stage2.py check
        verify the registration record against the protocol and the code; prints what it checked
    python scripts/ol1_stage2.py jobfile
        (registered only) write target/ol1/stage2/ol1_jobs_sealed.npz from the tt1f cache's sealed runs
    python scripts/ol1_stage2.py run --model claude-haiku-5-5 [--waves 0-6]
        (registered only) run the model's grid through the Message Batches API, one wave per mode, under
        the 'registered' ledger scope; resumes after a restart
    python scripts/ol1_stage2.py dryrun --model mock|claude-haiku-5-5 --modes 0 --seeds 1 [--cells reduced]
            [--max-rounds N] [--out DIR]
        the same runner on development seeds (mock client, or the real API under the 'pilot' scope)

Resuming: every model response is appended to turns.jsonl under its custom_id before the episode moves on,
and every submitted batch is recorded in submitted.jsonl (batch id, custom ids, ledger token) before its
results are read. On restart the environment is replayed from the recorded responses (it is deterministic),
batches already submitted are collected instead of resubmitted, and finished episodes are skipped.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ol1_anthropic as A
import ol1_core as C
import ol1_export as X
import repro_env

ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = ROOT / "docs/research/operator_in_the_loop_ol1_registration.json"
PROTOCOL = "docs/research/operator_in_the_loop_ol1_protocol.md"
STAGE2 = ROOT / "target/ol1/stage2"
SEALED_CACHE = Path(
    r"C:\Users\marcu\Videos\cursor-os-base-tt1\target\real-telemetry\tt1f"
)
SETUP = Path(r"C:\Users\marcu\Videos\cursor-os-base-tt1\target\tw1\tep_setup.json")
CODE_FILES = (
    "scripts/ol1_core.py",
    "scripts/ol1_anthropic.py",
    "scripts/ol1_export.py",
    "scripts/ol1_stage2.py",
    "scripts/ol1_analysis.py",
    "scripts/repro_env.py",
)

REDUCED = (
    ("loud", "P0"),
    ("twin_loud", "P0"),
    ("nuisance", "P0"),
    ("loud", "G"),
    ("nuisance", "G"),
)
# model -> list of (condition, arm, replicates, runs): protocol section 8
GRIDS = {
    "claude-haiku-5-5": [
        (c, a, (0, 1), tuple(range(8))) for c in C.CONDITIONS for a in ("P0", "G")
    ]
    + [(c, a, (0,), tuple(range(8))) for c in C.CONDITIONS for a in ("P1", "P2")],
    "claude-sonnet-5-5": [(c, a, (0,), tuple(range(8))) for c, a in REDUCED],
    "claude-opus-5-5": [(c, a, (0,), tuple(range(4))) for c, a in REDUCED],
}
REGISTRATION_FIELDS = (
    "study",  # "ol1"
    "registered_on",  # ISO date
    "protocol_path",  # PROTOCOL
    "protocol_sha256",  # sha256 of the protocol with LF line endings
    "code_commit",  # the commit whose CODE_FILES are registered
    "code_files",  # {path: sha256 with LF line endings} for CODE_FILES
    "caps_usd",  # equal to ol1_anthropic.CAPS["registered"]
    "ledger_scope",  # "registered"
    "grids",  # equal to grids_json()
)


class RegistrationError(RuntimeError):
    pass


def sha256_lf(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def grids_json():
    return {m: [[c, a, list(r), list(u)] for c, a, r, u in g] for m, g in GRIDS.items()}


def git(root, *args, check=True):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if check and r.returncode != 0:
        raise RegistrationError(
            f"git {' '.join(args)}: {r.stderr.decode(errors='replace').strip()}"
        )
    return r


def registration_template(root=ROOT, commit=None) -> dict:
    """The record the coordinating session fills and commits (helper; the check below is what counts)."""
    root = Path(root)
    return {
        "study": "ol1",
        "registered_on": time.strftime("%Y-%m-%d"),
        "protocol_path": PROTOCOL,
        "protocol_sha256": sha256_lf((root / PROTOCOL).read_bytes()),
        "code_commit": commit or git(root, "rev-parse", "HEAD").stdout.decode().strip(),
        "code_files": {f: sha256_lf((root / f).read_bytes()) for f in CODE_FILES},
        "caps_usd": A.CAPS["registered"],
        "ledger_scope": "registered",
        "grids": grids_json(),
    }


def check_registration(root=ROOT, reg_path=None) -> dict:
    """Refuse unless the registration record is committed and matches the protocol and the code."""
    root = Path(root)
    reg_path = Path(reg_path or root / REGISTRATION.relative_to(ROOT))
    if not reg_path.exists():
        raise RegistrationError(f"no registration record at {reg_path}")
    rel = reg_path.relative_to(root).as_posix()
    if not git(root, "ls-files", "--error-unmatch", rel, check=False).returncode == 0:
        raise RegistrationError("the registration record is not committed")
    if git(root, "status", "--porcelain", "--", rel).stdout.strip():
        raise RegistrationError("the registration record has uncommitted changes")
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    missing = [f for f in REGISTRATION_FIELDS if f not in reg]
    if missing:
        raise RegistrationError(f"registration record lacks {missing}")
    proto = (root / reg["protocol_path"]).read_bytes()
    if sha256_lf(proto) != reg["protocol_sha256"]:
        raise RegistrationError("the protocol differs from the registered digest")
    if b"**DRAFT" in proto:
        raise RegistrationError("the protocol is still marked DRAFT")
    commit = reg["code_commit"]
    if (
        git(root, "merge-base", "--is-ancestor", commit, "HEAD", check=False).returncode
        != 0
    ):
        raise RegistrationError(f"code commit {commit} is not an ancestor of HEAD")
    if set(reg["code_files"]) != set(CODE_FILES):
        raise RegistrationError(
            "the registered code files are not the runner's code files"
        )
    for f, digest in reg["code_files"].items():
        at_commit = git(root, "show", f"{commit}:{f}").stdout
        if (
            sha256_lf(at_commit) != digest
            or sha256_lf((root / f).read_bytes()) != digest
        ):
            raise RegistrationError(f"{f} differs from the registered version")
    if reg["caps_usd"] != A.CAPS["registered"] or reg["ledger_scope"] != "registered":
        raise RegistrationError("caps or ledger scope differ from the code")
    if reg["grids"] != grids_json():
        raise RegistrationError("grids differ from the code")
    return reg


def enable_sealed(root=ROOT):
    reg = check_registration(root)
    C.ALLOW_SEALED = True
    return reg


# ---------------------------------------------------------------- jobs
def grid_jobs(model: str, source: str, modes=range(7), dev_seeds=None) -> list:
    """[mode, seed, condition, arm] for a model's grid. Sealed: sealed_seed(mode, run, replicate).
    Development dry runs use the given development seeds in place of (run, replicate)."""
    out = []
    for m in modes:
        for cond, arm, reps, runs in GRIDS[model]:
            if source == "sealed":
                seeds = [C.sealed_seed(m, u, r) for u in runs for r in reps]
            else:
                seeds = list(dev_seeds)
                for s in seeds:
                    C.assert_development(s)
            out += [[m, s, cond, arm] for s in seeds]
    return out


def write_sealed_job_file(
    out: Path, cache: Path = SEALED_CACHE, setup: Path = SETUP, root=ROOT
):
    """Registered only. Reads the eight attack-free (sealed) runs of each mode from the tt1f cache, in the
    order of tep_setup.json, and writes the job file of every Claude grid's placements."""
    if not C.ALLOW_SEALED:
        raise C.SealedSeedError("call enable_sealed() first (registration check)")
    import numpy as np

    dev = C.load_modes_from_derived(X.DEV_INPUT)
    names = json.loads(Path(setup).read_text(encoding="utf-8"))["modes"]
    modes = {}
    for m in range(7):
        z = np.load(Path(cache) / f"mode_{m}.npz", allow_pickle=False)
        runs = [
            np.asarray(z["sealed::" + r["name"]], np.float64)
            for r in names[str(m)]["sealed"]
        ]
        d = dev[m]
        modes[m] = C.Mode(m, d.tau0, d.p, d.tau_tight, [], sealed_runs=runs)
    jobs = sorted({tuple(j) for model in GRIDS for j in grid_jobs(model, "sealed")})
    X.write_job_file(modes, [list(j) for j in jobs], out, "sealed")


# ---------------------------------------------------------------- the resumable batch runner
def job_key(job) -> str:
    m, s, c, a = job
    return f"m{m}-s{s}-{c}-{a}"


class ResumableRun:
    """One wave of episodes through the Message Batches API, with the state on disk (see module doc)."""

    def __init__(self, model, ledger, client, state_dir: Path, poll=30.0, log=print):
        self.model, self.ledger, self.client, self.poll, self.log = (
            model,
            ledger,
            client,
            poll,
            log,
        )
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.turns_path = self.dir / "turns.jsonl"
        self.sub_path = self.dir / "submitted.jsonl"
        self.ep_path = self.dir / "episodes.jsonl"

    def _read(self, p):
        if not p.exists():
            return []
        return [
            json.loads(x)
            for x in p.read_text(encoding="utf-8").splitlines()
            if x.strip()
        ]

    def _append(self, p, rec):
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def _collect(self, batch_id):
        while (
            self.client.messages.batches.retrieve(batch_id).processing_status != "ended"
        ):
            time.sleep(self.poll)
        got, cost = {}, 0.0
        for res in self.client.messages.batches.results(batch_id):
            if res.result.type == "succeeded":
                t = A.turn_from_message(res.result.message, self.model, batch=True)
            else:
                t = {
                    "content": [],
                    "stop_reason": "error",
                    "error": res.result.type,
                    "usage": {},
                    "cost": 0.0,
                }
            t["request_id"], t["batch_id"] = res.custom_id, batch_id
            cost += t["cost"]
            got[res.custom_id] = t
        return got, cost

    def run(self, jobs, make_episode, max_rounds=None) -> str:
        """jobs: [mode, seed, condition, arm]; make_episode(job) -> ol1_core.Episode. Returns 'done' or
        'paused' (max_rounds reached)."""
        turns = {r["custom_id"]: r["turn"] for r in self._read(self.turns_path)}
        # batches submitted before a restart whose results were not all recorded
        subs = self._read(self.sub_path)
        settled = {s["batch_id"] for s in subs if s.get("settled")}
        for sub in subs:
            if sub.get("settled") or sub["batch_id"] in settled:
                continue
            got, cost = self._collect(sub["batch_id"])
            for cid, t in got.items():
                if cid not in turns:
                    turns[cid] = t
                    self._append(self.turns_path, {"custom_id": cid, "turn": t})
            rec = {
                "batch_id": sub["batch_id"],
                "requests": len(sub["custom_ids"]),
                "batch": True,
                "resumed": True,
            }
            self.ledger.settle_foreign(
                self.model, sub["token"], sub["worst"], cost, rec
            )
            self._append(self.sub_path, {**sub, "settled": True, "custom_ids": []})
        done = {r["key"] for r in self._read(self.ep_path)}
        live = {}
        for job in jobs:
            k = job_key(job)
            if k in done:
                continue
            g = C.episode_steps(make_episode(job))
            live[k] = {"g": g, "n": 0, "req": next(g), "job": job}
        rounds = 0
        while live:
            # replay recorded responses until every live episode needs a new one
            need = {}
            for k in list(live):
                e = live[k]
                while True:
                    cid = f"{k}-c{e['n']:03d}"
                    if cid not in turns:
                        need[cid] = k
                        break
                    e["n"] += 1
                    try:
                        e["req"] = e["g"].send(turns[cid])
                    except StopIteration as stop:
                        r = stop.value
                        r.update(
                            {"key": k, "model": self.model, "leaks": C.leak_scan(r)}
                        )
                        r["cost"] = sum(
                            t.get("cost", 0.0)
                            for rv in r["reviews"]
                            for t in rv["calls"]
                        )
                        self._append(self.ep_path, r)
                        del live[k]
                        break
            if not need:
                continue
            if max_rounds is not None and rounds >= max_rounds:
                return "paused"
            rounds += 1
            reqs, worst = [], 0.0
            for cid, k in need.items():
                system, tools, messages = live[k]["req"]
                params = A.build_params(self.model, system, tools, messages, batch=True)
                worst += A.worst_case(self.model, params, batch=True)
                reqs.append({"custom_id": cid, "params": params})
            token = self.ledger.reserve(self.model, worst)
            try:
                batch = self.client.messages.batches.create(requests=reqs)
            except Exception:
                self.ledger.release(self.model, token)
                raise
            sub = {
                "batch_id": batch.id,
                "custom_ids": list(need),
                "token": token,
                "worst": worst,
            }
            self._append(self.sub_path, sub)
            self.log(
                f"{self.dir.name}: round {rounds}, batch {batch.id}, {len(reqs)} requests, worst case {worst:.4f}"
            )
            got, cost = self._collect(batch.id)
            for cid, t in got.items():
                turns[cid] = t
                self._append(self.turns_path, {"custom_id": cid, "turn": t})
            for cid in need:
                if (
                    cid not in turns
                ):  # a request missing from the results: recorded as an error turn
                    turns[cid] = {
                        "content": [],
                        "stop_reason": "error",
                        "error": "missing",
                        "usage": {},
                        "cost": 0.0,
                    }
                    self._append(
                        self.turns_path, {"custom_id": cid, "turn": turns[cid]}
                    )
            self.ledger.settle(
                self.model,
                token,
                cost,
                {"batch_id": batch.id, "requests": len(reqs), "batch": True},
            )
            self._append(self.sub_path, {**sub, "settled": True, "custom_ids": []})
        return "done"


def run_waves(
    model,
    jobs,
    make_episode,
    out_dir,
    ledger,
    client,
    waves=range(7),
    max_rounds=None,
    log=print,
):
    """One wave per mode, in order; a wave that is done is skipped. Returns {mode: status}."""
    status = {}
    for m in waves:
        wj = [j for j in jobs if j[0] == m]
        if not wj:
            continue
        d = Path(out_dir) / model / f"wave_mode{m}"
        if (d / "DONE").exists():
            status[m] = "done"
            continue
        s = ResumableRun(
            model, ledger, client, d, log=log, poll=getattr(client, "poll", 30.0)
        ).run(wj, make_episode, max_rounds)
        status[m] = s
        if s == "done":
            (d / "DONE").write_text("done\n", encoding="utf-8")
        else:
            break
    return status


# ---------------------------------------------------------------- mock client (dry runs and tests)
class MockMessage:
    def __init__(self, turn):
        self._d = {
            "id": "msg_mock",
            "model": "mock",
            "content": turn["content"],
            "stop_reason": turn["stop_reason"],
            "stop_details": None,
        }
        u = dict(turn["usage"])
        self.usage = type("U", (), {"to_dict": staticmethod(lambda: u)})()

    def to_dict(self):
        return json.loads(json.dumps(self._d))


class MockClient:
    """Message Batches look-alike answering with ol1_core.MockBackend."""

    poll = 0.0

    def __init__(self):
        outer = self
        self.store, self.backend = {}, C.MockBackend()

        class Batches:
            def create(self, requests):
                bid = f"mockbatch_{len(outer.store)}"
                outer.store[bid] = list(requests)
                return type("B", (), {"id": bid})()

            def retrieve(self, bid):
                return type("B", (), {"processing_status": "ended"})()

            def results(self, bid):
                out = []
                for r in reversed(outer.store[bid]):  # any order
                    p = r["params"]
                    turn = outer.backend.complete(
                        p["system"][0]["text"], p["tools"], p["messages"]
                    )
                    res = type(
                        "R", (), {"type": "succeeded", "message": MockMessage(turn)}
                    )()
                    out.append(
                        type("X", (), {"custom_id": r["custom_id"], "result": res})()
                    )
                return out

        self.messages = type("M", (), {"batches": Batches()})()


def make_dev_episode_factory():
    modes = C.load_modes_from_derived(X.DEV_INPUT)
    return lambda job: C.Episode(modes[job[0]], job[1], job[2], job[3])


def make_jobfile_factory(path):
    modes, windows, _, meta = C.load_job_input(path)
    src = meta["source"]
    return lambda job: C.Episode(
        modes[job[0]],
        job[1],
        job[2],
        job[3],
        source=src,
        windows=windows[(job[0], job[1])],
    )


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "check":
        reg = check_registration()
        print(
            "registration ok:",
            reg["registered_on"],
            reg["code_commit"],
            reg["protocol_sha256"][:16],
        )
    elif cmd == "jobfile":
        enable_sealed()
        write_sealed_job_file(STAGE2 / "ol1_jobs_sealed.npz")
    elif cmd == "run":
        enable_sealed()
        model = repro_env.option_value(argv, "--model")
        path = STAGE2 / "ol1_jobs_sealed.npz"
        status = run_waves(
            model,
            grid_jobs(model, "sealed"),
            make_jobfile_factory(path),
            STAGE2,
            A.Ledger("registered"),
            _real_client(),
            waves=X.parse_range(repro_env.option_value(argv, "--waves", "0-6")),
        )
        print(status)
    elif cmd == "dryrun":
        model = repro_env.option_value(argv, "--model", "mock")
        modes = X.parse_range(repro_env.option_value(argv, "--modes", "0"))
        seeds = X.parse_range(repro_env.option_value(argv, "--seeds", "1"))
        out = Path(
            repro_env.option_value(argv, "--out", str(ROOT / "target/ol1/dryrun"))
        )
        mr = repro_env.option_value(argv, "--max-rounds")
        grid_model = "claude-haiku-5-5" if model == "mock" else model
        jobs = grid_jobs(grid_model, "dev", modes, seeds)
        if repro_env.option_value(argv, "--cells") == "reduced":
            jobs = [j for j in jobs if (j[2], j[3]) in REDUCED]
        if model == "mock":
            ledger, client = A.Ledger("pilot", out / "ledger"), MockClient()
            model = "claude-haiku-5-5"
        else:
            ledger, client = A.Ledger("pilot"), _real_client()
        status = run_waves(model, jobs, make_dev_episode_factory(), out, ledger, client, waves=modes,
                           max_rounds=None if mr is None else int(mr))  # fmt: skip
        print(status, f"ledger pilot {model}: {ledger.spent[model]:.5f}")
    else:
        raise SystemExit(__doc__)


def _real_client():
    import anthropic

    return anthropic.Anthropic(api_key=A.load_key(), max_retries=3, timeout=300.0)


if __name__ == "__main__":
    repro_env.pin_from_environment()
    main(sys.argv[1:])
