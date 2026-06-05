// ============================================================================
// FerrumOS - Graphical Text Console
// ============================================================================
// A terminal-style text console rendered via the pixel framebuffer,
// replacing the legacy VGA text-mode console. Maintains a shadow text
// buffer so the "screen vision" syscall can read what is currently
// displayed without parsing pixels.
//
// The console tracks cursor position, handles newline/backspace, and
// scrolls when the cursor moves past the last row.
// ============================================================================

#![allow(dead_code)]

use core::fmt;
use spin::Mutex;

use crate::devices::vga_fb::FRAMEBUFFER;
use crate::graphics::font::{FONT_WIDTH, FONT_HEIGHT};
use crate::graphics;

// ============================================================================
// Constants
// ============================================================================

/// Maximum supported columns (enough for 1024 / 8 = 128).
pub const MAX_COLS: usize = 128;

/// Maximum supported rows (enough for 768 / 16 = 48).
pub const MAX_ROWS: usize = 48;

// ============================================================================
// Global Console Instance
// ============================================================================

/// Global graphical console, protected by a spinlock.
pub static CONSOLE: Mutex<Option<GraphicsConsole>> = Mutex::new(None);

// ============================================================================
// GraphicsConsole
// ============================================================================

/// A character-cell text console rendered onto the pixel framebuffer.
///
/// Each cell is `FONT_WIDTH × FONT_HEIGHT` pixels. The shadow
/// `text_buffer` records the ASCII code at every cell for the screen
/// vision subsystem.
pub struct GraphicsConsole {
    /// Current cursor column (0-based).
    col: u32,
    /// Current cursor row (0-based).
    row: u32,
    /// Number of usable text columns based on screen width.
    max_cols: u32,
    /// Number of usable text rows based on screen height.
    max_rows: u32,
    /// Current foreground color (0x00RRGGBB).
    fg_color: u32,
    /// Current background color (0x00RRGGBB).
    bg_color: u32,
    /// Shadow text buffer — stores the ASCII byte at each cell position.
    text_buffer: [[u8; MAX_COLS]; MAX_ROWS],
}

// Safety: GraphicsConsole is only accessed through the CONSOLE Mutex,
// ensuring exclusive access.
unsafe impl Send for GraphicsConsole {}

impl GraphicsConsole {
    /// Create a new `GraphicsConsole` sized to the given screen dimensions.
    ///
    /// `screen_width` and `screen_height` are in pixels. The console
    /// computes how many text cells fit and caps at `MAX_COLS` / `MAX_ROWS`.
    pub fn new(screen_width: u32, screen_height: u32) -> Self {
        let max_cols = core::cmp::min((screen_width / FONT_WIDTH) as usize, MAX_COLS) as u32;
        let max_rows = core::cmp::min((screen_height / FONT_HEIGHT) as usize, MAX_ROWS) as u32;

        GraphicsConsole {
            col: 0,
            row: 0,
            max_cols,
            max_rows,
            fg_color: graphics::COLOR_WHITE,
            bg_color: graphics::COLOR_BLACK,
            text_buffer: [[b' '; MAX_COLS]; MAX_ROWS],
        }
    }

    // ========================================================================
    // Text output
    // ========================================================================

    /// Write a single byte to the console.
    ///
    /// Handles:
    /// - `\n` (0x0A): move to a new line
    /// - Backspace (0x08): erase the previous character
    /// - Printable bytes: render the glyph and advance the cursor
    pub fn write_byte(&mut self, byte: u8) {
        match byte {
            b'\n' => self.new_line(),
            0x08 => self.backspace(),
            byte => {
                if self.col >= self.max_cols {
                    self.new_line();
                }

                let x = self.col * FONT_WIDTH;
                let y = self.row * FONT_HEIGHT;

                // Update shadow buffer
                self.text_buffer[self.row as usize][self.col as usize] = byte;

                // Render glyph to framebuffer
                self.draw_glyph(x, y, byte);

                self.col += 1;
            }
        }
    }

    /// Write a string to the console, byte by byte.
    pub fn write_string(&mut self, s: &str) {
        for byte in s.bytes() {
            match byte {
                // Printable ASCII or newline
                0x20..=0x7E | b'\n' | 0x08 => self.write_byte(byte),
                // Non-printable: render a placeholder block (0xFE)
                _ => self.write_byte(0xFE),
            }
        }
    }

    // ========================================================================
    // Cursor movement & scrolling
    // ========================================================================

    /// Advance to the next line. Scrolls the screen if the cursor is at
    /// the bottom row.
    pub fn new_line(&mut self) {
        self.col = 0;
        self.row += 1;
        if self.row >= self.max_rows {
            self.scroll_up();
            self.row = self.max_rows - 1;
        }
    }

    /// Scroll the entire console up by one text row.
    ///
    /// 1. Shifts the shadow text buffer rows up by one.
    /// 2. Asks the framebuffer to scroll up by `FONT_HEIGHT` pixels.
    /// 3. Clears the bottom row of the shadow buffer.
    pub fn scroll_up(&mut self) {
        // Shift shadow buffer up
        for r in 1..(self.max_rows as usize) {
            self.text_buffer[r - 1] = self.text_buffer[r];
        }
        // Clear last row in shadow buffer
        let last = (self.max_rows - 1) as usize;
        self.text_buffer[last] = [b' '; MAX_COLS];

        // Scroll framebuffer pixels
        let fb_guard = FRAMEBUFFER.lock();
        if let Some(fb) = fb_guard.as_ref() {
            fb.scroll_up(FONT_HEIGHT, self.bg_color);
        }
    }

    /// Clear the entire screen and reset the cursor to the top-left.
    pub fn clear(&mut self) {
        // Clear shadow buffer
        for row in self.text_buffer.iter_mut() {
            *row = [b' '; MAX_COLS];
        }

        // Clear framebuffer
        let fb_guard = FRAMEBUFFER.lock();
        if let Some(fb) = fb_guard.as_ref() {
            fb.clear(self.bg_color);
        }

        self.col = 0;
        self.row = 0;
    }

    // ========================================================================
    // Editing
    // ========================================================================

    /// Erase the character before the cursor (backspace).
    ///
    /// Moves the cursor back one position and draws a space glyph over
    /// the erased cell. Does nothing if the cursor is at position (0, 0).
    pub fn backspace(&mut self) {
        if self.col > 0 {
            self.col -= 1;
        } else if self.row > 0 {
            self.row -= 1;
            self.col = self.max_cols - 1;
        } else {
            return; // Already at (0, 0)
        }

        let x = self.col * FONT_WIDTH;
        let y = self.row * FONT_HEIGHT;

        // Clear the cell in the shadow buffer
        self.text_buffer[self.row as usize][self.col as usize] = b' ';

        // Overwrite with a space glyph
        self.draw_glyph(x, y, b' ');
    }

    // ========================================================================
    // Color control
    // ========================================================================

    /// Change the foreground and background colors for subsequent output.
    pub fn set_color(&mut self, fg: u32, bg: u32) {
        self.fg_color = fg;
        self.bg_color = bg;
    }

    // ========================================================================
    // Screen vision / introspection
    // ========================================================================

    /// Return a reference to the shadow text buffer.
    ///
    /// Each entry is the ASCII byte at that cell position, or `b' '` for
    /// empty cells. Used by the screen vision syscall to let userspace
    /// (and the agent runtime) read what is on screen without pixel
    /// parsing.
    pub fn read_text_buffer(&self) -> &[[u8; MAX_COLS]; MAX_ROWS] {
        &self.text_buffer
    }

    /// Return the current cursor position as `(col, row)`.
    pub fn cursor_position(&self) -> (u32, u32) {
        (self.col, self.row)
    }

    // ========================================================================
    // Private helpers
    // ========================================================================

    /// Render a single glyph at pixel coordinates `(x, y)`.
    ///
    /// Reads the bitmap from the font module and writes pixels directly
    /// to the framebuffer using the console's current colors.
    fn draw_glyph(&self, x: u32, y: u32, ch: u8) {
        let fb_guard = FRAMEBUFFER.lock();
        let fb = match fb_guard.as_ref() {
            Some(fb) => fb,
            None => return,
        };

        let glyph = crate::graphics::font::glyph(ch);
        for row in 0..FONT_HEIGHT {
            let bits = glyph[row as usize];
            for col in 0..FONT_WIDTH {
                let pixel_set = (bits >> (7 - col)) & 1 != 0;
                let color = if pixel_set { self.fg_color } else { self.bg_color };
                fb.set_pixel(x + col, y + row, color);
            }
        }
    }
}

// ============================================================================
// core::fmt::Write implementation
// ============================================================================

impl fmt::Write for GraphicsConsole {
    fn write_str(&mut self, s: &str) -> fmt::Result {
        self.write_string(s);
        Ok(())
    }
}

// ============================================================================
// Module-level functions
// ============================================================================

/// Initialize the global graphical console.
///
/// Creates a `GraphicsConsole` sized for the given screen dimensions
/// and stores it in the `CONSOLE` mutex.
pub fn init(width: u32, height: u32) {
    let console = GraphicsConsole::new(width, height);
    *CONSOLE.lock() = Some(console);
    crate::serial_println!("[graphics::console] Console initialized ({}x{} cells)",
        core::cmp::min((width / FONT_WIDTH) as usize, MAX_COLS),
        core::cmp::min((height / FONT_HEIGHT) as usize, MAX_ROWS),
    );
}

/// Internal print function for the graphical console.
///
/// Locks the global `CONSOLE`, writes the formatted arguments, and
/// also forwards the output to the serial port for debugging.
pub fn _print(args: fmt::Arguments) {
    use core::fmt::Write;
    use x86_64::instructions::interrupts;

    // Always forward to serial so output is visible in the QEMU terminal
    crate::serial::_print(args);

    interrupts::without_interrupts(|| {
        if let Some(console) = CONSOLE.lock().as_mut() {
            console.write_fmt(args).unwrap();
        }
    });
}
