// ============================================================================
// Heliox-Daemon - Runtime Configuration
// ============================================================================
// Reads the runtime configuration from the filesystem. The parsing and its
// fail-closed rules live in `config_parse.rs` (host-tested): no file gives
// the defaults; a file that exists and cannot be used gives auto_approve_tier
// 0 and one console message (fi2 Q3).
// ============================================================================

extern crate alloc;

use alloc::string::String;
use crate::{syscall3, syscall4, SYS_READ_FILE};

pub use crate::config_parse::{Config, LoadOutcome, LogLevel};

const SYS_WRITE: u64 = 34;
const FD_CONSOLE: u64 = 2;

/// Created only by the kernel shell (no ring-3 process can write under
/// `/tmp/heliox-hooks`, fi2 Q4). While it exists, a configured
/// `auto_approve_tier` of 4 is kept; otherwise it is clamped to 3.
pub const TIER_4_UNLOCK: &str = "/tmp/heliox-hooks/allow_auto_approve_tier_4";

/// Size of the buffer the configuration is read into.
pub const CONFIG_READ_BUFFER: usize = 8192;

fn detect_tier() -> String {
    let mut buf = [0u8; 512];
    let bytes_written = unsafe {
        crate::syscall4(
            29, // SYS_SYSTEM_QUERY
            0,  // query_type = system_info
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
            0,
        )
    };
    if bytes_written > 0 && (bytes_written as usize) <= buf.len() {
        if let Ok(text) = core::str::from_utf8(&buf[..bytes_written as usize]) {
            if let Some(idx) = text.find("\"tier\":") {
                let rest = &text[idx + "\"tier\":".len()..];
                // Find start quote of the string value
                if let Some(start_q) = rest.find('"') {
                    let val_rest = &rest[start_q + 1..];
                    if let Some(end_q) = val_rest.find('"') {
                        return String::from(&val_rest[..end_q]);
                    }
                }
            }
        }
    }
    String::from("low")
}

fn file_exists(path: &str) -> bool {
    let mut byte = [0u8; 1];
    let read = unsafe {
        syscall4(
            SYS_READ_FILE,
            path.as_ptr() as u64,
            path.len() as u64,
            byte.as_mut_ptr() as u64,
            byte.len() as u64,
        )
    };
    (read as i64) >= 0
}

fn console(message: &str) {
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, message.as_ptr() as u64, message.len() as u64);
    }
}

impl Config {
    /// Loads the configuration without printing anything about its outcome
    /// (for callers that only need a field, such as `record_audio`).
    pub fn load(path: &str) -> Self {
        Self::load_with_outcome(path).0
    }

    /// Loads the configuration; when the file exists and cannot be used, or
    /// the test unlock keeps tier 4, says so on the console once per load.
    pub fn load_reporting(path: &str) -> Self {
        let (config, outcome) = Self::load_with_outcome(path);
        match outcome {
            LoadOutcome::Rejected(why) => console(&alloc::format!(
                "[heliox-daemon] {} exists but cannot be used ({}): running with auto_approve_tier 0 until it is fixed\n",
                path, why
            )),
            _ if config.auto_approve_tier >= 4 => console(
                "[heliox-daemon] WARNING: test unlock present, auto_approve_tier 4 approves every tool without asking\n",
            ),
            _ => {}
        }
        config
    }

    pub fn load_with_outcome(path: &str) -> (Self, LoadOutcome) {
        let mut buf = alloc::vec![0u8; CONFIG_READ_BUFFER];
        let bytes_read = unsafe {
            syscall4(
                SYS_READ_FILE,
                path.as_ptr() as u64,
                path.len() as u64,
                buf.as_mut_ptr() as u64,
                buf.len() as u64,
            )
        };
        let read = if (bytes_read as i64) >= 0 {
            Some(&buf[..(bytes_read as usize).min(buf.len())])
        } else {
            None
        };
        let file_existed = read.is_some();
        let (mut config, outcome) = Config::parse(read, CONFIG_READ_BUFFER, file_exists(TIER_4_UNLOCK));

        // Post-load provider resolution. "auto" picks local-vs-cloud based on
        // hardware tier with no user say in it; "local" is an explicit user
        // choice to always prefer on-device inference (the setup wizard
        // offers both, see src/gui/compositor.rs). Both resolve to the same
        // tier-appropriate local model where one exists - "local" gracefully
        // falls back to cloud only on low-tier hardware that genuinely can't
        // run either local checkpoint (README's tier table), so the user's
        // choice is honored everywhere the hardware allows it.
        //
        // Gated on `file_existed`: a config.json that doesn't exist yet
        // means setup has never run, not that the user chose "auto". If
        // this resolved to a tier-appropriate local model regardless, the
        // daemon would start real autonomous inference on every boot before
        // the user ever completes the wizard (`tick()`'s idle-until-
        // configured check only skips ticking for a provider that doesn't
        // start with "local", so an unresolved "auto" default correctly
        // keeps it idle - a resolved "local-15M" default did not). Once a
        // config.json exists - including one a tool or user wrote with
        // `"provider": "auto"` explicitly - it resolves exactly as before.
        if file_existed && (config.provider == "auto" || config.provider == "local") {
            let tier = detect_tier();
            let resolved = match tier.as_str() {
                "high" => String::from("local-1.1B"),
                "standard" => String::from("local-15M"),
                _ => String::from("cloud"),
            };
            if config.provider == "local" && resolved == "cloud" {
                console("[heliox-daemon] requested local provider but hardware tier can't run it - falling back to cloud\n");
            }
            config.provider = resolved;
        }

        (config, outcome)
    }
}
