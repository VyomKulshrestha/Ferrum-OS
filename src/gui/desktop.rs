// ============================================================================
// FerrumOS - GUI Desktop & Taskbar
// ============================================================================

use crate::graphics;
use crate::devices::vga_fb::FRAMEBUFFER;

pub const COLOR_BACKGROUND: u32 = 0x000A0A0C; // Deep space gray
pub const COLOR_GRID: u32 = 0x00141418; // Subtle grid

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
    
    // We must drop fb before calling draw_string
    drop(fb_guard);
    
    // Draw Start Text
    graphics::draw_string(dock_x + 20, dock_y + 12, "FERRUM OS", neon_cyan, 0x00111111);
    
    // Draw Status on right
    let status_str = "SYS.ONLINE";
    graphics::draw_string(dock_x + dock_w - 100, dock_y + 12, status_str, 0x00AAAAAA, 0x00111111);
}
