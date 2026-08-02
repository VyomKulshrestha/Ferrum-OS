// ============================================================================
// FerrumOS - Shared Clipboard Service
// ============================================================================
// A small, kernel-owned broker shared by mutually isolated ring-3 processes.
// Clipboard contents are volatile by design and bounded so one application
// cannot turn this convenience service into unbounded kernel-heap growth.
// Access is capability-gated at the syscall and shell boundaries.
// ============================================================================

extern crate alloc;

use alloc::vec::Vec;
use spin::Mutex;

pub const MAX_CLIPBOARD_BYTES: usize = 64 * 1024;

#[derive(Clone)]
pub struct ClipboardSnapshot {
    pub bytes: Vec<u8>,
    pub generation: u64,
    pub owner_pid: u64,
}

struct ClipboardState {
    bytes: Vec<u8>,
    generation: u64,
    owner_pid: u64,
}

static CLIPBOARD: Mutex<ClipboardState> = Mutex::new(ClipboardState {
    bytes: Vec::new(),
    generation: 0,
    owner_pid: 0,
});

pub fn init() {
    let mut state = CLIPBOARD.lock();
    state.bytes.clear();
    state.generation = 0;
    state.owner_pid = 0;
}

pub fn write(owner_pid: u64, bytes: &[u8]) -> Result<u64, &'static str> {
    if bytes.len() > MAX_CLIPBOARD_BYTES {
        return Err("clipboard payload exceeds 64 KiB");
    }

    let mut state = CLIPBOARD.lock();
    state.bytes.clear();
    state.bytes.extend_from_slice(bytes);
    state.generation = state.generation.saturating_add(1);
    state.owner_pid = owner_pid;
    crate::serial_println!(
        "[clipboard] write pid={} bytes={} generation={}",
        owner_pid,
        bytes.len(),
        state.generation
    );
    Ok(state.generation)
}

pub fn snapshot() -> ClipboardSnapshot {
    let state = CLIPBOARD.lock();
    ClipboardSnapshot {
        bytes: state.bytes.clone(),
        generation: state.generation,
        owner_pid: state.owner_pid,
    }
}
