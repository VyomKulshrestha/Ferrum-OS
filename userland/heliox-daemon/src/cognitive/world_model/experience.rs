// ============================================================================
// Heliox World Model - Layer 2: Experience Buffer
// ============================================================================
// Records (state_before, action, state_after, reward) to disk on every
// tool call - the training set for Phase 2's learned transition model,
// collected passively from real agent use starting day one. Appended as
// a fixed-size binary record via SYS_WRITE_FILE (16), the same syscall
// config.rs already uses to persist state.
//
// Record size and MAX_TUPLES are deliberately much smaller than model.md's
// aspirational "50,000 tuples" figure: ext2's own create_file
// (src/fs/ext2.rs) only supports direct blocks - 12 max, ~48KB at this
// appliance image's 4096-byte block size - so a rewrite-on-every-append
// pattern (required because create_file errors on an existing path
// rather than truncating, the same reason config.rs/pkg::mod.rs already
// do remove-then-create) simply cannot exceed that ceiling. Growing this
// meaningfully needs either indirect-block support in ext2's write path
// or splitting across multiple small files - deferred, not silently
// ignored. At 44 bytes/record and MAX_TUPLES=200, the buffer tops out at
// 8800 bytes, safely under the ~12KB worst case even at a 1024-byte
// block size.
// ============================================================================

extern crate alloc;

use alloc::vec::Vec;
use crate::{syscall3, syscall4};

const SYS_READ_FILE: u64 = 15;
const SYS_WRITE_FILE: u64 = 16;
const SYS_DELETE_FILE: u64 = 22;
const SYS_CREATE_DIR: u64 = 21;

const EXP_DIR: &str = "/disk/heliox/world";
pub const EXP_PATH: &str = "/disk/heliox/world/exp.bin";
pub const RECORD_SIZE: usize = 44;
pub const MAX_TUPLES: usize = 200;

pub struct ExperienceTuple {
    pub tick: u64,
    pub action_id: u8,
    pub success: bool,
    pub reward: f32,
    pub risk: f32,
    pub proc_count_before: f32,
    pub proc_count_after: f32,
    pub heap_fraction_before: f32,
    pub heap_fraction_after: f32,
    pub disk_usage_before: f32,
    pub disk_usage_after: f32,
}

impl ExperienceTuple {
    fn to_bytes(&self) -> [u8; RECORD_SIZE] {
        let mut buf = [0u8; RECORD_SIZE];
        buf[0..8].copy_from_slice(&self.tick.to_le_bytes());
        buf[8] = self.action_id;
        buf[9] = self.success as u8;
        // 10..12 reserved/padding
        buf[12..16].copy_from_slice(&self.reward.to_le_bytes());
        buf[16..20].copy_from_slice(&self.risk.to_le_bytes());
        buf[20..24].copy_from_slice(&self.proc_count_before.to_le_bytes());
        buf[24..28].copy_from_slice(&self.proc_count_after.to_le_bytes());
        buf[28..32].copy_from_slice(&self.heap_fraction_before.to_le_bytes());
        buf[32..36].copy_from_slice(&self.heap_fraction_after.to_le_bytes());
        buf[36..40].copy_from_slice(&self.disk_usage_before.to_le_bytes());
        buf[40..44].copy_from_slice(&self.disk_usage_after.to_le_bytes());
        buf
    }
}

/// Reads exp.bin back, if it exists. Uses the raw SYS_READ_FILE syscall
/// directly (not a String-typed helper) - sys_read_file's kernel-side
/// implementation already reads via read_file_offset (binary-safe), so
/// this round-trips arbitrary bytes correctly (see src/syscall/fs.rs's
/// sys_read_file, and src/fs/mod.rs's read_file_bytes for the sibling
/// fix this project made on the sys_exec side of the same class of bug).
fn read_existing() -> Vec<u8> {
    let mut buf = alloc::vec![0u8; RECORD_SIZE * MAX_TUPLES];
    let n = unsafe {
        syscall4(
            SYS_READ_FILE,
            EXP_PATH.as_ptr() as u64,
            EXP_PATH.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    if (n as i64) <= 0 {
        return Vec::new();
    }
    buf.truncate(n as usize);
    // Defensive against a partial/corrupt tail from an interrupted write.
    let whole_records = buf.len() / RECORD_SIZE;
    buf.truncate(whole_records * RECORD_SIZE);
    buf
}

pub fn record_experience(tuple: &ExperienceTuple) {
    let mut existing = read_existing();

    // Front-truncate FIFO once at cap, mirroring src/logging/audit.rs's
    // MAX_ENTRIES pattern - drop the oldest record(s), not the newest.
    while existing.len() >= RECORD_SIZE * MAX_TUPLES {
        existing.drain(0..RECORD_SIZE);
    }
    existing.extend_from_slice(&tuple.to_bytes());

    unsafe {
        // Best-effort, idempotent: /disk/heliox/ already exists (created
        // at appliance-image build time or by the RamFS fallback), but
        // /disk/heliox/world/ doesn't - "already exists" on every call
        // after the first is expected and ignored, same as pkg::mod.rs's
        // create_dir calls.
        syscall4(SYS_CREATE_DIR, EXP_DIR.as_ptr() as u64, EXP_DIR.len() as u64, 0, 0);

        // ext2's create_file errors on an existing path rather than
        // truncating - remove-then-create, same as config.rs/pkg::mod.rs.
        // Ignoring the result: "not found" on the very first write is
        // expected and harmless.
        syscall3(SYS_DELETE_FILE, EXP_PATH.as_ptr() as u64, EXP_PATH.len() as u64, 0);
        syscall4(
            SYS_WRITE_FILE,
            EXP_PATH.as_ptr() as u64,
            EXP_PATH.len() as u64,
            existing.as_ptr() as u64,
            existing.len() as u64,
        );
    }
}

/// How many whole records currently exist in exp.bin - used by the
/// verification harness rather than anything the daemon itself needs at
/// runtime, but kept here since it's the natural place to read the
/// buffer's own format.
pub fn tuple_count() -> usize {
    read_existing().len() / RECORD_SIZE
}
