//! fi1 joint kernel + userland round: sender identity on the control mailbox
//! (K4) and approvals bound to the kernel's file version (K3).
use std::cell::Cell;

use heliox_gate_tests::cognitive::authority::{
    control_command_allowed, parse_control_message, version_subject, ControlCommand, ControlSender,
    SENDER_ASSISTANT_PANEL, SENDER_KERNEL_SHELL,
};
use heliox_gate_tests::cognitive::confirmation::{
    clear_for_execution, Clearance, ConfirmationGate, FileVersion,
};
use heliox_gate_tests::cognitive::json::JsonValue;
use heliox_gate_tests::{MAIN_SOURCE, ORCHESTRATOR_SOURCE};

fn s(v: &str) -> JsonValue {
    JsonValue::Str(v.into())
}
fn args(pairs: &[(&str, JsonValue)]) -> Vec<(String, JsonValue)> {
    pairs.iter().map(|(k, v)| (k.to_string(), v.clone())).collect()
}

// ---- K4: who may send control commands ------------------------------------

#[test]
fn k4_sender_table_is_exhaustive_over_commands_and_senders() {
    let commands = [
        ControlCommand::Confirm(7),
        ControlCommand::Deny(7),
        ControlCommand::Goal("x".into()),
        ControlCommand::NeuralArm,
        ControlCommand::NeuralDisarm,
        ControlCommand::ConfigUpdated,
        ControlCommand::Unrecognized,
    ];
    // (description, sender, is an operator channel)
    let senders: [(&str, Option<ControlSender>, bool); 8] = [
        ("kernel could not say", None, false),
        ("kernel shell", Some(ControlSender { pid: 0, flags: SENDER_KERNEL_SHELL }), true),
        ("operator panel", Some(ControlSender { pid: 412, flags: SENDER_ASSISTANT_PANEL }), true),
        ("both bits", Some(ControlSender { pid: 0, flags: SENDER_KERNEL_SHELL | SENDER_ASSISTANT_PANEL }), true),
        ("the daemon itself", Some(ControlSender { pid: 108, flags: 0 }), false),
        ("panel the agent exec'd", Some(ControlSender { pid: 500, flags: 0 }), false),
        ("pid 0 without the shell flag", Some(ControlSender { pid: 0, flags: 0 }), false),
        ("unknown flag bits only", Some(ControlSender { pid: 9, flags: 1 << 7 }), false),
    ];
    let mut cells = 0;
    for command in &commands {
        for (name, sender, operator) in &senders {
            let expected = match command {
                ControlCommand::NeuralDisarm => true,
                ControlCommand::Unrecognized => false,
                _ => *operator,
            };
            assert_eq!(control_command_allowed(command, *sender), expected, "{:?} from {}", command, name);
            cells += 1;
        }
    }
    assert_eq!(cells, 56);
}

#[test]
fn k4_a_forged_confirm_from_another_process_is_refused_end_to_end() {
    let message = parse_control_message("CONFIRM:4242");
    assert_eq!(message, ControlCommand::Confirm(4242));
    let forger = Some(ControlSender { pid: 131, flags: 0 });
    assert!(!control_command_allowed(&message, forger));
    let shell = Some(ControlSender { pid: 0, flags: SENDER_KERNEL_SHELL });
    assert!(control_command_allowed(&message, shell));
}

#[test]
fn k4_the_daemon_reads_its_mailbox_only_with_sender_identity() {
    // IpcReceiveFrom (61) with a sender record, and the policy applied
    // before any command; the plain IpcReceive (2) is not used on "heliox".
    assert!(ORCHESTRATOR_SOURCE.contains("const SYS_IPC_RECEIVE_FROM: u64 = 61;"));
    assert!(ORCHESTRATOR_SOURCE.contains("control_command_allowed(&command, Some(from))"));
    assert!(!ORCHESTRATOR_SOURCE.contains("SYS_IPC_RECEIVE,"));
    let poll = ORCHESTRATOR_SOURCE.split("fn ipc_poll").nth(1).expect("ipc_poll");
    let check = poll.find("control_command_allowed").expect("policy");
    let apply = poll.find("confirmation_gate.approve").expect("approve");
    assert!(check < apply, "the sender check must come before approving");
}

// ---- K3: approvals bound to the kernel's file version ---------------------

thread_local! {
    static VERSION: Cell<Option<u64>> = Cell::new(Some(1));
    static BROKEN: Cell<bool> = Cell::new(false);
}
fn set_version(v: Option<u64>) {
    VERSION.with(|c| c.set(v));
}
fn test_versions(_path: &str) -> Result<FileVersion, ()> {
    if BROKEN.with(|b| b.get()) {
        return Err(());
    }
    Ok(match VERSION.with(|c| c.get()) {
        Some(v) => FileVersion::Version(v),
        None => FileVersion::Absent,
    })
}
fn gate() -> ConfirmationGate {
    BROKEN.with(|b| b.set(false));
    set_version(Some(1));
    ConfirmationGate::new(600).with_file_versions(test_versions)
}
fn request(gate: &mut ConfirmationGate, tool: &str, a: &[(String, JsonValue)]) -> u32 {
    match clear_for_execution(gate, tool, a, 2, 10) {
        Clearance::Awaiting { id, .. } => id,
        other => panic!("{} expected to wait, got {:?}", tool, other),
    }
}

/// Every tool whose approval is about a file, with arguments.
fn file_tools() -> Vec<(&'static str, Vec<(String, JsonValue)>)> {
    vec![
        ("write_file", args(&[("path", s("/tmp/k3.txt")), ("content", s("approved text"))])),
        ("create_directory", args(&[("path", s("/tmp/k3dir"))])),
        ("delete_file", args(&[("path", s("/tmp/k3.txt"))])),
        ("exec_process", args(&[("path", s("/tmp/k3.bin"))])),
        ("trigger_kernel_upgrade", args(&[])),
    ]
}

#[derive(Debug, Clone, Copy)]
enum Change {
    None,
    Rewritten,      // another process wrote the file: new version
    Removed,        // it was deleted
    Created,        // it did not exist at request time, now does
    KernelCannotSay,
}

#[test]
fn k3_version_table_over_tools_changes_and_approval_state() {
    let changes = [Change::None, Change::Rewritten, Change::Removed, Change::Created, Change::KernelCannotSay];
    let mut cells = 0;
    for (tool, a) in file_tools() {
        for change in changes {
            for approve_before_change in [false, true] {
                let mut g = gate();
                let initial = if matches!(change, Change::Created) { None } else { Some(1) };
                set_version(initial);
                let id = request(&mut g, tool, &a);
                if approve_before_change {
                    assert!(g.approve(id));
                }
                match change {
                    Change::None => {}
                    Change::Rewritten => set_version(Some(2)),
                    Change::Removed => set_version(None),
                    Change::Created => set_version(Some(5)),
                    Change::KernelCannotSay => BROKEN.with(|b| b.set(true)),
                }
                if !approve_before_change {
                    // Approved after the change: the operator approved the
                    // request text, which was made before the change.
                    let _ = g.approve(id);
                }
                let got = clear_for_execution(&mut g, tool, &a, 2, 11);
                let expected = match change {
                    Change::None => Clearance::Proceed,
                    Change::KernelCannotSay => Clearance::Refused,
                    _ => Clearance::FileChanged,
                };
                assert_eq!(got, expected, "{} {:?} approved_first={}", tool, change, approve_before_change);
                if !matches!(change, Change::None | Change::KernelCannotSay) {
                    // Withdrawn: the next call is a new request with a new id.
                    BROKEN.with(|b| b.set(false));
                    let again = clear_for_execution(&mut g, tool, &a, 2, 12);
                    assert!(matches!(again, Clearance::Awaiting { id: new, .. } if new != id), "{} {:?}", tool, change);
                }
                cells += 1;
            }
        }
    }
    assert_eq!(cells, 5 * 5 * 2);
}

#[test]
fn k3_a_pending_request_whose_file_changed_is_withdrawn_before_approval() {
    let mut g = gate();
    let a = args(&[("path", s("/tmp/k3.txt"))]);
    let id = request(&mut g, "delete_file", &a);
    set_version(Some(9));
    assert_eq!(clear_for_execution(&mut g, "delete_file", &a, 2, 11), Clearance::FileChanged);
    // The old id no longer exists, so a late CONFIRM for it does nothing.
    assert!(!g.approve(id));
}

#[test]
fn k3_a_denial_stays_final_even_if_the_file_changes() {
    let mut g = gate();
    let a = args(&[("path", s("/tmp/k3.txt"))]);
    let id = request(&mut g, "delete_file", &a);
    assert!(g.deny(id));
    set_version(Some(3));
    assert_eq!(clear_for_execution(&mut g, "delete_file", &a, 2, 11), Clearance::Denied);
}

#[test]
fn k3_the_kernel_not_knowing_refuses_before_any_request_is_made() {
    let mut g = gate();
    BROKEN.with(|b| b.set(true));
    let a = args(&[("path", s("/tmp/k3.txt"))]);
    assert_eq!(clear_for_execution(&mut g, "delete_file", &a, 2, 10), Clearance::Refused);
    assert!(g.pending_list().is_empty());
}

#[test]
fn k3_the_default_gate_fails_closed_and_the_daemon_installs_the_kernel_source() {
    let mut g = ConfirmationGate::new(600);
    let a = args(&[("path", s("/tmp/k3.txt"))]);
    assert_eq!(clear_for_execution(&mut g, "delete_file", &a, 2, 10), Clearance::Refused);
    // Tools that do not act on a file need no version.
    let b = args(&[("service_id", JsonValue::Number(3.0))]);
    assert!(matches!(clear_for_execution(&mut g, "service_stop", &b, 2, 10), Clearance::Awaiting { .. }));
    // Both places the daemon builds its gate install the kernel source.
    assert!(ORCHESTRATOR_SOURCE.contains(".with_file_versions(kernel_file_version)"));
    assert!(MAIN_SOURCE.contains(".with_file_versions(cognitive::orchestrator::kernel_file_version)"));
    assert!(ORCHESTRATOR_SOURCE.contains("const SYS_FILE_VERSION: u64 = 62;"));
}

#[test]
fn k3_auto_approved_calls_need_no_version() {
    // Nothing to bind when no approval is involved: tier at or below the
    // configured auto-approve tier proceeds without asking the kernel.
    let mut g = ConfirmationGate::new(600);
    let a = args(&[("path", s("/tmp/k3.txt")), ("content", s("x"))]);
    assert_eq!(clear_for_execution(&mut g, "write_file", &a, 3, 10), Clearance::Proceed);
}

#[test]
fn k3_version_subject_is_the_path_the_kernel_receives() {
    let a = args(&[("path", s("/Tmp//K3.txt"))]);
    assert_eq!(version_subject("delete_file", &a).as_deref(), Some("/Tmp//K3.txt"));
    assert_eq!(version_subject("trigger_kernel_upgrade", &[]).as_deref(), Some("/disk/boot/kernel.bin"));
    assert_eq!(version_subject("read_file", &a), None);
}
