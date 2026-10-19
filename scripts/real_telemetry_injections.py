"""Incident-informed injection families for the real-telemetry study (development data only).

Each family turns a documented attack or failure mechanism into a telemetry signature applied to a
copy of normal data. Sources are the verified literature in real_telemetry_sources_v1.json; the
HAI testbed's own attack papers and manual and the SMD paper are excluded from the design because
they describe the evaluation data. Targets are drawn at random: actions uniformly, coupled sensors
by absolute correlation of first differences in normal fitting data. Magnitudes and durations use
one shared registered distribution for every family, including the generic-noise control, so the
families differ only in shape, targeting and coupling.
"""
from __future__ import annotations

import numpy as np

HAI_FAMILIES = {
    "development": ["setpoint_step", "slow_drift", "actuator_forcing", "replay_loop", "freeze", "saturation",
                    "command_pulse", "offset_polyline", "regime_flip"],
    "held_out": ["oscillating_actuator", "trip_without_cause", "masked_coordinated"],
}
SMD_FAMILIES = {
    "development": ["cpu_saturation", "leak_ramp", "exhaustion_ramp", "partition", "fail_slow", "transient_stop",
                    "burst_or_stall", "hang", "config_shift"],
    "held_out": ["staircase_leak", "retry_storm", "partial_partition"],
}
GENERIC = "generic_noise"

# Shared registered distributions (log-uniform). HAI steps are seconds; SMD steps are minutes.
DURATION = {"hai": (60, 3600), "smd": (5, 600)}
MAGNITUDE = (0.5, 5.0)               # robust-scale units of the targeted variables
TAU = {"hai": (10, 300), "smd": (1, 30)}


def log_uniform(rng, low, high):
    return float(np.exp(rng.uniform(np.log(low), np.log(high))))


def coupling(Z, V):
    """|corr| of first differences between each action and each sensor (normal fitting data)."""
    dz, dv = np.diff(Z, axis=0), np.diff(V, axis=0)
    dz = (dz - dz.mean(0)) / (dz.std(0) + 1e-9)
    dv = (dv - dv.mean(0)) / (dv.std(0) + 1e-9)
    return np.abs(dv.T @ dz) / len(dz)                         # (actions, sensors)


def sensor_groups(Z):
    """|corr| of first differences between sensors (used for correlated multi-metric families)."""
    dz = np.diff(Z, axis=0)
    dz = (dz - dz.mean(0)) / (dz.std(0) + 1e-9)
    return np.abs(dz.T @ dz) / len(dz)


def _lag_response(n, tau):
    return 1.0 - np.exp(-np.arange(n) / tau)


class Injector:
    """Applies one family to (Z, V) copies; returns (Z', V', labels)."""

    def __init__(self, domain, fit_Z, fit_V=None, seed=0):
        self.domain, self.rng = domain, np.random.default_rng(seed)
        self.low, self.high = fit_Z.min(0), fit_Z.max(0)
        self.corr = sensor_groups(fit_Z)
        self.couple = coupling(fit_Z, fit_V) if fit_V is not None else None
        if fit_V is not None:
            self.vlow, self.vhigh = fit_V.min(0), fit_V.max(0)
            self.levels = [np.unique(np.round(fit_V[:, j], 3))[:50] for j in range(fit_V.shape[1])]

    # -- target selection ----------------------------------------------------------------
    def _group(self, size):
        seed = int(self.rng.integers(self.corr.shape[0]))
        order = np.argsort(-self.corr[seed])
        return order[:size]

    def _action_and_sensors(self, k):
        a = int(self.rng.integers(self.couple.shape[0]))
        sensors = np.argsort(-self.couple[a])[:k]
        return a, sensors

    # -- application ---------------------------------------------------------------------
    def apply(self, Z, V, family, start=None):
        rng = self.rng
        Z = Z.copy()
        V = None if V is None else V.copy()
        T = len(Z)
        length = int(round(log_uniform(rng, *DURATION[self.domain])))
        length = min(length, T // 3)
        start = int(rng.integers(T // 4, T - length - 1)) if start is None else start
        end = start + length
        span = np.arange(length)
        mag = log_uniform(rng, *MAGNITUDE)
        sign = lambda n=1: rng.choice([-1.0, 1.0], n)
        tau = log_uniform(rng, *TAU[self.domain])
        y = np.zeros(T, np.int8)
        y[start:end] = 1

        def respond(sensors, delta_u, profile):
            gains = sign(len(sensors)) * rng.uniform(0.5, 2.0, len(sensors))
            Z[start:end, sensors] += np.outer(profile * delta_u, gains)

        f = family
        # ---------------- HAI (actions available) ----------------
        if f == "setpoint_step":                          # T0836 Modify Parameter; Oldsmar AA21-042A
            a, s = self._action_and_sensors(3)
            d = sign()[0] * mag
            V[start:end, a] += d
            respond(s, d, _lag_response(length, tau))
        elif f == "slow_drift":                           # Cardenas 2011 bias/geometric; Giraldo 2018
            cols = self._group(int(rng.integers(1, 3)))
            ramp = (span / max(length - 1, 1)) ** rng.uniform(1.0, 3.0)
            Z[start:end, cols] += np.outer(ramp, sign(len(cols)) * mag)
        elif f == "actuator_forcing":                     # T0831 Manipulation of Control; Urbina 2016
            a, s = self._action_and_sensors(3)
            target = self.vhigh[a] if rng.random() < 0.5 else self.vlow[a]
            d = target - V[start, a]
            V[start:end, a] = target
            respond(s, d, _lag_response(length, tau))
        elif f == "replay_loop":                          # Stuxnet input-image replay (Symantec 2011)
            cols = self._group(int(rng.integers(2, 6)))
            loop = int(rng.integers(21, 300))
            src = max(0, start - loop - int(rng.integers(0, 600)))
            Z[start:end, cols] = np.resize(Z[src:src + loop, cols], (length, len(cols)))
        elif f == "freeze":                               # stale-data DoS (Cardenas 2011); stuck-at (Ni 2009)
            cols = self._group(int(rng.integers(1, 4)))
            Z[start:end, cols] = Z[start - 1, cols]
        elif f == "saturation":                           # above-HH / below-LL (Kravchik 2021); clipping (Ni)
            cols = self._group(int(rng.integers(1, 3)))
            up = rng.random() < 0.5
            Z[start:end, cols] = (self.high[cols] if up else self.low[cols]) + (0.1 if up else -0.1) * mag
        elif f == "command_pulse":                        # T1692.001 Unauthorized Command; Ukraine 2015
            a, s = self._action_and_sensors(3)
            pulse = int(min(length, rng.integers(1, 31)))
            d = sign()[0] * mag
            V[start:start + pulse, a] += d
            profile = np.concatenate([_lag_response(pulse, tau), _lag_response(pulse, tau)[-1] * np.exp(-np.arange(length - pulse) / tau)])
            respond(s, d, profile)
        elif f == "offset_polyline":                      # BATADAL concealment offset (Taormina 2018)
            cols = self._group(int(rng.integers(1, 4)))
            knots = np.sort(rng.uniform(0, length, 3))
            values = rng.uniform(-mag, mag, 5)
            curve = np.interp(span, np.concatenate([[0], knots, [length]]), values)
            Z[start:end, cols] += curve[:, None]
        elif f == "regime_flip":                          # threshold/regime change (Maroochy C0020; BATADAL)
            a, s = self._action_and_sensors(3)
            levels = self.levels[a]
            new = levels[int(rng.integers(len(levels)))] if len(levels) > 1 else V[start, a] + mag
            d = new - V[start, a]
            V[start:end, a] = new
            respond(s, d if abs(d) > 1e-6 else mag, _lag_response(length, tau))
        elif f == "oscillating_actuator":                 # held out: Industroyer breaker loop; Urbina toggling
            a, s = self._action_and_sensors(3)
            period = int(rng.integers(4, 120))
            wave = np.where((span // max(period // 2, 1)) % 2 == 0, 1.0, -1.0) * mag
            V[start:end, a] += wave
            filtered = np.zeros(length)
            for i in range(1, length):
                filtered[i] = filtered[i - 1] + (wave[i] - filtered[i - 1]) / tau
            gains = sign(len(s)) * rng.uniform(0.5, 2.0, len(s))
            Z[start:end, s] += np.outer(filtered, gains)
        elif f == "trip_without_cause":                   # held out: Triton/TRISIS spurious safety trip
            cols = self._group(int(rng.integers(3, 7)))
            decay = _lag_response(length, tau)
            Z[start:end, cols] += np.outer(decay, self.low[cols] - Z[start, cols])
        elif f == "masked_coordinated":                   # held out: Stuxnet control change + view replay
            a, s = self._action_and_sensors(5)
            d = sign()[0] * mag
            V[start:end, a] += d
            respond(s, d, _lag_response(length, tau))
            hidden = s[:2]
            loop = int(rng.integers(21, 300))
            src = max(0, start - loop)
            Z[start:end, hidden] = np.resize(Z[src:src + loop, hidden], (length, len(hidden)))
        # ---------------- SMD (no actions) ----------------
        elif f == "cpu_saturation":                       # Cloudflare 2019; Ghosh 2022; Exathlon T4
            cols = self._group(int(rng.integers(2, 5)))
            Z[start:end, cols] = self.high[cols] + 0.05 * mag
        elif f == "leak_ramp":                            # RESIN steady leak (Lou 2022)
            cols = self._group(1)
            Z[start:end, cols] += np.outer(span / max(length - 1, 1), [mag])
        elif f == "exhaustion_ramp":                      # insufficient resource (Yin 2011); Yuan 2014
            cols = self._group(int(rng.integers(1, 3)))
            ramp = np.minimum(1.0, span / max(1, int(length * rng.uniform(0.3, 0.8))))
            Z[start:end, cols] = Z[start:end, cols] + np.outer(ramp, self.high[cols] + 0.05 * mag - Z[start, cols])
        elif f == "partition":                            # complete partition (Alquraan 2018)
            cols = self._group(int(rng.integers(2, 5)))
            Z[start:end, cols] = self.low[cols]
        elif f == "fail_slow":                            # fail-slow hardware (Gunawi 2018); Limplock 2013
            cols = self._group(int(rng.integers(1, 4)))
            factor = _lag_response(length, tau) * rng.uniform(0.3, 0.9)
            wobble = 1 + 0.2 * np.sin(2 * np.pi * span / max(10, int(rng.integers(10, 60))))
            Z[start:end, cols] = Z[start:end, cols] - np.outer(factor * wobble, Z[start:end, cols].mean(0) - self.low[cols])
        elif f == "transient_stop":                       # transient stop (Gunawi 2018); Exathlon T5/T6
            cols = self._group(int(rng.integers(2, 5)))
            every, down = int(rng.integers(10, 60)), int(rng.integers(1, 5))
            stops = (span % every) < down
            Z[start + np.flatnonzero(stops)[:, None], cols] = self.low[cols]
        elif f == "burst_or_stall":                       # bursty input / stalled input (Exathlon T1/T3)
            cols = self._group(int(rng.integers(1, 4)))
            if rng.random() < 0.5:
                Z[start:end, cols] += mag
            else:
                Z[start:end, cols] = self.low[cols]
        elif f == "hang":                                 # hung system (Yuan 2014); unresponsive (Liu 2019)
            cols = self._group(int(rng.integers(2, 5)))
            Z[start:end, cols[1:]] = Z[start - 1, cols[1:]]
            Z[start:end, cols[0]] += mag
        elif f == "config_shift":                         # config change (Yin 2011; Gunawi 2016; Ghosh 2022)
            cols = self._group(int(rng.integers(2, 6)))
            Z[start:end, cols] += sign(len(cols)) * mag
        elif f == "staircase_leak":                       # held out: RESIN stair/spike growth
            cols = self._group(1)
            steps = np.cumsum(rng.random(length) < 0.02) * (mag / 5)
            Z[start:end, cols] += steps[:, None]
        elif f == "retry_storm":                          # held out: metastable retries (Bronson 2021; Huang 2022)
            cols = self._group(int(rng.integers(3, 6)))
            trigger = int(min(length, rng.integers(2, 15)))
            level = np.concatenate([np.full(trigger, 2.0), 1.0 + 0.1 * np.arange(length - trigger) / max(length, 1)])
            osc = 1 + 0.3 * np.sin(2 * np.pi * span / max(5, int(rng.integers(5, 30))))
            Z[start:end, cols] += np.outer(level * osc * mag / 2, np.ones(len(cols)))
        elif f == "partial_partition":                    # held out: partial partition, split-brain (Alquraan)
            cols = self._group(int(rng.integers(4, 7)))
            half = len(cols) // 2
            Z[start:end, cols[:half]] = self.low[cols[:half]]
            Z[start:end, cols[half:]] += mag
            tail = min(T, end + length // 2)
            Z[end:tail, cols[half:]] += 0.3 * mag
            y[end:tail] = 1
        # ---------------- generic control ----------------
        elif f == GENERIC:                                # unstructured corruption, same budget
            n = int(rng.integers(1, 5))
            cols = rng.choice(Z.shape[1], n, replace=False)
            Z[start:end, cols] += rng.normal(0, mag, (length, n))
        else:
            raise ValueError(f)
        return Z, V, y
