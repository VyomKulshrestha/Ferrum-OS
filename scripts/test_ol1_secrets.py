"""No API key in ol1 results or in the git index.

The results directory must not contain even the key prefix. The git index is checked for the shape of a real
key (prefix, key kind and version, then a long secret): since the heliox gate tests (7a04b5b) the index holds a
fixture with the bare prefix and the word SECRET, which is not a key."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = "sk-" + "ant-"  # built from parts so this file does not match itself
KEY_SHAPE = MARK + "[a-z]+[0-9]{2}-[A-Za-z0-9_-]{20,}"
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


def test_key_shape():
    fake = MARK + "api03-" + "A" * 40
    assert re.search(KEY_SHAPE, fake)
    assert not re.search(KEY_SHAPE, MARK + 'SECRET\\"x"')


def test_git_index_has_no_key():
    r = subprocess.run(
        ["git", "grep", "--cached", "-I", "-l", "-E", KEY_SHAPE],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode in (0, 1), r.stderr
    assert r.stdout.strip() == "", r.stdout
