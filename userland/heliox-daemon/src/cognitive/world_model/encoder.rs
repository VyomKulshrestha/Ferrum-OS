// ============================================================================
// Heliox World Model - Layer 3: State Encoder
// ============================================================================
// Compresses an OsSnapshot into a fixed-size [f32; 128] the transition
// model can do arithmetic on. Slots 0..51 (7 hand-crafted scalars + a
// 41-wide one-hot last-action block) are always computed the same
// deterministic way - no ML, no allocation, fits in a stack frame - since
// safety.rs's risk rules and the transition model both read those exact
// indices. Slots 51..128 (77 floats, unused in Phase 1) are filled with
// a genuinely learned latent code from encoder_learned.rs whenever
// weights are staged (Layer 3.2), and left at zero otherwise - callers
// only ever see `StateEmbedding`, never which path filled it.
// ============================================================================

use super::observation::OsSnapshot;
use super::TOOL_NAMES;

pub const EMBEDDING_SIZE: usize = 128;
pub type StateEmbedding = [f32; EMBEDDING_SIZE];

// Fixed feature slots. Slots 10.. hold a one-hot over TOOL_NAMES
// (41 entries) for `last_action_id`, leaving slots past that unused
// today - reserved headroom for Phase 2's richer feature set without
// growing the embedding size.
const IDX_PROC_COUNT: usize = 0;
const IDX_HEAP_FRACTION: usize = 1;
const IDX_FS_FILE_COUNT: usize = 2;
const IDX_DISK_USAGE: usize = 3;
const IDX_SCREEN_HASH: usize = 4;
const IDX_LAST_ERROR: usize = 5;
const IDX_TICKS_SINCE_ACTION: usize = 6;
const IDX_TOOL_ONEHOT_BASE: usize = 10;

const NOMINAL_PROC_CAPACITY: f32 = 64.0;
const NOMINAL_FS_CAPACITY: f32 = 128.0;

/// Cheap FNV-1a rolling hash - not a real xxhash dependency (this is
/// no_std and doesn't need cryptographic quality), just something stable
/// and fast enough to fold `screen_text` into a single normalized float.
fn rolling_hash(s: &str) -> u32 {
    let mut h: u32 = 2166136261;
    for b in s.bytes() {
        h ^= b as u32;
        h = h.wrapping_mul(16777619);
    }
    h
}

pub fn encode(snapshot: &OsSnapshot) -> StateEmbedding {
    let mut v: StateEmbedding = [0.0; EMBEDDING_SIZE];

    v[IDX_PROC_COUNT] = (snapshot.proc_count as f32 / NOMINAL_PROC_CAPACITY).min(1.0);
    v[IDX_HEAP_FRACTION] = snapshot.heap_used as f32 / snapshot.heap_total as f32;
    v[IDX_FS_FILE_COUNT] = (snapshot.fs_file_count as f32 / NOMINAL_FS_CAPACITY).min(1.0);
    v[IDX_DISK_USAGE] = snapshot.disk_usage_fraction;
    v[IDX_SCREEN_HASH] = rolling_hash(&snapshot.screen_text) as f32 / u32::MAX as f32;
    v[IDX_LAST_ERROR] = if snapshot.last_action_failed { 1.0 } else { 0.0 };
    v[IDX_TICKS_SINCE_ACTION] = 0.0; // set by the caller when it knows the prior tick; see world_model::mod's gate wiring

    let id = super::tool_id(&snapshot.last_action_name);
    if (id as usize) < TOOL_NAMES.len() {
        v[IDX_TOOL_ONEHOT_BASE + id as usize] = 1.0;
    }

    // Layer 3.2: fill the otherwise-unused tail with a learned latent
    // code, if an encoder was staged and loaded at boot. `raw` mirrors
    // exactly what scripts/train_world_model_encoder.py's extract_raw()
    // pulls out of an already-built embedding - the same 7 scalars plus
    // the one-hot action block, just gathered into a contiguous array
    // for the MLP's input layer.
    let mut raw = [0f32; super::encoder_learned::RAW_INPUT_SIZE];
    raw[..7].copy_from_slice(&v[..7]);
    raw[7..].copy_from_slice(&v[IDX_TOOL_ONEHOT_BASE..IDX_TOOL_ONEHOT_BASE + TOOL_NAMES.len()]);
    if let Some(latent) = super::encoder_learned::encode_latent(&raw) {
        v[super::encoder_learned::LATENT_START..].copy_from_slice(&latent);
    }

    v
}

/// Named accessors so Layer 4/5 don't need to know the raw slot indices
/// above - keeps the feature layout private to this module.
pub fn proc_count(e: &StateEmbedding) -> f32 { e[IDX_PROC_COUNT] }
pub fn heap_fraction(e: &StateEmbedding) -> f32 { e[IDX_HEAP_FRACTION] }
pub fn fs_file_count(e: &StateEmbedding) -> f32 { e[IDX_FS_FILE_COUNT] }
pub fn disk_usage_fraction(e: &StateEmbedding) -> f32 { e[IDX_DISK_USAGE] }

pub fn set_proc_count(e: &mut StateEmbedding, v: f32) { e[IDX_PROC_COUNT] = v.clamp(0.0, 1.0); }
pub fn set_heap_fraction(e: &mut StateEmbedding, v: f32) { e[IDX_HEAP_FRACTION] = v.clamp(0.0, 1.0); }
pub fn set_fs_file_count(e: &mut StateEmbedding, v: f32) { e[IDX_FS_FILE_COUNT] = v.clamp(0.0, 1.0); }
pub fn set_disk_usage_fraction(e: &mut StateEmbedding, v: f32) { e[IDX_DISK_USAGE] = v.clamp(0.0, 1.0); }
