// ============================================================================
// FerrumOS - Filesystem Syscalls
// ============================================================================
// Bridges userspace file I/O requests to the kernel VFS layer.
//
// Syscall ABI:
//   ReadFile(15):  rdi=path_ptr, rsi=path_len, rdx=buf_ptr, r10=buf_len
//   WriteFile(16): rdi=path_ptr, rsi=path_len, rdx=data_ptr, r10=data_len
// ============================================================================

extern crate alloc;

use super::{SyscallResult, SyscallStatus};
use alloc::string::String;

/// Maximum path length we'll accept from userspace.
const MAX_PATH_LEN: usize = 4096;
/// Maximum data size for a single read/write (4 MB).
const MAX_DATA_LEN: usize = 4 * 1024 * 1024;

/// Read a string from a userspace pointer. Returns None if the pointer
/// looks invalid or the resulting bytes are not valid UTF-8.
///
/// # Safety
/// The caller must ensure we are in a kernel context where the user
/// address space is accessible (identity-mapped or via phys_to_virt).
pub unsafe fn read_user_str(ptr: u64, len: u64) -> Option<String> {
    let len = len as usize;
    if len == 0 || len > MAX_PATH_LEN || !valid_user_range(ptr, len) {
        return None;
    }
    let bytes = copy_from_user(ptr, len)?;
    String::from_utf8(bytes).ok()
}

/// Copy `len` bytes at user address `ptr` into a new kernel buffer, inside a
/// `UserAccess` window (SMAP). The caller has checked the range. The buffer
/// is reserved before the window opens.
unsafe fn copy_from_user(ptr: u64, len: usize) -> Option<alloc::vec::Vec<u8>> {
    let mut out = alloc::vec::Vec::new();
    out.try_reserve_exact(len).ok()?;
    {
        let _window = crate::cpu_protect::UserAccess::open();
        core::ptr::copy_nonoverlapping(ptr as *const u8, out.as_mut_ptr(), len);
        out.set_len(len);
    }
    Some(out)
}

/// Read raw bytes from a userspace pointer. Returns None if the
/// pointer looks invalid or reaches into the kernel half.
///
/// # Safety
/// The caller must ensure we are in a kernel context where the user
/// address space is accessible (identity-mapped or via phys_to_virt).
pub unsafe fn read_user_bytes(ptr: u64, len: u64, cap: usize) -> Option<alloc::vec::Vec<u8>> {
    let len = len as usize;
    if len == 0 || len > cap || !valid_user_range(ptr, len) {
        return None;
    }
    // Fallible copy: caps go up to 4 MiB (WriteFile), and an allocation
    // failure in `Vec::from` aborts the kernel.
    copy_from_user(ptr, len)
}

/// True only for a non-empty range backed by the currently running ring-3
/// process. Kernel-half and unmapped-but-canonical pointers are both denied.
pub(crate) fn valid_user_range(ptr: u64, len: usize) -> bool {
    if ptr == 0 || len == 0 {
        return false;
    }
    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    pid != 0 && crate::process::user_range_is_mapped(pid, ptr, len)
}

/// `valid_user_range`, and the whole range is writable by the process. Use
/// for every buffer the kernel writes into, before any side effect.
pub(crate) fn valid_user_write_range(ptr: u64, len: usize) -> bool {
    if ptr == 0 || len == 0 {
        return false;
    }
    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    pid != 0 && crate::process::user_range_is_writable(pid, ptr, len)
}

/// Copy bytes from a kernel buffer into a userspace buffer.
///
/// # Safety
/// The caller must ensure `dst` points to writable user memory of at
/// least `max_len` bytes.
pub(super) unsafe fn copy_to_user(dst: u64, src: &[u8], max_len: usize) -> usize {
    let to_copy = src.len().min(max_len);
    if to_copy > 0 {
        if !valid_user_write_range(dst, to_copy) {
            return 0;
        }
        let _window = crate::cpu_protect::UserAccess::open();
        core::ptr::copy_nonoverlapping(src.as_ptr(), dst as *mut u8, to_copy);
    }
    to_copy
}

fn valid_absolute_path(path: &str) -> bool {
    path.starts_with('/')
        && path.len() <= MAX_PATH_LEN
        && !path
            .split('/')
            .any(|component| component == "." || component == "..")
}

pub(crate) fn is_package_control_path(path: &str) -> bool {
    let mut components = path.split('/').filter(|component| !component.is_empty());
    matches!(components.next(), Some("disk"))
        && matches!(components.next(), Some("pkgs") | Some("pkgs-available"))
}

/// The daemon's startup test hooks read their triggers from here (fi2 Q4).
pub const SHELL_ONLY_DIR: &str = "/tmp/heliox-hooks";

/// True for `/tmp/heliox-hooks` and everything beneath it (any number of
/// slashes). No ring-3 process may create or write anything there: only the
/// kernel shell's `write` command (which does not go through a syscall) can
/// plant a hook trigger. Removing is allowed; it can only stop a hook.
pub fn is_shell_only_path(path: &str) -> bool {
    let mut components = path.split('/').filter(|component| !component.is_empty());
    matches!(components.next(), Some("tmp")) && matches!(components.next(), Some("heliox-hooks"))
}

/// Files only the kernel writes: the audit log it flushes, and the account
/// table whose profile the shell session's capabilities are read from on
/// every command. Any `fs:write` holder could rewrite or delete the audit
/// trail, or set a logged-in user's profile to root (fi2 kernel audit).
pub const KERNEL_RECORD_PATHS: [&str; 2] = ["/disk/heliox/audit.log", "/disk/accounts.txt"];

fn components(path: &str) -> impl Iterator<Item = &str> {
    path.split('/').filter(|component| !component.is_empty())
}

/// True for a kernel record file itself (any number of slashes) and, when
/// `ancestors` is set, for every directory above one: RamFS removes a
/// directory with everything in it.
pub fn is_kernel_record_path(path: &str, ancestors: bool) -> bool {
    KERNEL_RECORD_PATHS.iter().any(|record| {
        let mut wanted = components(record);
        let mut given = components(path);
        loop {
            match (given.next(), wanted.next()) {
                (None, None) => return true,
                (None, Some(_)) => return ancestors,
                (Some(_), None) => return false,
                (Some(a), Some(b)) if a != b => return false,
                _ => {}
            }
        }
    })
}

/// Refuses a ring-3 create, write or delete of a kernel record (and, for a
/// delete, of a directory above one).
fn refuse_kernel_record(path: &str, delete: bool) -> bool {
    if is_kernel_record_path(path, delete) {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            &alloc::format!("change to a kernel record denied: {}", path),
        );
        return true;
    }
    false
}

fn refuse_shell_only(path: &str) -> bool {
    if is_shell_only_path(path) {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            &alloc::format!("write to a shell-only path denied: {}", path),
        );
        return true;
    }
    false
}

pub(super) fn authorize_path(path: &str, write: bool, held_capabilities: &[String]) -> bool {
    if !valid_absolute_path(path) {
        return false;
    }

    let resource = if write { "fs:write:*" } else { "fs:read:*" };
    if !crate::security::has_capability(held_capabilities, resource) {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            &alloc::format!(
                "filesystem {} denied: {}",
                if write { "write" } else { "read" },
                path
            ),
        );
        return false;
    }

    if is_package_control_path(path)
        && !crate::security::holds_capability_token(held_capabilities, "cap:pkg:manage")
    {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            &alloc::format!("package repository path denied: {}", path),
        );
        return false;
    }

    true
}

/// `sys_read_file` — Read a file from the VFS into a userspace buffer.
///
/// args[0] = path_ptr (user pointer to path string)
/// args[1] = path_len
/// args[2] = buf_ptr  (user pointer to destination buffer)
/// args[3] = buf_len
///
/// Returns: number of bytes written to buf, or error.
pub fn sys_read_file(args: [u64; 6], held_capabilities: &[String]) -> SyscallResult {
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    if !authorize_path(&path, false, held_capabilities) {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    let buf_ptr = args[2];
    let buf_len = args[3] as usize;
    if buf_len == 0 || buf_len > MAX_DATA_LEN || !valid_user_write_range(buf_ptr, buf_len) {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let Some(mut temp_buf) = crate::fs::try_zeroed_vec(buf_len) else {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    };
    match crate::fs::read_file_offset(&path, 0, &mut temp_buf) {
        Ok(bytes_read) => {
            let copied = unsafe { copy_to_user(buf_ptr, &temp_buf[..bytes_read], bytes_read) };
            if copied == bytes_read {
                SyscallResult::ok(copied as u64)
            } else {
                SyscallResult::err(SyscallStatus::InvalidArgument)
            }
        }
        Err(e) => {
            crate::println!("[kernel-read] read {} failed: {}", path, e);
            // File not found or read error
            SyscallResult::err(SyscallStatus::InvalidArgument)
        }
    }
}

/// `sys_write_file` — Write data from userspace to a file via the VFS.
///
/// args[0] = path_ptr (user pointer to path string)
/// args[1] = path_len
/// args[2] = data_ptr (user pointer to data to write)
/// args[3] = data_len
///
/// Returns: 0 on success, or error.
pub fn sys_write_file(args: [u64; 6], held_capabilities: &[String]) -> SyscallResult {
    sys_write_file_checked(args, held_capabilities, None)
}

/// The result of a version-guarded filesystem operation.
fn guarded_result(result: Result<(), crate::fs::GuardError>) -> SyscallResult {
    match result {
        Ok(()) => SyscallResult::ok(0),
        Err(crate::fs::GuardError::VersionMismatch) => {
            SyscallResult::err(SyscallStatus::VersionMismatch)
        }
        Err(crate::fs::GuardError::Failed(_)) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// WriteFile, and WriteFileIfVersion when `expected` is given (fi1 K3: the
/// approved write runs only on the version the operator approved).
pub fn sys_write_file_checked(
    args: [u64; 6],
    held_capabilities: &[String],
    expected: Option<u64>,
) -> SyscallResult {
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    if !authorize_path(&path, true, held_capabilities)
        || refuse_shell_only(&path)
        || refuse_kernel_record(&path, false)
    {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    let data_ptr = args[2];
    let data_len = args[3] as usize;
    if data_ptr == 0 || data_len > MAX_DATA_LEN {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let data = match unsafe { read_user_bytes(data_ptr as u64, data_len as u64, MAX_DATA_LEN) } {
        Some(data) => data,
        None if data_len == 0 => alloc::vec::Vec::new(),
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    // RamFS content is charged to the writing process (heap ledger).
    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    if let Some(expected) = expected {
        return guarded_result(crate::memory::ledger::with_fs_owner(pid, || {
            crate::fs::write_file_if_version(&path, &data, expected)
        }));
    }
    match crate::memory::ledger::with_fs_owner(pid, || crate::fs::create_file_bytes(&path, &data)) {
        Ok(()) => SyscallResult::ok(0),
        Err(_e) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// `sys_read_dir` — List directory contents via the VFS.
///
/// args[0] = path_ptr (user pointer to directory path)
/// args[1] = path_len
/// args[2] = buf_ptr  (user pointer to destination buffer)
/// args[3] = buf_len
///
/// Returns: number of bytes written to buf (newline-separated entry names),
/// or error.
pub fn sys_read_dir(args: [u64; 6], held_capabilities: &[String]) -> SyscallResult {
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    if !authorize_path(&path, false, held_capabilities) {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    let buf_ptr = args[2];
    let buf_len = args[3] as usize;
    if buf_len == 0 || buf_len > MAX_DATA_LEN || !valid_user_write_range(buf_ptr, buf_len) {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    match crate::fs::list_dir(&path) {
        Ok(entries) => {
            // Serialize directory entries as newline-separated names
            // with a type prefix: "d <name>" for directories, "f <name>" for files
            let mut output = String::new();
            for entry in &entries {
                let prefix = if entry.is_dir { "d" } else { "f" };
                output.push_str(prefix);
                output.push(' ');
                output.push_str(&entry.name);
                output.push('\n');
            }
            let bytes = output.as_bytes();
            let copied = unsafe { copy_to_user(buf_ptr, bytes, buf_len) };
            if copied == bytes.len().min(buf_len) {
                SyscallResult::ok(copied as u64)
            } else {
                SyscallResult::err(SyscallStatus::InvalidArgument)
            }
        }
        Err(_e) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// `sys_create_dir` — Create a directory via the VFS.
///
/// args[0] = path_ptr (user pointer to path string)
/// args[1] = path_len
///
/// Returns: 0 on success, or error.
pub fn sys_create_dir(args: [u64; 6], held_capabilities: &[String]) -> SyscallResult {
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    if !authorize_path(&path, true, held_capabilities)
        || refuse_shell_only(&path)
        || refuse_kernel_record(&path, false)
    {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    match crate::fs::create_dir(&path) {
        Ok(()) => SyscallResult::ok(0),
        Err(_e) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// `sys_delete_file` — Remove a file or directory via the VFS.
///
/// args[0] = path_ptr (user pointer to path string)
/// args[1] = path_len
///
/// Returns: 0 on success, or error.
pub fn sys_delete_file(args: [u64; 6], held_capabilities: &[String]) -> SyscallResult {
    sys_delete_file_checked(args, held_capabilities, None)
}

/// DeleteFile, and DeleteFileIfVersion when `expected` is given.
pub fn sys_delete_file_checked(
    args: [u64; 6],
    held_capabilities: &[String],
    expected: Option<u64>,
) -> SyscallResult {
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    if !authorize_path(&path, true, held_capabilities) || refuse_kernel_record(&path, true) {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }
    if let Some(expected) = expected {
        return guarded_result(crate::fs::remove_if_version(&path, expected));
    }

    match crate::fs::remove(&path) {
        Ok(()) => SyscallResult::ok(0),
        Err(_e) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// `sys_file_version` — The change counter of the node at a path.
///
/// args[0] = path_ptr, args[1] = path_len
///
/// Returns the node's version (non-zero), 0 when nothing exists at the path,
/// PermissionDenied without read access, and InvalidArgument when the kernel
/// cannot establish a version (bad path, unmounted prefix, I/O error). A
/// caller that binds an approval to a file treats the error as a refusal.
pub fn sys_file_version(args: [u64; 6], held_capabilities: &[String]) -> SyscallResult {
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    if !authorize_path(&path, false, held_capabilities) {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }
    match crate::fs::file_version(&path) {
        Ok(Some(version)) => SyscallResult::ok(version),
        Ok(None) => SyscallResult::ok(0),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}
