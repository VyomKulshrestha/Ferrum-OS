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
        
        let message = escape_controls(message);
        // Also output to serial for external logging
        crate::serial_println!("[AUDIT] {:?}: {}", event, message);

        let entry = AuditEntry {
            tick,
            event,
            message,
            source,
        };
        insert_entry(&mut log, entry);
    }
}

/// `message` with every control character (C0, DEL, C1) and backslash
/// written as `\xNN` (`\u{NNNN}` above 0xFF). Messages carry text a process
/// chose: a path in a denied write, AuditWrite's text. A line break in one
/// wrote a second, forged line into the `[AUDIT]` serial output and into
/// audit.log, whose lines are `[tick] Event: message` (fi2 kernel audit).
pub fn escape_controls(message: &str) -> String {
    let mut out = String::with_capacity(message.len());
    for ch in message.chars() {
        if ch.is_control() || ch == '\\' {
            let code = ch as u32;
            if code <= 0xFF {
                out.push_str(&alloc::format!("\\x{:02x}", code));
            } else {
                out.push_str(&alloc::format!("\\u{{{:04x}}}", code));
            }
        } else {
            out.push(ch);
        }
    }
    out
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

    let override_path = FLUSH_PATH_OVERRIDE.lock().clone();
    let log_path = override_path.as_deref().unwrap_or(AUDIT_LOG_PATH);
    let mut content = match crate::fs::read_file(log_path) {
        Ok(c) => c,
        Err(_) => String::new(),
    };

    for entry in new_entries {
        let line = alloc::format!("[{}] {:?}: {}\n", entry.tick, entry.event, entry.message);
        content.push_str(&line);
    }

    const MAX_SIZE: usize = 128 * 1024;
    let content = trim_log(content, MAX_SIZE);

    // The entries above already count as flushed. The filesystem can refuse
    // the file (the ext2 driver writes 12 direct blocks, 12 to 48 KiB, under
    // the 128 KiB cap): every later flush then failed the same way and every
    // later entry was lost (fi2 kernel audit). Keep the newest lines that fit.
    if let Err(first) = crate::fs::create_file(log_path, &content) {
        let mut keep = content.len();
        loop {
            keep /= 2;
            if keep < 1024 {
                FLUSH_FAILURES.fetch_add(1, Ordering::SeqCst);
                crate::serial_println!("[AUDIT] flush failed: {}", escape_controls(&first));
                return Err(first);
            }
            let tail = trim_log(content.clone(), keep);
            if crate::fs::create_file(log_path, &tail).is_ok() {
                FLUSH_TRIMMED.fetch_add(1, Ordering::SeqCst);
                break;
            }
        }
    }
    let _ = crate::fs::sync();

    Ok(())
}

/// The newest whole lines of `content` within `max` bytes (a cut inside a
/// line drops that line). The cut used to be a byte offset into the
/// string: one that fell inside a multi-byte character stopped the kernel,
/// and any process can put such characters into the log through the path
/// of a denied write (fi2 kernel audit).
pub fn trim_log(content: String, max: usize) -> String {
    if content.len() <= max {
        return content;
    }
    let cut = content.len() - max;
    let bytes = content.as_bytes();
    let start = match bytes[cut..].iter().position(|&b| b == b'\n') {
        Some(pos) => cut + pos + 1,
        None => (cut..=content.len()).find(|&i| content.is_char_boundary(i)).unwrap_or(content.len()),
    };
    content[start..].to_string()
}

/// Where the audit log is flushed.
pub const AUDIT_LOG_PATH: &str = "/disk/heliox/audit.log";

/// Flushes go here instead while set (self-test `audit-flush` only).
pub static FLUSH_PATH_OVERRIDE: Mutex<Option<String>> = Mutex::new(None);

/// Flushes whose file the filesystem refused and that kept a shorter tail.
pub static FLUSH_TRIMMED: AtomicU64 = AtomicU64::new(0);

/// Flushes that could not write even a 1 KiB tail.
pub static FLUSH_FAILURES: AtomicU64 = AtomicU64::new(0);
