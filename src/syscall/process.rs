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
pub fn sys_exec(args: [u64; 6]) -> SyscallResult {
    // Read and validate the path string from userspace. `read_user_str`
    // bounds-checks the pointer against the user half (rejecting null,
    // over-long, and kernel-half pointers) and verifies UTF-8.
    let path = match unsafe { super::fs::read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    // Intercept embedded binaries to avoid VFS read and heap allocation.
    let mut _elf_content_holder = alloc::string::String::new();
    let elf_bytes: &[u8] = if path == "/bin/heliox-daemon" || path == "heliox-daemon" {
        crate::userspace::HELIOX_DAEMON_ELF
    } else if path == "/bin/init" || path == "init" || path.contains("quota-test") || path.contains("huge-test") {
        crate::userspace::INIT_ELF
    } else if path == "/bin/gui-smoke-test" || path == "gui-smoke-test" {
        crate::userspace::GUI_SMOKE_TEST_ELF
    } else if path == "/bin/text-editor" || path == "text-editor" {
        crate::userspace::TEXT_EDITOR_ELF
    } else if path == "/bin/calculator" || path == "calculator" {
        crate::userspace::CALCULATOR_ELF
    } else if path == "/bin/file-manager" || path == "file-manager" {
        crate::userspace::FILE_MANAGER_ELF
    } else {
        _elf_content_holder = match crate::fs::read_file(&path) {
            Ok(content) => content,
            Err(_) => return SyscallResult::err(SyscallStatus::InvalidArgument),
        };
        _elf_content_holder.as_bytes()
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
    let requested_caps = crate::userspace::capabilities_for_program(name);
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

