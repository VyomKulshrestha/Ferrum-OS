"""Rule factory for the tt1d registered study.

tt1d runs on data with a step other than one second, so every duration in the rules is given in seconds
and converted here. The rule code itself is not rewritten: the tt1c and tt1e libraries are loaded as
private copies whose step constants (event length, hold-off, episode gap, declustering run) are set from
the step, and the tt1b online rules (threshold_online) already take the number of steps per day.

Rules (all online models with tau() and update(x)):
  frozen, tracker (eta 0.01 spread), tracker_slow (eta / 10), tracker_tau (eta 0.01 tau0), daily,
  tighten_only                                             threshold_online (tt1b)
  daily_excl, tracker_hold, tracker_capped, spot_gr        threshold_rules_tt1c
  static_k, tracker_ceil_k, daily_ceil_k, spot_gr_ceil_k,
  spot_gate24, spot_gate6                                  threshold_rules_tt1e
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import threshold_online as O

HERE = Path(__file__).resolve().parent
EVENT_S, HOLD_S, GAP_S = 60.0, 3600.0, 60.0


def _copy(name, alias, **consts):
    spec = importlib.util.spec_from_file_location(alias, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for k, v in consts.items():
        if not hasattr(mod, k):
            raise AttributeError(f"{name} has no constant {k}")
        setattr(mod, k, v)
    return mod


class Rules:
    def __init__(self, step_seconds):
        self.step = float(step_seconds)
        self.steps_per_day = round(86400 / self.step)
        steps = lambda seconds: max(1, round(seconds / self.step))
        self.gap, self.event_l, self.hold = steps(GAP_S), steps(EVENT_S), steps(HOLD_S)
        tag = str(self.steps_per_day)
        self.N = _copy("threshold_rules_tt1c", f"_tt1c_{tag}", EVENT_L=self.event_l, HOLD=self.hold,
                       GAP=self.gap, DECLUST=self.gap)
        self.B = _copy("threshold_rules_tt1e", f"_tt1e_{tag}")
        self.B.N = self.N                               # the tt1e rules build on the time-scaled tt1c copy

    def make(self, rule, cfg, calib):
        spd = self.steps_per_day
        if rule == "frozen":
            return O.Static(cfg["tau0"])
        if rule == "tracker":
            return O.Tracker(cfg, cfg["eta"])
        if rule == "tracker_slow":
            return O.Tracker(cfg, cfg["eta"] / 10)
        if rule == "tracker_tau":
            return O.Tracker(cfg, 0.01 * cfg["tau0"])
        if rule == "daily":
            return O.Daily(cfg, spd)
        if rule == "tighten_only":
            return O.TightenOnly(cfg, cfg["eta"])
        if rule in ("daily_excl", "tracker_hold", "tracker_capped", "spot_gr"):
            return self.N.make(rule, cfg, calib, spd, self.hold)
        return self.B.make(rule, cfg, calib, spd)
