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

struct AuditLog {
    entries: Vec<AuditEntry>,
    initialized: bool,
}

static AUDIT_LOG: Mutex<AuditLog> = Mutex::new(AuditLog {
    entries: Vec::new(),
    initialized: false,
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
