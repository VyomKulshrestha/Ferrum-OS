# Car kit: a real 2WD robot for the physical bridge

Software for the Probots RC 2WD ESP32-CAM car kit, written before the kit arrived and tested
against a simulated car. `CarKitBackend` has the same surface as `PyBulletBackend`
(`reset_scene`, `submit_command` with `move_to`/`stop`, `poll_observation`, `close`), so a
`BridgeSession` can drive the real car instead of PyBullet. Positions come from a phone
looking down at the floor; observations are `evidence_class: "hardware_in_loop"`.

The backend has no authority. FerrumOS decides whether a command is issued; the backend
and firmware only make sure an issued command cannot run away.

| File | What it does |
|---|---|
| `wire.py` | UDP JSON protocol host <-> car, exact keys, PWM and TTL ranges |
| `tracker.py` | overhead colour tracking, homography, marker-height parallax correction, `PhoneSource` |
| `backend.py` | `CarKitBackend`: closed-loop `move_to`, geofence, stop on tracking/link loss |
| `mock_car.py` | firmware twin (same semantics) + tilted pinhole phone camera, for tests |
| `firmware/ferrum_car/ferrum_car.ino` | ESP32-CAM sketch: TTL dead-man, bump latch, token |
| `__main__.py` | bring-up commands: `selftest`, `calibrate`, `track`, `ping`, `wheels`, `goto` |
| `shadow_gate.py` | FerrumOS judging each proposed move from the tracked scene, actuator disabled (roadmap M1) |

## Shopping list (October 2026 prices)

| Item | Where | Price |
|---|---|---|
| Probots RC 2WD Smart Robot Car, ESP32 camera, unassembled | Probots | ₹3,799 |
| 2 x Samsung ICR18650-26J 2600 mAh (5.2 A max) | Probots | ₹338 |
| 2 x micro limit switch, long lever (bumpers) | Probots | ₹158 |
| amiciSmart dual-slot USB 18650 charger | Amazon | ₹617 |
| overhead phone clamp arm (39 cm) | Amazon | ₹749 |

The kit already includes the ESP32-CAM controller board, L298N, a 2 x 18650 holder, a
Type-C cable, two TT motors, wheels and the caster. Cells and charger are not included.

## Scene, no printer needed

- Floor, not a table: the car cannot fall. Mark a rectangle (e.g. 1.0 x 0.75 m) and put one
  object of a single colour (green tape squares work) on each corner.
- On top of the car, along its long axis: a red square at the front, a blue square at the
  rear (coloured paper or electrical tape, ~4 cm). Measure their centre-to-centre distance
  (`--marker-sep`) and their height above the floor (`--marker-height`).
- Obstacle: one object of a fourth colour (a yellow cup), height measured (`--obstacle-height`).
- Phone: free IP Webcam app, 640x480, main lens (not ultrawide, its distortion breaks the
  homography), on the clamp arm pointing straight down. Tape-measure the lens height.

## Wiring the bumpers

Both limit switches in parallel between `BUMP_PIN` (GPIO 2) and GND, normally-open
contacts, levers forward. Either one closing latches the wheels off.

## Flashing

`arduino-cli` 1.5.1 (winget `ArduinoSA.CLI`), esp32 core 3.3.12 and ArduinoJson 7.4.3 are
installed, config at `C:\Users\marcu\.arduino-cli\arduino-cli.yaml` (data kept outside
AppData). The sketch compiles for `esp32:esp32:esp32cam` with `--warnings all` and no
warnings, `PIN_TEST` 0 and 1 (29% flash, 14% RAM). Edit the Wi-Fi name/password and `TOKEN`
at the top of the sketch first, then:

```bash
arduino-cli --config-file C:/Users/marcu/.arduino-cli/arduino-cli.yaml compile --fqbn esp32:esp32:esp32cam tools/car_kit/firmware/ferrum_car
arduino-cli --config-file C:/Users/marcu/.arduino-cli/arduino-cli.yaml upload --fqbn esp32:esp32:esp32cam -p COM5 tools/car_kit/firmware/ferrum_car
```

The serial monitor (115200 baud) prints the car's IP.

## Bring-up order

1. Check the motor pins in the sketch against the kit's sample code (Probots page ->
   Downloads -> Code and Assembly Instructions). Flash with `PIN_TEST 1`, car lifted: each
   wheel turns forward then backward. A wheel turning the wrong way: swap its A/B pins.
2. Flash with `PIN_TEST 0`. `python -m tools.car_kit ping --car <ip> --token <token>`.
3. `python -m tools.car_kit wheels ...` with the car lifted; press a bumper while it runs.
4. `python -m tools.car_kit calibrate --source http://<phone-ip>:8080 --arena-w 1.0 --arena-h 0.75 --camera-height 0.80`
   and click the four corners (near-left, near-right, far-right, far-left), then the front
   square, the rear square, the obstacle.
5. `python -m tools.car_kit track --source ...`: walk the car around by hand, check the poses.
6. `python -m tools.car_kit goto ... --x 0.2 --y 0.1`: one supervised move.
7. Real runs: a `BridgeSession` with `BridgeHello(..., actuator_enabled=True)` around
   `CarKitBackend`, commands from FerrumOS.

## What stops the car

| Event | Stopped by | Within |
|---|---|---|
| host crash, Wi-Fi loss, stalled loop | firmware TTL (host sends 200 ms TTL at 15 Hz) | 0.2 s |
| bumper closes | firmware latch, re-armed only by `reset_scene` with the switch released | one loop pass |
| car not seen for 0.4 s | backend stop + TTL | 0.6 s |
| car leaves the arena rectangle | backend stop | one control period |
| target outside the arena (minus 5 cm) | backend, nothing is sent | before motion |
| move takes over 8 s | backend stop | - |

## Shadow gate (roadmap M1)

In M1 FerrumOS judges the car's moves but does not issue them. `ShadowGate` runs
`tools/car_gate`, a host program around `userland/physical-runtime/src/car_arena.rs`: one
hardware-in-loop runtime session with the actuator disabled, its policy built from measured
numbers (`ArenaMeasurements`). Each tracked `Scene` becomes the car's position and its
edge-to-edge clearance to the obstacle; each proposed move comes back as `allow`, `block` or
`require_approval` with the gate's reasons. The operator still drives with `goto`.

The policy's margin is `tracker p99 error + top speed x (camera-to-verdict latency + stopping
time)`. The geofence is the marked rectangle inset by the car's radius and the margin; the
clearance floor is the required clearance plus the margin plus the step bound, because a permit
covers at most `max_step` from the last tracked position (`MoveStepTooLong` otherwise). A scene
without the car or the obstacle sends nothing, so the readings age out and motion blocks
(`StaleProximitySensor`, `StaleActorPosition`). Measure the five numbers on the real car first;
the draft protocol `docs/research/car_m1_protocol_v1_draft.json` says how.

```bash
cargo build --release --manifest-path tools/car_gate/Cargo.toml --target x86_64-pc-windows-gnu
python -m unittest tools.car_kit.test_shadow_gate
```

On this host the MSVC linker is not installed; run cargo from PowerShell with the GNU toolchain's
own binaries (`rustup which --toolchain stable-x86_64-pc-windows-gnu cargo`, and `RUSTC` set to
its `rustc`), because a standalone MSVC Rust install comes first on PATH and Git Bash's `link`
shadows `link.exe`. One gate process is one session (8,192 evidence records, about 1,600
proposals): send the latest scene just before each proposal, and start a new gate per run.

## Tests

```bash
python -m unittest tools.car_kit.test_car_kit
```

Eleven tests against the simulated car (wrong wheel gains, motor deadband, UDP loss, tilted
camera): reaching a target through a `BridgeSession`, geofence, TTL stop, link loss,
tracking loss, bump latch and re-arm, token check, strict parsing, tracker accuracy. In the
mock, tracking error is about 0.7 cm with the parallax correction and about 3 cm without it.

Not yet checked on hardware: the kit's motor pin map, GPIO 12 boot strapping on that board,
motor brownouts on the 2-cell pack, colour separation under room lighting.
