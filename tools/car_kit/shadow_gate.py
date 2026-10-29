"""FerrumOS judging the car's moves from the overhead camera, actuator disabled (roadmap M1).

Runs tools/car_gate (the FerrumOS physical runtime in a hardware-in-loop session with the
actuator disabled, car-arena policy from `userland/physical-runtime/src/car_arena.rs`) as a
subprocess. Each tracked `Scene` goes in as the car's position and its edge-to-edge clearance
to the obstacle; each proposed move comes back as the gate's verdict and reasons. The car is
driven by the bring-up tool under supervision, never by this class: FerrumOS only judges, and
M1's test compares those judgements with what the car then did.

One process is one runtime session. Its evidence log is bounded (8,192 records), so send the
latest scene just before each proposal rather than every camera frame, and start a new
`ShadowGate` for each test run: about 1,600 proposals fit in one session.

Build the gate (no extra crates; on this host the GNU toolchain supplies the linker):
  cargo build --release --manifest-path tools/car_gate/Cargo.toml --target x86_64-pc-windows-gnu
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import time

from .tracker import Scene

ROOT = Path(__file__).resolve().parents[2]
_CANDIDATES = (
    ROOT / "tools/car_gate/target/x86_64-pc-windows-gnu/release/ferrum-car-gate.exe",
    ROOT / "tools/car_gate/target/release/ferrum-car-gate.exe",
    ROOT / "tools/car_gate/target/release/ferrum-car-gate",
)


def find_gate() -> Path | None:
    """The built gate: $CAR_GATE_EXE, else the default cargo output paths."""
    env = os.environ.get("CAR_GATE_EXE")
    if env:
        return Path(env) if Path(env).exists() else None
    return next((p for p in _CANDIDATES if p.exists()), None)


@dataclass(frozen=True)
class ArenaMeasurements:
    """Arena metres and seconds, centred like the tracker (x in [-w/2, w/2]). The last five are
    measured on the real car before any test; see the margin formula in the roadmap."""
    arena_w_m: float
    arena_h_m: float
    car_radius_m: float             # circle around the tracked centre that covers the body
    obstacle_radius_m: float
    required_clearance_m: float     # edge to edge
    tracker_error_p99_m: float
    max_speed_m_s: float
    latency_s: float                # camera capture to verdict
    stop_s: float                   # stop command to standstill
    max_step_m: float
    ticks_per_second: int = 100
    require_approval: bool = False

    def line(self, run_id: int, start_tick: int) -> str:
        mm = lambda v: int(round(v * 1000))
        return (f"arena run={run_id} start={start_tick} min_x={-mm(self.arena_w_m / 2)} max_x={mm(self.arena_w_m / 2)} "
                f"min_y={-mm(self.arena_h_m / 2)} max_y={mm(self.arena_h_m / 2)} car_radius={mm(self.car_radius_m)} "
                f"obstacle_radius={mm(self.obstacle_radius_m)} clearance={mm(self.required_clearance_m)} "
                f"e99={mm(self.tracker_error_p99_m)} vmax={mm(self.max_speed_m_s)} latency_ms={mm(self.latency_s)} "
                f"stop_ms={mm(self.stop_s)} step={mm(self.max_step_m)} tps={self.ticks_per_second} "
                f"approval={int(self.require_approval)}")


@dataclass(frozen=True)
class GatePolicy:
    margin_mm: int
    age_ticks: int
    min_clearance_mm: int
    step_mm: int
    fence_mm: tuple[int, int, int, int]      # min_x, max_x, min_y, max_y of the car's centre


@dataclass(frozen=True)
class Verdict:
    command_id: int
    verdict: str                  # allow | block | require_approval
    reasons: tuple[str, ...]

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"


class GateError(RuntimeError):
    pass


def _kv(text: str) -> dict[str, str]:
    return dict(tok.split("=", 1) for tok in text.split()[1:] if "=" in tok)


class ShadowGate:
    def __init__(self, arena: ArenaMeasurements, run_id: int = 1, exe: Path | None = None,
                 start_tick: int = 1_000, clock=time.monotonic) -> None:
        exe = exe or find_gate()
        if exe is None:
            raise GateError("tools/car_gate is not built (see this module's docstring)")
        self.arena, self.clock, self.tps = arena, clock, arena.ticks_per_second
        self._t0: float | None = None
        self._start = start_tick
        self._last_tick = start_tick
        self._proc = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      text=True, encoding="utf-8", bufsize=1)
        reply = self._ask(arena.line(run_id, start_tick))
        if not reply.startswith("policy "):
            raise GateError(reply)
        kv = _kv(reply)
        self.policy = GatePolicy(int(kv["margin"]), int(kv["age_ticks"]), int(kv["min_clearance"]),
                                 int(kv["step"]), tuple(int(v) for v in kv["fence"].split(",")))

    def _ask(self, line: str) -> str:
        assert self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()
        reply = self._proc.stdout.readline().strip()
        if not reply:
            raise GateError("car_gate exited")
        return reply

    def tick_of(self, t: float) -> int:
        """Seconds on the tracker's clock -> session ticks (never earlier than the last one used)."""
        if self._t0 is None:
            self._t0 = t
        tick = self._start + int((t - self._t0) * self.tps)
        self._last_tick = max(self._last_tick, tick)
        return tick

    def observe(self, scene: Scene, received_t: float | None = None) -> bool:
        """Hand one scene to the gate. A scene without the car or the obstacle sends nothing, so
        the readings age out and motion blocks. Returns whether frames were sent."""
        if not scene.ok or scene.obstacle is None:
            return False
        cap = self.tick_of(scene.t)
        tick = max(cap, self.tick_of(self.clock() if received_t is None else received_t))
        mm = lambda v: int(round(v * 1000))
        reply = self._ask(f"track tick={tick} cap={cap} rx={mm(scene.robot[0])} ry={mm(scene.robot[1])} "
                          f"ox={mm(scene.obstacle[0])} oy={mm(scene.obstacle[1])} q=900")
        if not reply.startswith("ok "):
            raise GateError(reply)
        return True

    def propose(self, command_id: int, target_xy_m: tuple[float, float], t: float | None = None,
                approved: bool = False) -> Verdict:
        tick = max(self._last_tick, self.tick_of(self.clock() if t is None else t))
        reply = self._ask(f"propose tick={tick} id={command_id} x={int(round(target_xy_m[0] * 1000))} "
                          f"y={int(round(target_xy_m[1] * 1000))} approved={int(approved)}")
        if not reply.startswith("verdict "):
            raise GateError(reply)
        kv = _kv(reply)
        reasons = tuple(r for r in kv.get("reasons", "").split(",") if r)
        return Verdict(int(kv["id"]), kv["verdict"], reasons)

    def close(self) -> None:
        try:
            if self._proc.poll() is None:
                assert self._proc.stdin
                self._proc.stdin.write("quit\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()
            self._proc.wait(timeout=5)
        finally:
            for pipe in (self._proc.stdin, self._proc.stdout):
                if pipe is not None:
                    pipe.close()

    def __enter__(self) -> "ShadowGate":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
