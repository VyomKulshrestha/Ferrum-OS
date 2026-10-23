"""Figure 3: threshold trajectories on BATADAL, stream test_dataset_1.  Run: python -B fig3_trajectories_batadal.py

The zoom panel shows days 68-100 (the first three attacks) instead of the first two
days, because the first attack of test_dataset_1 starts on day 72.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trajectories import draw, main

KW = dict(dataset="batadal", stream="test_dataset_1", per_day=96, unit_label="15-min step",
          zoom=(68.0, 100.0), zoom_title="Days 68-100 of test_dataset_1 (first three attacks)",
          stem="fig3_trajectories_batadal",
          # registered event counts over test_dataset_1 + test_dataset_2 (README)
          expected={"frozen": (14, 14), "tracker": (6, 14), "spot_mle": (14, 14), "dspot": (6, 14)})

if __name__ == "__main__":
    main(**KW)
else:
    fig, report = draw(**KW)
