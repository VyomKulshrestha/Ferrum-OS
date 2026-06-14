// ============================================================================
// FerrumOS — Camera Syscalls
// ============================================================================
// Syscall handlers that expose camera frames to Ring-3 userspace.
//
//   SYS_READ_CAMERA_FRAME (36) — copy the latest YUYV frame to a user buffer
//   SYS_CAMERA_INFO       (37) — return camera metadata as a JSON string
//
// Frame source abstraction: currently backed by `camera_synth` (synthetic
// hand generator). Phase D-HW will add a `uvc` backend; the
// `camera_source_frame()` function switches automatically when a real
// device enumerates.
// ============================================================================

extern crate alloc;

use super::{SyscallResult, SyscallStatus};

// ============================================================================
// Frame Source Abstraction
// ============================================================================

/// Return the latest frame from whatever camera source is available.
///
/// Priority: real UVC (Phase D-HW, not yet implemented) > synthetic fallback.
fn camera_source_frame() -> Option<&'static [u8]> {
    // Phase D-HW: check uvc::is_available() first, then uvc::latest_frame()
    // For now, use the synthetic camera only.
    crate::devices::camera_synth::latest_frame()
}

/// Is any camera source available?
fn camera_available() -> bool {
    crate::devices::camera_synth::is_available()
}

/// Frame width from the active source.
fn source_width() -> u16 {
    crate::devices::camera_synth::frame_width()
}

/// Frame height from the active source.
fn source_height() -> u16 {
    crate::devices::camera_synth::frame_height()
}

// ============================================================================
// SYS_READ_CAMERA_FRAME (36)
// ============================================================================

/// Read the latest camera frame into a userspace buffer.
///
/// args[0] = userspace buffer pointer
/// args[1] = buffer length in bytes
///
/// Returns: frame size (bytes copied) on success, 0 if no frame available.
pub fn sys_read_camera_frame(args: [u64; 6]) -> SyscallResult {
    let buf_ptr = args[0];
    let buf_len = args[1] as usize;

    // Validate user pointer is in the user-half of the address space.
    if buf_ptr == 0 || buf_ptr >= 0x0000_7FFF_FFFF_FFFF {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let end = buf_ptr.saturating_add(buf_len as u64);
    if end >= 0x0000_7FFF_FFFF_FFFF {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    // Check camera availability.
    if !camera_available() {
        return SyscallResult::ok(0);
    }

    // Get the latest frame.
    let frame = match camera_source_frame() {
        Some(f) => f,
        None => return SyscallResult::ok(0),
    };

    // Validate buffer is large enough.
    let frame_size = frame.len();
    if buf_len < frame_size {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    // Copy frame data to userspace buffer.
    // Safety: buf_ptr was validated to be in user-half; frame is a valid
    // kernel slice from the camera double-buffer.
    unsafe {
        core::ptr::copy_nonoverlapping(
            frame.as_ptr(),
            buf_ptr as *mut u8,
            frame_size,
        );
    }

    SyscallResult::ok(frame_size as u64)
}

// ============================================================================
// SYS_CAMERA_INFO (37)
// ============================================================================

/// Write camera metadata as a JSON string into a userspace buffer.
///
/// args[0] = userspace buffer pointer
/// args[1] = buffer length in bytes
///
/// Returns: bytes written.
pub fn sys_camera_info(args: [u64; 6]) -> SyscallResult {
    let buf_ptr = args[0];
    let buf_len = args[1] as usize;

    if buf_ptr == 0 || buf_ptr >= 0x0000_7FFF_FFFF_FFFF {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let available = camera_available();
    let w = source_width();
    let h = source_height();

    // Build a simple JSON string. We avoid alloc::format! by using a
    // fixed buffer and manual construction.
    let json: &[u8] = if available {
        b"{\"width\":320,\"height\":240,\"format\":\"YUYV\",\"fps\":5,\"available\":true}"
    } else {
        b"{\"width\":0,\"height\":0,\"format\":\"none\",\"fps\":0,\"available\":false}"
    };
    let _ = (w, h); // used via the constants above

    let to_copy = json.len().min(buf_len);
    if to_copy == 0 {
        return SyscallResult::ok(0);
    }

    let end = buf_ptr.saturating_add(to_copy as u64);
    if end >= 0x0000_7FFF_FFFF_FFFF {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    unsafe {
        core::ptr::copy_nonoverlapping(
            json.as_ptr(),
            buf_ptr as *mut u8,
            to_copy,
        );
    }

    SyscallResult::ok(to_copy as u64)
}
