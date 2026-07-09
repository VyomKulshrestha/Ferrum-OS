// ============================================================================
// FerrumOS - Notes (ferrumpkg demo package)
// ============================================================================
// A minimal scratchpad app, deliberately never embedded into the kernel
// binary (see build.rs) - it exists only as a staged package on the
// appliance disk under /disk/pkgs-available/notes/, and only runs at all
// once `pkg install notes` has been run. This is the proof that ferrumpkg
// installs genuinely new code, not just bookkeeping around apps the kernel
// already shipped with.
//
// Controls: type to insert, Backspace to delete, Enter for a newline,
// Escape to save. Nearly identical to text-editor on purpose - the point
// of this app is proving the package-install path works, not novelty.
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

static mut HEAP: [u8; 4 * 1024 * 1024] = [0; 4 * 1024 * 1024];

const NOTES_PATH: &str = "/disk/notes.txt";
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
    canvas.clear(0x1a, 0x20, 0x1a);
    canvas.fill_rect(0, 0, CANVAS_W, LINE_HEIGHT, 0x25, 0x40, 0x30);
    canvas.draw_string(MARGIN, 2, status, 0x00, 0xff, 0x99);

    let max_chars = ((CANVAS_W - MARGIN * 2) / ferrumgui::font::FONT_WIDTH) as usize;
    let lines = wrap_text(buffer, max_chars.max(1));
    let max_visible = ((CANVAS_H - LINE_HEIGHT - MARGIN) / LINE_HEIGHT) as usize;
    let start = lines.len().saturating_sub(max_visible);
    let mut y = LINE_HEIGHT + MARGIN;
    for line in &lines[start..] {
        canvas.draw_string(MARGIN, y, line, 0xcc, 0xdd, 0xcc);
        y += LINE_HEIGHT;
    }
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        ALLOCATOR.lock().init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len());
    }

    ferrumgui::write_console("[notes] alive in ring 3\n");

    let mut buffer = match ferrumgui::read_file(NOTES_PATH, MAX_FILE_LEN) {
        Some(bytes) => String::from_utf8_lossy(&bytes).into_owned(),
        None => String::new(),
    };

    let window_id = ferrumgui::create_window("Notes", CANVAS_W, CANVAS_H);
    ferrumgui::write_console("[notes] window created id=");
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
                continue; // only keypresses matter for a scratchpad
            }
            let ascii = a as u8;
            match ascii {
                0x1B => {
                    // Escape: save.
                    if ferrumgui::write_file(NOTES_PATH, buffer.as_bytes()) {
                        ferrumgui::write_console("[notes] saved\n");
                        status = "Saved";
                    } else {
                        ferrumgui::write_console("[notes] save failed\n");
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
