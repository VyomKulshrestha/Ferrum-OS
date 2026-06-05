// ============================================================================
// FerrumOS - Graphics / Framebuffer Syscalls
// ============================================================================
// Bridges userspace screen-vision requests to the kernel's graphical console
// and VGA framebuffer subsystems.
//
// Syscall ABI:
//   ReadTextBuffer(20):       rdi=buf_ptr, rsi=buf_len
//   ReadFramebufferInfo(21):  rdi=buf_ptr, rsi=buf_len
// ============================================================================

extern crate alloc;

use alloc::string::String;
use super::{SyscallResult, SyscallStatus};

/// Maximum text-buffer serialisation size (64 KB).
const MAX_TEXT_BUF: usize = 64 * 1024;

/// `sys_read_text_buffer` — Serialise the graphical console's shadow text
/// buffer into a userspace buffer as newline-separated rows (trailing spaces
/// trimmed).
///
/// # Arguments (via `args`)
///
/// * `args[0]` — `buf_ptr`: userspace destination pointer.
/// * `args[1]` — `buf_len`: size of the destination buffer.
///
/// # Returns
///
/// Number of bytes written on success, or `SyscallStatus::NotImplemented` if
/// the console has not been initialised yet.
pub fn sys_read_text_buffer(args: [u64; 6]) -> SyscallResult {
    let buf_ptr = args[0];
    let buf_len = args[1] as usize;

    if buf_ptr == 0 || buf_len == 0 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    // Attempt to lock the graphical console.
    let console = crate::graphics::console::CONSOLE.lock();
    let text_buf = match console.as_ref() {
        Some(c) => c.read_text_buffer(),
        None => return SyscallResult::err(SyscallStatus::NotImplemented),
    };

    // Serialise rows: each row is a string of characters with trailing spaces
    // trimmed, rows separated by newlines.
    let mut output = String::new();
    for row in text_buf.iter() {
        // Convert u8 array to string, replacing non-printable with space
        let line: String = row.iter().map(|&b| {
            if b >= 0x20 && b <= 0x7E { b as char } else { ' ' }
        }).collect();
        let trimmed = line.trim_end();
        output.push_str(trimmed);
        output.push('\n');
    }

    let bytes = output.as_bytes();
    let to_copy = bytes.len().min(buf_len).min(MAX_TEXT_BUF);

    if to_copy > 0 {
        unsafe {
            core::ptr::copy_nonoverlapping(bytes.as_ptr(), buf_ptr as *mut u8, to_copy);
        }
    }

    SyscallResult::ok(to_copy as u64)
}

/// `sys_read_framebuffer_info` — Write a human-readable framebuffer
/// descriptor (`"WIDTHxHEIGHTxBPP"`) into a userspace buffer.
///
/// # Arguments (via `args`)
///
/// * `args[0]` — `buf_ptr`: userspace destination pointer.
/// * `args[1]` — `buf_len`: size of the destination buffer.
///
/// # Returns
///
/// Number of bytes written on success, or `SyscallStatus::NotImplemented` if
/// the framebuffer is unavailable.
pub fn sys_read_framebuffer_info(args: [u64; 6]) -> SyscallResult {
    let buf_ptr = args[0];
    let buf_len = args[1] as usize;

    if buf_ptr == 0 || buf_len == 0 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let fb = crate::devices::vga_fb::FRAMEBUFFER.lock();
    let info = match fb.as_ref() {
        Some(f) => f,
        None => return SyscallResult::err(SyscallStatus::NotImplemented),
    };

    // Format: "WIDTHxHEIGHTxBPP" — BPP is always 32 for our VBE mode
    let desc = alloc::format!("{}x{}x32", info.width, info.height);

    let bytes = desc.as_bytes();
    let to_copy = bytes.len().min(buf_len);

    if to_copy > 0 {
        unsafe {
            core::ptr::copy_nonoverlapping(bytes.as_ptr(), buf_ptr as *mut u8, to_copy);
        }
    }

    SyscallResult::ok(to_copy as u64)
}
