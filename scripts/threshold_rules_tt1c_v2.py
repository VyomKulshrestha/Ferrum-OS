"""Corrections to threshold_rules_tt1c.py (a frozen file; see docs/research/monitor_audit_2026-11-10.md).

_Episodes   The online episode tracker behind tracker_hold starts a new episode when the step since the last
            alarm exceeds GAP (i - last > GAP), so two alarm runs separated by exactly GAP quiet steps are two
            episodes. The plan (alarms merged across the 60 s gap) and every batch counter
            (threshold_rules._episodes, DailyExcl) merge them: a new episode needs i - last > GAP + 1. The same
            off-by-one sets the end of the event episode for the hold-off. A run split this way can fail to
            reach EVENT_L, so tracker_hold keeps raising its threshold through what the batch definition calls
            an event.
TrackerHold tracker_hold on the corrected tracker. Constants default to the tt1c module; pass the time-scaled
            ones (threshold_rules_tt1d.Rules(step).N) for tt1d.
"""
from __future__ import annotations

import threshold_rules_tt1c as N
from threshold_rules_tt1c import *  # noqa: F401,F403  (re-export the unchanged rules)


class _Episodes:
    def __init__(self, gap=None, event_l=None, hold=None, mod=N):
        self.gap = mod.GAP if gap is None else gap
        self.event_l = mod.EVENT_L if event_l is None else event_l
        self.hold = mod.HOLD if hold is None else hold
        self.i, self.start, self.last, self.event, self.hold_until = 0, None, None, False, -1

    def step(self, alarm):
        i = self.i
        if alarm:
            if self.last is None or i - self.last > self.gap + 1:
                self.start, self.event = i, False
            self.last = i
            if i - self.start + 1 >= self.event_l:
                self.event = True
        elif self.event and i - self.last > self.gap + 1:
            self.hold_until, self.event = self.last + self.hold, False
        self.i += 1
        return (alarm and self.event) or i <= self.hold_until


class TrackerHold(N.TrackerHold):
    def __init__(self, cfg, mod=N):
        super().__init__(cfg)
        self.ep = _Episodes(mod=mod)


def make(rule, cfg, calib, steps_per_day, depth, mod=N):
    if rule == "tracker_hold":
        return TrackerHold(cfg, mod)
    return mod.make(rule, cfg, calib, steps_per_day, depth)
