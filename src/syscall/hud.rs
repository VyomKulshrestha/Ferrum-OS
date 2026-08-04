// ============================================================================
// FerrumOS — HUD and Fusion System Calls
// ============================================================================

extern crate alloc;

use super::{SyscallResult, SyscallStatus};
use core::sync::atomic::AtomicBool;
use spin::Mutex;

#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct HudState {
    pub flags: u32,               // bit0 = visible, bit1 = listening, bit2 = pointing
    pub waveform: [u8; 64],       // audio waveform values (0..255)
    pub gesture_type: u8,         // stable gesture enum
    pub point_x: u16,             // target x (screen coords)
    pub point_y: u16,             // target y (screen coords)
    pub landmark_count: u8,       // number of landmarks
    pub landmarks: [[u16; 2]; 8], // landmark coordinates
    pub suggestion_len: u8,       // suggestion text length
    pub suggestion: [u8; 128],    // suggestion text buffer
}

pub static HUD_STATE: Mutex<HudState> = Mutex::new(HudState {
    flags: 0,
    waveform: [0; 64],
    gesture_type: 0,
    point_x: 0,
    point_y: 0,
    landmark_count: 0,
    landmarks: [[0; 2]; 8],
    suggestion_len: 0,
    suggestion: [0; 128],
});

pub static HUD_ENABLED: AtomicBool = AtomicBool::new(true);

/// Guards the one-time "launch heliox-assistant-panel if unconfigured"
/// check (see `compositor::launch_assistant_panel_if_unconfigured`) so it
/// runs exactly once regardless of how many times `sys_hud_update` fires -
/// heliox-daemon's ambient loop calls this every ~30-50ms.
static ASSISTANT_PANEL_LAUNCH_CHECKED: AtomicBool = AtomicBool::new(false);
static LAST_MONITOR_UPDATE: core::sync::atomic::AtomicU64 =
    core::sync::atomic::AtomicU64::new(0);

pub fn sys_hud_update(args: [u64; 6]) -> SyscallResult {
    // Deliberately not done at raw kernel boot (main.rs, before the
    // interactive shell prompt exists): a process spawned that early has
    // to share the CPU with whatever userspace is doing immediately after
    // `ring3 init` - concretely, this used to race `init`'s own test-mode
    // setup logic in scripts/verify_inference.mjs, starving it of scheduling
    // time before it ever got to run at all. Deferred until the daemon's
    // ambient loop is already up and pumping, well past that fragile
    // early-boot window.
    if !ASSISTANT_PANEL_LAUNCH_CHECKED.swap(true, core::sync::atomic::Ordering::SeqCst) {
        crate::gui::compositor::launch_assistant_panel_if_unconfigured();
    }

    let ptr = args[0];
    let len = args[1];
    let size = core::mem::size_of::<HudState>();
    if len as usize != size {
        crate::serial_println!("SYS_HUD_UPDATE: Invalid size");
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    let bytes = match unsafe { super::fs::read_user_bytes(ptr, len, size) } {
        Some(b) => b,
        None => {
            crate::serial_println!("SYS_HUD_UPDATE: read_user_bytes failed");
            return SyscallResult::err(SyscallStatus::InvalidArgument);
        }
    };

    {
        let mut state = HUD_STATE.lock();
        unsafe {
            core::ptr::copy_nonoverlapping(
                bytes.as_ptr(),
                &mut *state as *mut HudState as *mut u8,
                size,
            );
        }
    }

    // Set needs_redraw to animate the HUD waveform/overlay.
    // The main GUI loop will perform the redraw and buffer swap on the next frame tick,
    // which prevents CPU thrashing and screen shaking.
    crate::gui::compositor::COMPOSITOR.lock().needs_redraw = true;

    // Render and swap buffers immediately to update screen in headless test modes (where desktop is inactive).
    // To prevent screen shaking (flicker), we ensure double buffering is initialized and active.
    // We also process input events and draw the mouse cursor so that the cursor is visible.
    if !crate::gui::is_active() && crate::gui::ambient_desktop_enabled() {
        let now = crate::scheduler::total_ticks();
        let last = LAST_MONITOR_UPDATE.load(core::sync::atomic::Ordering::Relaxed);
        if now.saturating_sub(last) >= 20 {
            LAST_MONITOR_UPDATE.store(now, core::sync::atomic::Ordering::Relaxed);
            crate::gui::compositor::update_system_monitor();
        }
        {
            let mut fb_guard = crate::devices::vga_fb::FRAMEBUFFER.lock();
            if let Some(fb) = fb_guard.as_mut() {
                fb.init_back_buffer();
            }
        }

        crate::gui::cursor::process_input();
        // A Power-menu sign-out can disable the ambient surface while the
        // input queue is being drained. Do not repaint it over the console
        // that `exit_desktop` just restored.
        if crate::gui::ambient_desktop_enabled() {
            crate::gui::compositor::render();
            crate::gui::cursor::save_and_draw();
            crate::gui::cursor::CURSOR.lock().dirty = false;

            {
                let fb_guard = crate::devices::vga_fb::FRAMEBUFFER.lock();
                if let Some(fb) = fb_guard.as_ref() {
                    fb.swap_buffers();
                }
            }
        }
    }

    SyscallResult::ok(size as u64)
}

pub fn sys_hit_test(args: [u64; 6]) -> SyscallResult {
    let x = args[0] as u32;
    let y = args[1] as u32;
    let label_buf = args[2];
    let label_len = args[3] as usize;

    {
        let state = crate::gui::compositor::COMPOSITOR.lock();
        crate::serial_println!(
            "HUD: sys_hit_test({}, {}) - windows count: {}",
            x,
            y,
            state.windows.len()
        );
        for w in &state.windows {
            crate::serial_println!(
                "  win ID={}: title={}, x={}, y={}, w={}, h={}",
                w.id,
                w.title,
                w.x,
                w.y,
                w.width,
                w.height
            );
        }
    }

    let (window_id, label) = crate::gui::compositor::hit_test_exclude(x, y, true);

    // Copy the label string to userspace
    let _copy_len = if label_buf != 0 && label_len > 0 {
        let label_bytes = label.as_bytes();
        let copy_len = core::cmp::min(label_bytes.len(), label_len);
        if copy_len > 0 && !super::fs::valid_user_range(label_buf, copy_len) {
            return SyscallResult::err(SyscallStatus::InvalidArgument);
        }
        if copy_len > 0
            && unsafe { super::fs::copy_to_user(label_buf, label_bytes, copy_len) } != copy_len
        {
            return SyscallResult::err(SyscallStatus::InvalidArgument);
        }
        copy_len
    } else {
        0
    };

    SyscallResult::ok(window_id)
}
