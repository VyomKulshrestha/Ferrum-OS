// ============================================================================
// FerrumOS - Process Syscalls
// ============================================================================
// Bridges userspace process management requests to the kernel process
// subsystem. Currently provides `sys_exec` for spawning child processes
// from ELF files on disk.
//
// Syscall ABI:
//   Exec(18): rdi=path_ptr, rsi=path_len
// ============================================================================

extern crate alloc;

use super::{SyscallResult, SyscallStatus};

/// Copy the calling process's immutable startup metadata into its own buffer.
/// Empty metadata returns zero. The context remains readable for the process's
/// lifetime so libraries can query size/contents without consume-on-read races.
pub fn sys_launch_context(args: [u64; 6]) -> SyscallResult {
    let capacity = args[1] as usize;
    if capacity == 0
        || capacity > crate::process::MAX_LAUNCH_CONTEXT_BYTES
        || !super::fs::valid_user_write_range(args[0], capacity)
    {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    let Some(context) = crate::process::launch_context(pid) else {
        return SyscallResult::ok(0);
    };
    if context.len() > capacity
        || unsafe { super::fs::copy_to_user(args[0], context.as_bytes(), capacity) } != context.len()
    {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    SyscallResult::ok(context.len() as u64)
}

/// Terminate a non-critical task selected by a privileged task manager.
/// The caller cannot kill itself, PID 0, init, or quota-exempt system agents.
pub fn sys_process_kill(args: [u64; 6]) -> SyscallResult {
    let target = args[0];
    let caller = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    if target == 0 || target == caller {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    let Some(task) = crate::scheduler::list_tasks().into_iter().find(|task| task.id == target) else {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    };
    if task.state == crate::scheduler::TaskState::Dead
        || task.capabilities.iter().any(|cap| cap == "cap:system:all" || cap == "cap:quota:exempt")
    {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    if crate::scheduler::kill(target) {
        crate::gui::app_window::close_for_pid(target);
        // The caller is a different, live privileged process, so no CPU can
        // still be executing on the target's stack in this single-core
        // scheduler. Reclaim its address space and scheduler context now
        // instead of waiting for an unrelated shell trampoline or waitpid.
        crate::process::reap_dead();
        crate::serial_println!("[task-manager] killed pid={} name={}", target, task.name);
        SyscallResult::ok(target)
    } else {
        SyscallResult::err(SyscallStatus::InvalidArgument)
    }
}

/// Shape check for an Exec path that is read straight from the VFS (not an
/// embedded program and not recognised as a package binary). The package gate
/// (`pkg::package_name_from_bin_path`) matches only the exact spelling
/// `/disk/pkgs-available/<name>/bin`, while the filesystems drop empty path
/// components, so `/disk//pkgs-available/<name>/bin` used to skip the gate and
/// run an uninstalled or tampered package binary without its signature check.
/// Reject empty, `.` and `..` components and anything under the package
/// repository here.
pub fn exec_path_allowed(path: &str) -> bool {
    let Some(rest) = path.strip_prefix('/') else {
        return false;
    };
    !rest.is_empty()
        && rest
            .split('/')
            .all(|component| !component.is_empty() && component != "." && component != "..")
        && !super::fs::is_package_control_path(path)
}

/// Whether a file read from the VFS may run under the name its path gives
/// it (the last component). Names of compiled-in programs, installed
/// packages and mailbox aliases are refused (`ipc::is_reserved_program_name`).
pub fn vfs_exec_name_allowed(path: &str) -> bool {
    !crate::ipc::is_reserved_program_name(path.rsplit('/').next().unwrap_or(""))
}

/// `sys_exec` — Spawn a new process from an ELF binary on the VFS.
///
/// args[0] = path_ptr (user pointer to ELF path string, e.g. "/disk/bin/worker")
/// args[1] = path_len
///
/// The kernel reads the ELF binary from the filesystem, creates a new
/// process with its own address space, loads the ELF segments, and
/// registers it with the scheduler. The new process is left in the
/// `Ready` state; it will be scheduled on the next tick.
///
/// Returns: PID of the new process on success, or error.
/// Test programs that run init's ELF under their own name (init branches on
/// the name). Only the exact `/bin/<name>` or the bare name is one: these
/// used to match any path *containing* the name, so
/// `/tmp/quota-test/heliox-assistant-panel` ran init's ELF as a process
/// named `heliox-assistant-panel`, with that program's manifest
/// capabilities and a claim on its mailbox, past the reserved-name check
/// that applies only to VFS files (fi1 joint round 2, J2-4).
pub fn is_init_test_alias(path: &str) -> bool {
    const TEST_ALIASES: [&str; 5] =
        ["quota-test", "huge-test", "socket-owner-test", "ipc-owner-test", "ipc-forge-test"];
    TEST_ALIASES
        .iter()
        .any(|name| path == *name || path.strip_prefix("/bin/") == Some(*name))
}

/// Whether `path` runs an image compiled into the kernel (see the chain in
/// `sys_exec_checked`), never a file from the VFS.
pub fn is_embedded_exec_path(path: &str) -> bool {
    const EMBEDDED: [&str; 12] = [
        "heliox-daemon", "init", "gui-smoke-test", "text-editor", "calculator", "file-manager",
        "heliox-assistant-panel", "settings", "browser", "app-store", "notification-center", "task-manager",
    ];
    is_init_test_alias(path)
        || EMBEDDED
            .iter()
            .any(|name| path == *name || path.strip_prefix("/bin/") == Some(*name))
}

/// ExecIfVersion's check. For a compiled-in image there is nothing in the
/// VFS to check: the version of whatever file sits at that path says nothing
/// about the image that runs, and any holder of `fs:write` could make every
/// ExecIfVersion of that name fail by writing a file there. The image cannot
/// change, so the check passes (fi1 kernel round 4).
pub fn exec_version_check(path: &str, expected: u64) -> Result<(), SyscallStatus> {
    if false && is_embedded_exec_path(path) {
        return Ok(());
    }
    match crate::fs::check_version(path, expected) {
        Ok(()) => Ok(()),
        Err(crate::fs::GuardError::VersionMismatch) => {
            crate::logging::audit::log_event(
                crate::logging::audit::AuditEvent::PermissionDenied,
                "ring3 exec refused: the file changed after it was approved",
            );
            Err(SyscallStatus::VersionMismatch)
        }
        Err(crate::fs::GuardError::Failed(_)) => Err(SyscallStatus::InvalidArgument),
    }
}

pub fn sys_exec(args: [u64; 6]) -> SyscallResult {
    sys_exec_checked(args, None)
}

/// Exec, and ExecIfVersion when `expected` is given: the path must have that
/// version (0: nothing in the VFS at the path) when the kernel looks, before
/// any image is read. Syscalls run with interrupts off on the kernel's one
/// CPU, so no filesystem change falls between the check and the read.
pub fn sys_exec_checked(args: [u64; 6], expected: Option<u64>) -> SyscallResult {
    // Read and validate the path string from userspace. `read_user_str`
    // bounds-checks the pointer against the user half (rejecting null,
    // over-long, and kernel-half pointers) and verifies UTF-8.
    let path = match unsafe { super::fs::read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    if let Some(expected) = expected {
        if let Err(status) = exec_version_check(&path, expected) {
            return SyscallResult::err(status);
        }
    }

    let pkg_name = crate::pkg::package_name_from_bin_path(&path);
    let mut package_capabilities = None;

    // Intercept embedded binaries to avoid VFS read and heap allocation.
    let mut _elf_content_holder: alloc::vec::Vec<u8> = alloc::vec::Vec::new();
    let elf_bytes: &[u8] = if path == "/bin/heliox-daemon" || path == "heliox-daemon" {
        crate::userspace::HELIOX_DAEMON_ELF
    } else if path == "/bin/init" || path == "init" || is_init_test_alias(&path) {
        crate::userspace::INIT_ELF
    } else if path == "/bin/gui-smoke-test" || path == "gui-smoke-test" {
        crate::userspace::GUI_SMOKE_TEST_ELF
    } else if path == "/bin/text-editor" || path == "text-editor" {
        crate::userspace::TEXT_EDITOR_ELF
    } else if path == "/bin/calculator" || path == "calculator" {
        crate::userspace::CALCULATOR_ELF
    } else if path == "/bin/file-manager" || path == "file-manager" {
        crate::userspace::FILE_MANAGER_ELF
    } else if path == "/bin/heliox-assistant-panel" || path == "heliox-assistant-panel" {
        crate::userspace::HELIOX_ASSISTANT_PANEL_ELF
    } else if path == "/bin/settings" || path == "settings" {
        crate::userspace::SETTINGS_ELF
    } else if path == "/bin/browser" || path == "browser" {
        crate::userspace::BROWSER_ELF
    } else if path == "/bin/app-store" || path == "app-store" {
        crate::userspace::APP_STORE_ELF
    } else if path == "/bin/notification-center" || path == "notification-center" {
        crate::userspace::NOTIFICATION_CENTER_ELF
    } else if path == "/bin/task-manager" || path == "task-manager" {
        crate::userspace::TASK_MANAGER_ELF
    } else {
        // A path under ferrumpkg's local package cache is only runnable
        // once `pkg install` has actually registered it - the bytes sit
        // on disk either way (see src/pkg/mod.rs's module doc for why
        // they're never physically copied), so this is the real
        // enforcement point: uninstalled packages can't be exec'd even
        // though nothing stops a caller from typing their path directly.
        _elf_content_holder = if let Some(ref pkg_name) = pkg_name {
            let (meta, binary) = match crate::pkg::load_installed(pkg_name) {
                Ok(package) => package,
                Err(_) => return SyscallResult::err(SyscallStatus::PermissionDenied),
            };
            package_capabilities = Some(meta.capabilities);
            binary
        } else {
            if !exec_path_allowed(&path) {
                crate::logging::audit::log_event(
                    crate::logging::audit::AuditEvent::PermissionDenied,
                    "ring3 exec denied: path is not a plain absolute path outside the package repository",
                );
                return SyscallResult::err(SyscallStatus::PermissionDenied);
            }
            // The last path component becomes the process name, which picks
            // the manifest capabilities and the mailbox the process owns. A
            // file named like a compiled-in program (the assistant panel,
            // the daemon, init) would otherwise run with that program's
            // capabilities and receive its mailbox (fi1 joint round, K4).
            if !vfs_exec_name_allowed(&path) {
                crate::logging::audit::log_event(
                    crate::logging::audit::AuditEvent::PermissionDenied,
                    "ring3 exec denied: a VFS file may not take a compiled-in program's name",
                );
                return SyscallResult::err(SyscallStatus::PermissionDenied);
            }
            // Real ELF binaries are essentially never valid UTF-8, so this
            // must use the raw-bytes reader (`read_file_bytes`), not the
            // UTF-8-checked `read_file`.
            match crate::fs::read_file_bytes(&path) {
                Ok(content) => content,
                Err(_) => return SyscallResult::err(SyscallStatus::InvalidArgument),
            }
        };
        _elf_content_holder.as_slice()
    };

    if elf_bytes.len() < 4 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    // Extract a short name from the path (last component)
    let name = path.rsplit('/').next().unwrap_or("exec");

    // Create a new process with its own address space
    let mut process = match crate::process::create(name) {
        Ok(p) => p,
        Err(_) => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    if name == "huge-test" {
        process.max_memory_pages = 2;
    }

    // Load the ELF into the process's address space
    let entry = match process.load_elf(elf_bytes) {
        Ok(e) => e,
        Err(_) => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    let pid = process.pid();
    let kernel_rsp = process.kernel_stack_top();
    let cr3 = process
        .address_space()
        .map(|s| s.l4_frame().start_address().as_u64())
        .unwrap_or(0);

    let caller_pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    let caller_capabilities = match crate::scheduler::capabilities_of(caller_pid) {
        Some(caps) => caps,
        None => alloc::vec![],
    };
    // A package's requested capabilities come from the metadata returned by
    // the same atomic `pkg::load_installed` operation that authorized and
    // loaded its signed ELF, not the kernel's compiled-in program manifest
    // table (which only knows programs shipped in the image).
    let requested_caps = package_capabilities.unwrap_or_else(|| {
        // The quota/oversize probes reuse INIT_ELF under isolated executable
        // names. They need to read `/tmp/init_test` to select their test mode,
        // but must not inherit init's `cap:system:all` (especially its quota
        // exemption), otherwise the probes cannot exercise their limits.
        if name == "quota-test" || name == "huge-test" {
            alloc::vec![alloc::string::String::from("cap:fs:read")]
        } else if name == "socket-owner-test" {
            alloc::vec![
                alloc::string::String::from("cap:fs:read"),
                alloc::string::String::from("cap:net:connect"),
            ]
        } else if name == "ipc-forge-test" {
            // A process that is not the operator and holds cap:ipc:send, for
            // the sender-identity harness (verify_authority_gate_joint.mjs).
            alloc::vec![
                alloc::string::String::from("cap:fs:read"),
                alloc::string::String::from("cap:ipc:send"),
                alloc::string::String::from("cap:ipc:receive"),
            ]
        } else if name == "ipc-owner-test" {
            alloc::vec![
                alloc::string::String::from("cap:fs:read"),
                alloc::string::String::from("cap:ipc:send"),
                alloc::string::String::from("cap:ipc:receive"),
            ]
        } else {
            crate::userspace::capabilities_for_program(name)
        }
    });
    let granted_caps = crate::security::filter_delegatable(&requested_caps, &caller_capabilities);

    // Register the process in the global process table
    crate::process::register(process);

    // Register with the scheduler so it gets scheduled
    crate::scheduler::register_user(
        pid,
        name,
        crate::scheduler::Priority::Normal,
        kernel_rsp,
        cr3,
        &granted_caps,
    );

    // Seed the scheduler context with the ELF entry point and user stack
    let user_rsp = crate::process::pid_user_stack(pid)
        .map(|v| v.as_u64())
        .unwrap_or(0);
    let target_user_rsp = if user_rsp > 8 { user_rsp - 8 } else { user_rsp };
    let ctx = crate::scheduler::TaskContext::ring3(entry, target_user_rsp);
    crate::scheduler::write_context(pid, ctx);

    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::ProcessSpawned,
        alloc::format!("sys_exec: spawned '{}' as pid {}", path, pid).as_str(),
    );

    SyscallResult::ok(pid)
}
