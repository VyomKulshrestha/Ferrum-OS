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
    // Simulator-only work order behind the deterministic physical supervisor;
    // it cannot reach an actuator (Live delivery is refused). Its
    // `confirm_simulation` flag is chosen by the caller and is not an operator
    // approval (open question O7 in docs/research/fi1_reports/userland_round1.md).
    ("physical_maintenance_demo", PermissionTier::Safe),
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
    // Tier 4: Destructive
    // Input injection acts with the operator's own authority: injected keys
    // reach the kernel shell and its GUI terminal (`heliox confirm <id>`,
    // `write`, `rm`) and injected clicks drive any focused app (task-manager
    // kill, app-store install/remove). A tool that can do anything the
    // operator can do is not a Tier-3 tool (round 2, finding R2-1).
    ("keyboard_type", PermissionTier::Destructive),
    ("mouse_click", PermissionTier::Destructive),
    ("mouse_move", PermissionTier::Destructive),
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
    /// keyboard_type text containing anything but printable ASCII: Enter,
    /// Escape, Backspace, Tab, Ctrl-<x> or non-ASCII bytes. Without them the
    /// agent can type into a field but never submit, erase or save it.
    InputControlCharacter,
    /// `sleep` longer than MAX_SLEEP_MS, negative, or not a number. A sleep
    /// blocks the whole daemon: the control mailbox is not polled, so the
    /// operator's CONFIRM/DENY, goals and neural disarm are not applied
    /// (round 3, R3-4).
    SleepOutOfRange,
}

/// Longest sleep the agent may request. The kernel's sleep syscall has no
/// upper bound (`ms` saturates to u64::MAX, roughly forever).
pub const MAX_SLEEP_MS: f64 = 10_000.0;

impl Refusal {
    pub fn as_str(self) -> &'static str {
        match self {
            Refusal::InputControlCharacter => {
                "keyboard_type may only type printable ASCII (no Enter, Escape, Backspace, Tab or control keys)"
            }
            Refusal::SleepOutOfRange => "sleep must be a number of milliseconds from 0 to 10000",
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
        // Enter is what turns typed text into a shell command (`heliox
        // confirm <id>` approves any pending request); Escape saves in the
        // text editor; Backspace erases what the operator typed. The agent
        // may type, a human submits.
        "keyboard_type" => {
            if let Some(text) = find_str(args, "text") {
                if !text.bytes().all(|b| (0x20..=0x7e).contains(&b)) {
                    return Err(Refusal::InputControlCharacter);
                }
            }
        }
        // An absent `ms` means the executor's 100 ms default. A present one
        // must be a number in range: the executor would read a string as the
        // default, so only numbers can lengthen the sleep, but anything that
        // is not a plain in-range number is refused (fail closed).
        "sleep" => {
            if let Some((_, value)) = args.iter().find(|(k, _)| k == "ms") {
                let in_range = matches!(value, JsonValue::Number(n) if *n >= 0.0 && *n <= MAX_SLEEP_MS);
                if !in_range {
                    return Err(Refusal::SleepOutOfRange);
                }
            }
        }
        _ => {}
    }
    Ok(())
}

/// Escapes everything outside printable ASCII. The operator's console font
/// is ASCII, and bidirectional overrides (U+202E), zero-width characters and
/// homoglyphs would otherwise let model-chosen text read as something else.
/// Injective: `\` itself is escaped, so `\u{..}` only arises from escaping.
fn push_escaped(out: &mut String, value: &str) {
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if !(' '..='~').contains(&c) => {
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

/// Largest complete rendering of a call the operator can be shown. A call
/// whose arguments do not fit is refused rather than approved half-seen.
pub const MAX_APPROVAL_DISPLAY_BYTES: usize = 8192;

/// Every byte of every argument, escaped onto one line, or `None` when that
/// exceeds `MAX_APPROVAL_DISPLAY_BYTES`. This is what the console prints when
/// a request is created, so an operator never approves text they could not
/// see (the short `approval_display` truncates values at 48 bytes).
pub fn approval_full_display(args: &[(String, JsonValue)]) -> Option<String> {
    let mut out = String::new();
    for (i, (key, value)) in args.iter().enumerate() {
        if i > 0 {
            out.push_str(", ");
        }
        out.push('"');
        push_escaped(&mut out, key);
        out.push_str("\"=");
        push_value_fingerprint(&mut out, value);
        if out.len() > MAX_APPROVAL_DISPLAY_BYTES {
            return None;
        }
    }
    Some(out)
}

/// Tools whose meaning depends on the file at their `path` argument.
const PATH_SUBJECT_TOOLS: [&str; 4] = ["write_file", "create_directory", "delete_file", "exec_process"];
/// Tools that change the file at their `path` argument.
pub const PATH_MODIFYING_TOOLS: [&str; 3] = ["write_file", "create_directory", "delete_file"];

/// The image `trigger_kernel_upgrade` reads and kexecs
/// (`self_evolve::trigger_hot_reload`). Normalized form.
pub const KERNEL_UPGRADE_IMAGE: &str = "/disk/boot/kernel.bin";

/// Tools whose meaning depends on a fixed file that is not among their
/// arguments. An approval of `trigger_kernel_upgrade {}` is an approval to
/// boot whatever `/disk/boot/kernel.bin` holds when it runs, so a later
/// write to that file must withdraw it, and the operator must be told which
/// file it is about (round 3, R3-1).
pub fn implicit_subject(tool: &str) -> Option<&'static str> {
    match tool {
        "trigger_kernel_upgrade" => Some(KERNEL_UPGRADE_IMAGE),
        _ => None,
    }
}

/// The normalized path an approval for `tool` is about, if any: components
/// with `.`/empty dropped and `..` applied, lowercased (over-matching only
/// revokes more approvals, never fewer).
pub fn subject_path(tool: &str, args: &[(String, JsonValue)]) -> Option<String> {
    if let Some(path) = implicit_subject(tool) {
        return Some(String::from(path));
    }
    if !PATH_SUBJECT_TOOLS.contains(&tool) {
        return None;
    }
    let path = find_str(args, "path")?;
    let mut out = String::new();
    for component in path_components(path) {
        out.push('/');
        out.push_str(&component.to_ascii_lowercase());
    }
    if out.is_empty() {
        out.push('/');
    }
    Some(out)
}

/// True when one normalized path is the other or lies beneath it.
pub fn paths_overlap(a: &str, b: &str) -> bool {
    fn under(child: &str, parent: &str) -> bool {
        child == parent
            || parent == "/"
            || (child.len() > parent.len()
                && child.starts_with(parent)
                && child.as_bytes()[parent.len()] == b'/')
    }
    under(a, b) || under(b, a)
}

/// Prefix of every audit entry the agent writes through `audit_write`. The
/// daemon's own entries ("neural: ...") and the kernel's never start with
/// it, so an agent entry cannot pose as one of them.
pub const AGENT_AUDIT_PREFIX: &str = "agent-audit: ";
/// The kernel refuses audit messages over 1024 bytes.
pub const MAX_AUDIT_BYTES: usize = 1024;

/// The audit text written for agent-chosen `body`: `prefix` followed by
/// `body` escaped to one line of printable ASCII, cut (and marked) to fit
/// the kernel's 1024-byte bound. The kernel stores and prints entries as
/// `[tick] Event: message` lines (`src/logging/audit.rs`), so an unescaped
/// line break would let the agent forge further entries (round 3, R3-2).
pub fn agent_audit_text(prefix: &str, body: &str) -> String {
    let mut escaped = String::new();
    push_escaped(&mut escaped, body);
    let marker = "...[truncated]";
    let room = MAX_AUDIT_BYTES - prefix.len();
    let mut out = String::from(prefix);
    if escaped.len() <= room {
        out.push_str(&escaped);
    } else {
        // Escaped text is ASCII, so any byte index is a char boundary.
        out.push_str(&escaped[..room - marker.len()]);
        out.push_str(marker);
    }
    out
}

/// Marker the daemon prints with the bridge pairing secret (main.rs).
pub const PAIRING_TOKEN_MARKER: &str = "bridge pairing token:";

/// Screen text as the agent may see it: the bridge pairing secret, printed on
/// the console for the physical operator, is replaced. Without this the
/// secret reached the model in every prompt (`observe` adds the screen) and
/// through `read_screen` (Tier 1), and `http_get` (Tier 2) could send it out
/// (round 3, R3-3).
pub fn redact_screen_secrets(screen: &str) -> String {
    const TOKEN_HEX_CHARS: usize = 32;
    let mut out = String::with_capacity(screen.len());
    // Hex characters of a token still to redact at the start of the next
    // row, when the console wrapped the token line.
    let mut carry = 0usize;
    for (i, line) in screen.split('\n').enumerate() {
        if i > 0 {
            out.push('\n');
        }
        let mut rest = line;
        if carry > 0 {
            let hex = rest
                .bytes()
                .take(carry)
                .take_while(|b| b.is_ascii_hexdigit())
                .count();
            if hex > 0 {
                out.push_str("[redacted]");
                rest = &rest[hex..];
            }
            carry = 0;
        }
        match rest.find(PAIRING_TOKEN_MARKER) {
            Some(at) => {
                let tail = &rest[at + PAIRING_TOKEN_MARKER.len()..];
                let shown = tail.trim_start().bytes().take_while(|b| b.is_ascii_hexdigit()).count();
                out.push_str(&rest[..at + PAIRING_TOKEN_MARKER.len()]);
                out.push_str(" [redacted]");
                carry = TOKEN_HEX_CHARS.saturating_sub(shown);
            }
            None => out.push_str(rest),
        }
    }
    out
}

/// File content as `read_file` returns it to the agent: for the daemon's own
/// configuration, the value of every `"api_key"` member is replaced. The
/// JSON-RPC `get_config` already omits the key ("not to round-trip
/// secrets"), but `read_file /disk/heliox/config.json` (Tier 1) returned it,
/// and `http_get` (Tier 2) could send it out (round 3, R3-3). Textual, so it
/// also covers a truncated or malformed file; an unterminated value is
/// redacted to the end.
pub fn redact_file_secrets(path: &str, content: &str) -> String {
    if !targets_own_config(path) {
        return String::from(content);
    }
    const KEY: &str = "\"api_key\"";
    let bytes = content.as_bytes();
    let mut out = String::with_capacity(content.len());
    let mut i = 0;
    while let Some(found) = content[i..].find(KEY) {
        let after_key = i + found + KEY.len();
        out.push_str(&content[i..after_key]);
        let mut j = after_key;
        while j < bytes.len() && (bytes[j] == b' ' || bytes[j] == b'\t' || bytes[j] == b'\n' || bytes[j] == b'\r' || bytes[j] == b':') {
            j += 1;
        }
        out.push_str(&content[after_key..j]);
        if j < bytes.len() && bytes[j] == b'"' {
            // Skip the string value, honouring backslash escapes.
            let mut k = j + 1;
            while k < bytes.len() && bytes[k] != b'"' {
                k += if bytes[k] == b'\\' { 2 } else { 1 };
            }
            out.push_str("\"[redacted]\"");
            i = core::cmp::min(k + 1, bytes.len());
        } else {
            // Not a string (or cut off): redact the rest of the member.
            let mut k = j;
            while k < bytes.len() && bytes[k] != b',' && bytes[k] != b'}' {
                k += 1;
            }
            if k > j {
                out.push_str("[redacted]");
            }
            i = k;
        }
        while i < bytes.len() && !content.is_char_boundary(i) {
            i += 1;
        }
    }
    out.push_str(&content[i..]);
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

/// Sender flags the kernel attaches to a mailbox message (IpcReceiveFrom,
/// `src/ipc/mod.rs`). Set only by kernel code, never by the sender.
pub const SENDER_KERNEL_SHELL: u64 = 1 << 0;
pub const SENDER_ASSISTANT_PANEL: u64 = 1 << 1;
/// Either of the operator's channels.
pub const OPERATOR_SENDERS: u64 = SENDER_KERNEL_SHELL | SENDER_ASSISTANT_PANEL;

/// Who sent a control message, as the kernel reports it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ControlSender {
    pub pid: u64,
    pub flags: u64,
}

/// Whether a control command may be applied, given who the kernel says sent
/// it (`None`: the kernel could not establish a sender). Confirmations,
/// denials, goals, neural arming and configuration reloads act with the
/// operator's authority and are applied only from the kernel shell
/// (`heliox confirm|deny|voice|neural`) or the assistant panel the kernel
/// launched for the operator. A message from this daemon, from a panel the
/// agent started, or from any other process is refused (fi1 K4). Neural
/// disarm only takes authority away and is accepted from any sender.
pub fn control_command_allowed(command: &ControlCommand, sender: Option<ControlSender>) -> bool {
    match command {
        ControlCommand::NeuralDisarm => true,
        ControlCommand::Unrecognized => false,
        ControlCommand::Confirm(_)
        | ControlCommand::Deny(_)
        | ControlCommand::Goal(_)
        | ControlCommand::NeuralArm
        | ControlCommand::ConfigUpdated => {
            matches!(sender, Some(s) if s.flags & OPERATOR_SENDERS != 0)
        }
    }
}

/// Tools whose approval is bound to what is under the pointer (fi1 K2).
pub fn binds_click_target(tool: &str) -> bool {
    tool == "mouse_click"
}

/// The text shown to the operator for a click's target. The title is chosen
/// by the window's owner, so it is escaped to printable ASCII and cut.
pub fn click_target_note(window: u64, owner: u64, rel_x: u32, rel_y: u32, title: &str) -> String {
    const MAX_TITLE: usize = 48;
    let mut shown = String::new();
    for (count, c) in title.chars().enumerate() {
        if count == MAX_TITLE {
            shown.push_str("...");
            break;
        }
        if c == '"' || c == '\\' {
            shown.push('\\');
            shown.push(c);
        } else if (' '..='~').contains(&c) {
            shown.push(c);
        } else {
            shown.push('?');
        }
    }
    if window == 0 {
        alloc::format!("[clicks the desktop at ({}, {})]", rel_x, rel_y)
    } else {
        alloc::format!(
            "[clicks window {} \"{}\" of pid {} at ({}, {}) in the window]",
            window, shown, owner, rel_x, rel_y
        )
    }
}

/// The path the kernel is asked for the version of, for a tool whose
/// approval is bound to a file: the fixed file of `implicit_subject`, or the
/// `path` argument exactly as the tool will pass it to the kernel (not the
/// lowercased `subject_path`, which only serves to over-revoke).
pub fn version_subject(tool: &str, args: &[(String, JsonValue)]) -> Option<String> {
    if let Some(path) = implicit_subject(tool) {
        return Some(String::from(path));
    }
    if !PATH_SUBJECT_TOOLS.contains(&tool) {
        return None;
    }
    find_str(args, "path").map(String::from)
}
