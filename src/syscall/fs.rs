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
    let slice = core::slice::from_raw_parts(ptr as *const u8, len);
    core::str::from_utf8(slice).ok().map(String::from)
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
    let slice = core::slice::from_raw_parts(ptr as *const u8, len);
    Some(alloc::vec::Vec::from(slice))
}

/// True only for a non-empty range backed by the currently running ring-3
/// process. Kernel-half and unmapped-but-canonical pointers are both denied.
pub(super) fn valid_user_range(ptr: u64, len: usize) -> bool {
    if ptr == 0 || len == 0 {
        return false;
    }
    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    pid != 0 && crate::process::user_range_is_mapped(pid, ptr, len)
}

/// Copy bytes from a kernel buffer into a userspace buffer.
///
/// # Safety
/// The caller must ensure `dst` points to writable user memory of at
/// least `max_len` bytes.
pub(super) unsafe fn copy_to_user(dst: u64, src: &[u8], max_len: usize) -> usize {
    let to_copy = src.len().min(max_len);
    if to_copy > 0 {
        if !valid_user_range(dst, to_copy) {
            return 0;
        }
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

fn is_package_control_path(path: &str) -> bool {
    let mut components = path.split('/').filter(|component| !component.is_empty());
    matches!(components.next(), Some("disk"))
        && matches!(components.next(), Some("pkgs") | Some("pkgs-available"))
}

fn authorize_path(path: &str, write: bool, held_capabilities: &[String]) -> bool {
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
    if buf_len == 0 || buf_len > MAX_DATA_LEN || !valid_user_range(buf_ptr, buf_len) {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let mut temp_buf = alloc::vec![0u8; buf_len];
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
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    if !authorize_path(&path, true, held_capabilities) {
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
    match crate::fs::create_file_bytes(&path, &data) {
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
    if buf_len == 0 || buf_len > MAX_DATA_LEN || !valid_user_range(buf_ptr, buf_len) {
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
    if !authorize_path(&path, true, held_capabilities) {
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
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    if !authorize_path(&path, true, held_capabilities) {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    match crate::fs::remove(&path) {
        Ok(()) => SyscallResult::ok(0),
        Err(_e) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}
