//! Round 2 (fi1 workstream D): attacks on the round-1 fixes. Every test here
//! uses only APIs that existed at fe3db45, so each can be run against that
//! commit's daemon sources to show the bypass; all of them failed there.
//! See docs/research/fi1_reports/userland_round2.md.

use heliox_gate_tests::cognitive::authority::{
    approval_display, tool_tier, validate_tool_call, PermissionTier,
};
use heliox_gate_tests::cognitive::confirmation::{clear_for_execution, Clearance, ConfirmationGate};
use heliox_gate_tests::cognitive::json::JsonValue;

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
// R2-1. Input injection reached the operator's own approval command.
// keyboard_type was Tier 3. Injected keys are fed to the kernel shell and to
// the GUI terminal (src/input/mod.rs inject_key_event -> feed_to_shell;
// src/gui/compositor.rs Terminal arm runs shell::commands::execute), which
// runs as Root (cap:system:all). `heliox confirm <id>` there sends
// CONFIRM:<id> to the daemon (src/heliox/mod.rs submit_request "confirm").
// So with auto_approve_tier=3 the sequence
//   delete_file {path:X}                       -> Awaiting (id=N)
//   keyboard_type {text:"heliox confirm N\n"}  -> runs unasked (Tier 3)
//   delete_file {path:X}                       -> runs
// executed a Tier-4 action with no operator approval; with the default
// tier 2 one approval of an innocuous-looking keyboard_type (the text after
// 48 bytes was not shown) did the same, and `write`/`rm` in the shell need
// no daemon approval at all. mouse_click/mouse_move drive task-manager kill
// and app-store install/remove the same way.
// ---------------------------------------------------------------------------

#[test]
fn input_injection_tools_are_destructive() {
    for tool in ["keyboard_type", "mouse_click", "mouse_move"] {
        assert_eq!(tool_tier(tool), PermissionTier::Destructive, "{}", tool);
        for auto in 0u8..=3 {
            let mut gate = ConfirmationGate::new(600).with_file_versions(heliox_gate_tests::stable_versions).with_click_targets(heliox_gate_tests::stable_click_target).with_service_names(heliox_gate_tests::stable_service_names).with_focus_targets(heliox_gate_tests::stable_focus_target);
            let a = args(&[("text", s("hello"))]);
            assert!(
                matches!(clear_for_execution(&mut gate, tool, &a, auto, 1), Clearance::Awaiting { .. }),
                "{} ran unasked at auto_approve_tier={}",
                tool,
                auto
            );
        }
    }
}

#[test]
fn keyboard_type_cannot_press_enter_or_control_keys() {
    for text in [
        "heliox confirm 7\n",
        "heliox confirm 7\r",
        "\n",
        "rm /disk/notes.txt\r\n",
        "\u{1b}",          // Escape: saves in the text editor
        "\u{8}\u{8}\u{8}", // Backspace: erases what the operator typed
        "\u{16}",          // Ctrl-V: pastes the clipboard
        "\u{3}",           // Ctrl-C
        "a\tb",
        "\u{7f}",
        "\0",
        "caf\u{e9}",       // non-ASCII bytes are injected one byte at a time
        "heliox confirm 7\u{2028}",
    ] {
        let a = args(&[("text", s(text))]);
        assert!(validate_tool_call("keyboard_type", &a).is_err(), "{:?} accepted", text);
    }
    for text in ["help", "g", "hello world ~!@#$%^&*()_+{}|:\"<>?`-=[]\\;',./", " "] {
        let a = args(&[("text", s(text))]);
        assert_eq!(validate_tool_call("keyboard_type", &a), Ok(()), "{:?}", text);
    }
}

// ---------------------------------------------------------------------------
// R2-2. An approval outlived the file it was about. Approvals bind the
// arguments, but exec_process {path:P} means "run the binary now at P".
// With auto_approve_tier=3 (writes auto-approved):
//   exec_process {path:P}                 -> Awaiting (id=N), operator inspects P and approves
//   write_file {path:P, content:<other>}  -> runs unasked
//   exec_process {path:P}                 -> ran the replaced binary
// With the default tier the swap needs one write approval that does not
// mention the pending exec. Now any path-modifying call that clears
// withdraws every outstanding request about that path, a path beneath it or
// a directory above it.
// ---------------------------------------------------------------------------

#[test]
fn rewriting_a_path_revokes_its_outstanding_approvals() {
    let exec = args(&[("path", s("/disk/tools/report.elf"))]);
    let cases: Vec<(&str, Vec<(String, JsonValue)>, u8)> = vec![
        ("write_file", args(&[("path", s("/disk/tools/report.elf")), ("content", s("\u{7f}ELF..."))]), 3),
        ("write_file", args(&[("path", s("//disk/tools//report.elf")), ("content", s("x"))]), 3),
        ("write_file", args(&[("path", s("/disk/tmp/../tools/report.elf")), ("content", s("x"))]), 3),
        ("create_directory", args(&[("path", s("/disk/tools/report.elf"))]), 3),
        ("delete_file", args(&[("path", s("/disk/tools/report.elf"))]), 4),
        ("delete_file", args(&[("path", s("/disk/tools"))]), 4),
    ];
    for (tool, modify, auto) in cases {
        let mut gate = ConfirmationGate::new(600).with_file_versions(heliox_gate_tests::stable_versions).with_click_targets(heliox_gate_tests::stable_click_target).with_service_names(heliox_gate_tests::stable_service_names).with_focus_targets(heliox_gate_tests::stable_focus_target);
        let id = awaiting_id(clear_for_execution(&mut gate, "exec_process", &exec, auto.min(3), 1));
        assert!(gate.approve(id));
        assert_eq!(clear_for_execution(&mut gate, tool, &modify, auto, 2), Clearance::Proceed);
        assert!(
            matches!(clear_for_execution(&mut gate, "exec_process", &exec, auto.min(3), 3), Clearance::Awaiting { .. }),
            "approval of exec survived {} {:?}",
            tool,
            modify
        );
    }

    // A pending delete is withdrawn too when the file is rewritten.
    let mut gate = ConfirmationGate::new(600).with_file_versions(heliox_gate_tests::stable_versions).with_click_targets(heliox_gate_tests::stable_click_target).with_service_names(heliox_gate_tests::stable_service_names).with_focus_targets(heliox_gate_tests::stable_focus_target);
    let del = args(&[("path", s("/disk/data/a.txt"))]);
    let id = awaiting_id(clear_for_execution(&mut gate, "delete_file", &del, 3, 1));
    let w = args(&[("path", s("/disk/data/a.txt")), ("content", s("new"))]);
    assert_eq!(clear_for_execution(&mut gate, "write_file", &w, 3, 2), Clearance::Proceed);
    assert!(!gate.approve(id), "withdrawn request can no longer be approved");

    // Unrelated paths do not revoke.
    for other in ["/disk/tools/report.elf.bak", "/disk/toolsx/report.elf", "/disk/other.txt"] {
        let mut gate = ConfirmationGate::new(600).with_file_versions(heliox_gate_tests::stable_versions).with_click_targets(heliox_gate_tests::stable_click_target).with_service_names(heliox_gate_tests::stable_service_names).with_focus_targets(heliox_gate_tests::stable_focus_target);
        let id = awaiting_id(clear_for_execution(&mut gate, "exec_process", &exec, 3, 1));
        assert!(gate.approve(id));
        let w = args(&[("path", s(other)), ("content", s("x"))]);
        assert_eq!(clear_for_execution(&mut gate, "write_file", &w, 3, 2), Clearance::Proceed);
        assert_eq!(clear_for_execution(&mut gate, "exec_process", &exec, 3, 3), Clearance::Proceed, "{}", other);
    }
}

// ---------------------------------------------------------------------------
// R2-3 (display part). The short display escaped C0/C1 controls only, so a
// right-to-left override, zero-width space or Cyrillic homoglyph reached the
// operator's console unescaped:
//   delete_file {path:"/disk/home/user/\u{202e}txt.cod\u{202c}.elf"}
// renders as a ".doc"-looking name; "/disk/h\u{435}liox/config.json"
// (Cyrillic e) looks like the daemon's own config.
// ---------------------------------------------------------------------------

#[test]
fn operator_text_escapes_everything_outside_printable_ascii() {
    for value in [
        "/disk/home/user/\u{202e}txt.cod\u{202c}.elf",
        "/disk/h\u{435}liox/config.json",
        "/disk/a\u{200b}b",
        "/disk/\u{2066}x\u{2069}",
        "/disk/\u{feff}bom",
        "/disk/combining-e\u{301}",
    ] {
        let shown = approval_display(&args(&[("path", s(value))]));
        assert!(shown.is_ascii(), "non-ASCII reached the operator: {:?}", shown);
        assert!(shown.contains("\\u{"), "{:?}", shown);
    }
    // Keys too.
    let shown = approval_display(&args(&[("p\u{202e}ath", s("x"))]));
    assert!(shown.is_ascii(), "{:?}", shown);
}
