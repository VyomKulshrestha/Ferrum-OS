"""Tests of the ol1 stage-2 runner: grid sizes, resumable batches with the mock client, the ledger across a
restart, the registration check (in a temporary git repository) and the sealed job-file guard.
No sealed run of the score cache is read: the sealed writer is exercised on synthetic arrays only."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ol1_anthropic as A
import ol1_core as C
import ol1_export as X
import ol1_stage2 as S

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mode():
    r = np.random.default_rng(9)
    blocks = [
        np.convolve(r.gamma(4.0, 1.0, 80_000), np.ones(17) / 17, mode="same")
        for _ in range(4)
    ]
    tau0 = C.calibrate(blocks, C.BUDGET_PER_DAY)
    return C.Mode(
        0,
        tau0,
        float((np.concatenate(blocks) > tau0).mean()),
        C.nuisance_threshold(blocks),
        blocks,
    )


def test_grid_sizes():
    n = {m: len(S.grid_jobs(m, "sealed")) for m in S.GRIDS}
    assert n == {
        "claude-haiku-5-5": 2352,
        "claude-sonnet-5-5": 280,
        "claude-opus-5-5": 140,
    }
    seeds = {j[1] for m in S.GRIDS for j in S.grid_jobs(m, "sealed")}
    assert not any(C.is_development(s) for s in seeds)
    with pytest.raises(C.SealedSeedError):
        S.grid_jobs("claude-haiku-5-5", "dev", [0], [C.sealed_seed(0, 0, 0)])


def run_mock(tmp, jobs, factory, max_rounds=None, client=None, ledger=None):
    ledger = ledger or A.Ledger("pilot", tmp / "ledger")
    client = client or S.MockClient()
    st = S.run_waves(
        "claude-haiku-5-5",
        jobs,
        factory,
        tmp,
        ledger,
        client,
        waves=[0],
        max_rounds=max_rounds,
        log=lambda *a: None,
    )
    return st, ledger, client


def outcomes(tmp):
    rows = [
        json.loads(x)
        for x in (tmp / "claude-haiku-5-5/wave_mode0/episodes.jsonl")
        .read_text()
        .splitlines()
    ]
    return {
        r["key"]: (
            r["outcomes"]["loosened_beyond_ceiling"],
            r["final_config"],
            r["terminal_by_duration"],
        )
        for r in rows
    }


def test_resume_gives_the_same_episodes(tmp_path, mode):
    jobs = [[0, s, c, a] for s in (1, 2) for c, a in S.REDUCED]
    factory = lambda j: C.Episode(mode, j[1], j[2], j[3])
    st, _, _ = run_mock(tmp_path / "a", jobs, factory)
    assert st == {0: "done"}
    st, _, _ = run_mock(tmp_path / "b", jobs, factory, max_rounds=4)
    assert st == {0: "paused"}
    (tmp_path / "b/ledger").joinpath(
        "ledger_pilot_claude-haiku-5-5.lock"
    ).unlink()  # a new process
    st, _, _ = run_mock(tmp_path / "b", jobs, factory)
    assert st == {0: "done"}
    assert outcomes(tmp_path / "a") == outcomes(tmp_path / "b")
    assert len(outcomes(tmp_path / "a")) == len(jobs)


def test_restart_after_submission_collects_the_batch(tmp_path, mode):
    jobs = [[0, 1, "loud", "P0"]]
    factory = lambda j: C.Episode(mode, j[1], j[2], j[3])
    client = S.MockClient()
    real_results = client.messages.batches.results

    def boom(bid):
        raise ConnectionError("killed")

    client.messages.batches.results = boom
    with pytest.raises(ConnectionError):
        run_mock(tmp_path, jobs, factory, client=client)
    led_path = tmp_path / "ledger/ledger_pilot_claude-haiku-5-5.jsonl"
    open_worst = A.Ledger.load(led_path)
    assert open_worst > 0  # the in-flight batch counts at its worst case
    (tmp_path / "ledger/ledger_pilot_claude-haiku-5-5.lock").unlink()
    client.messages.batches.results = real_results
    st, _, _ = run_mock(tmp_path, jobs, factory, client=client)
    assert st == {0: "done"}
    assert (
        len(client.store) == C.N_REVIEWS * 2
    )  # the first batch was collected, not resubmitted
    expected = (
        2
        * C.N_REVIEWS
        * A.cost_of(
            "claude-haiku-5-5", {"input_tokens": 1000, "output_tokens": 100}, batch=True
        )
    )
    assert A.Ledger.load(led_path) == pytest.approx(expected)


def test_sealed_writer_needs_registration(tmp_path):
    assert not C.ALLOW_SEALED
    with pytest.raises(C.SealedSeedError):
        S.write_sealed_job_file(tmp_path / "x.npz")
    with pytest.raises(S.RegistrationError):
        S.enable_sealed(tmp_path)
    assert not C.ALLOW_SEALED


@pytest.mark.skipif(
    not X.DEV_INPUT.exists(), reason="derived development input not built"
)
def test_sealed_writer_on_synthetic_arrays(tmp_path, monkeypatch):
    """Synthetic stand-ins for the sealed runs; the real cache is never opened here."""
    r = np.random.default_rng(2)
    setup = {"modes": {}}
    for m in range(7):
        names = [f"synthetic_{m}_{u}.csv" for u in range(8)]
        setup["modes"][str(m)] = {"sealed": [{"name": n} for n in names]}
        np.savez(
            tmp_path / f"mode_{m}.npz",
            **{"sealed::" + n: r.gamma(4.0, 1.0, 120_000) for n in names},
        )
    (tmp_path / "setup.json").write_text(json.dumps(setup))
    monkeypatch.setattr(C, "ALLOW_SEALED", True)
    monkeypatch.setattr(S, "GRIDS", {"claude-opus-5-5": [("loud", "P0", (0,), (0, 5))]})
    out = tmp_path / "jobs.npz"
    S.write_sealed_job_file(out, cache=tmp_path, setup=tmp_path / "setup.json")
    _, windows, jobs, meta = C.load_job_input(out)
    assert meta["source"] == "sealed" and len(jobs) == 14 and len(windows) == 14
    for (m, s), (_, _, rec) in windows.items():
        assert rec["block"] == (s - C.SEALED_SEED_BASE - 10_000 * m) // 100
        assert rec["twin_block"] != rec["block"]


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_registration_check(tmp_path):
    repo = tmp_path / "repo"
    for f in [S.PROTOCOL, *S.CODE_FILES]:
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / f, repo / f)
    proto = repo / S.PROTOCOL
    proto.write_text(
        proto.read_text(encoding="utf-8").replace("**DRAFT", "**REGISTERED"),
        encoding="utf-8",
    )
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "code")
    reg = S.registration_template(repo)
    reg_path = repo / S.REGISTRATION.relative_to(ROOT)
    reg_path.write_text(json.dumps(reg, indent=1))
    with pytest.raises(S.RegistrationError, match="not committed"):
        S.check_registration(repo)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "registration")
    assert S.check_registration(repo)["code_commit"] == reg["code_commit"]
    # a changed protocol, a changed code file, a DRAFT mark: each refused
    proto.write_text(proto.read_text(encoding="utf-8") + "\nedit\n", encoding="utf-8")
    with pytest.raises(S.RegistrationError, match="protocol differs"):
        S.check_registration(repo)
    git(repo, "checkout", "--", S.PROTOCOL)
    core = repo / "scripts/ol1_core.py"
    core.write_text(core.read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8")
    with pytest.raises(
        S.RegistrationError, match="differs from the registered version"
    ):
        S.check_registration(repo)
    git(repo, "checkout", "--", "scripts/ol1_core.py")
    proto.write_text(
        proto.read_text(encoding="utf-8").replace("**REGISTERED", "**DRAFT"),
        encoding="utf-8",
    )
    reg["protocol_sha256"] = S.sha256_lf(proto.read_bytes())
    reg_path.write_text(json.dumps(reg, indent=1))
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "draft again")
    with pytest.raises(S.RegistrationError, match="DRAFT"):
        S.check_registration(repo)
    assert set(S.REGISTRATION_FIELDS) == set(reg)
