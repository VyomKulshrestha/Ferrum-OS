"""Figure 2: threshold trajectories on HAI 20.07, stream test1.  Run: python -B fig2_trajectories_hai2007.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trajectories import draw, main

KW = dict(dataset="hai-20.07", stream="test1", per_day=1440, unit_label="minute",
          zoom=(0.0, 2.0), zoom_title="First two days of test1",
          stem="fig2_trajectories_hai2007",
          # registered event counts over test1 + test2 (README, figure_data section)
          expected={"frozen": (36, 38), "tracker": (20, 38), "spot_mle": (35, 38), "dspot": (36, 38)})

if __name__ == "__main__":
    main(**KW)
else:
    fig, report = draw(**KW)
