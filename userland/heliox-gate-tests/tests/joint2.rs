//! fi1 joint round 2: attacks on sender identity (K4), the injected mark (K1)
//! and file versions (K3), and the closing of K3's check-then-act window.
//!
//! The daemon half is tested here on the host. The kernel half is checked in
//! two ways: source checks of the syscall contract below, and the
//! `test-syscall file-guard` self-test the QEMU harness
//! `scripts/verify_authority_gate_joint.mjs` runs on the CI image.
use std::cell::Cell;

use heliox_gate_tests::cognitive::authority::{
    control_command_allowed, ControlCommand, ControlSender, SENDER_ASSISTANT_PANEL,
};
use heliox_gate_tests::cognitive::confirmation::{
    clear_for_execution, clear_for_execution_bound, expected_version_word, Clearance,
    ConfirmationGate, FileVersion,
};
use heliox_gate_tests::cognitive::json::JsonValue;
use heliox_gate_tests::{
    ASSISTANT_PANEL_SOURCE, KERNEL_FS_SOURCE, KERNEL_SYSCALL_FS_SOURCE,
    KERNEL_SYSCALL_PROCESS_SOURCE, KERNEL_SYSCALL_SOURCE, SELF_EVOLVE_SOURCE, TOOL_MAPPER_SOURCE,
};

fn s(v: &str) -> JsonValue {
    JsonValue::Str(v.into())
}
fn args(pairs: &[(&str, JsonValue)]) -> Vec<(String, JsonValue)> {
    pairs.iter().map(|(k, v)| (k.to_string(), v.clone())).collect()
}

thread_local! {
    static VERSION: Cell<Option<u64>> = Cell::new(Some(1));
}
fn set_version(v: Option<u64>) {
    VERSION.with(|c| c.set(v));
}
fn test_versions(_path: &str) -> Result<FileVersion, ()> {
    Ok(match VERSION.with(|c| c.get()) {
        Some(v) => FileVersion::Version(v),
        None => FileVersion::Absent,
    })
}
fn gate() -> ConfirmationGate {
    set_version(Some(1));
    ConfirmationGate::new(600).with_file_versions(test_versions)
}

/// The four tools whose executor hands the bound version to the kernel.
fn guarded_tools() -> Vec<(&'static str, Vec<(String, JsonValue)>)> {
    vec![
        ("write_file", args(&[("path", s("/tmp/j2.txt")), ("content", s("approved"))])),
        ("delete_file", args(&[("path", s("/tmp/j2.txt"))])),
        ("exec_process", args(&[("path", s("/tmp/j2.bin"))])),
        ("trigger_kernel_upgrade", args(&[])),
    ]
}

// ---- Item 2: the approved action carries its version to the kernel --------

#[test]
fn j2_k3_an_approved_file_action_carries_the_version_it_was_approved_for() {
    for start in [Some(41u64), None] {
        for (tool, a) in guarded_tools() {
            let mut g = gate();
            set_version(start);
            let id = match clear_for_execution(&mut g, tool, &a, 2, 10) {
                Clearance::Awaiting { id, .. } => id,
                other => panic!("{tool}: expected a request, got {other:?}"),
            };
            assert!(g.approve(id));
            let expected = match start {
                Some(v) => FileVersion::Version(v),
                None => FileVersion::Absent,
            };
            assert_eq!(
                clear_for_execution_bound(&mut g, tool, &a, 2, 11),
                (Clearance::Proceed, Some(expected)),
                "{tool} starting at {start:?}"
            );
            // Used once: the next call is a new request, bound to nothing yet.
            assert!(matches!(
                clear_for_execution_bound(&mut g, tool, &a, 2, 12),
                (Clearance::Awaiting { .. }, None)
            ));
        }
    }
}

#[test]
fn j2_k3_the_version_word_the_kernel_expects() {
    assert_eq!(expected_version_word(FileVersion::Absent), 0);
    assert_eq!(expected_version_word(FileVersion::Version(1 << 62 | 5)), 1 << 62 | 5);
}

#[test]
fn j2_k3_calls_that_run_without_an_approval_carry_no_version() {
    // Auto-approved by tier: no approval, nothing to bind (the old calls).
    let mut g = gate();
    let w = args(&[("path", s("/tmp/j2.txt")), ("content", s("x"))]);
    assert_eq!(clear_for_execution_bound(&mut g, "write_file", &w, 3, 1), (Clearance::Proceed, None));
    // An approved Tier-4 call that is not about a file.
    let k = args(&[("text", s("hello"))]);
    let id = match clear_for_execution(&mut g, "keyboard_type", &k, 3, 1) {
        Clearance::Awaiting { id, .. } => id,
        other => panic!("{other:?}"),
    };
    g.approve(id);
    assert_eq!(clear_for_execution_bound(&mut g, "keyboard_type", &k, 3, 2), (Clearance::Proceed, None));
    // Refusals, waits and withdrawals carry none either.
    let d = args(&[("path", s("/tmp/j2.txt"))]);
    assert!(matches!(clear_for_execution_bound(&mut g, "delete_file", &d, 2, 1), (Clearance::Awaiting { .. }, None)));
    set_version(Some(2));
    assert_eq!(clear_for_execution_bound(&mut g, "delete_file", &d, 2, 2), (Clearance::FileChanged, None));
}

#[test]
fn j2_k3_the_daemon_hands_the_bound_version_to_the_kernels_guarded_calls() {
    let tm = TOOL_MAPPER_SOURCE;
    for needle in [
        "const SYS_WRITE_FILE_IF_VERSION: u64 = 63;",
        "const SYS_DELETE_FILE_IF_VERSION: u64 = 64;",
        "const SYS_EXEC_IF_VERSION: u64 = 65;",
        "const VERSION_MISMATCH: i64 = -7;",
        "confirmation_result_bound(tool_call, confirmation_gate, auto_approve_tier, current_tick)",
        "\"write_file\" => execute_write_file(&tool_call.arguments, bound)",
        "\"delete_file\" => execute_delete_file(&tool_call.arguments, bound)",
        "\"exec_process\" => execute_exec_process(&tool_call.arguments, bound)",
        "\"trigger_kernel_upgrade\" => execute_trigger_kernel_upgrade(bound)",
        "SYS_WRITE_FILE_IF_VERSION,",
        "SYS_DELETE_FILE_IF_VERSION,",
        "SYS_EXEC_IF_VERSION,",
    ] {
        assert!(tm.contains(needle), "tool_mapper.rs lacks {needle}");
    }
    // `execute` takes its clearance from the bound variant only.
    let execute = &tm[tm.find("pub fn execute(").unwrap()..];
    let execute = &execute[..execute.find("match tool_call.name.as_str()").unwrap()];
    assert!(execute.contains("confirmation_result_bound("));
    assert!(!execute.contains("confirmation_result("));
    // The kernel image: Kexec takes bytes, so the daemon re-reads the
    // version after its single read and refuses on any change.
    assert!(SELF_EVOLVE_SOURCE.contains("pub fn trigger_hot_reload(bound: Option<super::confirmation::FileVersion>)"));
    let after_read = &SELF_EVOLVE_SOURCE[SELF_EVOLVE_SOURCE.find("read_file_to_vec(kernel_path)").unwrap()..];
    let check = after_read.find("kernel_file_version(kernel_path) != Ok(approved)").expect("no re-check");
    let kexec = after_read.find("SYS_KEXEC").expect("no kexec");
    assert!(check < kexec, "the version is re-checked after the read and before kexec");
}

#[test]
fn j2_k3_the_kernel_checks_and_acts_in_one_syscall() {
    let sys = KERNEL_SYSCALL_SOURCE;
    for needle in [
        "WriteFileIfVersion = 63,",
        "DeleteFileIfVersion = 64,",
        "ExecIfVersion = 65,",
        "VersionMismatch = -7,",
        "fs::sys_write_file_checked(args, held_capabilities, Some(args[4]))",
        "fs::sys_delete_file_checked(args, held_capabilities, Some(args[2]))",
        "process::sys_exec_checked(args, Some(args[2]))",
    ] {
        assert!(sys.contains(needle), "syscall/mod.rs lacks {needle}");
    }
    // The guarded delete is a DeleteFile for the kernel's own 'y' prompt.
    let gate = &sys[sys.find("let is_delete_file =").unwrap()..];
    let gate = &gate[..gate.find(';').unwrap()];
    assert!(gate.contains("SyscallNumber::DeleteFileIfVersion"), "{gate}");
    // ExecIfVersion needs process:spawn like Exec.
    let exec = &sys[sys.find("SyscallNumber::ExecIfVersion as u64 =>").unwrap()..];
    let exec = &exec[..exec.find("process::sys_exec_checked").unwrap()];
    assert!(exec.contains("\"process:spawn\""));
    // The old calls keep their behaviour (no expected version).
    assert!(KERNEL_SYSCALL_FS_SOURCE.contains("sys_write_file_checked(args, held_capabilities, None)"));
    assert!(KERNEL_SYSCALL_FS_SOURCE.contains("sys_delete_file_checked(args, held_capabilities, None)"));
    assert!(KERNEL_SYSCALL_PROCESS_SOURCE.contains("sys_exec_checked(args, None)"));
    // The exec check comes before the image is chosen or read.
    let ex = &KERNEL_SYSCALL_PROCESS_SOURCE[KERNEL_SYSCALL_PROCESS_SOURCE.find("pub fn sys_exec_checked").unwrap()..];
    assert!(ex.find("check_version(&path, expected)").unwrap() < ex.find("read_file_bytes(&path)").unwrap());
    // Check and act share one interrupts-off section.
    let fs = KERNEL_FS_SOURCE;
    for f in ["pub fn write_file_if_version", "pub fn remove_if_version"] {
        let body = &fs[fs.find(f).unwrap()..];
        let body = &body[..body.find("\n}\n").unwrap()];
        assert!(body.contains("without_interrupts"), "{f}");
        assert!(body.find("check_version").unwrap() < body.rfind("map_err(GuardError::Failed)").unwrap(), "{f}");
    }
}

// ---- Breaks in the file version (kernel; run-time check in file-guard) ----

#[test]
fn j2_2_the_version_comes_from_the_filesystem_not_the_mmap_test_shortcut() {
    // `fs::stat` answers "/disk/mmap_verify" with a fixed version, while
    // WriteFile, DeleteFile and Exec act on the real file at that path.
    let fs = KERNEL_FS_SOURCE;
    let body = &fs[fs.find("pub fn file_version(").unwrap()..];
    let body = &body[..body.find("\n}\n").unwrap()];
    assert!(body.contains("vfs::resolve(path)"), "file_version must ask the filesystem");
    assert!(!body.contains("match stat(path)"), "file_version must not use stat()'s synthetic answer");
}

#[test]
fn j2_1_a_ramfs_write_never_replaces_a_directory() {
    let fs = KERNEL_FS_SOURCE;
    let body = &fs[fs.find("fn create_file_bytes(&self, path: &str, content: &[u8])").unwrap()..];
    let body = &body[..body.find("fn create_dir").unwrap()];
    let refuse = body.find("Some(FsNode::Directory { .. })").expect("no directory check");
    let insert = body.find("children.insert(file_name").unwrap();
    assert!(refuse < insert);
}

#[test]
fn j2_3_a_directory_version_covers_its_subtree() {
    let fs = KERNEL_FS_SOURCE;
    for f in ["fn create_file_bytes(&self", "fn create_dir(&self", "fn remove(&self"] {
        let body = &fs[fs.find(f).unwrap()..];
        let body = &body[..body.find("\n    }\n").unwrap()];
        assert!(body.contains("bump_directory_versions(&mut root_guard, &parent_path)"), "{f}");
    }
}

#[test]
fn j2_4_only_exact_test_program_paths_run_inits_elf_under_a_test_name() {
    let p = KERNEL_SYSCALL_PROCESS_SOURCE;
    let exec = &p[p.find("pub fn sys_exec_checked").unwrap()..];
    assert!(!exec.contains("path.contains(\"quota-test\")"));
    assert!(exec.contains("is_init_test_alias(&path)"));
}

// ---- Policy, pinned: what the operator panel's flag allows ----------------

/// The panel the kernel launched for the operator sends only `GOAL:` (typed
/// by the operator) and `CONFIG_UPDATED:` (after its setup wizard writes the
/// configuration). Its flag is nevertheless accepted for every operator
/// command, including CONFIRM, DENY and NEURAL_ARM. Today that is unused
/// authority, not a bypass: the panel ignores injected input and forwards no
/// agent text. Narrowing it is option (a) in the round-2 report.
#[test]
fn documents_j2_q_the_panel_flag_is_accepted_for_every_operator_command() {
    let panel = Some(ControlSender { pid: 300, flags: SENDER_ASSISTANT_PANEL });
    for command in [
        ControlCommand::Confirm(1),
        ControlCommand::Deny(1),
        ControlCommand::NeuralArm,
        ControlCommand::Goal("x".into()),
        ControlCommand::ConfigUpdated,
    ] {
        assert!(control_command_allowed(&command, panel), "{command:?}");
    }
    // What the panel actually sends.
    let sends: Vec<&str> = ASSISTANT_PANEL_SOURCE
        .match_indices("ipc_send(\"heliox\"")
        .map(|(i, _)| &ASSISTANT_PANEL_SOURCE[i..i + 60])
        .collect();
    assert_eq!(sends.len(), 2, "{sends:?}");
    assert!(sends.iter().any(|s| s.contains("b\"CONFIG_UPDATED:\"")));
    assert!(sends.iter().any(|s| s.contains("goal_msg")));
    assert!(ASSISTANT_PANEL_SOURCE.contains("let goal_msg = format!(\"GOAL:{}\", text);"));
    // ...and it drops injected keys before any of them.
    let input = &ASSISTANT_PANEL_SOURCE[ASSISTANT_PANEL_SOURCE.find("poll_window_input_marked").unwrap()..];
    assert!(input.find("if injected").unwrap() < input.find("ipc_send(").unwrap());
}
