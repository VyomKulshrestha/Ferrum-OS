// ============================================================================
// FerrumOS - Audio Syscalls
// ============================================================================
// Bridges userspace audio requests to the kernel audio subsystem.
//
// Syscall ABI:
//   PlayAudio:   rdi=data_ptr, rsi=data_len
//   RecordAudio: rdi=buf_ptr,  rsi=buf_len,  rdx=duration_ms
//   SetVolume:   rdi=volume (0-127)
// ============================================================================

extern crate alloc;

use super::{SyscallResult, SyscallStatus};

/// Maximum PCM buffer we'll accept from / deliver to userspace (4 MB).
/// At 48 kHz / 16-bit / stereo this is ~21 seconds — plenty for a single
/// syscall; longer streams should be submitted in chunks.
const MAX_AUDIO_BUF: usize = 4 * 1024 * 1024;

/// Copy bytes from a kernel buffer into a userspace buffer.
///
/// Returns the number of bytes actually copied (capped at `max_len`).
///
/// # Safety
/// The caller must ensure `dst` points to writable user memory of at
/// least `max_len` bytes.
unsafe fn copy_to_user(dst: u64, src: &[u8], max_len: usize) -> usize {
    let to_copy = src.len().min(max_len);
    if to_copy > 0 && dst != 0 {
        let end = dst.saturating_add(to_copy as u64);
        if end >= 0x0000_7FFF_FFFF_FFFF {
            return 0;
        }
        // SAFETY: caller guarantees the destination is valid and writable.
        core::ptr::copy_nonoverlapping(src.as_ptr(), dst as *mut u8, to_copy);
    }
    to_copy
}

/// `sys_play_audio` — Submit raw PCM data for playback.
///
/// # Arguments (via `args`)
///
/// * `args[0]` — `data_ptr`: userspace pointer to PCM sample data.
/// * `args[1]` — `data_len`: length of the sample data in bytes.
///
/// # Returns
///
/// `0` on success, or an appropriate `SyscallStatus` error.
#[allow(dead_code)]
pub fn sys_play_audio(args: [u64; 6]) -> SyscallResult {
    let data_ptr = args[0];
    let data_len = args[1] as usize;

    if data_ptr == 0 || data_len == 0 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    if data_len > MAX_AUDIO_BUF {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    let end = data_ptr.saturating_add(data_len as u64);
    if end >= 0x0000_7FFF_FFFF_FFFF {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    // SAFETY: we are in kernel context where the user address space is
    // identity-mapped. data_ptr is validated non-null above.
    let data = unsafe {
        core::slice::from_raw_parts(data_ptr as *const u8, data_len)
    };

    match crate::audio::play(data) {
        Ok(()) => SyscallResult::ok(0),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// `sys_record_audio` — Record PCM audio into a userspace buffer.
///
/// # Arguments (via `args`)
///
/// * `args[0]` — `buf_ptr`:     userspace pointer to the destination buffer.
/// * `args[1]` — `buf_len`:     size of the destination buffer in bytes.
/// * `args[2]` — `duration_ms`: recording length in milliseconds.
///
/// # Returns
///
/// Number of bytes written to `buf_ptr` on success, or an error status.
#[allow(dead_code)]
pub fn sys_record_audio(args: [u64; 6]) -> SyscallResult {
    let buf_ptr = args[0];
    let buf_len = args[1] as usize;
    let duration_ms = args[2] as u32;

    if buf_ptr == 0 || buf_len == 0 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    if buf_len > MAX_AUDIO_BUF {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    if duration_ms == 0 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let recorded = match crate::audio::record(duration_ms) {
        Ok(data) => data,
        Err(_) => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    // SAFETY: buf_ptr was validated non-null and we cap the copy at
    // buf_len which the caller guarantees is the buffer's capacity.
    let copied = unsafe { copy_to_user(buf_ptr, &recorded, buf_len) };

    SyscallResult::ok(copied as u64)
}

/// `sys_set_volume` — Set the master audio output volume.
///
/// # Arguments (via `args`)
///
/// * `args[0]` — `volume`: desired volume level (0–127).
///
/// # Returns
///
/// `0` on success. Values above 127 are clamped by the driver.
#[allow(dead_code)]
pub fn sys_set_volume(args: [u64; 6]) -> SyscallResult {
    let level = args[0];

    if level > 127 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    crate::audio::set_volume(level as u8);
    SyscallResult::ok(0)
}
