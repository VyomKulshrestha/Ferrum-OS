// ============================================================================
// FerrumOS - Graphics Subsystem
// ============================================================================
// High-level drawing API layered on top of the Bochs VBE framebuffer driver.
// Provides character/string rendering using the embedded bitmap font,
// geometric primitives, and a graphical text console.
// ============================================================================

#![allow(dead_code)]

pub mod font;
pub mod console;

use crate::devices::vga_fb;
use crate::devices::vga_fb::FRAMEBUFFER;

// ============================================================================
// Color Constants (0x00RRGGBB format)
// ============================================================================

pub const COLOR_BLACK: u32     = 0x00000000;
pub const COLOR_WHITE: u32     = 0x00FFFFFF;
pub const COLOR_GREEN: u32     = 0x0000FF00;
pub const COLOR_CYAN: u32      = 0x0000FFFF;
pub const COLOR_RED: u32       = 0x00FF0000;
pub const COLOR_YELLOW: u32    = 0x00FFFF00;
pub const COLOR_DARK_GRAY: u32 = 0x00333333;

// ============================================================================
// Initialization
// ============================================================================

/// Initialize the graphics subsystem.
///
/// Programs the Bochs VBE adapter for the requested resolution (32bpp),
/// maps the linear framebuffer, and stores it in the global
/// `FRAMEBUFFER` mutex for use by all drawing functions.
pub fn init(width: u32, height: u32) {
    match vga_fb::init(width, height) {
        Ok(fb) => {
            fb.clear(COLOR_BLACK);
            *FRAMEBUFFER.lock() = Some(fb);
            crate::serial_println!("[graphics] VBE framebuffer {}x{} initialized", width, height);
        }
        Err(e) => {
            crate::serial_println!("[graphics] Failed to init VBE framebuffer: {}", e);
        }
    }
}

/// Returns `true` if the framebuffer has been successfully initialized.
pub fn is_initialized() -> bool {
    FRAMEBUFFER.lock().is_some()
}

// ============================================================================
// Character & String Rendering
// ============================================================================

/// Draw a single character from the embedded bitmap font.
///
/// `(x, y)` is the top-left pixel coordinate of the glyph cell.
/// Each glyph is 8 pixels wide × 16 pixels tall.
/// `fg` and `bg` are foreground and background colors in 0x00RRGGBB.
pub fn draw_char(x: u32, y: u32, ch: u8, fg: u32, bg: u32) {
    let fb_guard = FRAMEBUFFER.lock();
    let fb = match fb_guard.as_ref() {
        Some(fb) => fb,
        None => return,
    };

    let glyph = font::glyph(ch);
    for row in 0..font::FONT_HEIGHT {
        let bits = glyph[row as usize];
        for col in 0..font::FONT_WIDTH {
            let pixel_set = (bits >> (7 - col)) & 1 != 0;
            let color = if pixel_set { fg } else { bg };
            fb.set_pixel(x + col, y + row, color);
        }
    }
}

/// Draw a string starting at `(x, y)`, advancing horizontally by
/// `FONT_WIDTH` pixels for each character.
///
/// Characters that would extend beyond the framebuffer width are still
/// rendered (they will be clipped by `set_pixel`).
pub fn draw_string(x: u32, y: u32, s: &str, fg: u32, bg: u32) {
    let mut cx = x;
    for byte in s.bytes() {
        draw_char(cx, y, byte, fg, bg);
        cx += font::FONT_WIDTH;
    }
}

// ============================================================================
// Geometric Primitives
// ============================================================================

/// Draw a line between two points using Bresenham's line algorithm.
///
/// Works for all octants (any slope / direction). Coordinates are
/// silently clipped by the underlying `set_pixel`.
pub fn draw_line(x0: u32, y0: u32, x1: u32, y1: u32, color: u32) {
    let fb_guard = FRAMEBUFFER.lock();
    let fb = match fb_guard.as_ref() {
        Some(fb) => fb,
        None => return,
    };

    // Use signed arithmetic for Bresenham
    let mut x = x0 as i32;
    let mut y = y0 as i32;
    let x1 = x1 as i32;
    let y1 = y1 as i32;

    let dx = (x1 - x).abs();
    let dy = -(y1 - y).abs();
    let sx: i32 = if x < x1 { 1 } else { -1 };
    let sy: i32 = if y < y1 { 1 } else { -1 };
    let mut err = dx + dy;

    loop {
        if x >= 0 && y >= 0 {
            fb.set_pixel(x as u32, y as u32, color);
        }

        if x == x1 && y == y1 {
            break;
        }

        let e2 = 2 * err;
        if e2 >= dy {
            err += dy;
            x += sx;
        }
        if e2 <= dx {
            err += dx;
            y += sy;
        }
    }
}

/// Draw a filled rectangle at `(x, y)` with dimensions `w × h`.
///
/// Delegates to the framebuffer's optimized `draw_rect` method.
pub fn fill_rect(x: u32, y: u32, w: u32, h: u32, color: u32) {
    let fb_guard = FRAMEBUFFER.lock();
    if let Some(fb) = fb_guard.as_ref() {
        fb.draw_rect(x, y, w, h, color);
    }
}
