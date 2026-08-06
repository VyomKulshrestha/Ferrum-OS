# World-model HUD boundary calibration

This post-training study replays **240 real QEMU episodes** across **12 argument-size regimes**. The corpus was collected after model training and remains outside the registered episode-level split, so it is an independent safe negative control rather than extra training data.

## Result

Every action executed successfully. Observed normalized heap delta was exactly zero in 240/240 episodes. The deployed transition's heap-delta MAE was `0.00295566` and RMSE was `0.00401832`. It produced 0 unadjusted resource alarms at the 0.95 threshold; adding the reported empirical p95 upper-residual margin (`0.00221868`) would produce 0 alarms on this same calibration set.

The margin is **analysis only**. It was not installed into the production safety gate because this single-action safe corpus cannot establish dangerous-action coverage. Its value is narrower and useful: long HUD arguments, including the 128-byte render boundary that exposed and motivated the compositor fix, do not consume measurable normalized heap in these runs and do not trigger false resource blocks.

## Reproduction

```powershell
python scripts/evaluate_world_model_boundary_calibration.py
```

Dataset SHA-256: `e6baebb2757a03100f785a32526c2da7a78703e1c8cdbfd06b03a78da9204445`
