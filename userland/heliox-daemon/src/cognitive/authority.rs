// ============================================================================
// Heliox-Daemon - Authority policy (pure decision logic)
// ============================================================================
// The deterministic part of the agent's authority gate, kept free of
// syscalls so it can be tested exhaustively on the host
// (userland/heliox-gate-tests). Everything here fails closed:
//
//   - tool_tier: the 5-tier permission table; unknown names are Destructive.
//   - validate_tool_call: structural refusals that no approval can lift
//     (duplicate argument keys, malformed tool names, control messages to
//     the daemon's own mailbox, writes to the daemon's own configuration).
//   - approval_fingerprint: the exact, complete identity an operator
//     approval is bound to. Two calls share an approval only if every
//     argument is identical.
//   - approval_display: what the operator is shown. Model-controlled text is
//     escaped so it cannot forge lines, and truncation is always marked.
//   - parse_control_message: one command per IPC message.
// ============================================================================

use alloc::format;
use alloc::string::String;

use super::json::JsonValue;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum PermissionTier {
    Observe = 0,
    Safe = 1,
    Network = 2,
    Modify = 3,
    Destructive = 4,
}

/// Every tool the daemon can execute, with its tier. `tool_tier` is defined
/// by this table so the decision table can be enumerated in tests.
pub const TOOL_TIERS: &[(&str, PermissionTier)] = &[
    // Tier 0: Observe
    ("query_memory", PermissionTier::Observe),
    ("get_config", PermissionTier::Observe),
    ("system_info", PermissionTier::Observe),
    ("list_processes", PermissionTier::Observe),
    ("add_subtask", PermissionTier::Observe),
    ("camera_capture", PermissionTier::Observe),
    ("gesture_status", PermissionTier::Observe),
    ("hud_update", PermissionTier::Observe),
    ("hit_test", PermissionTier::Observe),
    ("physical_status", PermissionTier::Observe),
    // Tier 1: Safe
    ("ipc_send", PermissionTier::Safe),
    ("audit_write", PermissionTier::Safe),
    ("yield_cpu", PermissionTier::Safe),
    ("report_status", PermissionTier::Safe),
    ("capability_check", PermissionTier::Safe),
    ("read_file", PermissionTier::Safe),
    ("read_dir", PermissionTier::Safe),
    ("sleep", PermissionTier::Safe),
    ("read_screen", PermissionTier::Safe),
    ("set_volume", PermissionTier::Safe),
    ("poll_input", PermissionTier::Safe),
    ("local_inference", PermissionTier::Safe),
    // Tier 2: Network
    ("net_connect", PermissionTier::Network),
    ("net_send", PermissionTier::Network),
    ("net_recv", PermissionTier::Network),
    ("http_get", PermissionTier::Network),
    ("load_memory", PermissionTier::Network),
    ("set_goal", PermissionTier::Network),
    ("record_audio", PermissionTier::Network),
    ("browse_url", PermissionTier::Network),
    // Tier 3: Modify
    ("write_file", PermissionTier::Modify),
    ("create_directory", PermissionTier::Modify),
    ("save_memory", PermissionTier::Modify),
    ("service_start", PermissionTier::Modify),
    ("service_stop", PermissionTier::Modify),
    ("play_audio", PermissionTier::Modify),
    ("keyboard_type", PermissionTier::Modify),
    ("mouse_click", PermissionTier::Modify),
    ("mouse_move", PermissionTier::Modify),
    // Simulator-only, but it runs a work order end to end: the model's own
    // `confirm_simulation` flag is not an operator approval.
    ("physical_maintenance_demo", PermissionTier::Modify),
    // Tier 4: Destructive
    ("exec_process", PermissionTier::Destructive),
    ("delete_file", PermissionTier::Destructive),
    ("trigger_kernel_upgrade", PermissionTier::Destructive),
];

pub fn tool_tier(name: &str) -> PermissionTier {
    TOOL_TIERS
        .iter()
        .find(|(tool, _)| *tool == name)
        .map(|(_, tier)| *tier)
        // Unknown tools default to the highest tier.
        .unwrap_or(PermissionTier::Destructive)
}

/// A tool needs operator confirmation when its tier is above the configured
/// auto-approve tier.
pub fn needs_confirmation(tier: PermissionTier, auto_approve_tier: u8) -> bool {
    (tier as u8) > auto_approve_tier
}

/// Mailboxes the kernel resolves to the daemon itself
/// (`src/ipc/mod.rs::service_owner_pid`). A message there is read by
/// `Orchestrator::ipc_poll` as an operator control command.
pub const DAEMON_OWNED_SERVICES: &[&str] = &["heliox", "heliox-daemon"];

/// The daemon's own configuration. It sets `auto_approve_tier`, so the agent
/// writing it would be the agent granting itself authority.
const OWN_CONFIG_COMPONENTS: [&str; 3] = ["disk", "heliox", "config.json"];

pub const MAX_TOOL_NAME_BYTES: usize = 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Refusal {
    MalformedToolName,
    DuplicateArgument,
    ControlMessageToOwnMailbox,
    WritesOwnConfiguration,
}

impl Refusal {
    pub fn as_str(self) -> &'static str {
        match self {
            Refusal::MalformedToolName => "malformed tool name",
            Refusal::DuplicateArgument => "duplicate argument key (ambiguous call)",
            Refusal::ControlMessageToOwnMailbox => {
                "the agent may not send messages to its own control mailbox"
            }
            Refusal::WritesOwnConfiguration => {
                "the agent may not modify its own authority configuration"
            }
        }
    }
}

fn find_str<'a>(args: &'a [(String, JsonValue)], key: &str) -> Option<&'a str> {
    args.iter()
        .find(|(k, _)| k == key)
        .and_then(|(_, v)| match v {
            JsonValue::Str(s) => Some(s.as_str()),
            _ => None,
        })
}

/// Lexically normalizes an absolute path the way the world model's
/// protected-path check does (`.` and empty components dropped, `..` pops).
fn path_components(path: &str) -> alloc::vec::Vec<&str> {
    let mut components = alloc::vec::Vec::new();
    for component in path.trim().split('/') {
        match component {
            "" | "." => {}
            ".." => {
                components.pop();
            }
            value => components.push(value),
        }
    }
    components
}

pub fn targets_own_config(path: &str) -> bool {
    let components = path_components(path);
    components.len() == OWN_CONFIG_COMPONENTS.len()
        && components
            .iter()
            .zip(OWN_CONFIG_COMPONENTS.iter())
            .all(|(have, want)| have.eq_ignore_ascii_case(want))
}

pub fn is_daemon_owned_service(service: &str) -> bool {
    let normalized = service.trim();
    DAEMON_OWNED_SERVICES
        .iter()
        .any(|owned| normalized.eq_ignore_ascii_case(owned))
}

/// Structural checks applied to every tool call before prediction,
/// confirmation or execution. A refusal here cannot be approved.
pub fn validate_tool_call(name: &str, args: &[(String, JsonValue)]) -> Result<(), Refusal> {
    if name.is_empty()
        || name.len() > MAX_TOOL_NAME_BYTES
        || !name.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
    {
        return Err(Refusal::MalformedToolName);
    }
    for (index, (key, _)) in args.iter().enumerate() {
        if args[..index].iter().any(|(earlier, _)| earlier == key) {
            return Err(Refusal::DuplicateArgument);
        }
    }
    match name {
        "ipc_send" => {
            if let Some(target) = find_str(args, "target_service") {
                if is_daemon_owned_service(target) {
                    return Err(Refusal::ControlMessageToOwnMailbox);
                }
            }
        }
        // delete_file of the config is blocked deterministically by the world
        // model's protected-path rule (transition.rs::deletes_own_config),
        // which the QEMU harnesses exercise; it is not duplicated here.
        "write_file" | "create_directory" => {
            if let Some(path) = find_str(args, "path") {
                if targets_own_config(path) {
                    return Err(Refusal::WritesOwnConfiguration);
                }
            }
        }
        _ => {}
    }
    Ok(())
}

fn push_escaped(out: &mut String, value: &str) {
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 || (c as u32) == 0x7f || ((c as u32) >= 0x80 && (c as u32) < 0xa0) => {
                out.push_str(&format!("\\u{{{:x}}}", c as u32));
            }
            c => out.push(c),
        }
    }
}

fn push_value_fingerprint(out: &mut String, value: &JsonValue) {
    match value {
        JsonValue::Null => out.push_str("null"),
        JsonValue::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        // Debug keeps -0.0 distinct from 0.0 and prints every digit needed to
        // round-trip the value.
        JsonValue::Number(n) => out.push_str(&format!("{:?}", n)),
        JsonValue::Str(s) => {
            out.push('"');
            push_escaped(out, s);
            out.push('"');
        }
        JsonValue::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                push_value_fingerprint(out, item);
            }
            out.push(']');
        }
        JsonValue::Object(pairs) => {
            out.push('{');
            push_pairs_fingerprint(out, pairs);
            out.push('}');
        }
    }
}

fn push_pairs_fingerprint(out: &mut String, pairs: &[(String, JsonValue)]) {
    for (i, (key, value)) in pairs.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        out.push('"');
        push_escaped(out, key);
        out.push_str("\":");
        push_value_fingerprint(out, value);
    }
}

/// The complete, unambiguous identity of a call's arguments. An operator
/// approval is bound to exactly this string; nothing is truncated.
pub fn approval_fingerprint(args: &[(String, JsonValue)]) -> String {
    let mut out = String::new();
    push_pairs_fingerprint(&mut out, args);
    out
}

pub const DISPLAY_VALUE_BYTES: usize = 48;
pub const DISPLAY_KEY_BYTES: usize = 32;
pub const DISPLAY_TOTAL_BYTES: usize = 512;

fn truncate_utf8(value: &str, max_bytes: usize) -> &str {
    if value.len() <= max_bytes {
        return value;
    }
    let mut end = max_bytes;
    while end > 0 && !value.is_char_boundary(end) {
        end -= 1;
    }
    &value[..end]
}

fn push_display_str(out: &mut String, value: &str, max_bytes: usize) {
    let shown = truncate_utf8(value, max_bytes);
    out.push('"');
    push_escaped(out, shown);
    out.push('"');
    if shown.len() < value.len() {
        out.push_str(&format!("...[{} of {} bytes shown]", shown.len(), value.len()));
    }
}

/// What the operator sees for a pending approval: single-line, escaped, and
/// with every truncation stated, so model-chosen text cannot pose as other
/// requests or hide what it carries.
pub fn approval_display(args: &[(String, JsonValue)]) -> String {
    let mut out = String::new();
    for (i, (key, value)) in args.iter().enumerate() {
        if out.len() >= DISPLAY_TOTAL_BYTES {
            out.push_str(&format!(", ...[{} more arguments]", args.len() - i));
            break;
        }
        if i > 0 {
            out.push_str(", ");
        }
        push_display_str(&mut out, key, DISPLAY_KEY_BYTES);
        out.push('=');
        match value {
            JsonValue::Str(s) => push_display_str(&mut out, s, DISPLAY_VALUE_BYTES),
            JsonValue::Number(n) => out.push_str(&format!("{:?}", n)),
            JsonValue::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            JsonValue::Null => out.push_str("null"),
            other => {
                let mut nested = String::new();
                push_value_fingerprint(&mut nested, other);
                push_display_str(&mut out, &nested, DISPLAY_VALUE_BYTES);
            }
        }
    }
    out
}

/// An operator control command read from the daemon's mailbox.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ControlCommand {
    Confirm(u32),
    Deny(u32),
    Goal(String),
    NeuralArm,
    NeuralDisarm,
    ConfigUpdated,
    Unrecognized,
}

fn parse_id(text: &str) -> Option<u32> {
    let text = text.trim();
    if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    text.parse::<u32>().ok()
}

/// One message carries exactly one command. A goal's text is everything after
/// `GOAL:` (line breaks become spaces), so text inside a goal can never be
/// read as a second, separate CONFIRM/DENY command.
pub fn parse_control_message(message: &str) -> ControlCommand {
    let trimmed = message.trim();
    if let Some(goal) = trimmed.strip_prefix("GOAL:") {
        let goal: String = goal
            .trim()
            .chars()
            .map(|c| if c == '\n' || c == '\r' { ' ' } else { c })
            .collect();
        return ControlCommand::Goal(goal);
    }
    if trimmed.contains('\n') || trimmed.contains('\r') {
        return ControlCommand::Unrecognized;
    }
    if let Some(id) = trimmed.strip_prefix("CONFIRM:") {
        return parse_id(id).map(ControlCommand::Confirm).unwrap_or(ControlCommand::Unrecognized);
    }
    if let Some(id) = trimmed.strip_prefix("DENY:") {
        return parse_id(id).map(ControlCommand::Deny).unwrap_or(ControlCommand::Unrecognized);
    }
    match trimmed {
        "NEURAL_ARM" | "NEURAL_ARM:" => ControlCommand::NeuralArm,
        "NEURAL_DISARM" | "NEURAL_DISARM:" => ControlCommand::NeuralDisarm,
        "CONFIG_UPDATED" | "CONFIG_UPDATED:" => ControlCommand::ConfigUpdated,
        _ => ControlCommand::Unrecognized,
    }
}
