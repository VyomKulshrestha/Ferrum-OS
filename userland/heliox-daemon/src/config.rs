// ============================================================================
// Heliox-Daemon - Runtime Configuration
// ============================================================================
// Loads and parses the runtime configuration from the Ext2 filesystem.
// Provides default values if the configuration file is missing or invalid.
// ============================================================================

extern crate alloc;

use alloc::string::String;
use crate::{syscall3, syscall4, SYS_READ_FILE};
use crate::cognitive::json::{self, JsonValue};

const SYS_WRITE: u64 = 34;
const FD_CONSOLE: u64 = 2;

#[derive(Debug, Clone, PartialEq)]
pub enum LogLevel {
    Debug,
    Info,
    Warn,
    Error,
}

impl LogLevel {
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "debug" => Self::Debug,
            "info" => Self::Info,
            "warn" => Self::Warn,
            "error" => Self::Error,
            _ => Self::Info,
        }
    }
}

/// Runtime configuration for the Heliox daemon.
#[derive(Debug, Clone)]
pub struct Config {
    pub provider: String,
    pub model_name: String,
    pub api_host: String,
    pub api_port: u16,
    pub api_path: String,
    pub api_key: String,
    pub max_retries: u32,
    pub tick_interval: u64,
    pub save_interval: u64,
    pub confirmation_timeout: u64,
    pub log_level: LogLevel,
    pub auto_approve_tier: u8,
    pub stt_host: String,
    pub stt_port: u16,
    pub vad_threshold: u32,
}

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

impl Config {
    /// Returns the default configuration.
    pub fn default() -> Self {
        Self {
            provider: String::from("auto"),
            model_name: String::from("llama3"),
            api_host: String::from("unconfigured"),
            api_port: 11434,
            api_path: String::from("/api/generate"),
            api_key: String::new(),
            max_retries: 3,
            tick_interval: 100,
            save_interval: 1000,
            confirmation_timeout: 600,
            log_level: LogLevel::Info,
            auto_approve_tier: 2, // Auto-approve tiers 0, 1, 2
            stt_host: String::from("unconfigured"),
            stt_port: 8786,
            vad_threshold: 500,
        }
    }

    /// Loads the configuration from a JSON file on the VFS.
    /// Falls back to defaults for any missing fields or if the file cannot be read.
    pub fn load(path: &str) -> Self {
        let mut config = Self::default();

        let mut buf = alloc::vec![0u8; 8192];
        let bytes_read = unsafe {
            syscall4(
                SYS_READ_FILE,
                path.as_ptr() as u64,
                path.len() as u64,
                buf.as_mut_ptr() as u64,
                buf.len() as u64,
            )
        };

        let file_existed = (bytes_read as i64) >= 0;
        if file_existed {
            let json_str = core::str::from_utf8(&buf[..bytes_read as usize]).unwrap_or("");
            
            if let Ok(parsed) = json::parse(json_str) {
                if let Some(obj) = parsed.as_object() {
                    for (k, v) in obj {
                        match k.as_str() {
                            "provider" => if let Some(s) = v.as_str() { config.provider = String::from(s); },
                            "model_name" => if let Some(s) = v.as_str() { config.model_name = String::from(s); },
                            "api_host" => if let Some(s) = v.as_str() { config.api_host = String::from(s); },
                            "api_port" => if let Some(n) = v.as_f64() { config.api_port = n as u16; },
                            "api_path" => if let Some(s) = v.as_str() { config.api_path = String::from(s); },
                            "api_key" => if let Some(s) = v.as_str() { config.api_key = String::from(s); },
                            "max_retries" => if let Some(n) = v.as_f64() { config.max_retries = n as u32; },
                            "tick_interval" => if let Some(n) = v.as_f64() { config.tick_interval = n as u64; },
                            "save_interval" => if let Some(n) = v.as_f64() { config.save_interval = n as u64; },
                            "confirmation_timeout" => if let Some(n) = v.as_f64() { config.confirmation_timeout = n as u64; },
                            "log_level" => if let Some(s) = v.as_str() { config.log_level = LogLevel::from_str(s); },
                            "auto_approve_tier" => if let Some(n) = v.as_f64() { config.auto_approve_tier = n as u8; },
                            "stt_host" => if let Some(s) = v.as_str() { config.stt_host = String::from(s); },
                            "stt_port" => if let Some(n) = v.as_f64() { config.stt_port = n as u16; },
                            "vad_threshold" => if let Some(n) = v.as_f64() { config.vad_threshold = n as u32; },
                            _ => {}
                        }
                    }
                }
            }
        }

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
                let msg = "[heliox-daemon] requested local provider but hardware tier can't run it - falling back to cloud\n";
                unsafe {
                    syscall3(SYS_WRITE, FD_CONSOLE, msg.as_ptr() as u64, msg.len() as u64);
                }
            }
            config.provider = resolved;
        }

        config
    }
}
