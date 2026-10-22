# FerrumOS on the Georgia Tech Robotarium

Real robots for the vision-caution work: robot 0 plays the FerrumOS robot and robot 1 a
parked obstacle in the Robotarium arena (free remote testbed, robotarium.gatech.edu).
Each runtime step is a FerrumOS `PhysicalAction` from the same generator as the
runtime-scene proxy, scaled 0.7 (the runtime geofence becomes a projected 1.4 m square;
the 16 cm runtime robot becomes 11.2 cm, about a GRITSbot).

| file | role |
|---|---|
| `ferrum_experiment.py` | the file to upload; numpy + `rps` only; edit `SEED` per submission |
| `check_in_simulator.py` | runs the upload file in the official simulator and reports the testbed's own checks |
| `label_robotarium_log.py` | labels a returned run with the runtime's hazard rules |

Testbed limits respected: 600 s per experiment (8 episodes take about 450 s), no robot
pair within 0.135 m (a local safety layer keeps robot 0 at least 0.20 m from the
obstacle), no robot outside the arena, wheel speeds kept under 90% of the motor limit.
Real contact is never produced, so the Robotarium labels cover proximity and geofence
exit only.

## Pilot (seed 101)

Ran on 2026-10-22 with the version at commit 46a590a. The testbed returned our three data
files, a log and a 1920x1080, 25 fps overhead video (wide-angle lens, strong barrel
distortion). The white projected fence was invisible on the bright floor; the projector
darkens by withholding light, so the fence is now black and 10 px wide, and a dark disc is
projected under the parked obstacle so the two identical GRITSbots differ visually.

## Check before uploading

The simulator and `cvxopt` live in a separate venv so the main environment is untouched:

```bash
git clone --depth 1 https://github.com/robotarium/robotarium_python_simulator target/robotarium/robotarium_python_simulator
python -m venv target/robotarium/venv
target/robotarium/venv/Scripts/python -m pip install numpy==2.2.6 matplotlib==3.10.8 cvxopt==1.3.2
target/robotarium/venv/Scripts/python scripts/robotarium/check_in_simulator.py --seeds 101 102 103
```

Seeds 101-103 pass with zero too-close, out-of-bounds and actuator-limit counts.

## After a run

Download the run's files into a folder and label them:

```bash
python scripts/robotarium/label_robotarium_log.py path/to/run --out path/to/run/labels.npz
```

Pilot runs (seeds 101-110) are exploratory: they show what the testbed returns (data, and
whether a video comes back). Any evaluation on Robotarium footage needs its own protocol
registered before the runs it scores.
