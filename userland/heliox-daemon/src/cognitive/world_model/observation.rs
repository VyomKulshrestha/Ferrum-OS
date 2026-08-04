// ============================================================================
// Heliox World Model - Layer 1: Observation Collector
// ============================================================================
// Samples a snapshot of live OS state through syscalls the daemon already
// calls elsewhere - SystemQuery (29, query types 0/2) for process/heap
// stats exactly as config.rs's detect_tier() and tool_mapper.rs's
// execute_system_info() already call it, persistent filesystem usage through
// SystemQuery type 4, ReadDir (17) for the observable file count, and
// screen_vision::capture_screen() (which itself wraps ReadTextBuffer, 20).
// ============================================================================

extern crate alloc;

use alloc::string::String;
use crate::{syscall4, SYS_READ_DIR};

const SYS_SYSTEM_QUERY: u64 = 29;

#[derive(Debug, Clone)]
pub struct OsSnapshot {
    pub tick: u64,
    pub proc_count: u32,
    pub heap_used: u64,
    pub heap_total: u64,
    pub fs_file_count: u32,
    /// Fraction of allocated blocks on the persistent filesystem. Falls back
    /// to zero when no persistent mount is available; it never substitutes a
    /// file-count heuristic for real capacity telemetry.
    pub disk_usage_fraction: f32,
    pub screen_text: String,
    pub last_action_name: String,
    pub last_action_failed: bool,
}

/// Tiny substring-based extractor for a `"key":<number>` field in a flat
/// JSON blob - no real JSON parser needed for reading back the daemon's
/// own SystemQuery output (matches config.rs's detect_tier() and
/// userland/settings's extract_field() precedent for pragmatic scoping).
fn extract_u64(text: &str, key: &str) -> Option<u64> {
    let needle = alloc::format!("\"{}\":", key);
    let idx = text.find(&needle)?;
    let rest = &text[idx + needle.len()..];
    let end = rest.find(|c: char| !c.is_ascii_digit()).unwrap_or(rest.len());
    rest[..end].parse::<u64>().ok()
}

fn query_active_tasks() -> u32 {
    let mut buf = [0u8; 512];
    let n = unsafe { syscall4(SYS_SYSTEM_QUERY, 0, buf.as_mut_ptr() as u64, buf.len() as u64, 0) };
    if n <= 0 {
        return 0;
    }
    let text = core::str::from_utf8(&buf[..n as usize]).unwrap_or("{}");
    extract_u64(text, "active_tasks").unwrap_or(0) as u32
}

fn query_heap() -> (u64, u64) {
    let mut buf = [0u8; 256];
    let n = unsafe { syscall4(SYS_SYSTEM_QUERY, 2, buf.as_mut_ptr() as u64, buf.len() as u64, 0) };
    if n <= 0 {
        return (0, 1);
    }
    let text = core::str::from_utf8(&buf[..n as usize]).unwrap_or("{}");
    let used = extract_u64(text, "heap_used").unwrap_or(0);
    let total = extract_u64(text, "heap_total").unwrap_or(1).max(1);
    (used, total)
}

fn query_disk_usage_fraction() -> f32 {
    let mut buf = [0u8; 256];
    let n = unsafe { syscall4(SYS_SYSTEM_QUERY, 4, buf.as_mut_ptr() as u64, buf.len() as u64, 0) };
    if n <= 0 {
        return 0.0;
    }
    let text = core::str::from_utf8(&buf[..n as usize]).unwrap_or("{}");
    let used = extract_u64(text, "used_bytes").unwrap_or(0);
    let total = extract_u64(text, "total_bytes").unwrap_or(0);
    if total == 0 {
        0.0
    } else {
        (used as f32 / total as f32).clamp(0.0, 1.0)
    }
}

fn query_fs_file_count(path: &str) -> u32 {
    let mut buf = alloc::vec![0u8; 8 * 1024];
    let n = unsafe {
        syscall4(
            SYS_READ_DIR,
            path.as_ptr() as u64,
            path.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    if n <= 0 {
        return 0;
    }
    let text = core::str::from_utf8(&buf[..n as usize]).unwrap_or("");
    // sys_read_dir's output format is "<f|d> <name>\n" per entry
    // (src/syscall/fs.rs's sys_read_dir) - count files, not directories.
    text.lines().filter(|l| l.starts_with("f ")).count() as u32
}

pub fn capture_snapshot(tick: u64, last_action_name: &str, last_action_failed: bool) -> OsSnapshot {
    let proc_count = query_active_tasks();
    let (heap_used, heap_total) = query_heap();
    let fs_file_count = query_fs_file_count("/disk");
    let screen_text = crate::cognitive::screen_vision::capture_screen()
        .map(|c| c.full_text())
        .unwrap_or_default();

    OsSnapshot {
        tick,
        proc_count,
        heap_used,
        heap_total,
        fs_file_count,
        disk_usage_fraction: query_disk_usage_fraction(),
        screen_text,
        last_action_name: String::from(last_action_name),
        last_action_failed,
    }
}
