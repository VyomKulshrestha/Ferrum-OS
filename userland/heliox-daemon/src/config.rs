// ============================================================================
// Heliox-Daemon - Runtime Configuration
// ============================================================================
// Loads and parses the runtime configuration from the Ext2 filesystem.
// Provides default values if the configuration file is missing or invalid.
// ============================================================================

extern crate alloc;

use alloc::string::String;
use crate::{syscall4, SYS_READ_FILE};
use crate::cognitive::json::{self, JsonValue};

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
    pub model_name: String,
    pub api_host: String,
    pub api_port: u16,
    pub api_path: String,
    pub max_retries: u32,
    pub tick_interval: u64,
    pub save_interval: u64,
    pub confirmation_timeout: u64,
    pub log_level: LogLevel,
    pub auto_approve_tier: u8,
}

impl Config {
    /// Returns the default configuration.
    pub fn default() -> Self {
        Self {
            model_name: String::from("llama3"),
            api_host: String::from("10.0.2.2"),
            api_port: 11434,
            api_path: String::from("/api/generate"),
            max_retries: 3,
            tick_interval: 100,
            save_interval: 1000,
            confirmation_timeout: 600,
            log_level: LogLevel::Info,
            auto_approve_tier: 2, // Auto-approve tiers 0, 1, 2
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

        if (bytes_read as i64) < 0 {
            // Failed to read file, return defaults
            return config;
        }

        let json_str = core::str::from_utf8(&buf[..bytes_read as usize]).unwrap_or("");
        
        if let Ok(parsed) = json::parse(json_str) {
            if let Some(obj) = parsed.as_object() {
                for (k, v) in obj {
                    match k.as_str() {
                        "model_name" => if let Some(s) = v.as_str() { config.model_name = String::from(s); },
                        "api_host" => if let Some(s) = v.as_str() { config.api_host = String::from(s); },
                        "api_port" => if let Some(n) = v.as_f64() { config.api_port = n as u16; },
                        "api_path" => if let Some(s) = v.as_str() { config.api_path = String::from(s); },
                        "max_retries" => if let Some(n) = v.as_f64() { config.max_retries = n as u32; },
                        "tick_interval" => if let Some(n) = v.as_f64() { config.tick_interval = n as u64; },
                        "save_interval" => if let Some(n) = v.as_f64() { config.save_interval = n as u64; },
                        "confirmation_timeout" => if let Some(n) = v.as_f64() { config.confirmation_timeout = n as u64; },
                        "log_level" => if let Some(s) = v.as_str() { config.log_level = LogLevel::from_str(s); },
                        "auto_approve_tier" => if let Some(n) = v.as_f64() { config.auto_approve_tier = n as u8; },
                        _ => {}
                    }
                }
            }
        }

        config
    }
}
