//! Shadow gate for the car kit (roadmap M1). Reads one command per line on stdin, answers one
//! line per command on stdout. The decisions come from `ferrum_physical_runtime::car_arena`:
//! a hardware-in-loop, actuator-disabled runtime session with the car-arena policy. This
//! program only judges; it has no route to the car.
//!
//! Lines in (keys in any order, values are integers in mm / ms / ticks):
//!   arena run= min_x= max_x= min_y= max_y= car_radius= obstacle_radius= clearance=
//!         e99= vmax= latency_ms= stop_ms= step= tps= [approval=0|1] [start=]
//!   track tick= cap= rx= ry= ox= oy= q=      one tracked scene (received at tick, captured at cap)
//!   propose tick= id= x= y= [approved=0|1]   judge a move of the car's centre to (x, y)
//!   quit
//! Lines out:
//!   policy margin= age_ticks= min_clearance= step= fence=min_x,max_x,min_y,max_y
//!   ok event=
//!   verdict id= verdict=allow|block|require_approval reasons=A,B event=
//!   error <what>

use std::io::{self, BufRead, Write};

use ferrum_physical_runtime::car_arena::{CarArena, CarGate, CarSessionIdentity, TrackedScene};
use ferrum_physical_runtime::domain::SiteId;
use ferrum_physical_runtime::safety::SafetyVerdict;

fn fields(rest: &[&str]) -> Result<Vec<(String, i64)>, String> {
    rest.iter()
        .map(|token| {
            let (key, value) = token
                .split_once('=')
                .ok_or_else(|| format!("expected key=value, got {token}"))?;
            let value = value
                .parse::<i64>()
                .map_err(|_| format!("{key} is not an integer"))?;
            Ok((key.to_string(), value))
        })
        .collect()
}

fn get(fields: &[(String, i64)], key: &str) -> Result<i64, String> {
    fields
        .iter()
        .find(|(name, _)| name == key)
        .map(|(_, value)| *value)
        .ok_or_else(|| format!("missing {key}"))
}

fn get_or(fields: &[(String, i64)], key: &str, default: i64) -> i64 {
    get(fields, key).unwrap_or(default)
}

fn tick(value: i64, key: &str) -> Result<u64, String> {
    u64::try_from(value).map_err(|_| format!("{key} must not be negative"))
}

fn coordinate(value: i64, key: &str) -> Result<i32, String> {
    i32::try_from(value).map_err(|_| format!("{key} out of range"))
}

/// Non-cryptographic fingerprint (FNV-1a, spread over 32 bytes) naming the arena configuration
/// in the session descriptor. It identifies; it does not authenticate.
fn fingerprint(text: &str, salt: u8) -> [u8; 32] {
    let mut out = [0u8; 32];
    for (chunk, slot) in out.chunks_mut(8).enumerate() {
        let mut hash: u64 = 0xcbf2_9ce4_8422_2325 ^ u64::from(salt) ^ (chunk as u64);
        for byte in text.bytes() {
            hash ^= u64::from(byte);
            hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
        }
        slot.copy_from_slice(&hash.to_le_bytes());
    }
    if out.iter().all(|byte| *byte == 0) {
        out[0] = 1;
    }
    out
}

fn arena_from(fields: &[(String, i64)]) -> Result<CarArena, String> {
    Ok(CarArena {
        site_id: SiteId(1),
        zone_id: 1,
        policy_revision: 1,
        proximity_sensor_id: 1,
        arena_min_x_mm: get(fields, "min_x")?,
        arena_max_x_mm: get(fields, "max_x")?,
        arena_min_y_mm: get(fields, "min_y")?,
        arena_max_y_mm: get(fields, "max_y")?,
        car_radius_mm: get(fields, "car_radius")?,
        obstacle_radius_mm: get(fields, "obstacle_radius")?,
        required_clearance_mm: get(fields, "clearance")?,
        require_approval_for_motion: get_or(fields, "approval", 0) != 0,
        ticks_per_second: tick(get(fields, "tps")?, "tps")?,
        tracker_error_p99_mm: get(fields, "e99")?,
        max_speed_mm_per_s: get(fields, "vmax")?,
        latency_ms: get(fields, "latency_ms")?,
        stop_ms: get(fields, "stop_ms")?,
        max_step_mm: get(fields, "step")?,
    })
}

fn handle(line: &str, gate: &mut Option<CarGate>) -> Result<Option<String>, String> {
    let tokens: Vec<&str> = line.split_whitespace().collect();
    let Some((verb, rest)) = tokens.split_first() else {
        return Ok(None);
    };
    let fields = fields(rest)?;
    match *verb {
        "arena" => {
            if gate.is_some() {
                return Err("arena already set; start a new process for a new session".into());
            }
            let arena = arena_from(&fields)?;
            let identity = CarSessionIdentity {
                run_id: tick(get(&fields, "run")?, "run")?.max(1),
                started_at_tick: tick(get_or(&fields, "start", 0), "start")?,
                topology_sha256: fingerprint(line, 1),
                policy_sha256: fingerprint(line, 2),
                transport_digest: fingerprint("ferrum car tracker link", 3),
            };
            let new_gate = CarGate::new(arena, identity).map_err(|error| format!("{error:?}"))?;
            let policy = *new_gate.policy();
            *gate = Some(new_gate);
            Ok(Some(format!(
                "policy margin={} age_ticks={} min_clearance={} step={} fence={},{},{},{}",
                arena.margin_mm(),
                policy.maximum_sensor_age_ticks,
                policy.minimum_clearance_mm,
                policy.maximum_step_mm.unwrap_or(0),
                policy.geofence.minimum_x_mm,
                policy.geofence.maximum_x_mm,
                policy.geofence.minimum_y_mm,
                policy.geofence.maximum_y_mm
            )))
        }
        "track" => {
            let gate = gate.as_mut().ok_or("no arena yet")?;
            let scene = TrackedScene {
                captured_at_tick: tick(get(&fields, "cap")?, "cap")?,
                robot_x_mm: coordinate(get(&fields, "rx")?, "rx")?,
                robot_y_mm: coordinate(get(&fields, "ry")?, "ry")?,
                obstacle_x_mm: coordinate(get(&fields, "ox")?, "ox")?,
                obstacle_y_mm: coordinate(get(&fields, "oy")?, "oy")?,
                quality_permille: u16::try_from(get(&fields, "q")?.clamp(0, 1_000)).unwrap_or(0),
            };
            let event = gate
                .ingest(&scene, tick(get(&fields, "tick")?, "tick")?)
                .map_err(|error| format!("{error:?}"))?;
            Ok(Some(format!("ok event={event}")))
        }
        "propose" => {
            let gate = gate.as_mut().ok_or("no arena yet")?;
            let id = tick(get(&fields, "id")?, "id")?;
            let decision = gate
                .propose(
                    id,
                    get(&fields, "x")?,
                    get(&fields, "y")?,
                    tick(get(&fields, "tick")?, "tick")?,
                    get_or(&fields, "approved", 0) != 0,
                )
                .map_err(|error| format!("{error:?}"))?;
            let verdict = match decision.verdict {
                SafetyVerdict::Allow => "allow",
                SafetyVerdict::RequireApproval => "require_approval",
                SafetyVerdict::Block => "block",
            };
            let reasons: Vec<String> = decision
                .reasons
                .iter()
                .map(|reason| format!("{reason:?}"))
                .collect();
            Ok(Some(format!(
                "verdict id={id} verdict={verdict} reasons={} event={}",
                reasons.join(","),
                gate.runtime().twin().snapshot().latest_event_id
            )))
        }
        other => Err(format!("unknown command {other}")),
    }
}

fn main() {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    let mut gate: Option<CarGate> = None;
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        let line = line.trim_start_matches('\u{feff}').trim(); // some shells prepend a BOM
        if line == "quit" {
            break;
        }
        let answer = match handle(line, &mut gate) {
            Ok(Some(answer)) => answer,
            Ok(None) => continue,
            Err(error) => format!("error {error}"),
        };
        if writeln!(stdout, "{answer}")
            .and_then(|()| stdout.flush())
            .is_err()
        {
            break;
        }
    }
}
