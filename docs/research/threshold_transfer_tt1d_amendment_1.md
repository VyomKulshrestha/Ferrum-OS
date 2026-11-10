# tt1d, amendment 1: missing register values in the ProvICS sealed rows

Dated 2026-11-10. Written and committed before the second attempt at the ProvICS final. The Tennessee
Eastman final is not affected.

## What happened

`python scripts/tt1d_final.py final provics` ran once under the registration (commit 8863382). It
recorded the access (`provics-attack` and `provics-sealed-normal`, 2026-11-10T10:55:01Z) and then stopped
with `ValueError: Input X contains NaN` inside the monitor while scoring the sealed attack-free rows.

- No result file was written, and the run printed nothing after "provics monitor ready": no event count,
  no detection, no gate. The log is `target/real-telemetry/tt1d-final/provics.log`.
- The rules had already run over the attack recording in memory when the error occurred. Those values
  were never printed or saved, and nobody has seen them.

## Diagnosis

A second, ledgered read counted missing values only (no score, label or outcome):

| Rows | Rows read | Rows with a missing register | Missing cells |
|---|---|---|---|
| Development (first 75 % of the attack-free recording) | 98,205 | 0 | 0 |
| Sealed (last 25 %) | 32,735 | 1 | 9 |
| Attack recording | 51,425 | 0 | 0 |

The one affected row is sealed row 14,064; its nine setpoint registers are empty and its thirteen
measurement registers are present. The development rows have no missing value, so the rehearsal could not
have met the case.

## Change

A register with no value in a row repeats its previous value (a gap at the very start takes the next
value). This is the registered loader's rule for an empty step of the 2 s grid, applied to an empty cell.

Nothing else changes: hypotheses, rules, settings, event scoring, campaign placements, seeds and the frozen
files are as registered. `scripts/tt1d_provics_amendment1.py` imports the frozen harness and loader
unmodified, wraps the loader's file reader with the fill, checks the frozen digests, records the second
access in the ledger and runs the registered pipeline once. The result file records the amendment, the
script's sha256 and the number of cells filled.

## Effect on the claims

The fill touches one of 32,735 sealed attack-free rows and no row of the attack recording. The real-event
hypotheses (P1 to P3) use the attack recording only and cannot be affected by the fill. The campaign
hypotheses (P4 to P6) and the false-alarm counts use the sealed rows.

The paper reports the ProvICS result as registered with one dated amendment after a failed first attempt.
