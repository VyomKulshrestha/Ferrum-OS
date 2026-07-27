// ============================================================================
// Heliox World Model - Canonical Action Argument Features
// ============================================================================
// Provider responses are normalized into ToolCall before reaching this layer.
// These features therefore describe only the proposed OS action, never which
// LLM produced it. They make argument-dependent effects learnable without
// coupling the world model to a provider or language-model size.
// ============================================================================

use super::super::json::{JsonValue, ToolCall};

pub const ACTION_FEATURE_SIZE: usize = 16;
pub type ActionFeatures = [f32; ACTION_FEATURE_SIZE];

const MAX_ARGS: f32 = 8.0;
const MAX_STRING_BYTES: f32 = 4096.0;
const MAX_PATH_BYTES: f32 = 256.0;
const MAX_TEXT_BYTES: f32 = 1024.0;
const MAX_NUMERIC_MAGNITUDE: f64 = 10_000.0;

fn clamp_ratio(value: usize, max: f32) -> f32 {
    (value as f32 / max).clamp(0.0, 1.0)
}

fn rolling_hash(s: &str) -> f32 {
    let mut h: u32 = 2166136261;
    for b in s.bytes() {
        h ^= b as u32;
        h = h.wrapping_mul(16777619);
    }
    h as f32 / u32::MAX as f32
}

fn signed_number(value: f64) -> f32 {
    ((value.clamp(-MAX_NUMERIC_MAGNITUDE, MAX_NUMERIC_MAGNITUDE)
        / MAX_NUMERIC_MAGNITUDE
        + 1.0)
        * 0.5) as f32
}

/// Layout:
///  0 argument count, 1 total string bytes, 2 content bytes, 3 path bytes,
///  4 path hash, 5 text bytes, 6 host hash, 7 port, 8/9 first two numbers,
/// 10 config-path flag, 11 heliox-tree flag, 12 disk-tree flag,
/// 13 missing/nonexistent marker, 14 string count, 15 numeric count.
pub fn encode(action: &ToolCall) -> ActionFeatures {
    let mut out = [0.0f32; ACTION_FEATURE_SIZE];
    out[0] = clamp_ratio(action.arguments.len(), MAX_ARGS);

    let mut total_string_bytes = 0usize;
    let mut string_count = 0usize;
    let mut numeric_count = 0usize;
    let mut numbers = [0.0f64; 2];

    for (key, value) in &action.arguments {
        match value {
            JsonValue::Str(s) => {
                string_count += 1;
                total_string_bytes = total_string_bytes.saturating_add(s.len());
                match key.as_str() {
                    "content" => out[2] = clamp_ratio(s.len(), MAX_STRING_BYTES),
                    "path" => {
                        out[3] = clamp_ratio(s.len(), MAX_PATH_BYTES);
                        out[4] = rolling_hash(s);
                        out[10] = if s.contains("/disk/heliox/config.json") { 1.0 } else { 0.0 };
                        out[11] = if s.starts_with("/disk/heliox") { 1.0 } else { 0.0 };
                        out[12] = if s.starts_with("/disk/") { 1.0 } else { 0.0 };
                        let lower = s.to_ascii_lowercase();
                        out[13] = if lower.contains("missing") || lower.contains("nonexistent") {
                            1.0
                        } else {
                            0.0
                        };
                    }
                    "text" | "query" | "goal" => {
                        out[5] = clamp_ratio(s.len(), MAX_TEXT_BYTES);
                    }
                    "host" => out[6] = rolling_hash(s),
                    _ => {}
                }
            }
            JsonValue::Number(n) => {
                if numeric_count < numbers.len() {
                    numbers[numeric_count] = *n;
                }
                numeric_count += 1;
                if key == "port" {
                    out[7] = (*n / 65_535.0).clamp(0.0, 1.0) as f32;
                }
            }
            _ => {}
        }
    }

    out[1] = clamp_ratio(total_string_bytes, MAX_STRING_BYTES);
    out[8] = signed_number(numbers[0]);
    out[9] = signed_number(numbers[1]);
    out[14] = clamp_ratio(string_count, MAX_ARGS);
    out[15] = clamp_ratio(numeric_count, MAX_ARGS);
    out
}
