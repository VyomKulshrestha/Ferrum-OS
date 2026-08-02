// ============================================================================
// FerrumOS - Notification Syscalls
// ============================================================================

use super::{SyscallResult, SyscallStatus};

/// Post a notification. args[0..3]=title ptr/len, body ptr/len.
pub fn sys_notification_post(args: [u64; 6]) -> SyscallResult {
    let title = match unsafe { super::fs::read_user_str(args[0], args[1]) } {
        Some(value) => value,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    let body = match unsafe { super::fs::read_user_str(args[2], args[3]) } {
        Some(value) => value,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    match crate::notification::post(pid, &title, &body) {
        Ok(id) => {
            crate::gui::compositor::request_redraw();
            SyscallResult::ok(id)
        }
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// Serialize newest-first notification history into a caller buffer.
pub fn sys_notification_list(args: [u64; 6]) -> SyscallResult {
    let out_ptr = args[0];
    let out_len = args[1] as usize;
    if out_len > crate::notification::MAX_LIST_BYTES || (out_len > 0 && out_ptr == 0) {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    let bytes = crate::notification::serialize();
    let to_copy = bytes.len().min(out_len);
    if to_copy > 0 {
        let end = out_ptr.saturating_add(to_copy as u64);
        if end >= 0x0000_7FFF_FFFF_FFFF {
            return SyscallResult::err(SyscallStatus::InvalidArgument);
        }
        unsafe { core::ptr::copy_nonoverlapping(bytes.as_ptr(), out_ptr as *mut u8, to_copy) };
    }
    SyscallResult::ok(to_copy as u64)
}

/// Dismiss one notification by id, or clear all when id=0.
pub fn sys_notification_dismiss(args: [u64; 6]) -> SyscallResult {
    let removed = crate::notification::dismiss(args[0]);
    crate::gui::compositor::request_redraw();
    SyscallResult::ok(removed as u64)
}

