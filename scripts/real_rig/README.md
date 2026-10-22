# Real-camera rig: an Android phone over a tabletop

First real-camera footage for the vision caution advisory, with no printer and no robot.
The phone is the camera; you move a small object by hand (stop-motion), following
FerrumOS runtime actions shown on the laptop.

## What you need

- The Android phone with **IP Webcam** (free, Play Store), on the same Wi-Fi as the laptop.
- A floor or table area about 90 x 90 cm, plain and not shiny.
- Tape or string to mark a **60 x 60 cm square** (the runtime geofence).
- Four bright objects for the corners (bottle caps, sticky notes).
- A **robot**: a small object about 5 cm wide in a distinct colour (a red matchbox or toy
  car). An **obstacle** of a different colour, about the same size (a blue box). Neither
  colour should appear anywhere else in view.
- Somewhere to fix the phone about 1 m up, looking down, so it sees the whole square plus
  a hand-width around it: taped under a shelf or chair, or leaning on books. An angled
  view is fine. It must not move during a session.

## Steps

1. In IP Webcam, set the video resolution to 1280x720, then tap **Start server**. Note the
   address it shows, for example `http://192.168.1.23:8080`.
2. Calibrate (once per phone position):
   ```bash
   python scripts/real_rig/phone_rig.py calibrate --source http://192.168.1.23:8080 --session home1
   ```
   Click the 4 fence corners in order: near-left, near-right, far-right, far-left. Clear
   the square and press SPACE. Then place the robot and click it, place the obstacle and
   click it.
3. Record:
   ```bash
   python scripts/real_rig/phone_rig.py record --source http://192.168.1.23:8080 --session home1 --seed 1 --episodes 10
   ```
   Put the robot on the green ring and the obstacle on the pink ring. For a MOVE, slide
   the robot to the new green ring and take your hand out of view. For any other action,
   leave everything still. A frame saves by itself after about a second of stillness with
   no hand in view. If the ring overlaps the obstacle or you can't reach it, push the
   robot as far as it goes and press **B**. Press **Q** to stop; finished episodes are
   kept, and running the same command again resumes.
4. Build the dataset: `python scripts/real_rig/phone_rig.py build --session home1`

Each episode is 12 steps, about 1.5 minutes. Footage stays in `target/real-rig/`
(gitignored). Recording seeds and sessions for an evaluation are assigned by a protocol
registered before recording; nothing recorded before that counts as a test set.

`python scripts/real_rig/phone_rig.py selftest` runs the whole pipeline on a synthetic
phone and operator.
