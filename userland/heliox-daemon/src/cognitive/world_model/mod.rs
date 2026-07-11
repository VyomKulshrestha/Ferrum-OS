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
pub mod encoder_learned;
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

/// Layer 6.2: how many times ahead the proposed action is simulated
/// against itself (see `evaluate_action`'s doc comment for why this is
/// self-composition lookahead rather than LLM-branching search).
pub const MAX_LOOKAHEAD: u32 = 3;

pub struct GateDecision {
    pub allowed: bool,
    pub risk: f32,
    pub reason: String,
    /// How many simulated repetitions it took to reach `risk` - 1 means
    /// the action alone was risky; >1 means it only became risky once
    /// repeated, the case MAX_LOOKAHEAD=1 (Phase 1) could never catch.
    pub lookahead_steps: u32,
}

/// Ties Layers 1/3/4/5/6 together for a single proposed action: encode
/// the current snapshot, then simulate up to `MAX_LOOKAHEAD` repetitions
/// of *this same action* via the transition model, taking the worst risk
/// seen across the chain.
///
/// This is deliberately self-composition lookahead, not full LLM-branching
/// search (model.md's `plan_with_simulation` sketch, which needs the LLM
/// re-queried per candidate per step - a real re-architecture of the
/// ReAct prompt/response protocol, deferred to Phase 3's beam search).
/// What this *does* buy over Phase 1's MAX_LOOKAHEAD=1: an action whose
/// single-step effect looks safe can still be caught if repeating it
/// would compound into something dangerous - a ReAct loop stuck
/// re-proposing a similar write/spawn is a real, observed failure mode,
/// not a hypothetical one. `deletes_own_config` is checked freshly at
/// every step (not just the first) since args could differ per real
/// call, even though this simulation reuses one fixed action throughout.
pub fn evaluate_action(state: &OsSnapshot, action: &ToolCall) -> GateDecision {
    let mut embedding = encoder::encode(state);
    let mut worst_risk = 0.0f32;
    let mut worst_reason = String::new();
    let mut worst_step = 1u32;

    for step in 1..=MAX_LOOKAHEAD {
        let prediction = transition::predict_next_state(&embedding, action);
        let (risk, reason) = safety::risk_score(&prediction);
        if risk > worst_risk {
            worst_risk = risk;
            worst_step = step;
            worst_reason = if step == 1 {
                reason
            } else {
                format!("after {} repeated steps: {}", step, reason)
            };
        }
        if worst_risk > safety::BLOCK_THRESHOLD {
            break;
        }
        embedding = prediction.embedding;
    }

    GateDecision {
        allowed: worst_risk <= safety::BLOCK_THRESHOLD,
        risk: worst_risk,
        reason: worst_reason,
        lookahead_steps: worst_step,
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
