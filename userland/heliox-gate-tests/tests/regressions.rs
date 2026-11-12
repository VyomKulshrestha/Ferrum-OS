//! Defect regressions for the heliox-daemon authority gate (fi1 round 1).
//! Each test here failed on main at dba7016 and passes after the fix.

use heliox_gate_tests::cognitive::authority::PermissionTier;
use heliox_gate_tests::cognitive::confirmation::{ConfirmationGate, ConfirmationStatus};
use heliox_gate_tests::cognitive::json;

/// U2: a denied request could be flipped to approved by a later CONFIRM for
/// the same id, so a stale or replayed approval overrode the operator's no.
#[test]
fn approve_after_deny_does_not_turn_a_denial_into_an_approval() {
    let mut gate = ConfirmationGate::new(600);
    let id = match gate.check_or_request("delete_file", "path=/disk/a", PermissionTier::Destructive, 10) {
        ConfirmationStatus::Pending(id) => id,
        other => panic!("expected pending, got {:?}", other),
    };
    assert!(gate.deny(id));
    assert!(!gate.approve(id), "a denied request must not be re-approvable");
    assert_eq!(
        gate.check_or_request("delete_file", "path=/disk/a", PermissionTier::Destructive, 11),
        ConfirmationStatus::Denied
    );
}

/// U3: the expiry check computed `current_tick - created_at_tick` without
/// saturation; a tick earlier than the request's creation panicked (debug)
/// or wrapped to a huge age (release).
#[test]
fn tick_rollback_neither_panics_nor_approves() {
    let mut gate = ConfirmationGate::new(600);
    let first = gate.check_or_request("write_file", "path=/disk/x", PermissionTier::Modify, 1_000);
    assert!(matches!(first, ConfirmationStatus::Pending(_)));
    let again = gate.check_or_request("write_file", "path=/disk/x", PermissionTier::Modify, 5);
    assert!(matches!(again, ConfirmationStatus::Pending(_)), "got {:?}", again);
    gate.cleanup_expired(5);
    assert_eq!(gate.pending_list().len(), 1);
}

/// U4: the pending queue had no bound; a model emitting distinct Tier-3/4
/// calls grew it (and the operator's list) without limit.
#[test]
fn pending_queue_is_bounded_and_refuses_beyond_the_bound() {
    let mut gate = ConfirmationGate::new(600);
    let mut refused = 0;
    for i in 0..1_000u32 {
        let args = format!("path=/disk/f{}", i);
        match gate.check_or_request("write_file", &args, PermissionTier::Modify, 1) {
            ConfirmationStatus::Pending(_) => {}
            ConfirmationStatus::Refused => refused += 1,
            other => panic!("unexpected {:?}", other),
        }
    }
    assert!(gate.pending_list().len() <= heliox_gate_tests::cognitive::confirmation::MAX_PENDING);
    assert_eq!(refused, 1_000 - heliox_gate_tests::cognitive::confirmation::MAX_PENDING);
}

/// U5: the JSON parser had no nesting limit; a provider response of deeply
/// nested arrays recursed until the daemon's stack overflowed.
#[test]
fn deeply_nested_json_is_rejected_not_recursed() {
    let depth = 1_000;
    let input = format!("{}{}", "[".repeat(depth), "]".repeat(depth));
    assert!(json::parse(&input).is_err());
    let ok = format!("{}{}", "[".repeat(32), "]".repeat(32));
    assert!(json::parse(&ok).is_ok());
}

/// U6: exponent digits were accumulated in an i32 without overflow checks
/// (panic in debug, wrap in release) and applied by a loop of up to 2^31
/// multiplications; non-finite results reached `as u64` casts in tool
/// arguments (e.g. sleep ms = u64::MAX).
#[test]
fn huge_or_non_finite_numbers_fail_closed() {
    assert!(json::parse("1e99999999999").is_err());
    assert!(json::parse("1e400").is_err());
    assert!(json::parse("-1e400").is_err());
    assert!(matches!(json::parse("1e300"), Ok(json::JsonValue::Number(_))));
    assert!(matches!(json::parse("1e-400"), Ok(json::JsonValue::Number(n)) if n == 0.0));
}

/// U7: a lone '-' (and other digit-less tokens) parsed as the number -0.0.
#[test]
fn digitless_numbers_are_rejected() {
    for bad in ["-", "-.", "-e5", "{\"ms\": -}"] {
        assert!(json::parse(bad).is_err(), "{:?} parsed", bad);
    }
    assert!(matches!(json::parse("-0"), Ok(json::JsonValue::Number(_))));
}

/// U12: a tool call whose `arguments` string failed to parse ran with no
/// arguments at all, so tools with defaults (sleep 100 ms, record_audio
/// 2000 ms) executed something the model never validly asked for.
#[test]
fn tool_calls_with_unparseable_arguments_are_dropped() {
    let response = json::parse(
        r#"{"choices":[{"message":{"tool_calls":[
            {"function":{"name":"record_audio","arguments":"{\"duration_ms\": 50"}},
            {"function":{"name":"sleep","arguments":"[1,2]"}},
            {"function":{"name":"read_dir","arguments":"{\"path\":\"/disk\"}"}},
            {"function":{"name":"yield_cpu"}},
            {"function":{"name":"system_info","arguments":"  "}}
        ]}}]}"#,
    )
    .unwrap();
    let calls = json::extract_tool_calls(&response);
    let names: Vec<&str> = calls.iter().map(|c| c.name.as_str()).collect();
    assert_eq!(names, vec!["read_dir", "yield_cpu", "system_info"]);
}
