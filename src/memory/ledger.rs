// ============================================================================
// FerrumOS - Per-process kernel heap ledger
// ============================================================================
// Each kind of kernel object a process can make the kernel allocate had its
// own bound (16 messages per mailbox, 16 sockets per owner, 4 windows per
// process, the RamFS total), but nothing capped one process's total: a single
// process could hold about 10 MB of the 12 MiB kernel heap through windows,
// RamFS files, IPC payloads and socket buffers together (fi1 kernel rounds 3
// and 4, "What remains"). The ledger caps the sum (fi2 K1, item 4).
//
// What is counted, per process:
// - IPC: payload plus envelope of every message it sent that is still
//   queued; released when the message is received or dropped;
// - launch context: the bytes stored for it;
// - audit: records it wrote with AuditWrite that are still in the ring;
//   released when the ring drops them;
// - RamFS: bytes of files it created or last rewrote; released when the
//   file is removed or rewritten;
// - windows: its app-window canvases (read from the compositor);
// - sockets: buffers of its sockets (read from the descriptor table).
// The last two are read from their owners' tables at each check, so no
// release site can be missed. A request that would take the sum past
// `PROCESS_HEAP_CAP` is refused before anything is allocated. The entry is
// removed when the process is reaped (`process::drop_by_pid`); objects that
// outlive it (RamFS files, queued messages) are released against an entry
// that no longer exists, which is a no-op. Pids are never reused.
//
// The kernel itself (pid 0) is not charged.
// ============================================================================

extern crate alloc;

use alloc::collections::BTreeMap;
use core::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use spin::Mutex;

/// Kernel heap one process may hold through the objects above. The heap is
/// 12 MiB; the largest shipped app (one window of about 0.9 MB, a few
/// messages, configuration files) stays far below this.
pub const PROCESS_HEAP_CAP: usize = 4 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Ipc = 0,
    LaunchContext = 1,
    Audit = 2,
    RamFs = 3,
}

const COUNTED: usize = 4;

/// Self-test switch: off records charges but refuses nothing.
pub static ENFORCE: AtomicBool = AtomicBool::new(true);
/// Requests refused since boot.
pub static REFUSED: AtomicU64 = AtomicU64::new(0);

struct Entry {
    counted: [usize; COUNTED],
    peak: usize,
}

static LEDGER: Mutex<BTreeMap<u64, Entry>> = Mutex::new(BTreeMap::new());

/// Canvas bytes of `pid`'s app windows plus buffers of its sockets.
fn computed(pid: u64) -> (usize, usize) {
    (
        crate::gui::app_window::canvas_bytes_of(pid),
        crate::net::iface::sockets_owned_by(pid) * crate::net::iface::SOCKET_HEAP_BYTES,
    )
}

/// Per-kind usage of `pid`: [ipc, launch context, audit, ramfs, windows,
/// sockets]. Call without holding the compositor or socket table locks.
pub fn usage(pid: u64) -> [usize; 6] {
    let counted = x86_64::instructions::interrupts::without_interrupts(|| {
        LEDGER.lock().get(&pid).map(|e| e.counted).unwrap_or([0; COUNTED])
    });
    let (windows, sockets) = computed(pid);
    [counted[0], counted[1], counted[2], counted[3], windows, sockets]
}

pub fn total(pid: u64) -> usize {
    usage(pid).iter().sum()
}

/// Highest total seen for `pid` at a check (self-tests).
pub fn peak(pid: u64) -> usize {
    x86_64::instructions::interrupts::without_interrupts(|| LEDGER.lock().get(&pid).map(|e| e.peak).unwrap_or(0))
}

/// Whether `pid` may make the kernel allocate `bytes` more. Call before the
/// allocation, without holding the compositor, socket table, RamFS or IPC
/// broker locks.
pub fn fits(pid: u64, bytes: usize) -> bool {
    if pid == 0 {
        return true;
    }
    let after = total(pid).saturating_add(bytes);
    let allowed = after <= PROCESS_HEAP_CAP || !ENFORCE.load(Ordering::SeqCst);
    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut ledger = LEDGER.lock();
        let entry = ledger.entry(pid).or_insert(Entry { counted: [0; COUNTED], peak: 0 });
        if allowed {
            entry.peak = entry.peak.max(after);
        }
    });
    if allowed {
        return true;
    }
    REFUSED.fetch_add(1, Ordering::SeqCst);
    crate::serial_println!(
        "[ledger] pid {} refused {} bytes: {} of {} held",
        pid,
        bytes,
        after - bytes,
        PROCESS_HEAP_CAP
    );
    false
}

/// Record `bytes` of `kind` for `pid` (after `fits`). Leaf lock: safe under
/// the RamFS and IPC locks.
pub fn add(pid: u64, kind: Kind, bytes: usize) {
    if pid == 0 || bytes == 0 {
        return;
    }
    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut ledger = LEDGER.lock();
        let entry = ledger.entry(pid).or_insert(Entry { counted: [0; COUNTED], peak: 0 });
        entry.counted[kind as usize] = entry.counted[kind as usize].saturating_add(bytes);
    });
}

/// Release `bytes` of `kind` for `pid`. No-op for a reaped pid.
pub fn sub(pid: u64, kind: Kind, bytes: usize) {
    if pid == 0 || bytes == 0 {
        return;
    }
    x86_64::instructions::interrupts::without_interrupts(|| {
        if let Some(entry) = LEDGER.lock().get_mut(&pid) {
            entry.counted[kind as usize] = entry.counted[kind as usize].saturating_sub(bytes);
        }
    });
}

/// `fits` and `add` in one step.
pub fn charge(pid: u64, kind: Kind, bytes: usize) -> bool {
    if !fits(pid, bytes) {
        return false;
    }
    add(pid, kind, bytes);
    true
}

/// Drop `pid`'s entry (reap).
pub fn release_all(pid: u64) {
    x86_64::instructions::interrupts::without_interrupts(|| {
        LEDGER.lock().remove(&pid);
    });
}

/// The process a RamFS write is charged to: set only around the WriteFile
/// syscalls, so the kernel's own writes (the audit log, configuration the
/// kernel saves while a process is current) are never charged to whichever
/// process happens to be current.
static FS_OWNER: AtomicU64 = AtomicU64::new(0);

pub fn fs_owner() -> u64 {
    FS_OWNER.load(Ordering::SeqCst)
}

/// Run `f` with RamFS writes charged to `pid`.
pub fn with_fs_owner<R>(pid: u64, f: impl FnOnce() -> R) -> R {
    let previous = FS_OWNER.swap(pid, Ordering::SeqCst);
    let result = f();
    FS_OWNER.store(previous, Ordering::SeqCst);
    result
}

/// Whether `pid` has an entry (self-tests).
pub fn has_entry(pid: u64) -> bool {
    x86_64::instructions::interrupts::without_interrupts(|| LEDGER.lock().contains_key(&pid))
}
