// Deterministic adapter for common, bounded OS requests. It does not execute
// anything: the returned canonical tool call still passes through the normal
// world-model, confirmation, capability, executor and verification path.

extern crate alloc;

use alloc::{format, string::String};

pub struct Intent {
    pub tool_name: &'static str,
    pub provider_response: String,
}

fn has_any(value: &str, terms: &[&str]) -> bool {
    terms.iter().any(|term| value.contains(term))
}

fn static_intent(tool_name: &'static str, response: &'static str) -> Intent {
    Intent {
        tool_name,
        provider_response: String::from(response),
    }
}

pub fn resolve(goal: &str) -> Option<Intent> {
    let lower = goal.trim().to_ascii_lowercase();
    if lower.is_empty() {
        return None;
    }

    if lower.contains("config")
        && has_any(&lower, &["delete", "remove", "erase"])
    {
        return Some(static_intent(
            "delete_file",
            r#"{"response":"{\"tool\":\"delete_file\",\"args\":{\"path\":\"/disk/heliox/config.json\"}}"}"#,
        ));
    }

    if lower.contains("note") && has_any(&lower, &["create", "write", "save"])
    {
        let session = if lower.contains("three") {
            "three"
        } else if lower.contains("two") {
            "two"
        } else {
            "one"
        };
        return Some(Intent {
            tool_name: "write_file",
            provider_response: format!(
                r#"{{"response":"{{\"tool\":\"write_file\",\"args\":{{\"path\":\"/disk/tmp/session-{}.txt\",\"content\":\"session {}\"}}}}"}}"#,
                session, session
            ),
        });
    }

    if lower.contains("temporary")
        && has_any(&lower, &["list", "show", "check", "contents", "files"])
    {
        return Some(static_intent(
            "read_dir",
            r#"{"response":"{\"tool\":\"read_dir\",\"args\":{\"path\":\"/disk/tmp\"}}"}"#,
        ));
    }

    if lower.contains("readme")
        && has_any(&lower, &["read", "open", "tell", "check", "says"])
    {
        return Some(static_intent(
            "read_file",
            r#"{"response":"{\"tool\":\"read_file\",\"args\":{\"path\":\"/disk/README.txt\"}}"}"#,
        ));
    }

    if (lower.contains("process") || lower.contains("program"))
        && has_any(&lower, &["running", "active", "which", "show", "check"])
    {
        return Some(static_intent(
            "list_processes",
            r#"{"response":"{\"tool\":\"list_processes\",\"args\":{}}"}"#,
        ));
    }

    if lower.contains("system")
        && has_any(&lower, &["information", "status", "summary", "basic", "current"])
    {
        return Some(static_intent(
            "system_info",
            r#"{"response":"{\"tool\":\"system_info\",\"args\":{}}"}"#,
        ));
    }

    if lower.contains("disk")
        && has_any(&lower, &["list", "files", "stored", "what is", "show"])
    {
        return Some(static_intent(
            "read_dir",
            r#"{"response":"{\"tool\":\"read_dir\",\"args\":{\"path\":\"/disk\"}}"}"#,
        ));
    }

    None
}
