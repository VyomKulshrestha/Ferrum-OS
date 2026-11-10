// ============================================================================
// FerrumOS - Memory Mapping (mmap) Syscalls
// ============================================================================

extern crate alloc;

use super::{SyscallResult, SyscallStatus};

/// `sys_mmap` — Create a file-backed memory mapping.
///
/// args[0] = path_ptr (user pointer to path string)
/// args[1] = path_len
/// args[2] = len
/// args[3] = flags
///
/// Returns: virtual address base on success, or error.
pub fn sys_mmap(args: [u64; 6], held_capabilities: &[alloc::string::String]) -> SyscallResult {
    let path = match unsafe { crate::syscall::fs::read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    // Faulting a mapped page reads the file's contents into the caller's
    // address space, so mapping is a file read and needs the same path
    // authorization as ReadFile (fs:read, no dot components, and
    // cap:pkg:manage for the package repository).
    if !crate::syscall::fs::authorize_path(&path, false, held_capabilities) {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    let len = args[2];
    let flags = args[3];

    if len == 0 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    // Verify the file exists by stating it
    if crate::fs::stat(&path).is_err() {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    if pid == 0 {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    match crate::process::register_mmap(pid, path, len, flags) {
        Ok(vaddr) => SyscallResult::ok(vaddr.as_u64()),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}
