// ============================================================================
// FerrumOS — HUD and Fusion System Calls
// ============================================================================

extern crate alloc;

use super::{SyscallResult, SyscallStatus};
use spin::Mutex;
use core::sync::atomic::AtomicBool;

#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct HudState {
    pub flags: u32,               // bit0 = visible, bit1 = listening, bit2 = pointing
    pub waveform: [u8; 64],       // audio waveform values (0..255)
    pub gesture_type: u8,         // stable gesture enum
    pub point_x: u16,             // target x (screen coords)
    pub point_y: u16,             // target y (screen coords)
    pub landmark_count: u8,       // number of landmarks
    pub landmarks: [[u16; 2]; 8],  // landmark coordinates
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

pub fn sys_hud_update(args: [u64; 6]) -> SyscallResult {
    let ptr = args[0];
    let len = args[1];
    let size = core::mem::size_of::<HudState>();
    crate::serial_println!("SYS_HUD_UPDATE: ptr=0x{:X}, len={}, size_of={}", ptr, len, size);
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
            core::ptr::copy_nonoverlapping(bytes.as_ptr(), &mut *state as *mut HudState as *mut u8, size);
        }
        crate::serial_println!("SYS_HUD_UPDATE: copied state, flags={}, visible={}", state.flags, (state.flags & 1) != 0);
    }
    
    // Set needs_redraw to animate the HUD waveform/overlay
    crate::gui::compositor::COMPOSITOR.lock().needs_redraw = true;
    
    // Render and swap buffers immediately to update screen in headless test modes
    crate::gui::compositor::render();
    if let Some(fb) = crate::devices::vga_fb::FRAMEBUFFER.lock().as_ref() {
        fb.swap_buffers();
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
        crate::serial_println!("HUD: sys_hit_test({}, {}) - windows count: {}", x, y, state.windows.len());
        for w in &state.windows {
            crate::serial_println!("  win ID={}: title={}, x={}, y={}, w={}, h={}", w.id, w.title, w.x, w.y, w.width, w.height);
        }
    }
    
    let (window_id, label) = crate::gui::compositor::hit_test_exclude(x, y, true);
    
    // Copy the label string to userspace
    let _copy_len = if label_buf != 0 && label_len > 0 {
        let label_bytes = label.as_bytes();
        let copy_len = core::cmp::min(label_bytes.len(), label_len);
        let end = label_buf.saturating_add(copy_len as u64);
        if end >= 0x0000_7FFF_FFFF_FFFF {
            return SyscallResult::err(SyscallStatus::InvalidArgument);
        }
        unsafe {
            core::ptr::copy_nonoverlapping(label_bytes.as_ptr(), label_buf as *mut u8, copy_len);
        }
        copy_len
    } else {
        0
    };
    
    SyscallResult::ok(window_id)
}
