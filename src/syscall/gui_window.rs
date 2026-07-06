// ============================================================================
// FerrumOS - Generic App Window Syscalls
// ============================================================================
// CreateWindow(44) / PresentWindow(45) / PollWindowInput(46): the syscall
// surface for the D1 app-window framework (`crate::gui::app_window`). Gated
// behind the `gui:window:*` capability at dispatch, same pattern as every
// other resource-gated syscall in this module.
//
// Wire format for `PresentWindow`'s buffer: RGBA8, 4 bytes/pixel (R,G,B,A;
// A is ignored), row-major top-to-bottom, exactly `canvas_w * canvas_h * 4`
// bytes as returned by the `CreateWindow` call that made the window.
// ============================================================================

extern crate alloc;

use super::{SyscallResult, SyscallStatus};

/// `sys_create_window` — args[0]=title_ptr, args[1]=title_len,
/// args[2]=canvas_w, args[3]=canvas_h. Returns the new window id.
pub fn sys_create_window(args: [u64; 6]) -> SyscallResult {
    let title = match unsafe { super::fs::read_user_str(args[0], args[1]) } {
        Some(t) if !t.is_empty() && t.len() <= 64 => t,
        _ => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    let canvas_w = args[2] as u32;
    let canvas_h = args[3] as u32;
    if canvas_w == 0 || canvas_h == 0 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    if pid == 0 {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    let window_id = crate::gui::app_window::create_window(pid, &title, canvas_w, canvas_h);
    SyscallResult::ok(window_id)
}

/// `sys_present_window` — args[0]=window_id, args[1]=buf_ptr, args[2]=buf_len.
pub fn sys_present_window(args: [u64; 6]) -> SyscallResult {
    let window_id = args[0];
    let buf_ptr = args[1];
    let buf_len = args[2];

    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    if pid == 0 {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    // Cap the read at the largest canvas `create_window` will ever allow,
    // so a bogus buf_len can't force an unbounded copy.
    const MAX_CANVAS_BYTES: usize = 760 * 560 * 4;
    let bytes = match unsafe { super::fs::read_user_bytes(buf_ptr, buf_len, MAX_CANVAS_BYTES) } {
        Some(b) => b,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    match crate::gui::app_window::present(window_id, pid, &bytes) {
        Ok(()) => SyscallResult::ok(0),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// `sys_poll_window_input` — args[0]=window_id, args[1]=out_ptr,
/// args[2]=out_len (must be >= 20 bytes). Returns 1 and fills `out_ptr`
/// with a 5xu32 event if one was pending, else 0.
pub fn sys_poll_window_input(args: [u64; 6]) -> SyscallResult {
    let window_id = args[0];
    let out_ptr = args[1];
    let out_len = args[2] as usize;

    if out_ptr == 0 || out_len < 20 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    let end = out_ptr.saturating_add(20);
    if end >= 0x0000_7FFF_FFFF_FFFF {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    if pid == 0 {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    match crate::gui::app_window::poll_input(window_id, pid) {
        Some(ev) => {
            let out = out_ptr as *mut u32;
            // SAFETY: out_ptr/out_len were validated above and the dispatch
            // layer only reaches here for a live ring-3 caller's own
            // user-half pointer.
            unsafe {
                core::ptr::write_volatile(out, ev.tag);
                core::ptr::write_volatile(out.add(1), ev.a);
                core::ptr::write_volatile(out.add(2), ev.b);
                core::ptr::write_volatile(out.add(3), ev.c);
                core::ptr::write_volatile(out.add(4), ev.d);
            }
            SyscallResult::ok(1)
        }
        None => SyscallResult::ok(0),
    }
}
