// ============================================================================
// Heliox World Model - Layer 3.2: Learned Encoder
// ============================================================================
// Fills the state embedding's currently-unused slots (51..128, 77 floats)
// with a genuinely learned latent code, reconstructed from the same 48
// raw scalars (7 hand-crafted scalars + the 41-wide one-hot last-action
// block) the Phase 1 encoder already computes into slots 0..51 -
// trained offline as an autoencoder (scripts/train_world_model_encoder.py,
// pure numpy) and loaded here the same way learned.rs loads the
// transition model's weights.
//
// Deliberately does *not* touch slots 0..51: safety.rs's risk rules and
// the already-verified Layer 4.2 transition model both read those exact
// indices, and growing the embedding to a fresh space (model.md's
// literal 256-float Layer 3.2 spec) would need an entirely new
// data-collection pass to get real (before, after) pairs in that space.
// Reusing the 77 dims already sitting unused inside the existing
// 128-float embedding gets a genuinely learned representation for the
// majority of what the transition model sees without that cost or the
// risk of destabilizing the safety-critical fields.
//
// Strictly additive and optional, exactly like learned.rs: a boot with
// no encoder weights staged just leaves slots 51..128 at zero, which is
// what Phase 1's encoder already left them at.
// ============================================================================

extern crate alloc;

use alloc::vec;
use alloc::vec::Vec;
use spin::Mutex;
use super::NUM_TOOLS;
use super::encoder::EMBEDDING_SIZE;

const SYS_READ_FILE: u64 = 15;
pub const WEIGHTS_PATH: &str = "/disk/heliox/world/model_encoder.bin";
pub const RAW_INPUT_SIZE: usize = 7 + NUM_TOOLS; // 7 hand-crafted scalars + one-hot action
pub const LATENT_START: usize = 51;
pub const LATENT_SIZE: usize = EMBEDDING_SIZE - LATENT_START; // 77
const MAX_FILE_SIZE: usize = 2 * 1024 * 1024;

struct Mlp {
    input_size: usize,
    hidden_size: usize,
    output_size: usize,
    w1: Vec<f32>,
    b1: Vec<f32>,
    w2: Vec<f32>,
    b2: Vec<f32>,
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

/// Same flat-binary format as learned.rs's transition weights: header
/// (3 x u32 LE: input_size, hidden_size, output_size) then f32 LE arrays
/// w1/b1/w2/b2 - written by scripts/train_world_model_encoder.py's
/// write_encoder_weights.
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
        return false;
    }
    let len = n as usize;
    buf.truncate(len);

    let input_size = read_u32_le(&buf, 0) as usize;
    let hidden_size = read_u32_le(&buf, 4) as usize;
    let output_size = read_u32_le(&buf, 8) as usize;

    let expected_len = 12 + (input_size * hidden_size + hidden_size + hidden_size * output_size + output_size) * 4;
    if input_size != RAW_INPUT_SIZE || output_size != LATENT_SIZE || expected_len != len {
        let msg = alloc::format!(
            "[heliox-daemon] [world-model] learned encoder weights file has unexpected shape (input={} hidden={} output={} expected_bytes={} actual_bytes={}), ignoring\n",
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
        "[heliox-daemon] [world-model] loaded learned encoder (input={} hidden={} output={})\n",
        input_size, hidden_size, output_size
    );
    unsafe { crate::syscall3(34, 1, msg.as_ptr() as u64, msg.len() as u64) };
    true
}

pub fn is_loaded() -> bool {
    MODEL.lock().is_some()
}

/// Computes the 77-float learned latent code for slots 51..128, given
/// the 48 raw scalars (7 hand-crafted scalars + one-hot last action)
/// `encoder::encode` already has on hand. Returns None if no encoder is
/// loaded - caller leaves those slots at zero, same as Phase 1.
pub fn encode_latent(raw: &[f32; RAW_INPUT_SIZE]) -> Option<[f32; LATENT_SIZE]> {
    let guard = MODEL.lock();
    let model = guard.as_ref()?;

    let mut hidden = alloc::vec![0f32; model.hidden_size];
    for h in 0..model.hidden_size {
        let mut sum = model.b1[h];
        for i in 0..model.input_size {
            sum += raw[i] * model.w1[i * model.hidden_size + h];
        }
        hidden[h] = sum.max(0.0);
    }

    let mut latent = [0f32; LATENT_SIZE];
    for o in 0..model.output_size {
        let mut sum = model.b2[o];
        for h in 0..model.hidden_size {
            sum += hidden[h] * model.w2[h * model.output_size + o];
        }
        latent[o] = sum;
    }
    Some(latent)
}
