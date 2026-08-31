# Physical JEPA Safety-Gymnasium external-execution handoff v1

## Status

This is a replication-ready handoff, not evidence of independent execution. The report authors have not run this package as an external executor, and no independent execution, assessment, live HIL, sensor-only control, physical deployment, or safety-certification claim is presently supported.

Technical Report v1.1 remains frozen. A completed handoff should be published as a separate replication artifact and cited by a later paper version only after the executor's identity, raw outputs, attestation, and package verification are available.

## Frozen question

Can a non-author reproduce the registered Safety-Gymnasium v12 five-arm result with the same controller, shield, model artifact, runtime versions, final seeds, and gates?

This is an execution replication of an already opened benchmark, not a new blinded estimate. The benchmark task and hazard-cost implementation are third-party Safety-Gymnasium; the adapter, privileged deterministic planner, shield, and analysis remain author-designed.

## Canonical result wording

> A privileged deterministic planner achieved 94.53% completion and 66.93% lower hazard cost on the prospective Safety-Gymnasium benchmark, while the active safety union failed its registered recall and realized-cost gates.

Do not summarize the result as “FerrumOS achieved 94.53% completion and 66.93% hazard reduction.” The planner uses direct simulator geometry, and the active union failed dangerous-recall and realized-cost gates.

## Executor eligibility

The executor must not be an author of Technical Report v1.1. The executor supplies their own name, affiliation, and stable identifier; the repository does not invent or prefill those fields. Execution by a non-author supports an **independently executed replication** claim only. It does not make the benchmark independently designed or independently assessed.

For stronger independence, the executor should:

1. use a fresh clone on a machine not controlled by a report author;
2. retain the exact commit and package hashes in the generated attestation;
3. publish the raw result, raw case catalog, stdout, stderr, and generated attestation;
4. optionally sign the attestation file or archive it under their own institutional or repository account; and
5. report discrepancies rather than repairing, tuning, or rerunning the frozen benchmark.

## Environment

Install the exact registered Python runtime and packages. On Windows:

```powershell
uv python install 3.10.20
uv venv --python 3.10.20 target/safety-gymnasium-venv
uv pip install --python target/safety-gymnasium-venv/Scripts/python.exe safety-gymnasium==1.0.0 gymnasium==0.28.1 gymnasium-robotics==1.2.2 mujoco==2.3.3 numpy==1.23.5 pygame==2.1.0
```

On Linux or macOS, use `target/safety-gymnasium-venv/bin/python` for the final command.

The registered v12 protocol and selection were originally hashed with CRLF line endings, while the Python runner and case catalog use LF. The wrapper materializes byte-identical protocol and selection copies inside the output directory before execution, so a fresh checkout does not gain or lose eligibility merely because of platform checkout conventions. Model binaries and the frozen PDF remain raw-byte locked.

## Preflight

Run the package verifier before executing the benchmark:

```powershell
python scripts/verify_physical_jepa_external_execution_handoff_v1.py --check-only
```

The verifier must report `all_checks_pass: true` and `external_execution_completed: false`. That second value is expected before another party runs the handoff.

## One-shot external execution

From a clean clone, the eligible executor runs exactly one command, substituting only their truthful identity fields and an unused output directory:

```powershell
python scripts/run_physical_jepa_external_execution_v1.py `
  --executor-name "FULL NAME" `
  --executor-affiliation "AFFILIATION OR INDEPENDENT RESEARCHER" `
  --executor-identifier "ORCID, INSTITUTIONAL ID, OR PUBLIC PROFILE URL" `
  --attest-not-a-paper-author `
  --output-dir external-execution/physical-jepa-v1
```

The underlying v12 runner is expected to return a nonzero gate status because the active union failed the registered dangerous-recall and realized-cost gates. The handoff wrapper treats that retained scientific result as an expected completed execution, not as a reason to hide or rerun it.

The wrapper writes:

- `frozen_protocol.json` and `frozen_selection.json` - byte-identical registered inputs materialized without changing the checkout;
- `raw_result.json` - the frozen runner output;
- `raw_cases.jsonl` - the full five-arm case catalog;
- `runner.stdout.txt` and `runner.stderr.txt` - captured process evidence; and
- `execution_attestation.json` - executor identity, command, environment, git revision, hashes, exact-reproduction checks, and claim eligibility.

After the run, verify the completed bundle:

```powershell
python scripts/verify_physical_jepa_external_execution_handoff_v1.py `
  --check-only `
  --execution-dir external-execution/physical-jepa-v1
```

An exact bundle reports `external_execution_completed: true` and `non_author_execution_evidence_eligible: true`. Identity remains an attestation that readers should cross-check against the public executor identifier.

## Interpretation

An attestation is eligible to support “executed by an independent non-author” only when:

- the executor truthfully attests they are not a paper author;
- every frozen input digest and runtime version matches;
- the raw case catalog is byte-identical to the registered v12 catalog;
- the normalized raw result is identical to the registered v12 result;
- physical actuator attempts and deliveries remain zero;
- the active union's failed gates remain visible; and
- no artifact is promoted or replaced.

If any condition fails, publish the discrepancy as a replication result. Do not call it a successful independent reproduction.

## What remains impossible to add locally

Actuator-disabled **live HIL** still requires actual hardware clocks, sensor interfaces, actuator electronics or a disabled power stage, measured latency, and an independently testable emergency-stop path. A software backend named `ActuatorDisabledBackend` is useful plumbing but is not live HIL evidence. No local script can honestly create that evidence without the hardware and measured run.
