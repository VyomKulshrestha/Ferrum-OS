// ============================================================================
// Heliox World Model - Layer 4.1: Rule-Based Transition Model
// ============================================================================
// f(state_embedding, action) -> predicted next state embedding, computed
// *before* the real syscall fires. Phase 1 is a hand-coded lookup table,
// not ML - roughly the tools already gated Tier 3/4 in tool_mapper.rs
// (write_file, delete_file, exec_process, create_directory,
// service_start/stop, trigger_kernel_upgrade) plus net_connect, since
// those are the ones with actually predictable, high-consequence effects.
// Phase 2 replaces the body of `predict_next_state` with a learned MLP
// trained on exp.bin - the function signature doesn't change.
// ============================================================================

extern crate alloc;

use super::encoder::{self, StateEmbedding};
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
    let mut next = *state;
    let mut deletes_own_config = false;
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
            let path = find_tool_arg_string(&action.arguments, "path").unwrap_or_default();
            if path.contains(OWN_CONFIG_PATH) {
                // The exact failure mode config.rs's idle-until-configured
                // gate exists to prevent the *daemon* from causing -
                // this closes the same class of gap for the *agent*
                // causing it deliberately.
                deletes_own_config = true;
            }
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

    Prediction {
        embedding: next,
        deletes_own_config,
        proc_count_delta,
    }
}

