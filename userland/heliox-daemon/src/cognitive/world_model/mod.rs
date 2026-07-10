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
pub mod learned;

use alloc::format;
use alloc::string::String;
use alloc::vec;
use super::json::{JsonValue, ToolCall};
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

pub const NUM_TOOLS: usize = TOOL_NAMES.len();

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

/// Deterministically generates the i-th action in a fixed rotation over
/// every tool `transition.rs`'s rule table actually models, with varied
/// (numbered) arguments - used by `Orchestrator::run_data_collection` to
/// gather real (not synthetic-in-the-sense-of-fake) experience data:
/// every action still goes through the exact same capture/predict/gate/
/// dispatch/record path production traffic does, real syscalls and all,
/// just without waiting on an LLM round-trip to propose the next one.
///
/// Every 47th call deliberately targets the daemon's own config.json
/// with delete_file - a guaranteed-blocked case, included on purpose so
/// the collected dataset has real examples of the gate actually firing,
/// not just allowed actions.
pub fn synthetic_action(i: u32) -> ToolCall {
    if i > 0 && i % 47 == 0 {
        return ToolCall {
            name: String::from("delete_file"),
            arguments: vec![(String::from("path"), JsonValue::Str(String::from("/disk/heliox/config.json")))],
        };
    }

    let n = i % 13;
    let (name, arguments): (&str, alloc::vec::Vec<(String, JsonValue)>) = match n {
        0 => ("write_file", vec![
            (String::from("path"), JsonValue::Str(format!("/disk/wm_data_{}.txt", i))),
            (String::from("content"), JsonValue::Str(format!("sample data {}", i))),
        ]),
        1 => ("create_directory", vec![
            // Reused from a small fixed pool (not ever-growing by i) -
            // there's no remove-directory tool in the 39-tool set to
            // clean these up, so an unbounded name here would leave
            // /disk's directory listing growing forever, which
            // query_fs_file_count's ReadDir call re-scans on every
            // single snapshot - a real, previously-hit slowdown during
            // long collection runs. Repeat calls legitimately fail
            // ("already exists"), which is itself valid training signal.
            (String::from("path"), JsonValue::Str(format!("/disk/wm_dir_{}", i % 5))),
        ]),
        2 => ("delete_file", vec![
            (String::from("path"), JsonValue::Str(format!("/disk/wm_data_{}.txt", i.saturating_sub(2)))),
        ]),
        3 => ("exec_process", vec![
            (String::from("path"), JsonValue::Str(String::from("/disk/pkgs-available/notes/bin"))),
        ]),
        4 => ("service_start", vec![(String::from("service_id"), JsonValue::Number(1.0))]),
        5 => ("service_stop", vec![(String::from("service_id"), JsonValue::Number(1.0))]),
        6 => ("net_connect", vec![
            (String::from("host"), JsonValue::Str(String::from("10.0.2.2"))),
            (String::from("port"), JsonValue::Number(9.0)),
        ]),
        7 => ("save_memory", vec![]),
        8 => ("play_audio", vec![]),
        9 => ("keyboard_type", vec![(String::from("text"), JsonValue::Str(String::from("x")))]),
        10 => ("mouse_click", vec![(String::from("button"), JsonValue::Number(0.0))]),
        11 => ("mouse_move", vec![
            (String::from("dx"), JsonValue::Number(1.0)),
            (String::from("dy"), JsonValue::Number(1.0)),
        ]),
        _ => ("read_file", vec![(String::from("path"), JsonValue::Str(String::from("/disk/heliox/config.json")))]),
    };
    ToolCall { name: String::from(name), arguments }
}

/// Exports one full training example to the serial log as hex-encoded
/// f32 arrays - the compact 44-byte records `experience::record_experience`
/// writes to exp.bin can't hold full 128-float embeddings (see
/// experience.rs's module doc for why), so offline training reads real
/// data from here instead: `scripts/collect_world_model_dataset.mjs`
/// parses these lines out of the serial log into a host-side dataset.
pub fn emit_dataset_row(
    tick: u64,
    state_before: &encoder::StateEmbedding,
    action_id: u8,
    state_after: &encoder::StateEmbedding,
    reward: f32,
) {
    let mut before_hex = String::with_capacity(encoder::EMBEDDING_SIZE * 8);
    for f in state_before.iter() {
        before_hex.push_str(&format!("{:08x}", f.to_bits()));
    }
    let mut after_hex = String::with_capacity(encoder::EMBEDDING_SIZE * 8);
    for f in state_after.iter() {
        after_hex.push_str(&format!("{:08x}", f.to_bits()));
    }
    let line = format!(
        "[heliox-daemon] [world-model-dataset] tick={} action={} reward={:.4} before={} after={}\n",
        tick, action_id, reward, before_hex, after_hex
    );
    unsafe {
        crate::syscall3(34, 1, line.as_ptr() as u64, line.len() as u64);
    }
}
