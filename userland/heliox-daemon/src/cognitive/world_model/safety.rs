// ============================================================================
// Heliox World Model - Layer 5.1: Safety Gate
// ============================================================================
// Scores a Layer 4 prediction for risk and blocks the real syscall if the
// score crosses a threshold - a second, *predictive* check that runs
// before, and independently of, the existing reactive ConfirmationGate
// (confirmation.rs). Both gates must pass: this one catches classes of
// harm a fixed Tier list can't enumerate (a Tier-2 write_file that
// happens to target config.json isn't Tier-4, but predicting its effect
// on that specific path catches it anyway); ConfirmationGate still
// catches everything already scoped to Tier 3/4 regardless of what this
// predicts. Neither replaces the other.
// ============================================================================

extern crate alloc;

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use super::encoder;
use super::transition::Prediction;

pub const BLOCK_THRESHOLD: f32 = 0.7;

/// 50 processes in one step, expressed in the same normalized [0,1]
/// space the encoder represents proc_count in (NOMINAL_PROC_CAPACITY=64
/// in encoder.rs) - i.e. 50/64. Kept as a named constant rather than a
/// bare literal so the "50 processes" figure from the design doc is
/// traceable to this exact threshold.
const FORK_BOMB_DELTA_FRACTION: f32 = 50.0 / 64.0;

/// Returns (total risk, human-readable reason string joining every rule
/// that fired - empty if none did).
pub fn risk_score(prediction: &Prediction) -> (f32, String) {
    let mut risk = 0.0f32;
    let mut reasons: Vec<String> = Vec::new();

    if encoder::disk_usage_fraction(&prediction.embedding) > 0.95 {
        risk += 0.8;
        reasons.push(String::from("predicted disk usage > 95%"));
    }

    if (prediction.proc_count_delta.unsigned_abs() as f32) / 64.0 > FORK_BOMB_DELTA_FRACTION {
        risk += 0.7;
        reasons.push(format!(
            "process-count delta of {} looks like a fork-bomb pattern",
            prediction.proc_count_delta
        ));
    }

    if prediction.deletes_own_config {
        risk += 0.9;
        reasons.push(String::from("would delete the daemon's own config.json"));
    }

    if encoder::heap_fraction(&prediction.embedding) > 0.95 {
        risk += 0.6;
        reasons.push(String::from("predicted heap usage > 95%"));
    }

    (risk, reasons.join("; "))
}
