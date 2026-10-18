#!/usr/bin/env python3
"""Sequential development-trial queue with transparent retry on CUDA infrastructure faults.

Each queue line holds incident_dynamics_v3_trial.py arguments. A trial that dies with a
CUDA runtime fault before writing its record is retried (at most twice); every failure is
appended to the infrastructure log so reruns remain visible in the development record.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import incident_dynamics_v3_data as v3

INFRA = v3.WORK / "infrastructure_failures.jsonl"


def main():
    queue = Path(sys.argv[1])
    for line in queue.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        args = line.split()
        for attempt in range(3):
            started = time.time()
            process = subprocess.run([sys.executable, "-u", "incident_dynamics_v3_trial.py", *args],
                                     capture_output=True, text=True)
            output = process.stdout + process.stderr
            result = [x for x in process.stdout.splitlines() if x.startswith('{"trial"')]
            if process.returncode == 0 and result:
                print(result[-1], flush=True)
                break
            fault = "CUDA error" in output
            with INFRA.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"args": args, "attempt": attempt, "returncode": process.returncode,
                                         "cuda_fault": fault, "seconds": round(time.time() - started, 1),
                                         "tail": output[-600:]}) + "\n")
            print(json.dumps({"failed": args, "attempt": attempt, "cuda_fault": fault}), flush=True)
            if not fault:
                break


if __name__ == "__main__":
    main()
