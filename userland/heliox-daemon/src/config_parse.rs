// ============================================================================
// Heliox-Daemon - Configuration parsing (pure, host-tested)
// ============================================================================
// Turns the bytes of /disk/heliox/config.json into a Config. No syscalls, so
// userland/heliox-gate-tests compiles this file and tests every outcome.
//
// Fail-closed rules (fi2 Q3, Q5):
//   - no file: defaults (first-run setup has not happened yet);
//   - a file that exists but cannot be used (larger than the read buffer,
//     not UTF-8, not JSON, not an object): defaults with auto_approve_tier 0,
//     and the caller prints one console message saying so;
//   - auto_approve_tier is clamped to 0..=3, so tier 4 always asks, unless
//     the kernel shell created the test unlock (see `parse`);
//   - tick_interval and save_interval are at least 1 (the orchestrator
//     divides by them).
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;

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
    /// Extra hosts network tools may reach without approval (fi2 Q1). The
    /// provider (`api_host`) and speech (`stt_host`) hosts are always on it.
    pub network_allowlist: Vec<String>,
}

/// How the configuration file was read.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoadOutcome {
    /// No file: defaults.
    Missing,
    /// The file was used.
    Loaded,
    /// The file exists and could not be used; defaults with
    /// auto_approve_tier 0. The text says why, for the console.
    Rejected(&'static str),
}

/// Most hosts `network_allowlist` may name; further entries are ignored.
pub const MAX_ALLOWLIST_HOSTS: usize = 32;

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
            network_allowlist: Vec::new(),
        }
    }

    /// The hosts network tools may reach without approval: the provider and
    /// speech hosts (when configured) and `network_allowlist`.
    pub fn network_hosts(&self) -> Vec<String> {
        let mut hosts = Vec::new();
        for host in [&self.api_host, &self.stt_host] {
            if !host.is_empty() && host.as_str() != "unconfigured" {
                hosts.push(host.clone());
            }
        }
        for host in &self.network_allowlist {
            if !host.trim().is_empty() {
                hosts.push(String::from(host.trim()));
            }
        }
        hosts
    }

    /// Builds the configuration from what reading the file returned.
    /// `read`: `None` when there is no file, otherwise the bytes read into a
    /// buffer of `buffer_len` bytes (a read that fills the buffer may be cut
    /// short and is rejected). `allow_tier_4`: the kernel shell created the
    /// test unlock (`/tmp/heliox-hooks/allow_auto_approve_tier_4`, a path no
    /// ring-3 process can write), so a configured tier of 4 is kept for the
    /// QEMU harnesses and the world-model collection tooling.
    pub fn parse(read: Option<&[u8]>, buffer_len: usize, allow_tier_4: bool) -> (Self, LoadOutcome) {
        let mut config = Self::default();
        let Some(bytes) = read else {
            return (config, LoadOutcome::Missing);
        };
        let rejected = |why: &'static str| {
            let mut fallback = Self::default();
            fallback.auto_approve_tier = 0;
            (fallback, LoadOutcome::Rejected(why))
        };
        if bytes.len() >= buffer_len {
            return rejected("larger than the read buffer");
        }
        let Ok(text) = core::str::from_utf8(bytes) else {
            return rejected("not UTF-8");
        };
        let Ok(parsed) = json::parse(text) else {
            return rejected("not valid JSON");
        };
        let Some(obj) = parsed.as_object() else {
            return rejected("not a JSON object");
        };
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
                "auto_approve_tier" => if let Some(n) = v.as_f64() {
                    config.auto_approve_tier = if allow_tier_4 && n >= 4.0 {
                        4
                    } else {
                        crate::cognitive::authority::clamp_auto_approve_tier(n)
                    };
                },
                "stt_host" => if let Some(s) = v.as_str() { config.stt_host = String::from(s); },
                "stt_port" => if let Some(n) = v.as_f64() { config.stt_port = n as u16; },
                "vad_threshold" => if let Some(n) = v.as_f64() { config.vad_threshold = n as u32; },
                "network_allowlist" => {
                    if let JsonValue::Array(items) = v {
                        config.network_allowlist = items
                            .iter()
                            .filter_map(|item| item.as_str())
                            .take(MAX_ALLOWLIST_HOSTS)
                            .map(String::from)
                            .collect();
                    }
                }
                _ => {}
            }
        }
        // Both divide the orchestrator's tick count.
        config.tick_interval = config.tick_interval.max(1);
        config.save_interval = config.save_interval.max(1);
        (config, LoadOutcome::Loaded)
    }
}
