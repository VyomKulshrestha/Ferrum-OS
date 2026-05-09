// ============================================================================
// FerrumOS - VGA Text Mode Driver
// ============================================================================
// Provides direct access to the VGA text mode framebuffer at 0xB8000.
// Supports colored text output with a global writer protected by a spinlock.
//
// The VGA buffer is 80 columns x 25 rows of character cells, each cell
// containing an ASCII character and a color attribute byte.
// ============================================================================

use core::fmt;
use lazy_static::lazy_static;
use spin::Mutex;

// ============================================================================
// Color System
// ============================================================================

/// Standard VGA text mode colors (4-bit)
#[allow(dead_code)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Color {
    Black = 0,
    Blue = 1,
    Green = 2,
    Cyan = 3,
    Red = 4,
    Magenta = 5,
    Brown = 6,
    LightGray = 7,
    DarkGray = 8,
    LightBlue = 9,
    LightGreen = 10,
    LightCyan = 11,
    LightRed = 12,
    Pink = 13,
    Yellow = 14,
    White = 15,
}

/// A VGA color attribute byte combining foreground and background colors
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(transparent)]
pub struct ColorCode(u8);

impl ColorCode {
    /// Create a new color code from foreground and background colors
    pub const fn new(foreground: Color, background: Color) -> ColorCode {
        ColorCode((background as u8) << 4 | (foreground as u8))
    }
}

// ============================================================================
// VGA Buffer
// ============================================================================

/// A single character cell in the VGA buffer
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(C)]
struct ScreenChar {
    ascii_character: u8,
    color_code: ColorCode,
}

/// VGA buffer dimensions
const BUFFER_HEIGHT: usize = 25;
const BUFFER_WIDTH: usize = 80;

/// The VGA text mode framebuffer
/// 
/// We use raw volatile reads/writes to prevent the compiler from
/// optimizing away writes to the memory-mapped buffer.
#[repr(transparent)]
struct Buffer {
    chars: [[ScreenChar; BUFFER_WIDTH]; BUFFER_HEIGHT],
}

impl Buffer {
    /// Volatile read from buffer position
    fn read(&self, row: usize, col: usize) -> ScreenChar {
        unsafe {
            core::ptr::read_volatile(&self.chars[row][col] as *const ScreenChar)
        }
    }
    
    /// Volatile write to buffer position
    fn write(&mut self, row: usize, col: usize, val: ScreenChar) {
        unsafe {
            core::ptr::write_volatile(&mut self.chars[row][col] as *mut ScreenChar, val);
        }
    }
}

// ============================================================================
// Writer
// ============================================================================

/// VGA text mode writer
/// 
/// Manages cursor position and provides write operations to the VGA buffer.
/// Supports automatic line wrapping and scrolling.
pub struct Writer {
    column_position: usize,
    color_code: ColorCode,
    buffer: &'static mut Buffer,
}

impl Writer {
    /// Write a single ASCII byte to the VGA buffer
    pub fn write_byte(&mut self, byte: u8) {
        match byte {
            b'\n' => self.new_line(),
            byte => {
                if self.column_position >= BUFFER_WIDTH {
                    self.new_line();
                }

                let row = BUFFER_HEIGHT - 1;
                let col = self.column_position;

                let color_code = self.color_code;
                self.buffer.write(row, col, ScreenChar {
                    ascii_character: byte,
                    color_code,
                });
                self.column_position += 1;
            }
        }
    }

    /// Write a string to the VGA buffer
    /// 
    /// Only ASCII printable characters and newlines are supported.
    pub fn write_string(&mut self, s: &str) {
        for byte in s.bytes() {
            match byte {
                0x20..=0x7e | b'\n' => self.write_byte(byte),
                _ => self.write_byte(0xfe),
            }
        }
    }

    /// Scroll the buffer up by one line
    fn new_line(&mut self) {
        for row in 1..BUFFER_HEIGHT {
            for col in 0..BUFFER_WIDTH {
                let character = self.buffer.read(row, col);
                self.buffer.write(row - 1, col, character);
            }
        }
        self.clear_row(BUFFER_HEIGHT - 1);
        self.column_position = 0;
    }

    /// Clear a single row by filling it with spaces
    fn clear_row(&mut self, row: usize) {
        let blank = ScreenChar {
            ascii_character: b' ',
            color_code: self.color_code,
        };
        for col in 0..BUFFER_WIDTH {
            self.buffer.write(row, col, blank);
        }
    }

    /// Clear the entire screen
    pub fn clear_screen(&mut self) {
        for row in 0..BUFFER_HEIGHT {
            self.clear_row(row);
        }
        self.column_position = 0;
    }

    /// Set the current text color
    pub fn set_color(&mut self, foreground: Color, background: Color) {
        self.color_code = ColorCode::new(foreground, background);
    }

    /// Delete the last character (backspace)
    pub fn backspace(&mut self) {
        if self.column_position > 0 {
            self.column_position -= 1;
            let row = BUFFER_HEIGHT - 1;
            let col = self.column_position;
            self.buffer.write(row, col, ScreenChar {
                ascii_character: b' ',
                color_code: self.color_code,
            });
        }
    }
}

impl fmt::Write for Writer {
    fn write_str(&mut self, s: &str) -> fmt::Result {
        self.write_string(s);
        Ok(())
    }
}

// ============================================================================
// Global Writer Instance
// ============================================================================

lazy_static! {
    /// Global VGA writer instance, protected by a spinlock
    pub static ref WRITER: Mutex<Writer> = Mutex::new(Writer {
        column_position: 0,
        color_code: ColorCode::new(Color::LightCyan, Color::Black),
        buffer: unsafe { &mut *(0xb8000 as *mut Buffer) },
    });
}

// ============================================================================
// Print Macros
// ============================================================================

/// Print to the VGA text buffer (no newline)
#[macro_export]
macro_rules! print {
    ($($arg:tt)*) => ($crate::vga::_print(format_args!($($arg)*)));
}

/// Print to the VGA text buffer with a trailing newline
#[macro_export]
macro_rules! println {
    () => ($crate::print!("\n"));
    ($($arg:tt)*) => ($crate::print!("{}\n", format_args!($($arg)*)));
}

/// Internal print function - do not call directly
#[doc(hidden)]
pub fn _print(args: fmt::Arguments) {
    use core::fmt::Write;
    use x86_64::instructions::interrupts;

    interrupts::without_interrupts(|| {
        WRITER.lock().write_fmt(args).unwrap();
    });
}
