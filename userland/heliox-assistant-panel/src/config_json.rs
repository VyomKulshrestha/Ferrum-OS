// ============================================================================
// Heliox Assistant Panel - the configuration its setup wizard writes
// ============================================================================
// Pure (no syscalls), so userland/heliox-gate-tests compiles this file and
// tests it on the host. Every string the operator typed is escaped as a JSON
// string, so an API key or host containing `"` cannot add or change a field
// such as `auto_approve_tier` (fi2 Q5, round 2's H1).
// ============================================================================

use alloc::format;
use alloc::string::String;

/// `value` as the inside of a JSON string: `"` and `\` escaped, control
/// characters as `\u00XX`.
pub fn json_escape(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 || c as u32 == 0x7f => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

/// The text of config.json for the wizard's choices.
pub fn setup_config_json(provider: &str, host: &str, port: u16, api_key: &str, model_name: &str) -> String {
    format!(
        r#"{{ "provider": "{}", "api_host": "{}", "api_port": {}, "api_key": "{}", "model_name": "{}" }}"#,
        json_escape(provider),
        json_escape(host),
        port,
        json_escape(api_key),
        json_escape(model_name)
    )
}
