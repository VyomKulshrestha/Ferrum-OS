// ============================================================================
// FerrumOS - Clipboard Syscalls
// ============================================================================

use super::{SyscallResult, SyscallStatus};

/// Copy the current shared clipboard into a caller-owned buffer.
/// args[0]=buffer pointer, args[1]=capacity. Returns bytes copied.
pub fn sys_clipboard_read(args: [u64; 6]) -> SyscallResult {
    let out_ptr = args[0];
    let out_len = args[1] as usize;
    if out_len > crate::clipboard::MAX_CLIPBOARD_BYTES || (out_len > 0 && out_ptr == 0) {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let snapshot = crate::clipboard::snapshot();
    let to_copy = snapshot.bytes.len().min(out_len);
    if to_copy > 0 {
        if !super::fs::valid_user_range(out_ptr, to_copy) {
            return SyscallResult::err(SyscallStatus::InvalidArgument);
        }
        if unsafe { super::fs::copy_to_user(out_ptr, &snapshot.bytes, to_copy) } != to_copy {
            return SyscallResult::err(SyscallStatus::InvalidArgument);
        }
    }
    SyscallResult::ok(to_copy as u64)
}

/// Replace the current shared clipboard.
/// args[0]=data pointer, args[1]=length. Returns the new generation.
pub fn sys_clipboard_write(args: [u64; 6]) -> SyscallResult {
    let bytes = match unsafe {
        super::fs::read_user_bytes(args[0], args[1], crate::clipboard::MAX_CLIPBOARD_BYTES)
    } {
        Some(bytes) => bytes,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    match crate::clipboard::write(pid, &bytes) {
        Ok(generation) => SyscallResult::ok(generation),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}
