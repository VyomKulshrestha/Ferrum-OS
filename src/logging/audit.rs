// ============================================================================
// FerrumOS - Audit Trail Logger
// ============================================================================
// Records security-relevant events for post-incident analysis.
// All security violations, capability changes, and system events are logged.
// ============================================================================

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec::Vec;
use spin::Mutex;

/// Categories of audit events
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AuditEvent {
    SystemBoot,
    SystemShutdown,
    SecurityViolation,
    CapabilityGranted,
    CapabilityRevoked,
    ServiceRegistered,
    ServiceStarted,
    ServiceStopped,
    ProcessSpawned,
    ProcessKilled,
    FileAccess,
    UserAudit,
    PermissionDenied,
}

/// A single audit log entry
#[derive(Debug, Clone)]
pub struct AuditEntry {
    pub tick: u64,
    pub event: AuditEvent,
    pub message: String,
    /// Who the entry counts against (fi2 Q6): the pid that wrote it with
    /// AuditWrite, or the task that was running when the kernel logged it.
    pub source: u64,
}

/// Maximum number of audit entries to retain in memory
pub const MAX_ENTRIES: usize = 256;

/// Most entries one source may hold among the entries not yet flushed to
/// disk. A source over its share loses its own oldest unflushed entry.
pub const PER_SOURCE_UNFLUSHED: usize = 64;

use core::sync::atomic::{AtomicBool, AtomicU64, Ordering};

pub static FLUSH_PENDING: AtomicBool = AtomicBool::new(false);

/// fi2 Q6. On (the default): when the ring is full, a writer evicts an
/// already flushed entry or its own oldest entry, never another source's
/// unflushed entry, and each source holds at most PER_SOURCE_UNFLUSHED
/// unflushed entries. Off (the self-test's negative control only): the
/// oldest entry is dropped, whoever wrote it.
pub static SOURCE_QUOTA: AtomicBool = AtomicBool::new(true);

/// Entries dropped from memory before they were flushed.
pub static UNFLUSHED_DROPPED: AtomicU64 = AtomicU64::new(0);

struct AuditLog {
    entries: Vec<AuditEntry>,
    initialized: bool,
    flushed_count: usize,
}

static AUDIT_LOG: Mutex<AuditLog> = Mutex::new(AuditLog {
    entries: Vec::new(),
    initialized: false,
    flushed_count: 0,
});

/// Initialize the audit log
pub fn init() {
    let mut log = AUDIT_LOG.lock();
    log.initialized = true;
}

/// Log an audit event, counted against the task running now.
pub fn log_event(event: AuditEvent, message: &str) {
    log_event_from(crate::scheduler::CURRENT_PID.load(Ordering::SeqCst), event, message);
}

/// Log an audit event counted against `source` (a pid, or the running task).
pub fn log_event_from(source: u64, event: AuditEvent, message: &str) {
    if let Some(mut log) = AUDIT_LOG.try_lock() {
        if !log.initialized {
            return;
        }
        
        // Get current tick count (may fail if scheduler not yet initialized)
        let tick = crate::scheduler::total_ticks();
        
        let entry = AuditEntry {
            tick,
            event,
            message: message.to_string(),
            source,
        };
        insert_entry(&mut log, entry);

        // Also output to serial for external logging
        crate::serial_println!("[AUDIT] {:?}: {}", event, message);
    }
}

/// Removes entry `index`, keeping `flushed_count` the number of flushed
/// entries at the front.
fn remove_entry(log: &mut AuditLog, index: usize) {
    if index < log.flushed_count {
        log.flushed_count -= 1;
    } else {
        UNFLUSHED_DROPPED.fetch_add(1, Ordering::SeqCst);
    }
    log.entries.remove(index);
}

fn insert_entry(log: &mut AuditLog, entry: AuditEntry) {
    let source = entry.source;
    log.entries.push(entry);
    if !SOURCE_QUOTA.load(Ordering::SeqCst) {
        // Before fi2: drop the oldest entries, whoever wrote them.
        if log.entries.len() > MAX_ENTRIES {
            let drain_count = log.entries.len() - MAX_ENTRIES;
            let unflushed_lost = drain_count.saturating_sub(log.flushed_count);
            UNFLUSHED_DROPPED.fetch_add(unflushed_lost as u64, Ordering::SeqCst);
            log.entries.drain(0..drain_count);
            log.flushed_count = log.flushed_count.saturating_sub(drain_count);
        }
        return;
    }
    let oldest_own_unflushed = |log: &AuditLog| {
        (log.flushed_count..log.entries.len()).find(|&i| log.entries[i].source == source)
    };
    // A source over its share of the unflushed entries loses its own oldest.
    let own_unflushed = log.entries[log.flushed_count..]
        .iter()
        .filter(|e| e.source == source)
        .count();
    if own_unflushed > PER_SOURCE_UNFLUSHED {
        if let Some(index) = oldest_own_unflushed(log) {
            remove_entry(log, index);
        }
    }
    // Over capacity: drop a flushed entry if there is one, otherwise the
    // writer's own oldest unflushed entry (at worst the one just written).
    while log.entries.len() > MAX_ENTRIES {
        if log.flushed_count > 0 {
            remove_entry(log, 0);
        } else if let Some(index) = oldest_own_unflushed(log) {
            remove_entry(log, index);
        } else {
            break;
        }
    }
}

/// Entries in memory from `source` that are not yet flushed (self-tests).
pub fn unflushed_from(source: u64) -> usize {
    let log = AUDIT_LOG.lock();
    log.entries[log.flushed_count..]
        .iter()
        .filter(|e| e.source == source)
        .count()
}

/// Whether an entry from `source` with exactly `message` is in memory.
pub fn holds(source: u64, message: &str) -> bool {
    AUDIT_LOG
        .lock()
        .entries
        .iter()
        .any(|e| e.source == source && e.message == message)
}

/// Get the most recent N audit entries
pub fn recent_entries(count: usize) -> Vec<AuditEntry> {
    let log = AUDIT_LOG.lock();
    let start = if log.entries.len() > count {
        log.entries.len() - count
    } else {
        0
    };
    log.entries[start..].to_vec()
}

/// Get total number of audit entries
pub fn total_entries() -> usize {
    AUDIT_LOG.lock().entries.len()
}

/// Flush memory audit log to /disk/heliox/audit.log
pub fn flush_to_disk() -> Result<(), String> {
    let mut new_entries = Vec::new();
    {
        if let Some(mut log) = AUDIT_LOG.try_lock() {
            if !log.initialized {
                return Ok(());
            }
            let total = log.entries.len();
            if log.flushed_count < total {
                new_entries = log.entries[log.flushed_count..total].to_vec();
                log.flushed_count = total;
            }
        } else {
            return Ok(());
        }
    }

    if new_entries.is_empty() {
        return Ok(());
    }

    let log_path = "/disk/heliox/audit.log";
    let mut content = match crate::fs::read_file(log_path) {
        Ok(c) => c,
        Err(_) => String::new(),
    };

    for entry in new_entries {
        let line = alloc::format!("[{}] {:?}: {}\n", entry.tick, entry.event, entry.message);
        content.push_str(&line);
    }

    const MAX_SIZE: usize = 128 * 1024;
    if content.len() > MAX_SIZE {
        let overflow = content.len() - MAX_SIZE;
        if let Some(pos) = content[overflow..].find('\n') {
            content = content[overflow + pos + 1..].to_string();
        } else {
            content = content[content.len() - MAX_SIZE..].to_string();
        }
    }

    crate::fs::create_file(log_path, &content)?;
    let _ = crate::fs::sync();

    Ok(())
}
