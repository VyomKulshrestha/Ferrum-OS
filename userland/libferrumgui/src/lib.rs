// ============================================================================
// FerrumOS - libferrumgui: shared no_std SDK for GUI apps
// ============================================================================
// Syscall wrappers, an RGBA8 canvas with drawing primitives, and input
// polling, shared by every app built on the D1 app-window framework
// (CreateWindow/PresentWindow/PollWindowInput). Extracted once there was
// more than one consumer (File Manager, Text Editor, Calculator) - a
// single app (gui-smoke-test) didn't justify this abstraction yet.
//
// Consumers must set up their own #[global_allocator] (this crate uses
// `alloc::vec::Vec`/`String` but owns no heap itself) and their own
// panic_handler/_start, following userland/gui-smoke-test's skeleton.
// ============================================================================
#![no_std]

extern crate alloc;

pub mod font;

use alloc::string::String;
use alloc::vec::Vec;
use core::arch::asm;

// Syscall numbers - must match src/syscall/mod.rs::SyscallNumber.
pub const SYS_YIELD: u64 = 0;
pub const SYS_READ_FILE: u64 = 15;
pub const SYS_WRITE_FILE: u64 = 16;
pub const SYS_READ_DIR: u64 = 17;
pub const SYS_EXEC: u64 = 18;
pub const SYS_EXIT: u64 = 30;
pub const SYS_GETPID: u64 = 31;
pub const SYS_SLEEP: u64 = 32;
pub const SYS_WRITE: u64 = 34;
pub const SYS_CREATE_WINDOW: u64 = 44;
pub const SYS_PRESENT_WINDOW: u64 = 45;
pub const SYS_POLL_WINDOW_INPUT: u64 = 46;

/// File descriptor for the console (mirrored to serial).
pub const FD_CONSOLE: u64 = 2;

#[inline(always)]
pub unsafe fn syscall3(number: u64, a1: u64, a2: u64, a3: u64) -> u64 {
    let ret: u64;
    asm!(
        "int 0x80",
        inout("rax") number => ret,
        in("rdi") a1,
        in("rsi") a2,
        in("rdx") a3,
        out("rcx") _,
        out("r11") _,
        options(nostack, preserves_flags),
    );
    ret
}

#[inline(always)]
pub unsafe fn syscall4(number: u64, a1: u64, a2: u64, a3: u64, a4: u64) -> u64 {
    let ret: u64;
    asm!(
        "int 0x80",
        inout("rax") number => ret,
        in("rdi") a1,
        in("rsi") a2,
        in("rdx") a3,
        in("r10") a4,
        out("rcx") _,
        out("r11") _,
        options(nostack, preserves_flags),
    );
    ret
}

pub fn write_console(msg: &str) {
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, msg.as_ptr() as u64, msg.len() as u64);
    }
}

pub fn sleep(ms: u64) {
    unsafe {
        syscall3(SYS_SLEEP, ms, 0, 0);
    }
}

pub fn exit(code: u64) -> ! {
    unsafe {
        syscall3(SYS_EXIT, code, 0, 0);
    }
    loop {
        unsafe {
            syscall3(SYS_YIELD, 0, 0, 0);
        }
    }
}

/// Write an integer to the console with no surrounding text, for chaining
/// onto separately-written prefix/suffix text.
pub fn write_int(num: i64) {
    let mut buf = [0u8; 20];
    let mut i = 20;
    let is_neg = num < 0;
    let mut val = if is_neg { -num } else { num } as u64;
    if val == 0 {
        i -= 1;
        buf[i] = b'0';
    } else {
        while val > 0 {
            i -= 1;
            buf[i] = b'0' + (val % 10) as u8;
            val /= 10;
        }
    }
    if is_neg {
        i -= 1;
        buf[i] = b'-';
    }
    unsafe {
        let s = core::str::from_utf8_unchecked(&buf[i..]);
        write_console(s);
    }
}

/// Read a whole file into a heap buffer, up to `max_len` bytes. Returns
/// `None` if the file doesn't exist or is empty.
pub fn read_file(path: &str, max_len: usize) -> Option<Vec<u8>> {
    let mut buf = alloc::vec![0u8; max_len];
    let res = unsafe { syscall4(SYS_READ_FILE, path.as_ptr() as u64, path.len() as u64, buf.as_mut_ptr() as u64, buf.len() as u64) };
    if (res as i64) <= 0 {
        return None;
    }
    buf.truncate(res as usize);
    Some(buf)
}

pub fn write_file(path: &str, data: &[u8]) -> bool {
    let res = unsafe { syscall4(SYS_WRITE_FILE, path.as_ptr() as u64, path.len() as u64, data.as_ptr() as u64, data.len() as u64) };
    (res as i64) >= 0
}

/// Directory entry, parsed from the `SYS_READ_DIR` "d/f <name>\n" format.
pub struct DirEntry {
    pub name: String,
    pub is_dir: bool,
}

pub fn read_dir(path: &str, max_len: usize) -> Vec<DirEntry> {
    let mut buf = alloc::vec![0u8; max_len];
    let res = unsafe { syscall4(SYS_READ_DIR, path.as_ptr() as u64, path.len() as u64, buf.as_mut_ptr() as u64, buf.len() as u64) };
    if (res as i64) <= 0 {
        return Vec::new();
    }
    buf.truncate(res as usize);
    let text = String::from_utf8_lossy(&buf);
    let mut entries = Vec::new();
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("d ") {
            entries.push(DirEntry { name: String::from(rest), is_dir: true });
        } else if let Some(rest) = line.strip_prefix("f ") {
            entries.push(DirEntry { name: String::from(rest), is_dir: false });
        }
    }
    entries
}

/// Spawn another installed app by its embedded-binary path (e.g.
/// `/bin/text-editor`). Returns the new pid, or `None` on failure.
pub fn exec(path: &str) -> Option<u64> {
    let res = unsafe { syscall3(SYS_EXEC, path.as_ptr() as u64, path.len() as u64, 0) };
    if (res as i64) >= 0 { Some(res) } else { None }
}

// ============================================================================
// Window + input
// ============================================================================

pub fn create_window(title: &str, canvas_w: u32, canvas_h: u32) -> u64 {
    unsafe { syscall4(SYS_CREATE_WINDOW, title.as_ptr() as u64, title.len() as u64, canvas_w as u64, canvas_h as u64) }
}

/// One input event scoped to this app's window: tag 0 = KeyPress (a=ascii),
/// tag 3 = MouseButtonDown (a=button, b=pressed, c=x, d=y). Matches
/// `crate::gui::app_window::AppInputEvent`'s wire format.
#[derive(Debug, Clone, Copy)]
pub struct InputEvent {
    pub tag: u32,
    pub a: u32,
    pub b: u32,
    pub c: u32,
    pub d: u32,
}

pub fn poll_window_input(window_id: u64) -> Option<InputEvent> {
    let mut buf = [0u32; 5];
    let got = unsafe { syscall3(SYS_POLL_WINDOW_INPUT, window_id, buf.as_mut_ptr() as u64, 20) };
    if got == 1 {
        Some(InputEvent { tag: buf[0], a: buf[1], b: buf[2], c: buf[3], d: buf[4] })
    } else {
        None
    }
}

// ============================================================================
// Canvas
// ============================================================================

/// An RGBA8 pixel buffer an app draws into, then hands to `PresentWindow`
/// wholesale. `pixels.len() == w * h * 4` always.
pub struct Canvas {
    pub w: u32,
    pub h: u32,
    pub pixels: Vec<u8>,
}

impl Canvas {
    pub fn new(w: u32, h: u32) -> Self {
        Canvas { w, h, pixels: alloc::vec![0u8; (w as usize) * (h as usize) * 4] }
    }

    pub fn clear(&mut self, r: u8, g: u8, b: u8) {
        let mut i = 0;
        while i < self.pixels.len() {
            self.pixels[i] = r;
            self.pixels[i + 1] = g;
            self.pixels[i + 2] = b;
            self.pixels[i + 3] = 0xFF;
            i += 4;
        }
    }

    pub fn set_pixel(&mut self, x: u32, y: u32, r: u8, g: u8, b: u8) {
        if x >= self.w || y >= self.h {
            return;
        }
        let o = ((y * self.w + x) * 4) as usize;
        self.pixels[o] = r;
        self.pixels[o + 1] = g;
        self.pixels[o + 2] = b;
        self.pixels[o + 3] = 0xFF;
    }

    pub fn fill_rect(&mut self, x: u32, y: u32, w: u32, h: u32, r: u8, g: u8, b: u8) {
        for yy in y..(y + h).min(self.h) {
            for xx in x..(x + w).min(self.w) {
                self.set_pixel(xx, yy, r, g, b);
            }
        }
    }

    pub fn draw_rect_outline(&mut self, x: u32, y: u32, w: u32, h: u32, r: u8, g: u8, b: u8) {
        if w == 0 || h == 0 {
            return;
        }
        for xx in x..(x + w).min(self.w) {
            self.set_pixel(xx, y, r, g, b);
            if y + h > 0 {
                self.set_pixel(xx, y + h - 1, r, g, b);
            }
        }
        for yy in y..(y + h).min(self.h) {
            self.set_pixel(x, yy, r, g, b);
            if x + w > 0 {
                self.set_pixel(x + w - 1, yy, r, g, b);
            }
        }
    }

    pub fn draw_char(&mut self, x: u32, y: u32, ch: u8, r: u8, g: u8, b: u8) {
        let bitmap = font::glyph(ch);
        for (row, bits) in bitmap.iter().enumerate() {
            for col in 0..8u32 {
                if bits & (0x80 >> col) != 0 {
                    self.set_pixel(x + col, y + row as u32, r, g, b);
                }
            }
        }
    }

    pub fn draw_string(&mut self, x: u32, y: u32, s: &str, r: u8, g: u8, b: u8) {
        let mut cx = x;
        for ch in s.bytes() {
            self.draw_char(cx, y, ch, r, g, b);
            cx += font::FONT_WIDTH;
        }
    }

    pub fn present(&self, window_id: u64) -> bool {
        let res = unsafe { syscall3(SYS_PRESENT_WINDOW, window_id, self.pixels.as_ptr() as u64, self.pixels.len() as u64) };
        (res as i64) >= 0
    }
}
