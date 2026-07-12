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
/// every tool `transition.rs`'s rule table actually models. Both the
/// rotation slot (`i % 13`) and a `variant` counter (`i / 13`, how many
/// full cycles have elapsed) feed the arguments, so repeated visits to
/// the same tool genuinely vary content size, service id, mouse button/
/// delta, network port, keyboard text, and - for exec_process/read_file
/// - occasionally target a path that doesn't exist, a real failure case
/// otherwise absent from the dataset. Used by
/// `Orchestrator::run_data_collection` to gather real (not
/// synthetic-in-the-sense-of-fake) experience data: every action still
/// goes through the exact same capture/predict/gate/dispatch/record path
/// production traffic does, real syscalls and all, just without waiting
/// on an LLM round-trip to propose the next one.
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
    // Every tool still gets visited on the same fixed 13-slot rotation
    // above, but each visit's *arguments* now vary by how many full
    // cycles have elapsed (`variant`), not just by `i` alone - the
    // original version only ever varied file names/counters, so
    // service_id, mouse button, dx/dy, net_connect's port, and
    // keyboard_type's text were constant across every single one of
    // the 300-2,000-6,000 collected examples, meaning more repetitions
    // couldn't add signal the transition model didn't already have.
    // These are real, valid variations (see tool_mapper.rs: service_id
    // and net_connect's port are unvalidated numeric args the kernel
    // handles gracefully even out of range; mouse_click's button is
    // validated to 0/1/2; exec_process and read_file targeting a path
    // that doesn't exist just fails gracefully, which is itself useful
    // training signal the dataset previously never contained).
    let variant = i / 13;
    let (name, arguments): (&str, alloc::vec::Vec<(String, JsonValue)>) = match n {
        0 => {
            let content = match variant % 4 {
                0 => format!("sample data {}", i),
                1 => "x".repeat(64),
                2 => "y".repeat(512),
                _ => "z".repeat(2048),
            };
            ("write_file", vec![
                (String::from("path"), JsonValue::Str(format!("/disk/wm_data_{}.txt", i))),
                (String::from("content"), JsonValue::Str(content)),
            ])
        }
        1 => ("create_directory", vec![
            // Reused from a small fixed pool (not ever-growing by i) -
            // there's no remove-directory tool in the 39-tool set to
            // clean these up, so an unbounded name here would leave
            // /disk's directory listing growing forever, which
            // query_fs_file_count's ReadDir call re-scans on every
            // single snapshot - a real, previously-hit slowdown during
            // long collection runs. Repeat calls legitimately fail
            // ("already exists"), which is itself valid training signal.
            (String::from("path"), JsonValue::Str(format!("/disk/wm_dir_{}", i % 8))),
        ]),
        2 => ("delete_file", vec![
            (String::from("path"), JsonValue::Str(format!("/disk/wm_data_{}.txt", i.saturating_sub(2)))),
        ]),
        3 => {
            // 1-in-4 targets a path that doesn't exist, a real failure
            // case the dataset never previously covered.
            let path = if variant % 4 == 3 {
                format!("/disk/wm_missing_{}", i % 7)
            } else {
                String::from("/disk/pkgs-available/notes/bin")
            };
            ("exec_process", vec![(String::from("path"), JsonValue::Str(path))])
        }
        4 => ("service_start", vec![(String::from("service_id"), JsonValue::Number(((variant % 3) + 1) as f64))]),
        5 => ("service_stop", vec![(String::from("service_id"), JsonValue::Number(((variant % 3) + 1) as f64))]),
        6 => {
            let port = match variant % 4 {
                0 => 9.0,
                1 => 80.0,
                2 => 443.0,
                _ => 8785.0,
            };
            ("net_connect", vec![
                (String::from("host"), JsonValue::Str(String::from("10.0.2.2"))),
                (String::from("port"), JsonValue::Number(port)),
            ])
        }
        7 => ("save_memory", vec![]),
        8 => ("play_audio", vec![]),
        9 => {
            let text = match variant % 4 {
                0 => String::from("x"),
                1 => String::from("hello"),
                2 => String::from("The quick brown fox"),
                _ => String::from("1234567890"),
            };
            ("keyboard_type", vec![(String::from("text"), JsonValue::Str(text))])
        }
        10 => ("mouse_click", vec![(String::from("button"), JsonValue::Number((variant % 3) as f64))]),
        11 => {
            let (dx, dy) = match variant % 4 {
                0 => (1.0, 1.0),
                1 => (-5.0, 3.0),
                2 => (10.0, -10.0),
                _ => (-1.0, -1.0),
            };
            ("mouse_move", vec![
                (String::from("dx"), JsonValue::Number(dx)),
                (String::from("dy"), JsonValue::Number(dy)),
            ])
        }
        _ => {
            // 1-in-3 targets a path that doesn't exist, so last_error
            // and reward actually vary instead of every read_file call
            // in the dataset being an identical guaranteed-success case.
            let path = if variant % 3 == 2 {
                String::from("/disk/wm_missing_read.txt")
            } else {
                String::from("/disk/heliox/config.json")
            };
            ("read_file", vec![(String::from("path"), JsonValue::Str(path))])
        }
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
