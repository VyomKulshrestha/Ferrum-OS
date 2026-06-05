// ============================================================================
// FerrumOS - GUI Desktop & Taskbar
// ============================================================================

use crate::graphics;
use crate::devices::vga_fb::FRAMEBUFFER;

pub const COLOR_BACKGROUND: u32 = 0x00008080; // Classic Teal

pub fn init() {
    // Nothing to initialize for MVP
}

pub fn render_background() {
    let fb_guard = FRAMEBUFFER.lock();
    if let Some(fb) = fb_guard.as_ref() {
        // Draw solid background color
        fb.clear(COLOR_BACKGROUND);
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
    let taskbar_h = 30;
    let y = h - taskbar_h;
    
    // Draw Taskbar Background
    fb.draw_rect(0, y, w, taskbar_h, 0x00C0C0C0); // Classic Light Gray
    
    // Draw Top Highlight Line
    for x in 0..w {
        fb.set_pixel(x, y, 0x00FFFFFF);
    }
    
    // Draw Start Button (or Ferrum Button)
    fb.draw_rect(2, y + 2, 70, taskbar_h - 4, 0x00A0A0A0);
    // Draw String
    // We can't easily lock FB while using graphics::draw_string, 
    // because draw_string locks FB.
}

pub fn render_taskbar_overlays() {
    let fb_guard = FRAMEBUFFER.lock();
    let (w, h) = match fb_guard.as_ref() {
        Some(fb) => (fb.width, fb.height),
        None => return,
    };
    drop(fb_guard); // Must drop so draw_string can lock it
    
    let taskbar_h = 30;
    let y = h - taskbar_h;
    
    // Draw Start Text
    graphics::draw_string(10, y + 8, "Ferrum", graphics::COLOR_BLACK, 0x00A0A0A0);
    
    // Draw Time on right
    let time_str = "12:00 PM";
    graphics::draw_string(w - 80, y + 8, time_str, graphics::COLOR_BLACK, 0x00C0C0C0);
}
