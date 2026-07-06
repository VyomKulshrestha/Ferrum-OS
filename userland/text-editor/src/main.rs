// ============================================================================
// FerrumOS - Text Editor (D3 core app)
// ============================================================================
// Reads/edits/saves a plain text file in a real GUI window on the D1
// app-window framework. Deliberately edits a single fixed path rather than
// prompting for a filename - there is no argv mechanism for a spawned
// process in this OS to receive "which file", so File Manager previews
// content in its own window instead of launching this with a target file.
//
// Controls: type to insert, Backspace to delete, Enter for a newline,
// Escape to save.
#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use core::panic::PanicInfo;
use ferrumgui::{Canvas, InputEvent};
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

// Must comfortably exceed the canvas buffer (CANVAS_W * CANVAS_H * 4 =
// ~614 KB) plus the text buffer/wrap_text's Vec<String> - undersizing this
// caused a silent allocation failure (abort) right after window creation,
// before this comment was added.
static mut HEAP: [u8; 4 * 1024 * 1024] = [0; 4 * 1024 * 1024];

const EDIT_PATH: &str = "/disk/scratch.txt";
const MAX_FILE_LEN: usize = 64 * 1024;
const CANVAS_W: u32 = 480;
const CANVAS_H: u32 = 320;
const LINE_HEIGHT: u32 = 18;
const MARGIN: u32 = 8;

fn wrap_text(text: &str, max_chars: usize) -> Vec<String> {
    let mut lines = Vec::new();
    let mut current = String::new();
    for ch in text.chars() {
        if ch == '\n' {
            lines.push(current);
            current = String::new();
        } else {
            current.push(ch);
            if current.chars().count() >= max_chars {
                lines.push(current);
                current = String::new();
            }
        }
    }
    lines.push(current);
    lines
}

fn redraw(canvas: &mut Canvas, buffer: &str, status: &str) {
    canvas.clear(0x1a, 0x1a, 0x20);
    canvas.fill_rect(0, 0, CANVAS_W, LINE_HEIGHT, 0x25, 0x30, 0x40);
    canvas.draw_string(MARGIN, 2, status, 0x00, 0xff, 0xcc);

    let max_chars = ((CANVAS_W - MARGIN * 2) / ferrumgui::font::FONT_WIDTH) as usize;
    let lines = wrap_text(buffer, max_chars.max(1));
    let max_visible = ((CANVAS_H - LINE_HEIGHT - MARGIN) / LINE_HEIGHT) as usize;
    let start = lines.len().saturating_sub(max_visible);
    let mut y = LINE_HEIGHT + MARGIN;
    for line in &lines[start..] {
        canvas.draw_string(MARGIN, y, line, 0xcc, 0xcc, 0xcc);
        y += LINE_HEIGHT;
    }
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        ALLOCATOR.lock().init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len());
    }

    ferrumgui::write_console("[text-editor] alive in ring 3\n");

    let mut buffer = match ferrumgui::read_file(EDIT_PATH, MAX_FILE_LEN) {
        Some(bytes) => String::from_utf8_lossy(&bytes).into_owned(),
        None => String::new(),
    };
    ferrumgui::write_console("[text-editor] loaded: ");
    ferrumgui::write_console(&buffer);
    ferrumgui::write_console("\n");

    let window_id = ferrumgui::create_window("Text Editor", CANVAS_W, CANVAS_H);
    ferrumgui::write_console("[text-editor] window created id=");
    ferrumgui::write_int(window_id as i64);
    ferrumgui::write_console("\n");

    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    let mut status = "Escape to save";
    redraw(&mut canvas, &buffer, status);
    canvas.present(window_id);

    loop {
        let mut dirty = false;
        while let Some(InputEvent { tag, a, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag != 0 {
                continue; // only keypresses matter for a text editor
            }
            let ascii = a as u8;
            match ascii {
                0x1B => {
                    // Escape: save.
                    if ferrumgui::write_file(EDIT_PATH, buffer.as_bytes()) {
                        ferrumgui::write_console("[text-editor] saved\n");
                        status = "Saved";
                    } else {
                        ferrumgui::write_console("[text-editor] save failed\n");
                        status = "Save failed";
                    }
                    dirty = true;
                }
                0x08 => {
                    buffer.pop();
                    status = "Escape to save";
                    dirty = true;
                }
                b'\n' | b'\r' => {
                    buffer.push('\n');
                    status = "Escape to save";
                    dirty = true;
                }
                _ if ascii.is_ascii_graphic() || ascii == b' ' => {
                    buffer.push(ascii as char);
                    status = "Escape to save";
                    dirty = true;
                }
                _ => {}
            }
        }

        if dirty {
            redraw(&mut canvas, &buffer, status);
            canvas.present(window_id);
        }

        ferrumgui::sleep(30);
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    ferrumgui::exit(1);
}
