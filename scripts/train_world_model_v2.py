#!/usr/bin/env python3
"""Pinned entry point for ``train_world_model.py`` (fi1 workstream B, round 3).

``train_world_model.py`` is frozen by digest in the incident-dynamics selections v1 and v2 and in world_model_training_config.json; it stays byte-identical. This entry point runs it unchanged with the
BLAS (and, where loaded, PyTorch) thread count pinned, one thread by default, and adds the environment
record (``repro_env.environment_record``) to its JSON output under ````reproducibility_environment````. Results computed with
multi-threaded linear algebra depend on the thread count (fi1 report, section 1; pipeline_round3.md);
with one thread they repeat bit for bit on the same machine.

    python scripts/train_world_model_v2.py [--threads N] <arguments of train_world_model.py>
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import repro_env  # noqa: E402

ORIGINAL = HERE / "train_world_model.py"
OUTPUT_OPTIONS = ["--metrics-out"]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    threads = int(repro_env.option_value(argv, "--threads", "1"))
    if "--threads" in argv:
        index = argv.index("--threads")
        del argv[index : index + 2]
    argv = [a for a in argv if not a.startswith("--threads=")]
    outputs = [repro_env.option_value(argv, option) for option in OUTPUT_OPTIONS]
    return repro_env.run_script_pinned(
        ORIGINAL, argv, threads, [o for o in outputs if o]
    )


if __name__ == "__main__":
    raise SystemExit(main())
