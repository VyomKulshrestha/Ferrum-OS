// ============================================================================
// Heliox World Model - Layer 4: Transition Model
// ============================================================================
// f(state_embedding, action) -> predicted next state embedding, computed
// *before* the real syscall fires. Two interchangeable implementations
// behind the same `predict_next_state` signature:
//   - Phase 1 (`rule_based_delta`): a hand-coded lookup table - roughly
//     the tools already gated Tier 3/4 in tool_mapper.rs (write_file,
//     delete_file, exec_process, create_directory, service_start/stop,
//     trigger_kernel_upgrade) plus net_connect, the ones with
//     actually predictable, high-consequence effects.
//   - Phase 2 (`learned::predict_delta`): a small MLP trained offline on
//     real collected data (scripts/train_world_model.py), used
//     automatically whenever `learned::try_load()` found weights at
//     boot - falling back to the rule table otherwise. Neither the
//     safety gate nor anything upstream needs to know which one ran.
// ============================================================================

extern crate alloc;

use super::encoder::{self, StateEmbedding};
use super::learned;
use super::super::json::{find_tool_arg_string, ToolCall};

/// The prediction Layer 5 scores. Carries both the predicted embedding
/// (for generic threshold checks) and two specific flags the embedding
/// alone can't cleanly represent - a file path match and a raw
/// process-count delta - because the safety gate's rules for those are
/// about a *specific* predicted event (deleting one exact file, spawning
/// N processes in one step), not just a threshold on a normalized float.
pub struct Prediction {
    pub embedding: StateEmbedding,
    pub deletes_own_config: bool,
    pub proc_count_delta: i32,
}

const OWN_CONFIG_PATH: &str = "/disk/heliox/config.json";

pub fn predict_next_state(state: &StateEmbedding, action: &ToolCall) -> Prediction {
    // `deletes_own_config` is a fact about the action's *arguments*, not
    // a numeric prediction - always checked directly regardless of which
    // embedding-delta source is used below, so a config.json deletion
    // stays caught even before a learned model has ever seen the
    // one exact path this daemon's own config lives at.
    let deletes_own_config = action.name == "delete_file"
        && find_tool_arg_string(&action.arguments, "path")
            .unwrap_or_default()
            .contains(OWN_CONFIG_PATH);

    if let Some(delta) = learned::predict_delta(state, super::tool_id(&action.name)) {
        let mut next = *state;
        for i in 0..next.len() {
            // Clamped to [0,1]: every field encoder.rs actually defines
            // (proc_count, heap_fraction, fs_file_count, disk_usage,
            // screen_hash, last_error, one-hot slots) lives in that
            // range by construction - the MLP has no such constraint
            // built in, so an imperfectly-trained model could otherwise
            // predict a nonsensical out-of-range value the safety gate's
            // threshold checks (> 0.95) were never meant to see.
            next[i] = (next[i] + delta[i]).clamp(0.0, 1.0);
        }
        // Derived from the learned model's own predicted proc_count
        // delta (normalized by encoder.rs's NOMINAL_PROC_CAPACITY=64) -
        // works for *any* action the model has learned an effect for,
        // not just the three the rule table hardcodes below. Manual
        // round-half-away-from-zero: f32::round() needs std, unavailable
        // in this no_std crate.
        let raw = delta[0] * 64.0;
        let proc_count_delta = if raw >= 0.0 { (raw + 0.5) as i32 } else { (raw - 0.5) as i32 };
        return Prediction { embedding: next, deletes_own_config, proc_count_delta };
    }

    let (next, proc_count_delta) = rule_based_delta(state, action);
    Prediction { embedding: next, deletes_own_config, proc_count_delta }
}

fn rule_based_delta(state: &StateEmbedding, action: &ToolCall) -> (StateEmbedding, i32) {
    let mut next = *state;
    let mut proc_count_delta: i32 = 0;

    match action.name.as_str() {
        "write_file" => {
            // A write grows disk usage and (usually) the file count by
            // one small nudge each - Phase 1 has no way to know the
            // actual byte size being written ahead of time.
            let disk = encoder::disk_usage_fraction(&next) + 0.02;
            encoder::set_disk_usage_fraction(&mut next, disk);
            let files = encoder::fs_file_count(&next) + 0.01;
            encoder::set_fs_file_count(&mut next, files);
        }
        "delete_file" => {
            // deletes_own_config is computed once in predict_next_state,
            // regardless of which delta source is active - see there.
            let files = encoder::fs_file_count(&next) - 0.01;
            encoder::set_fs_file_count(&mut next, files);
        }
        "create_directory" => {
            let disk = encoder::disk_usage_fraction(&next) + 0.005;
            encoder::set_disk_usage_fraction(&mut next, disk);
        }
        "exec_process" => {
            proc_count_delta = 1;
            let procs = encoder::proc_count(&next) + 1.0 / 64.0;
            encoder::set_proc_count(&mut next, procs);
        }
        "service_start" => {
            proc_count_delta = 1;
            let procs = encoder::proc_count(&next) + 1.0 / 64.0;
            encoder::set_proc_count(&mut next, procs);
        }
        "service_stop" => {
            proc_count_delta = -1;
            let procs = encoder::proc_count(&next) - 1.0 / 64.0;
            encoder::set_proc_count(&mut next, procs);
        }
        "trigger_kernel_upgrade" => {
            // The single highest-consequence action modeled: a kexec
            // swaps the running kernel image out from under every
            // process on the system. No embedding threshold captures
            // that honestly, so this forces heap_fraction to its max to
            // guarantee Layer 5 blocks it regardless of other state.
            encoder::set_heap_fraction(&mut next, 1.0);
        }
        "net_connect" => {
            // Modeled for completeness (it's the one non-Tier-3/4 tool
            // model.md calls out) - no embedding field represents
            // network state today, so this is a documented no-op rather
            // than a fabricated effect.
        }
        "save_memory" | "play_audio" | "keyboard_type" | "mouse_click" | "mouse_move" => {
            // Tier-3 tools with no predictable effect on any field this
            // embedding tracks - modeled explicitly (not silently
            // falling through to the wildcard arm) so this rule table's
            // coverage of Tier 3/4 is complete and auditable.
        }
        _ => {
            // Every other tool (Tier 0-2, or unrecognized): no
            // predicted change. This is the honest default - Phase 1
            // doesn't try to model low-consequence/read-only tools.
        }
    }

    (next, proc_count_delta)
}

