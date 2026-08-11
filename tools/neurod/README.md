# neurod

`neurod` is FerrumOS's host-side neural acquisition and intent-decoding boundary.
It keeps raw samples outside the OS, emits only fixed-width signed evidence, and
abstains whenever quality, confidence, dwell, or provenance checks fail.

The built-in synthetic source is a deterministic test fixture, not human EEG:

```powershell
python tools/neurod/neurod.py synthetic --frequency 12 --windows 3
```

Add `--pairing-token <current-token>` to emit a signed `intent_hex` compatible
with `ferrum-neural-protocol`. Never publish a live pairing token or recording.
Real-board acquisition is optional and requires the upstream `brainflow` Python
package; first validate the board independently in its vendor/OpenBCI GUI.

Recording is intentionally API-only until an explicit consent UX is connected.
`ConsentRecorder` writes a pseudonymous, BIDS-shaped local folder and refuses to
start unless the caller supplies affirmative consent.

