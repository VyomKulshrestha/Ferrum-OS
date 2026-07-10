// ============================================================================
// Heliox World Model - Phase 1
// ============================================================================
// A predictive safety layer in front of the ReAct loop's act() dispatch:
// before any tool call reaches tool_mapper::execute(), predict what state
// it would produce and reject it if the prediction looks bad. Lives
// entirely in heliox-daemon userspace, observes through syscalls the
// daemon already calls elsewhere, and never touches the kernel - see
// model.md (repo root, gitignored) for the full design rationale and the
// Phase 2/3 roadmap this deliberately doesn't build yet.
//
// Strictly additive: everything here runs *in addition to* the existing
// Tier 3/4 ConfirmationGate (confirmation.rs), never replacing it. If
// this module's gate is bypassed or its predictions ignored,
// heliox-daemon behaves exactly as it did before this existed.
// ============================================================================

extern crate alloc;

pub mod observation;
pub mod encoder;
pub mod transition;
pub mod safety;
pub mod experience;

use alloc::string::String;
use super::json::ToolCall;
use observation::OsSnapshot;

/// Tool names in a fixed, stable order - used both for the encoder's
/// one-hot `last_action_id` feature and the experience buffer's compact
/// `action_id` byte. Order doesn't need to match any canonical list, it
/// just needs to be consistent across calls within a boot.
pub const TOOL_NAMES: [&str; 41] = [
    "ipc_send", "audit_write", "yield_cpu", "camera_capture", "gesture_status",
    "report_status", "capability_check", "read_file", "read_dir", "query_memory",
    "get_config", "system_info", "list_processes", "net_connect", "net_send",
    "net_recv", "http_get", "write_file", "create_directory", "save_memory",
    "load_memory", "set_goal", "sleep", "service_start", "service_stop",
    "exec_process", "delete_file", "local_inference", "trigger_kernel_upgrade",
    "hud_update", "hit_test", "read_screen", "add_subtask", "record_audio",
    "play_audio", "set_volume", "keyboard_type", "mouse_click", "mouse_move",
    "browse_url", "poll_input",
];

pub fn tool_id(name: &str) -> u8 {
    TOOL_NAMES.iter().position(|t| *t == name).map(|i| i as u8).unwrap_or(255)
}

/// Layer 6 stub result (MAX_LOOKAHEAD=1 - see model.md's Layer 6 section
/// for why this isn't real multi-step planning yet).
pub struct GateDecision {
    pub allowed: bool,
    pub risk: f32,
    pub reason: String,
}

/// Ties Layers 1/3/4/5 together for a single proposed action: encode the
/// current snapshot, predict its effect, score the prediction for risk,
/// and decide whether `act()` should be allowed to dispatch it for real.
pub fn evaluate_action(state: &OsSnapshot, action: &ToolCall) -> GateDecision {
    let embedding = encoder::encode(state);
    let prediction = transition::predict_next_state(&embedding, action);
    let (risk, reason) = safety::risk_score(&prediction);
    GateDecision {
        allowed: risk <= safety::BLOCK_THRESHOLD,
        risk,
        reason,
    }
}
