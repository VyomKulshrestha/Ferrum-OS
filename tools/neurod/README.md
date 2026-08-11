# neurod

`neurod` is FerrumOS's host-side neural acquisition and intent-decoding boundary.
It keeps raw samples outside the OS, emits only fixed-width signed evidence, and
abstains whenever quality, confidence, dwell, or provenance checks fail.

The built-in synthetic source is a deterministic test fixture, not human EEG:

```powershell
python tools/neurod/neurod.py synthetic --frequency 12 --windows 3
```

Run the localhost-only visual fixture console with:

```powershell
python tools/neurod/dashboard.py
```

It deliberately does not render 8–15 Hz flicker: the frequency controls select
generated samples, avoiding a photosensitivity risk. The dashboard has no
pairing token and no OS action endpoint.

Add `--pairing-token <current-token>` to emit a signed `intent_hex` compatible
with `ferrum-neural-protocol`. Never publish a live pairing token or recording.
Real-board acquisition is optional and requires the upstream `brainflow` Python
package; first validate the board independently in its vendor/OpenBCI GUI.

For an end-to-end synthetic preview against a running QEMU bridge, keep the
pairing token out of shell history, run the command, and arm locally at the
FerrumOS console when prompted by the wait:

```powershell
$env:FERRUM_NEURAL_PAIRING_TOKEN = "<current 32-hex console token>"
python tools/neurod/neurod.py bridge-synthetic --frequency 12
# In FerrumOS: heliox neural arm
```

The default operation previews and then disarms. `--commit` is explicit and is
still limited by FerrumOS to focus changes or the three compiled read-only
targets. Physical-goal evidence is proposal-only and cannot be committed.

Recording is intentionally API-only until an explicit consent UX is connected.
`ConsentRecorder` writes a pseudonymous, BIDS-shaped local folder and refuses to
start unless the caller supplies affirmative consent. Its sidecar records
whether the source was human, playback, or synthetic so fixtures cannot be
mistaken for human EEG.

Reproduce the registered synthetic safety gates with:

```powershell
python -m unittest discover -s tools/neurod -p 'test_*.py'
python scripts/evaluate_neural_simulator.py
```

The committed fixture result is 600/600 accepted signal windows, 400/400
artifact-window abstentions, and zero emitted candidates in 10,000 no-control
windows. Those numbers validate the deterministic software path only. They do
not measure live EEG accuracy, false activations per natural-use hour, comfort,
or cross-session/participant performance.
