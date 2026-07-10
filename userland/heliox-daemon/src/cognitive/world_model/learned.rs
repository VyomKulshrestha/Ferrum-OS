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
use super::NUM_TOOLS;

const SYS_READ_FILE: u64 = 15;
pub const WEIGHTS_PATH: &str = "/disk/heliox/world/model_learned.bin";
const INPUT_SIZE: usize = EMBEDDING_SIZE + NUM_TOOLS;
const MAX_FILE_SIZE: usize = 2 * 1024 * 1024; // generous - actual weights are a few hundred KB at most

struct Mlp {
    input_size: usize,
    hidden_size: usize,
    output_size: usize,
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

/// Loads the learned weights file if present. Called once at daemon
/// boot; safe to call repeatedly (e.g. after retraining and re-staging a
/// new weights file) since it just replaces whatever was loaded before.
///
/// Format (written by scripts/train_world_model.py's write_weights):
///   header: 3 x u32 LE = input_size, hidden_size, output_size
///   then f32 LE arrays: w1 (input*hidden), b1 (hidden), w2 (hidden*output), b2 (output)
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

    let input_size = read_u32_le(&buf, 0) as usize;
    let hidden_size = read_u32_le(&buf, 4) as usize;
    let output_size = read_u32_le(&buf, 8) as usize;

    let expected_len = 12 + (input_size * hidden_size + hidden_size + hidden_size * output_size + output_size) * 4;
    if input_size != INPUT_SIZE || output_size != EMBEDDING_SIZE || expected_len != len {
        let msg = alloc::format!(
            "[heliox-daemon] [world-model] learned model weights file has unexpected shape (input={} hidden={} output={} expected_bytes={} actual_bytes={}), ignoring\n",
            input_size, hidden_size, output_size, expected_len, len
        );
        unsafe { crate::syscall3(34, 1, msg.as_ptr() as u64, msg.len() as u64) };
        return false;
    }

    let mut offset = 12;
    let w1 = read_f32_slice(&buf, offset, input_size * hidden_size);
    offset += w1.len() * 4;
    let b1 = read_f32_slice(&buf, offset, hidden_size);
    offset += b1.len() * 4;
    let w2 = read_f32_slice(&buf, offset, hidden_size * output_size);
    offset += w2.len() * 4;
    let b2 = read_f32_slice(&buf, offset, output_size);

    *MODEL.lock() = Some(Mlp { input_size, hidden_size, output_size, w1, b1, w2, b2 });

    let msg = alloc::format!(
        "[heliox-daemon] [world-model] loaded learned transition model (input={} hidden={} output={})\n",
        input_size, hidden_size, output_size
    );
    unsafe { crate::syscall3(34, 1, msg.as_ptr() as u64, msg.len() as u64) };
    true
}

pub fn is_loaded() -> bool {
    MODEL.lock().is_some()
}

/// Predicts the embedding *delta* a proposed action would produce, given
/// the current embedding and its one-hot tool id. Returns None if no
/// model is loaded (caller falls back to the Phase 1 rule table).
pub fn predict_delta(state: &StateEmbedding, action_id: u8) -> Option<[f32; EMBEDDING_SIZE]> {
    let guard = MODEL.lock();
    let model = guard.as_ref()?;

    let mut input = [0f32; INPUT_SIZE];
    input[..EMBEDDING_SIZE].copy_from_slice(state);
    if (action_id as usize) < NUM_TOOLS {
        input[EMBEDDING_SIZE + action_id as usize] = 1.0;
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
    Some(delta)
}
