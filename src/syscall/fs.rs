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

use alloc::string::String;
use super::{SyscallResult, SyscallStatus};

/// Maximum path length we'll accept from userspace.
const MAX_PATH_LEN: usize = 4096;
/// Maximum data size for a single read/write (1 MB).
const MAX_DATA_LEN: usize = 1024 * 1024;

/// Read a string from a userspace pointer. Returns None if the pointer
/// looks invalid or the resulting bytes are not valid UTF-8.
///
/// # Safety
/// The caller must ensure we are in a kernel context where the user
/// address space is accessible (identity-mapped or via phys_to_virt).
pub unsafe fn read_user_str(ptr: u64, len: u64) -> Option<String> {
    let len = len as usize;
    if len == 0 || len > MAX_PATH_LEN || ptr == 0 {
        return None;
    }
    let end = ptr.saturating_add(len as u64);
    if end >= 0x0000_7FFF_FFFF_FFFF {
        return None; // Prevent accessing kernel space
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
    if len == 0 || len > cap || ptr == 0 {
        return None;
    }
    let end = ptr.saturating_add(len as u64);
    if end >= 0x0000_7FFF_FFFF_FFFF {
        return None; // Prevent accessing kernel space
    }
    let slice = core::slice::from_raw_parts(ptr as *const u8, len);
    Some(alloc::vec::Vec::from(slice))
}

/// Copy bytes from a kernel buffer into a userspace buffer.
///
/// # Safety
/// The caller must ensure `dst` points to writable user memory of at
/// least `max_len` bytes.
unsafe fn copy_to_user(dst: u64, src: &[u8], max_len: usize) -> usize {
    let to_copy = src.len().min(max_len);
    if to_copy > 0 && dst != 0 {
        let end = dst.saturating_add(to_copy as u64);
        if end >= 0x0000_7FFF_FFFF_FFFF {
            return 0; // Prevent writing to kernel space
        }
        core::ptr::copy_nonoverlapping(src.as_ptr(), dst as *mut u8, to_copy);
    }
    to_copy
}

/// `sys_read_file` — Read a file from the VFS into a userspace buffer.
///
/// args[0] = path_ptr (user pointer to path string)
/// args[1] = path_len
/// args[2] = buf_ptr  (user pointer to destination buffer)
/// args[3] = buf_len
///
/// Returns: number of bytes written to buf, or error.
pub fn sys_read_file(args: [u64; 6]) -> SyscallResult {
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    let buf_ptr = args[2];
    let buf_len = args[3] as usize;
    if buf_ptr == 0 || buf_len == 0 || buf_len > MAX_DATA_LEN {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    match crate::fs::read_file(&path) {
        Ok(content) => {
            let bytes = content.as_bytes();
            let copied = unsafe { copy_to_user(buf_ptr, bytes, buf_len) };
            SyscallResult::ok(copied as u64)
        }
        Err(_e) => {
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
pub fn sys_write_file(args: [u64; 6]) -> SyscallResult {
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    let data_ptr = args[2];
    let data_len = args[3] as usize;
    if data_ptr == 0 || data_len > MAX_DATA_LEN {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    // Read data from userspace
    let content = if data_len == 0 {
        String::new()
    } else {
        let slice = unsafe {
            core::slice::from_raw_parts(data_ptr as *const u8, data_len)
        };
        match core::str::from_utf8(slice) {
            Ok(s) => String::from(s),
            Err(_) => return SyscallResult::err(SyscallStatus::InvalidArgument),
        }
    };

    match crate::fs::create_file(&path, &content) {
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
pub fn sys_read_dir(args: [u64; 6]) -> SyscallResult {
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    let buf_ptr = args[2];
    let buf_len = args[3] as usize;
    if buf_ptr == 0 || buf_len == 0 || buf_len > MAX_DATA_LEN {
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
            SyscallResult::ok(copied as u64)
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
pub fn sys_create_dir(args: [u64; 6]) -> SyscallResult {
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

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
pub fn sys_delete_file(args: [u64; 6]) -> SyscallResult {
    let path = match unsafe { read_user_str(args[0], args[1]) } {
        Some(p) => p,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    match crate::fs::remove(&path) {
        Ok(()) => SyscallResult::ok(0),
        Err(_e) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}
