// ============================================================================
// FerrumOS — Input Syscall Handlers
// ============================================================================
// Provides syscall interface for input injection (keyboard/mouse) and
// input event polling. Used by the heliox-daemon to automate user input.
//
// Syscalls:
//   InjectKey   = 26  — inject a keystroke (ASCII code)
//   InjectMouse = 27  — inject a mouse event (type, x/button, y/pressed)
//   PollInput   = 28  — poll pending input events
// ============================================================================

extern crate alloc;

use super::{SyscallResult, SyscallStatus};

/// Inject a keystroke as if typed on the keyboard.
///
/// args[0] = ASCII code of the key to press
///
/// The key event is injected into both the input event queue (for
/// syscall-based consumers) and the shell keyboard queue (so the
/// interactive shell sees synthetic keystrokes from the agent).
pub fn sys_inject_key(args: [u64; 6]) -> SyscallResult {
    let ascii = args[0] as u8;

    if ascii == 0 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    use core::sync::atomic::Ordering;
    crate::input::INJECTING_AGENT_KEY.store(true, Ordering::SeqCst);
    crate::input::inject_key(ascii);
    crate::input::INJECTING_AGENT_KEY.store(false, Ordering::SeqCst);

    SyscallResult::ok(0)
}

/// Inject a mouse event.
///
/// args[0] = event_type:
///   0 = mouse move (args[1]=dx as i16, args[2]=dy as i16)
///   1 = mouse click (args[1]=button_id, args[2]=0)
///
/// For mouse move: dx/dy are signed displacements.
/// For mouse click: button_id 0=left, 1=right, 2=middle.
pub fn sys_inject_mouse(args: [u64; 6]) -> SyscallResult {
    let event_type = args[0];

    match event_type {
        0 => {
            // Mouse move
            let dx = args[1] as i16;
            let dy = args[2] as i16;
            crate::input::inject_mouse_move(dx, dy);
        }
        1 => {
            // Mouse click
            let button = args[1] as u8;
            if button > 2 {
                return SyscallResult::err(SyscallStatus::InvalidArgument);
            }
            crate::input::inject_mouse_click(button);
        }
        _ => {
            return SyscallResult::err(SyscallStatus::InvalidArgument);
        }
    }

    SyscallResult::ok(0)
}

/// Poll pending input events from the event queue.
///
/// args[0] = buf_ptr — pointer to user buffer for InputEvent structs
/// args[1] = buf_len — size of buffer in bytes
///
/// Each InputEvent is serialized as 16 bytes:
///   [0..3]  = event_type tag (0=KeyPress, 1=KeyRelease, 2=MouseMove, 3=MouseButton)
///   [4..7]  = param1 (ascii code, dx, or button_id)
///   [8..11] = param2 (0, dy, or pressed flag)
///   [12..15] = timestamp (lower 32 bits)
///
/// Returns the number of events written.
pub fn sys_poll_input(args: [u64; 6]) -> SyscallResult {
    let buf_ptr = args[0] as usize;
    let buf_len = args[1] as usize;

    if buf_ptr == 0 || buf_len < 16 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    // Maximum events that fit in the buffer
    let max_events = buf_len / 16;
    let mut count: usize = 0;

    // Drain events from the input queue
    let mut queue = crate::input::DAEMON_EVENT_QUEUE.lock();
    while count < max_events {
        if let Some(event) = queue.pop() {
            let offset = buf_ptr + count * 16;
            let out = offset as *mut u32;

            // Serialize the event
            let (tag, p1, p2) = match event.event_type {
                crate::input::InputEventType::KeyPress(ascii) => {
                    (0u32, ascii as u32, 0u32)
                }
                crate::input::InputEventType::KeyRelease(ascii) => {
                    (1u32, ascii as u32, 0u32)
                }
                crate::input::InputEventType::MouseMove(dx, dy) => {
                    (2u32, dx as u16 as u32, dy as u16 as u32)
                }
                crate::input::InputEventType::MouseButton(btn, pressed) => {
                    (3u32, btn as u32, pressed as u32)
                }
                crate::input::InputEventType::GestureEvent(gesture_id) => {
                    (4u32, gesture_id as u32, 0u32)
                }
            };

            // Safety: buf_ptr is in the process's address space, validated
            // by the syscall dispatcher. We write 16 bytes per event.
            unsafe {
                core::ptr::write_volatile(out, tag);
                core::ptr::write_volatile(out.add(1), p1);
                core::ptr::write_volatile(out.add(2), p2);
                core::ptr::write_volatile(out.add(3), event.timestamp as u32);
            }

            count += 1;
        } else {
            break;
        }
    }

    SyscallResult::ok(count as u64)
}
