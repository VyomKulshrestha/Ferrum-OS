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

    // Read the ELF binary from the VFS
    let elf_content = match crate::fs::read_file(&path) {
        Ok(content) => content,
        Err(_) => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    let elf_bytes = elf_content.as_bytes();
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

    // Register the process in the global process table
    crate::process::register(process);

    // Register with the scheduler so it gets scheduled
    crate::scheduler::register_user(
        pid,
        &alloc::format!("user-{}", name),
        crate::scheduler::Priority::Normal,
        kernel_rsp,
        cr3,
    );

    // Seed the scheduler context with the ELF entry point and user stack
    let user_rsp = crate::process::pid_user_stack(pid)
        .map(|v| v.as_u64())
        .unwrap_or(0);
    let ctx = crate::scheduler::TaskContext::ring3(entry, user_rsp);
    crate::scheduler::write_context(pid, ctx);

    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::ProcessSpawned,
        alloc::format!("sys_exec: spawned '{}' as pid {}", path, pid).as_str(),
    );

    SyscallResult::ok(pid)
}
