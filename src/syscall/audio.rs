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

/// State for an in-progress non-blocking audio capture. Only one recording
/// can be active at a time (the HDA controller has a single input stream),
/// so a single slot is sufficient.
struct CaptureSession {
    pid: u64,
    user_buf_ptr: u64,
    user_buf_len: usize,
    /// Kernel-side accumulation buffer, sized to the requested duration.
    accum: alloc::vec::Vec<u8>,
    copied_bytes: usize,
    last_lpib: usize,
    /// Absolute PIT tick at which we give up waiting for more data and
    /// return whatever has been captured so far.
    deadline_tick: u64,
}

static ACTIVE_CAPTURE: spin::Mutex<Option<CaptureSession>> = spin::Mutex::new(None);

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
///
/// # Non-blocking design
///
/// The underlying HDA capture is DMA-driven and takes as long as
/// `duration_ms` to fill (hundreds of milliseconds to seconds). Waiting for
/// it with a busy-spin loop inside this syscall would run in kernel
/// context and monopolize the single core for the whole duration, freezing
/// every other task on the system.
///
/// Instead this syscall is a state machine driven by the kernel's existing
/// generic `SyscallStatus::Blocked` retry mechanism (the same one the
/// confirmation gate uses): the first call kicks off DMA and returns
/// `Blocked`, which makes the interrupt layer rewind the caller's `int
/// 0x80` and re-queue the task at the *back* of its run queue - giving any
/// other ready task a scheduling slot before this task is retried. Each
/// retry polls the DMA position once (no spinning) and either completes or
/// returns `Blocked` again.
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

    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    let mut session = ACTIVE_CAPTURE.lock();

    match session.as_mut() {
        Some(s) if s.pid == pid => {
            // Retry: poll once, no spinning.
            let now = crate::scheduler::total_ticks();
            let target_len = s.accum.len();
            let mut copied = s.copied_bytes;
            let mut last_lpib = s.last_lpib;
            let done = match crate::devices::hda::poll_recording_once(&mut s.accum, &mut copied, &mut last_lpib) {
                Ok(d) => d,
                Err(_) => {
                    *session = None;
                    return SyscallResult::err(SyscallStatus::InvalidArgument);
                }
            };
            s.copied_bytes = copied;
            s.last_lpib = last_lpib;

            if done || now >= s.deadline_tick {
                crate::devices::hda::finish_recording_nonblocking();
                let accum = core::mem::take(&mut s.accum);
                let user_ptr = s.user_buf_ptr;
                let user_len = s.user_buf_len;
                let n = s.copied_bytes.min(target_len);
                *session = None;
                drop(session);
                // SAFETY: user_ptr/user_len were validated when the capture
                // started; they are immutable for the life of this session.
                let out = unsafe { copy_to_user(user_ptr, &accum[..n], user_len) };
                SyscallResult::ok(out as u64)
            } else {
                SyscallResult::err(SyscallStatus::Blocked)
            }
        }
        Some(_) => {
            // A different process already has a capture in flight - the
            // single HDA input stream can't serve two callers at once.
            SyscallResult::err(SyscallStatus::PermissionDenied)
        }
        None => {
            // First call for this pid: kick off DMA and start the retry loop.
            let format = crate::audio::AudioFormat::PCM_48KHZ_16BIT_STEREO;
            let target_len = format.bytes_for_duration(duration_ms).min(MAX_AUDIO_BUF);
            if target_len == 0 {
                return SyscallResult::err(SyscallStatus::InvalidArgument);
            }
            if crate::devices::hda::start_recording_nonblocking().is_err() {
                return SyscallResult::err(SyscallStatus::InvalidArgument);
            }
            // Generous safety margin over the requested duration so a slow
            // DMA doesn't get truncated early; the PIT runs at ~18.2 Hz.
            let timeout_ticks = ((duration_ms as u64 * 18) / 1000).saturating_add(36);
            *session = Some(CaptureSession {
                pid,
                user_buf_ptr: buf_ptr,
                user_buf_len: buf_len,
                accum: alloc::vec![0u8; target_len],
                copied_bytes: 0,
                last_lpib: 0,
                deadline_tick: crate::scheduler::total_ticks().saturating_add(timeout_ticks),
            });
            SyscallResult::err(SyscallStatus::Blocked)
        }
    }
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
