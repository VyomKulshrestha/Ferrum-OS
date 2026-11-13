// ============================================================================
// FerrumOS - Console Write syscall (34) with marked process output
// ============================================================================
// The kernel asks the operator for confirmation with lines that start with
// `[SECURITY]` on the serial port and on the screen. A process used to print
// its text unmarked, so it could print a line that reads exactly like that
// prompt (fi1 kernel round 1, round 4: "the real prompt cannot be told apart
// by its text"). Process output is now marked (fi2 K1, item 3):
//
// - every console line a process starts begins with `[pid N] `, inserted by
//   the kernel; a write continues the process's previous line without a
//   prefix only if nothing else reached the console in between;
// - the tag `[SECURITY` never appears in process text: it is written
//   `[pid-SECURITY`, and a tag split across two writes is broken by the
//   prefix, inserted between the two parts;
// - bytes outside printable ASCII (control characters such as CR, backspace
//   and ESC, and every non-ASCII byte, which could draw a look-alike tag) are
//   written as `\xNN`; newline and tab pass.
//
// So no line of process output can begin with, or contain, the kernel's tag:
// not at the start of a line, not after the terminal or the framebuffer wraps
// a long line, and not by erasing or overwriting the prefix. Direct port I/O
// to the UART is closed separately (user RFLAGS.IOPL is 0).
// ============================================================================

extern crate alloc;

use super::{SyscallResult, SyscallStatus};
use alloc::string::String;
use alloc::vec::Vec;
use core::sync::atomic::{AtomicBool, Ordering};
use spin::Mutex;

/// The kernel's reserved tag (without the closing bracket, so that a
/// partial tag at a line end cannot be completed by the next write).
const TAG: &[u8] = b"[SECURITY";
const TAG_REPLACEMENT: &[u8] = b"[pid-SECURITY";

/// Self-test switch: off restores the old, unmarked output.
pub static MARK_PROCESS_OUTPUT: AtomicBool = AtomicBool::new(true);

/// The last process write that reached the console: (pid, fd, console
/// sequence number right after it, the end of its current line, up to
/// `TAG.len() - 1` bytes).
struct LastWrite {
    pid: u64,
    fd: u64,
    seq: u64,
    tail: Vec<u8>,
}

static LAST: Mutex<Option<LastWrite>> = Mutex::new(None);

/// Mark `raw` (the bytes a process asked to write) for the console. `continued`
/// is the end of the process's own current line when this write continues
/// it, else None.
pub fn mark(pid: u64, raw: &[u8], continued: Option<&[u8]>) -> (Vec<u8>, Vec<u8>) {
    let prefix = alloc::format!("[pid {}] ", pid);
    // 1. Printable ASCII only (newline and tab pass).
    let mut text = Vec::with_capacity(raw.len() + 16);
    for &b in raw {
        if (0x20..0x7F).contains(&b) || b == b'\n' || b == b'\t' {
            text.push(b);
        } else {
            text.extend_from_slice(alloc::format!("\\x{:02x}", b).as_bytes());
        }
    }
    // 2. The reserved tag inside this write.
    let mut cleaned = Vec::with_capacity(text.len() + 8);
    let mut i = 0;
    while i < text.len() {
        if text[i..].starts_with(TAG) {
            cleaned.extend_from_slice(TAG_REPLACEMENT);
            i += TAG.len();
        } else {
            cleaned.push(text[i]);
            i += 1;
        }
    }
    // 3. A tag that would cross the boundary with the previous write: start
    // a new, marked line instead of continuing.
    let mut continued = continued;
    if let Some(tail) = continued {
        let mut joined = Vec::from(tail);
        joined.extend_from_slice(&cleaned[..cleaned.len().min(TAG.len())]);
        let crosses = (0..joined.len()).any(|k| joined[k..].starts_with(TAG) && k < tail.len());
        if crosses {
            continued = None;
        }
    }
    // 4. Every line this write starts gets the prefix.
    let mut out = Vec::with_capacity(cleaned.len() + 16);
    match continued {
        Some(_) => {}
        None => out.extend_from_slice(prefix.as_bytes()),
    }
    for (k, &b) in cleaned.iter().enumerate() {
        out.push(b);
        if b == b'\n' && k + 1 < cleaned.len() {
            out.extend_from_slice(prefix.as_bytes());
        }
    }
    // The end of the line now open (after the last newline), for the next
    // write's boundary check.
    let line_start = out.iter().rposition(|&b| b == b'\n').map(|p| p + 1).unwrap_or(0);
    let mut tail: Vec<u8> = Vec::from(&out[line_start..]);
    if line_start == 0 {
        if let Some(prev) = continued {
            let mut t = Vec::from(prev);
            t.extend_from_slice(&tail);
            tail = t;
        }
    }
    let keep = TAG.len() - 1;
    if tail.len() > keep {
        tail.drain(..tail.len() - keep);
    }
    (out, tail)
}

/// `sys_write_console` — write bytes from userspace to the console.
///
/// args[0] = fd: 1 = console + serial, 2 = serial only.
/// args[1] = ptr (user pointer to bytes)
/// args[2] = len (capped at 4096)
///
/// Returns the number of bytes taken from the caller.
pub fn sys_write_console(pid: u64, args: [u64; 6]) -> SyscallResult {
    let fd = args[0];
    if fd != 1 && fd != 2 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    let bytes = match unsafe { super::fs::read_user_bytes(args[1], args[2], 4096) } {
        Some(b) => b,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    let text: String = if MARK_PROCESS_OUTPUT.load(Ordering::SeqCst) {
        let seq_now = crate::serial::CONSOLE_SEQ.load(Ordering::SeqCst);
        let mut last = LAST.lock();
        let continued = match last.as_ref() {
            Some(l) if l.pid == pid && l.fd == fd && l.seq == seq_now && !l.tail.is_empty() => Some(l.tail.clone()),
            _ => None,
        };
        let (out, tail) = mark(pid, &bytes, continued.as_deref());
        *last = Some(LastWrite { pid, fd, seq: 0, tail });
        drop(last);
        // `out` is printable ASCII and newlines.
        String::from_utf8(out).unwrap_or_default()
    } else {
        String::from_utf8_lossy(&bytes).into_owned()
    };
    // `print!` already tees to the serial port (see vga::_print), so
    // fd=1 must not also call serial_print! or every byte doubles on
    // the serial console. fd=2 is the serial-only path.
    //
    // int 0x80 uses an interrupt gate, so IF is normally clear throughout a
    // syscall. UART/framebuffer output can take milliseconds; keeping IF
    // clear for that whole write starves the PS/2 keyboard while background
    // userspace logs. This handler holds no scheduler or device locks before
    // printing, so hardware IRQs can safely run for the duration of the I/O.
    let interrupts_were_enabled = x86_64::instructions::interrupts::are_enabled();
    if !interrupts_were_enabled {
        x86_64::instructions::interrupts::enable();
    }
    if fd == 1 {
        crate::print!("{}", text);
    } else {
        crate::serial_print!("{}", text);
    }
    if !interrupts_were_enabled {
        x86_64::instructions::interrupts::disable();
    }
    // The console's sequence number after this write: the next write of the
    // same process continues the line only if nothing printed in between.
    if let Some(l) = LAST.lock().as_mut() {
        if l.pid == pid && l.fd == fd {
            l.seq = crate::serial::CONSOLE_SEQ.load(Ordering::SeqCst);
        }
    }
    SyscallResult::ok(bytes.len() as u64)
}
