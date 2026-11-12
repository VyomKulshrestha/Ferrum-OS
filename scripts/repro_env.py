#!/usr/bin/env python3
"""Pin the thread count of the numerical libraries and record the environment of a run.

Results computed with multi-threaded linear algebra depend on the number of threads: the order of
floating-point summation in a matrix product changes with it (fi1 report, section 1; workstream B
round 3). New work calls ``pin_threads`` once, before any numerical work, and stores
``environment_record()`` in its result file, so that a result names the configuration that
reproduces it.

``pin_threads(n)``
    sets the BLAS and OpenMP pools of this process through threadpoolctl (when installed), the
    environment variables that child processes and libraries loaded later read, PyTorch's intra-op
    and inter-op threads when torch is already imported or importable, and returns the LightGBM
    keyword (``num_threads``) to pass to every LightGBM fit and predict, because LightGBM takes its
    thread count per call and not from a global setting.

``environment_record()``
    returns versions (Python, NumPy, SciPy, scikit-learn, LightGBM, PyTorch), the BLAS and OpenMP
    pools as threadpoolctl reports them (vendor, version, kernel architecture, threads), the pinned
    count if any, logical CPUs and the platform.

Importing this module has no side effect.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import platform
import sys

# Variables read by OpenBLAS, MKL, BLIS, OpenMP runtimes, Apple Accelerate and numexpr when they
# initialise. Setting them affects child processes and libraries loaded after the call.
THREAD_ENVIRONMENT_VARIABLES = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

PACKAGES = ("numpy", "scipy", "scikit-learn", "lightgbm", "torch", "threadpoolctl")

_state: dict = {"pinned": None, "limiter": None}


def _module(name: str):
    try:
        return importlib.import_module(name)
    except Exception:  # an optional dependency may be absent or broken
        return None


def pin_threads(n: int, *, torch_import: bool = False) -> dict:
    """Use exactly ``n`` threads in every numerical library this process and its children load.

    Returns ``{"lightgbm": {"num_threads": n}, "pinned": n, ...}``; pass the LightGBM keywords to
    every LightGBM fit and predict. With ``torch_import=False`` torch is pinned only when it is
    already imported, which keeps the call cheap for scripts that do not use it; a script that
    imports torch later should call ``pin_threads`` after that import or pass ``torch_import=True``.
    """
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError(f"thread count must be a positive integer, got {n!r}")
    if "saved_environment" not in _state:
        _state["saved_environment"] = {
            name: os.environ.get(name) for name in THREAD_ENVIRONMENT_VARIABLES
        }
        torch_loaded = sys.modules.get("torch")
        _state["saved_torch"] = (
            None if torch_loaded is None else torch_loaded.get_num_threads()
        )
    if _state["limiter"] is not None:
        _state["limiter"].restore_original_limits()
    for name in THREAD_ENVIRONMENT_VARIABLES:
        os.environ[name] = str(n)
    applied = {"environment": list(THREAD_ENVIRONMENT_VARIABLES)}
    threadpoolctl = _module("threadpoolctl")
    if threadpoolctl is not None:
        # Keep the limiter alive: threadpoolctl restores the old limits when it is unregistered.
        limiter = threadpoolctl.threadpool_limits(limits=n)
        _state["limiter"] = limiter
        applied["threadpoolctl"] = sorted(
            {pool["internal_api"] for pool in threadpoolctl.threadpool_info()}
        )
    else:
        applied["threadpoolctl"] = None
    torch = sys.modules.get("torch")
    if torch is None and torch_import:
        torch = _module("torch")
    if torch is not None:
        torch.set_num_threads(n)
        try:
            torch.set_num_interop_threads(n)
        except RuntimeError:
            # Only possible before the first parallel op; the intra-op count is what decides
            # reduction order in CPU kernels.
            pass
        applied["torch"] = {
            "num_threads": torch.get_num_threads(),
            "num_interop_threads": torch.get_num_interop_threads(),
        }
    else:
        applied["torch"] = None
    _state["pinned"] = n
    return {"pinned": n, "lightgbm": {"num_threads": n}, "applied": applied}


def unpin() -> None:
    """Undo ``pin_threads``: restore the BLAS limits, the environment and torch's thread count."""
    if _state["limiter"] is not None:
        _state["limiter"].restore_original_limits()
        _state["limiter"] = None
    for name, value in _state.pop("saved_environment", {}).items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    saved_torch = _state.pop("saved_torch", None)
    torch = sys.modules.get("torch")
    if torch is not None and saved_torch is not None:
        torch.set_num_threads(saved_torch)
    _state["pinned"] = None


def lightgbm_params(params: dict | None = None) -> dict:
    """Return LightGBM parameters with the pinned thread count (``num_threads``) set.

    Raises if ``pin_threads`` has not been called, so a script cannot silently fall back to
    LightGBM's default of one thread per core.
    """
    if _state["pinned"] is None:
        raise RuntimeError(
            "call repro_env.pin_threads(n) before building LightGBM parameters"
        )
    merged = dict(params or {})
    for alias in ("n_jobs", "num_thread", "nthread", "nthreads"):
        merged.pop(alias, None)
    merged["num_threads"] = _state["pinned"]
    return merged


def _version(distribution: str):
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _thread_pools() -> list[dict] | None:
    threadpoolctl = _module("threadpoolctl")
    if threadpoolctl is None:
        return None
    keys = (
        "user_api",
        "internal_api",
        "version",
        "architecture",
        "num_threads",
        "prefix",
    )
    pools = [
        {key: pool.get(key) for key in keys} for pool in threadpoolctl.threadpool_info()
    ]
    return sorted(
        pools, key=lambda pool: (pool["user_api"] or "", pool["prefix"] or "")
    )


def environment_record() -> dict:
    """What a result file should carry to name the configuration that reproduces it."""
    torch = sys.modules.get("torch")
    record = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "packages": {name: _version(name) for name in PACKAGES},
        "thread_pools": _thread_pools(),
        "pinned_threads": _state["pinned"],
        "thread_environment": {
            name: os.environ.get(name) for name in THREAD_ENVIRONMENT_VARIABLES
        },
        "torch_threads": None
        if torch is None
        else {
            "num_threads": torch.get_num_threads(),
            "num_interop_threads": torch.get_num_interop_threads(),
        },
        "logical_cpus": os.cpu_count(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
    }
    return record


RECORD_KEY = "reproducibility_environment"


def pin_from_environment(default: int = 1) -> dict:
    """Pin to ``REPRO_THREADS`` (default ``default``): the switch scripts with their own argument
    parsing use, so ``REPRO_THREADS=4 python scripts/x.py ...`` reruns them at another count."""
    return pin_threads(int(os.environ.get("REPRO_THREADS", default)))


def stamp_json(path, record: dict | None = None) -> dict:
    """Add the environment record to a JSON result file under ``RECORD_KEY`` (LF line endings);
    a result that is not a JSON object gets a ``<stem>.environment.json`` sidecar instead."""
    import json
    from pathlib import Path

    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    record = record if record is not None else environment_record()
    if not isinstance(data, dict):
        # A result that is not an object keeps its shape; the record goes into a sidecar file.
        sidecar = path.with_name(path.stem + ".environment.json")
        sidecar.write_text(
            json.dumps({RECORD_KEY: record}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return data
    data[RECORD_KEY] = record
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return data


def run_script_pinned(script, argv: list[str], threads: int, outputs: list = ()) -> int:
    """Run a script's ``__main__`` in this process with ``threads`` pinned, then stamp its outputs.

    The ``_v2`` entry points use this so that a frozen trainer or evaluator stays byte-identical
    while new runs of it are pinned and carry the environment record. Returns the exit code.
    """
    import runpy
    from pathlib import Path

    pin_threads(threads, torch_import=False)
    script = Path(script)
    saved_argv, saved_path = sys.argv, list(sys.path)
    sys.argv = [str(script), *argv]
    sys.path.insert(0, str(script.parent))
    code = 0
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exit_:
        code = (
            exit_.code
            if isinstance(exit_.code, int)
            else (0 if exit_.code is None else 1)
        )
    finally:
        sys.argv, sys.path[:] = saved_argv, saved_path
    record = environment_record()
    for output in outputs:
        if Path(output).is_file():
            stamp_json(output, record)
    return code


def option_value(argv: list[str], name: str, default=None):
    """The value of ``--name value`` or ``--name=value`` in an argument list."""
    for index, item in enumerate(argv):
        if item == name and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith(name + "="):
            return item.split("=", 1)[1]
    return default


if __name__ == "__main__":
    import json

    print(json.dumps(environment_record(), indent=2, sort_keys=True))
