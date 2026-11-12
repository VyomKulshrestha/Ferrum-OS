"""No API key in ol1 results or in the git index."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = "sk-" + "ant-"  # built from parts so this file does not match itself
RESULTS = ROOT / "target/ol1"


def test_results_directory_has_no_key():
    if not RESULTS.exists():
        return
    hits = []
    for p in RESULTS.rglob("*"):
        if (
            p.is_file()
            and "ol1-venv" not in p.parts
            and MARK.encode() in p.read_bytes()
        ):
            hits.append(str(p))
    assert hits == []


def test_git_index_has_no_key():
    r = subprocess.run(
        ["git", "grep", "--cached", "-I", "-l", "-F", MARK],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode in (0, 1), r.stderr
    assert r.stdout.strip() == "", r.stdout
