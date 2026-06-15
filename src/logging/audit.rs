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
    PermissionDenied,
}

/// A single audit log entry
#[derive(Debug, Clone)]
pub struct AuditEntry {
    pub tick: u64,
    pub event: AuditEvent,
    pub message: String,
}

/// Maximum number of audit entries to retain in memory
const MAX_ENTRIES: usize = 256;

use core::sync::atomic::AtomicBool;

pub static FLUSH_PENDING: AtomicBool = AtomicBool::new(false);

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

/// Log an audit event
pub fn log_event(event: AuditEvent, message: &str) {
    if let Some(mut log) = AUDIT_LOG.try_lock() {
        if !log.initialized {
            return;
        }
        
        // Get current tick count (may fail if scheduler not yet initialized)
        let tick = crate::scheduler::total_ticks();
        
        log.entries.push(AuditEntry {
            tick,
            event,
            message: message.to_string(),
        });
        
        // Trim old entries if over capacity
        if log.entries.len() > MAX_ENTRIES {
            let drain_count = log.entries.len() - MAX_ENTRIES;
            log.entries.drain(0..drain_count);
            log.flushed_count = log.flushed_count.saturating_sub(drain_count);
        }
        
        // Also output to serial for external logging
        crate::serial_println!("[AUDIT] {:?}: {}", event, message);
    }
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
