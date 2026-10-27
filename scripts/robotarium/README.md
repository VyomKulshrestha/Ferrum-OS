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
| `label_robotarium_log.py` | labels a returned run with the runtime's hazard rules (body centres) |
| `video_frames.py` | syncs the returned video to the log, fits the camera, writes rectified per-step frames |

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

What the pilot taught the tooling:
- Real execution matches the simulator: Move end-to-target error median 1.7 cm (sim 2.1),
  79% within 3 cm (sim 71%), drift while holding at most 3 mm.
- The testbed loop runs about 1% slow with +-0.2 s jitter, so the video is synced per
  30 s window, and the camera is fitted only on hold frames (robots still).
- The logged pose is behind the visible body centre along the heading (fitted 3.1 cm;
  the testbed's collision check uses 0.025 m). Labels use body centres with 0.025 m.
- OpenCV's full camera model diverges from a single plane; a homography plus one radial
  term fits all 555 hold frames at 1.0 px median (0.2 cm).
- Exploratory only: the sim-trained v2 head, unchanged, scored AUC-PR 0.717 against a
  0.455 base rate on the pilot's 88 decisions (recall 0.275 at its frozen threshold,
  FPR 0.021). One run; not evidence.

## Registered study (seeds 201-204 calibration, 301-306 sealed): primary FAIL

`docs/research/vision_caution_robotarium_protocol_v1.json` (committed 53364ce before the runs),
scored once by `evaluate_real.py` on 2026-10-23:

| arm (528 sealed decisions, prevalence 0.220) | AUC-PR | ROC | recall | false alarms |
|---|---|---|---|---|
| vision head, real-calibrated threshold (primary) | 0.279 | 0.552 | 0.052 | 0.015 |
| vision head, simulation threshold | 0.279 | 0.552 | 0.905 | 0.905 |
| action-only control | 0.220 | 0.511 | 0.052 | 0.056 |
| true-position reference | 0.725 | 0.872 | 0.552 | 0.051 |

G1 (camera beats action-only) FAIL, recall difference 0.0, CI95 [-0.088, 0.091]; G2 (budget)
PASS. Exploratory diagnosis (`vision_caution_robotarium_diagnosis_v1.json`): the black
projected fence and obstacle disc, added after the pilot, read as "outside the fence" to the
proxy-trained head (dark floor = outside in the proxy), lifting every logit by about 3.3 and
erasing the ranking. All ten runs passed the quality gate.

## Registered study v2 (head trained on real footage): primary FAIL, underpowered

`docs/research/vision_caution_robotarium_protocol_v2.json` (committed 0bdd002 before its runs;
amendment 1, 7a3aa23: runs whose testbed video is truncated fail the quality gate), scored once
by `train_eval_real.py` on 2026-10-26. The testbed truncated 5 of 20 videos (407, 503, 603, 606,
607) and one failed sync (604), leaving train 17 runs, selection 3, sealed 4 (601, 602, 605, 608).

| arm (352 sealed decisions, 32 episodes, prevalence 0.173) | AUC-PR | ROC | recall | false alarms |
|---|---|---|---|---|
| vision head trained on real frames, 256 px (primary) | 0.412 | 0.753 | 0.230 | 0.041 |
| sim v2 head fine-tuned on real frames (secondary) | 0.634 | 0.870 | 0.262 | 0.024 |
| pixel probe | 0.365 | 0.627 | 0.393 | 0.100 |
| action-only control | 0.236 | 0.617 | 0.049 | 0.038 |
| true-position reference | 0.774 | 0.894 | 0.508 | 0.014 |

G1 FAIL: recall difference vs action-only +0.180, CI95 [-0.054, 0.440] (32 episodes, 61
positives); G2 (budget) PASS. The primary head caught 30% of proximity hazards and 0 of 19
geofence exits. Unlike v1 (AUC-PR 0.279 vs base 0.220), real-footage training gives a clear
signal; the strongest camera arm was the sim-pretrained head fine-tuned on real frames.

## Study B (sim head in the arena's look, seeds 701-712 sealed): primary PASS on the amended gate

`docs/research/vision_caution_robotarium_protocol_v3.json` (c24ac0b, before its runs), harness
`study_b.py`. All 12 sealed runs were submitted on 2026-10-26 and scored once on 2026-10-28
(`docs/research/vision_caution_robotarium_result_v3.json`, ledger `robotarium-sealed-v3`). Seed 702's
stored video is 389 s against a 409 s run and fails the gate; seeds 701 and 706 first crashed on host
memory and passed on their one retry (amendment 2, 81a46af), so 11 runs count.

| arm (968 sealed decisions, 88 episodes, prevalence 0.191) | AUC-PR | ROC | recall | false alarms |
|---|---|---|---|---|
| vision head trained in simulation only, arena look (primary) | 0.328 | 0.630 | 0.130 | 0.042 |
| same head fine-tuned on spent real runs (secondary) | 0.525 | 0.829 | 0.108 | 0.011 |
| action-only control | 0.215 | 0.526 | 0.103 | 0.066 |
| true-position reference | 0.810 | 0.922 | 0.422 | 0.005 |

G1 (amended) PASS: AUC-PR difference vs action-only +0.113, CI95 [0.015, 0.219]; G2 PASS. S1 PASS
(fine-tuned vs action-only +0.310, CI95 [0.207, 0.414]); S2 PASS (fine-tuned vs sim-only +0.197, CI95
[0.087, 0.310]). The registered recall gates all fail: recall difference vs action-only +0.027, CI95
[-0.054, 0.117]. The simulation-only head catches 22% of proximity hazards and 3% of geofence exits at
its frozen threshold. Against v1 (sim head in the proxy look, AUC-PR 0.279 vs base 0.220, no
separation) the arena look gives a sim-only head that ranks real hazards above action-only, with a
lower bound close to zero; its alarms are not yet useful.

Amendment 1 (`..._protocol_v3_amendment1.json`, before any sealed run was downloaded) changes the
decision rule only. An exploratory power check on the spent runs (`power_study_b.py`) showed the
registered recall gate passing in 1-4% of resampled sealed sets at any size from 4 to 16 runs:
the head ranks hazards far better than action-only (AUC-PR 0.431 vs 0.226) but catches 9.1% vs
7.3% at the half-budget threshold. G1/S1/S2 are now decided by the episode-cluster CI95 of the
AUC-PR difference (estimated power 0.95 at 8 usable runs, optimistic); the registered recall
criteria are still reported. The amended gate is threshold-free: a pass means the camera head
ranks real hazards better, not that its alarms catch many of them.

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

Put the run's data files, log and video (`experiment_video.mp4`) in one folder, then:

```bash
python scripts/robotarium/label_robotarium_log.py path/to/run --out path/to/run/labels.npz
python scripts/robotarium/video_frames.py path/to/run
```

`frames.npz` has the keys of the proxy dataset, so `vision_runtime_proxy_final.decisions`
reads it unchanged.

Pilot runs (seeds 101-110) are exploratory: they show what the testbed returns (data, and
whether a video comes back). Any evaluation on Robotarium footage needs its own protocol
registered before the runs it scores.
