// ============================================================================
// FerrumOS - GUI Desktop & Taskbar
// ============================================================================

use crate::graphics;
use crate::devices::vga_fb::FRAMEBUFFER;
use crate::gui::compositor::HoverTarget;

pub const COLOR_BACKGROUND: u32 = 0x00101824; // Deep blue-gray, visibly non-black
pub const COLOR_GRID: u32 = 0x001B2A3A; // Subtle grid

pub fn init() {
    // Nothing to initialize for MVP
}

pub fn render_background() {
    let fb_guard = FRAMEBUFFER.lock();
    if let Some(fb) = fb_guard.as_ref() {
        // Draw solid background color
        fb.clear(COLOR_BACKGROUND);

        // Draw subtle grid
        for x in (0..fb.width).step_by(32) {
            for y in 0..fb.height {
                fb.set_pixel(x, y, COLOR_GRID);
            }
        }
        for y in (0..fb.height).step_by(32) {
            for x in 0..fb.width {
                fb.set_pixel(x, y, COLOR_GRID);
            }
        }

        // A soft horizontal gradient along the top 60 pixels
        // gives the desktop some depth and reads as a status
        // bar / menu strip instead of a flat void.
        for y in 0..60 {
            let t = y as f32 / 60.0;
            // Blend from background at y=59 up to a slightly
            // lighter blue at y=0.
            let r = (0x10 as f32 + (0x20 - 0x10) as f32 * (1.0 - t)) as u32;
            let g = (0x18 as f32 + (0x30 - 0x18) as f32 * (1.0 - t)) as u32;
            let b = (0x24 as f32 + (0x48 - 0x24) as f32 * (1.0 - t)) as u32;
            let color = (r << 16) | (g << 8) | b;
            for x in 0..fb.width {
                fb.set_pixel(x, y, color);
            }
        }
    }
}

/// Draw a single taskbar button. `bg` and `border` change
/// based on the button's hover/press state so the user gets
/// immediate visual feedback.
fn draw_button(
    fb: &crate::devices::vga_fb::Framebuffer,
    x: u32,
    y: u32,
    w: u32,
    h: u32,
    label: &str,
    label_color: u32,
    state: ButtonState,
) {
    let (bg, border) = match state {
        ButtonState::Idle => (0x00222222u32, 0x00444444u32),
        ButtonState::Hover => (0x00304050u32, 0x0000FFCCu32),
        ButtonState::Pressed => (0x00445878u32, 0x00FFFFFFu32),
    };
    fb.draw_rect(x, y, w, h, bg);
    for px in x..x + w {
        fb.set_pixel(px, y, border);
        fb.set_pixel(px, y + h - 1, border);
    }
    for py in y..y + h {
        fb.set_pixel(x, py, border);
        fb.set_pixel(x + w - 1, py, border);
    }
    graphics::draw_string(x + 10, y + 5, label, label_color, bg);
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ButtonState {
    Idle,
    Hover,
    Pressed,
}

pub fn render_taskbar(
    hover: HoverTarget,
    pressed: HoverTarget,
    _mx: u32,
    _my: u32,
    _left_down: bool,
) {
    let fb_guard = FRAMEBUFFER.lock();
    let fb = match fb_guard.as_ref() {
        Some(fb) => fb,
        None => return,
    };

    let w = fb.width;
    let h = fb.height;

    let dock_w = 400;
    let dock_h = 40;
    let dock_x = (w - dock_w) / 2;
    let dock_y = h - dock_h - 10;

    // Draw Dock Background with a soft top highlight so the
    // dock looks elevated above the desktop.
    fb.draw_rect(dock_x, dock_y, dock_w, dock_h, 0x00141828);
    for y in dock_y..dock_y + 2 {
        for x in dock_x..dock_x + dock_w {
            fb.set_pixel(x, y, 0x00202838);
        }
    }

    // Draw Neon Cyan Border
    let neon_cyan = 0x0000FFCC;
    for x in dock_x..dock_x + dock_w {
        fb.set_pixel(x, dock_y, neon_cyan);
        fb.set_pixel(x, dock_y + dock_h - 1, neon_cyan);
    }
    for y in dock_y..dock_y + dock_h {
        fb.set_pixel(dock_x, y, neon_cyan);
        fb.set_pixel(dock_x + dock_w - 1, y, neon_cyan);
    }

    // Button layout (must match `hit_test_taskbar` in
    // `compositor.rs`).
    let btn1_x = dock_x + 15;
    let btn1_y = dock_y + 8;
    let btn1_w = 100;
    let btn1_h = 24;
    let btn2_x = dock_x + 130;
    let btn2_y = dock_y + 8;
    let btn2_w = 100;
    let btn2_h = 24;
    let btn3_x = dock_x + 245;
    let btn3_y = dock_y + 8;
    let btn3_w = 60;
    let btn3_h = 24;

    // Compute each button's state.
    let s1 = if pressed == HoverTarget::TerminalButton {
        ButtonState::Pressed
    } else if hover == HoverTarget::TerminalButton {
        ButtonState::Hover
    } else {
        ButtonState::Idle
    };
    let s2 = if pressed == HoverTarget::SysMonButton {
        ButtonState::Pressed
    } else if hover == HoverTarget::SysMonButton {
        ButtonState::Hover
    } else {
        ButtonState::Idle
    };
    let s3 = if pressed == HoverTarget::ExitButton {
        ButtonState::Pressed
    } else if hover == HoverTarget::ExitButton {
        ButtonState::Hover
    } else {
        ButtonState::Idle
    };

    draw_button(fb, btn1_x, btn1_y, btn1_w, btn1_h, "TERMINAL", 0x0000FFCC, s1);
    draw_button(fb, btn2_x, btn2_y, btn2_w, btn2_h, "SYS MON", 0x0000FFCC, s2);
    draw_button(fb, btn3_x, btn3_y, btn3_w, btn3_h, "EXIT", 0x00FF3333, s3);

    drop(fb_guard);

    graphics::draw_string(24, 12, "FerrumOS Desktop", 0x0000FFCC, COLOR_BACKGROUND);
    graphics::draw_string(24, 32, "Click a dock button or drag a window title bar", 0x00B8C7D9, COLOR_BACKGROUND);

    // Draw Status on right of the dock.
    let status_str = "ONLINE";
    let status_color = 0x0088FF88;
    graphics::draw_string(dock_x + dock_w - 75, dock_y + 12, status_str, status_color, 0x00141828);
}
