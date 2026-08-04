// ============================================================================
// Heliox World Model - Layer 4.2: Learned Transition Model
// ============================================================================
// A small MLP predicting the *delta* a tool call produces on the state
// embedding, trained offline (scripts/train_world_model.py, pure numpy)
// on real data collected via Orchestrator::run_data_collection
// (scripts/collect_world_model_dataset.mjs) and loaded here the same way
// inference.rs already loads the real llama2.c checkpoint: a flat binary
// weights file read via SYS_READ_FILE, parsed into plain f32 arrays, no
// framework, no allocation beyond the arrays themselves.
//
// Strictly additive and optional: if the weights file doesn't exist
// (e.g. a boot with no appliance disk attached, or one that simply never
// had a model trained for it), `is_loaded()` returns false and
// `transition::predict_next_state` falls straight back to Phase 1's
// rule table - nothing about the safety gate's behavior depends on this
// module ever succeeding.
// ============================================================================

extern crate alloc;

use alloc::vec;
use alloc::vec::Vec;
use spin::Mutex;
use super::encoder::{EMBEDDING_SIZE, StateEmbedding};
use super::action_features;
use super::super::json::ToolCall;
use super::{NUM_TOOLS, tool_id};

const SYS_READ_FILE: u64 = 15;
pub const WEIGHTS_PATH: &str = "/disk/heliox/world/model_learned.bin";
const LEGACY_INPUT_SIZE: usize = EMBEDDING_SIZE + NUM_TOOLS;
const HYBRID_INPUT_SIZE: usize = LEGACY_INPUT_SIZE + action_features::ACTION_FEATURE_SIZE;
const MAX_FILE_SIZE: usize = 2 * 1024 * 1024; // generous - actual weights are a few hundred KB at most
const V2_MAGIC: u32 = u32::from_le_bytes(*b"FWM2");
const V2_VERSION: u32 = 2;
const POLICY_ONLY_COVERAGE: u64 = 1u64 << 28; // trigger_kernel_upgrade

// The legacy corpus trained only this 13-tool rotation. Its file format has
// no coverage metadata, so unseen actions must fall back to deterministic
// rules instead of activating random, never-trained one-hot columns.
const LEGACY_COVERAGE: u64 =
    (1u64 << 7) | (1u64 << 13) | (1u64 << 17) | (1u64 << 18) |
    (1u64 << 19) | (1u64 << 23) | (1u64 << 24) | (1u64 << 25) |
    (1u64 << 26) | (1u64 << 34) | (1u64 << 36) | (1u64 << 37) |
    (1u64 << 38);

struct Mlp {
    input_size: usize,
    hidden_size: usize,
    output_size: usize,
    action_feature_size: usize,
    coverage: u64,
    w1: Vec<f32>, // [input_size][hidden_size], row-major
    b1: Vec<f32>, // [hidden_size]
    w2: Vec<f32>, // [hidden_size][output_size], row-major
    b2: Vec<f32>, // [output_size]
}

static MODEL: Mutex<Option<Mlp>> = Mutex::new(None);

fn read_u32_le(buf: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes([buf[offset], buf[offset + 1], buf[offset + 2], buf[offset + 3]])
}

fn read_f32_slice(buf: &[u8], offset: usize, count: usize) -> Vec<f32> {
    let mut out = Vec::with_capacity(count);
    for i in 0..count {
        let o = offset + i * 4;
        out.push(f32::from_le_bytes([buf[o], buf[o + 1], buf[o + 2], buf[o + 3]]));
    }
    out
}

fn expected_weight_bytes(
    header_len: usize,
    input_size: usize,
    hidden_size: usize,
    output_size: usize,
) -> Option<usize> {
    input_size
        .checked_mul(hidden_size)?
        .checked_add(hidden_size)?
        .checked_add(hidden_size.checked_mul(output_size)?)?
        .checked_add(output_size)?
        .checked_mul(core::mem::size_of::<f32>())?
        .checked_add(header_len)
}

/// Loads the learned weights file if present. Called once at daemon
/// boot; safe to call repeatedly (e.g. after retraining and re-staging a
/// new weights file) since it just replaces whatever was loaded before.
///
/// Legacy format: 3 x u32 LE = input_size, hidden_size, output_size.
/// Hybrid v2 format: "FWM2", version, input/hidden/output sizes,
/// action-feature size, and a 64-bit trained-tool coverage mask.
/// Both are followed by f32 LE arrays w1, b1, w2, b2.
pub fn try_load() -> bool {
    let mut buf = vec![0u8; MAX_FILE_SIZE];
    let n = unsafe {
        crate::syscall4(
            SYS_READ_FILE,
            WEIGHTS_PATH.as_ptr() as u64,
            WEIGHTS_PATH.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    if (n as i64) <= 12 {
        return false; // missing, or too small to even hold the header
    }
    let len = n as usize;
    buf.truncate(len);

    let first = read_u32_le(&buf, 0);
    let (header_len, input_size, hidden_size, output_size, action_feature_size, coverage) =
        if first == V2_MAGIC {
            if len < 32 || read_u32_le(&buf, 4) != V2_VERSION {
                return false;
            }
            let coverage_low = read_u32_le(&buf, 24) as u64;
            let coverage_high = read_u32_le(&buf, 28) as u64;
            (
                32usize,
                read_u32_le(&buf, 8) as usize,
                read_u32_le(&buf, 12) as usize,
                read_u32_le(&buf, 16) as usize,
                read_u32_le(&buf, 20) as usize,
                coverage_low | (coverage_high << 32),
            )
        } else {
            (
                12usize,
                first as usize,
                read_u32_le(&buf, 4) as usize,
                read_u32_le(&buf, 8) as usize,
                0usize,
                LEGACY_COVERAGE,
            )
        };

    let expected_input = LEGACY_INPUT_SIZE + action_feature_size;
    let expected_len = expected_weight_bytes(header_len, input_size, hidden_size, output_size);
    let valid_coverage_mask = (1u64 << NUM_TOOLS) - 1;
    if input_size != expected_input
        || hidden_size == 0
        || (action_feature_size != 0 && action_feature_size != action_features::ACTION_FEATURE_SIZE)
        || output_size != EMBEDDING_SIZE
        || expected_len != Some(len)
        || coverage == 0
        || coverage & !valid_coverage_mask != 0
        || coverage & POLICY_ONLY_COVERAGE != 0
    {
        let msg = alloc::format!(
            "[heliox-daemon] [world-model] learned model weights file has invalid metadata (input={} hidden={} output={} expected_bytes={:?} actual_bytes={} coverage=0x{:x}), ignoring\n",
            input_size, hidden_size, output_size, expected_len, len, coverage
        );
        unsafe { crate::syscall3(34, 1, msg.as_ptr() as u64, msg.len() as u64) };
        return false;
    }

    let mut offset = header_len;
    let w1 = read_f32_slice(&buf, offset, input_size * hidden_size);
    offset += w1.len() * 4;
    let b1 = read_f32_slice(&buf, offset, hidden_size);
    offset += b1.len() * 4;
    let w2 = read_f32_slice(&buf, offset, hidden_size * output_size);
    offset += w2.len() * 4;
    let b2 = read_f32_slice(&buf, offset, output_size);

    if !w1.iter().chain(&b1).chain(&w2).chain(&b2).all(|value| value.is_finite()) {
        let msg = b"[heliox-daemon] [world-model] learned model contains non-finite weights, ignoring\n";
        unsafe { crate::syscall3(34, 1, msg.as_ptr() as u64, msg.len() as u64) };
        return false;
    }

    *MODEL.lock() = Some(Mlp {
        input_size,
        hidden_size,
        output_size,
        action_feature_size,
        coverage,
        w1,
        b1,
        w2,
        b2,
    });

    let msg = alloc::format!(
        "[heliox-daemon] [world-model] loaded learned transition model (input={} hidden={} output={} arg_features={} coverage=0x{:x})\n",
        input_size, hidden_size, output_size, action_feature_size, coverage
    );
    unsafe { crate::syscall3(34, 1, msg.as_ptr() as u64, msg.len() as u64) };
    true
}

pub fn is_loaded() -> bool {
    MODEL.lock().is_some()
}

/// Predicts the embedding delta for a canonical ToolCall. Hybrid weights see
/// both the tool id and argument features; legacy weights see only the id.
/// An action absent from the weight file's coverage mask falls back to the
/// deterministic rule table.
pub fn predict_delta(state: &StateEmbedding, action: &ToolCall) -> Option<[f32; EMBEDDING_SIZE]> {
    let guard = MODEL.lock();
    let model = guard.as_ref()?;
    let action_id = tool_id(&action.name);
    if action_id as usize >= NUM_TOOLS || model.coverage & (1u64 << action_id) == 0 {
        return None;
    }

    let mut input = alloc::vec![0f32; model.input_size];
    input[..EMBEDDING_SIZE].copy_from_slice(state);
    if (action_id as usize) < NUM_TOOLS {
        input[EMBEDDING_SIZE + action_id as usize] = 1.0;
    }
    if model.action_feature_size == action_features::ACTION_FEATURE_SIZE {
        let features = action_features::encode(action);
        input[LEGACY_INPUT_SIZE..HYBRID_INPUT_SIZE].copy_from_slice(&features);
    }

    // hidden = relu(input @ w1 + b1) - w1 is [input_size][hidden_size] row-major.
    let mut hidden = alloc::vec![0f32; model.hidden_size];
    for h in 0..model.hidden_size {
        let mut sum = model.b1[h];
        for i in 0..model.input_size {
            sum += input[i] * model.w1[i * model.hidden_size + h];
        }
        hidden[h] = sum.max(0.0);
    }

    // output = hidden @ w2 + b2 - this *is* the delta, not the absolute
    // next embedding (see scripts/train_world_model.py's module doc for
    // why delta-prediction was chosen).
    let mut delta = [0f32; EMBEDDING_SIZE];
    for o in 0..model.output_size {
        let mut sum = model.b2[o];
        for h in 0..model.hidden_size {
            sum += hidden[h] * model.w2[h * model.output_size + o];
        }
        delta[o] = sum;
    }
    // Finite weights can still overflow during a hostile or corrupted
    // multiply-accumulate. Never let NaN/Inf reach safety comparisons;
    // None selects the deterministic transition table at the call site.
    if !delta.iter().all(|value| value.is_finite()) {
        return None;
    }
    Some(delta)
}
