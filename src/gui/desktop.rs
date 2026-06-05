// ============================================================================
// FerrumOS - GUI Desktop & Taskbar
// ============================================================================

use crate::graphics;
use crate::devices::vga_fb::FRAMEBUFFER;

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
    }
}

pub fn render_taskbar() {
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
    
    // Draw Dock Background
    fb.draw_rect(dock_x, dock_y, dock_w, dock_h, 0x00111111); // Dark background
    
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
    
    // Draw Button Backgrounds and borders
    // Button 1: Terminal
    let btn1_x = dock_x + 15;
    let btn1_y = dock_y + 8;
    let btn1_w = 100;
    let btn1_h = 24;
    fb.draw_rect(btn1_x, btn1_y, btn1_w, btn1_h, 0x00222222);
    for x in btn1_x..btn1_x + btn1_w {
        fb.set_pixel(x, btn1_y, 0x00444444);
        fb.set_pixel(x, btn1_y + btn1_h - 1, 0x00444444);
    }
    for y in btn1_y..btn1_y + btn1_h {
        fb.set_pixel(btn1_x, y, 0x00444444);
        fb.set_pixel(btn1_x + btn1_w - 1, y, 0x00444444);
    }

    // Button 2: Sys Mon
    let btn2_x = dock_x + 130;
    let btn2_y = dock_y + 8;
    let btn2_w = 100;
    let btn2_h = 24;
    fb.draw_rect(btn2_x, btn2_y, btn2_w, btn2_h, 0x00222222);
    for x in btn2_x..btn2_x + btn2_w {
        fb.set_pixel(x, btn2_y, 0x00444444);
        fb.set_pixel(x, btn2_y + btn2_h - 1, 0x00444444);
    }
    for y in btn2_y..btn2_y + btn2_h {
        fb.set_pixel(btn2_x, y, 0x00444444);
        fb.set_pixel(btn2_x + btn2_w - 1, y, 0x00444444);
    }

    // Button 3: Exit
    let btn3_x = dock_x + 245;
    let btn3_y = dock_y + 8;
    let btn3_w = 60;
    let btn3_h = 24;
    fb.draw_rect(btn3_x, btn3_y, btn3_w, btn3_h, 0x00222222);
    for x in btn3_x..btn3_x + btn3_w {
        fb.set_pixel(x, btn3_y, 0x00444444);
        fb.set_pixel(x, btn3_y + btn3_h - 1, 0x00444444);
    }
    for y in btn3_y..btn3_y + btn3_h {
        fb.set_pixel(btn3_x, y, 0x00444444);
        fb.set_pixel(btn3_x + btn3_w - 1, y, 0x00444444);
    }
    
    drop(fb_guard);

    graphics::draw_string(24, 24, "FerrumOS Desktop", 0x0000FFCC, COLOR_BACKGROUND);
    graphics::draw_string(24, 44, "Terminal and System Monitor are active", 0x00B8C7D9, COLOR_BACKGROUND);
    
    // Draw button texts
    graphics::draw_string(btn1_x + 10, btn1_y + 5, "TERMINAL", 0x0000FFCC, 0x00222222);
    graphics::draw_string(btn2_x + 10, btn2_y + 5, "SYS MON", 0x0000FFCC, 0x00222222);
    graphics::draw_string(btn3_x + 15, btn3_y + 5, "EXIT", 0x00FF3333, 0x00222222);
    
    // Draw Status on right
    let status_str = "ONLINE";
    graphics::draw_string(dock_x + dock_w - 75, dock_y + 12, status_str, 0x00888888, 0x00111111);
}
