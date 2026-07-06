// ============================================================================
// FerrumOS - File Manager (D3 core app)
// ============================================================================
// Browses the ext2 /disk filesystem and previews file contents in its own
// window. Deliberately read-only and doesn't launch text-editor on a file:
// there's no argv mechanism in this OS for a spawned process to learn
// "which file", so opening a file here means reading and displaying it
// directly rather than handing off to another app.
#![no_std]
#![no_main]

extern crate alloc;

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use core::panic::PanicInfo;
use ferrumgui::{Canvas, DirEntry, InputEvent};
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

// Must comfortably exceed the canvas buffer (CANVAS_W * CANVAS_H * 4 =
// ~672 KB) plus directory-listing/file-preview buffers - undersizing this
// caused a silent allocation failure (abort) right after window creation,
// before this comment was added.
static mut HEAP: [u8; 4 * 1024 * 1024] = [0; 4 * 1024 * 1024];

const CANVAS_W: u32 = 420;
const CANVAS_H: u32 = 400;
const LINE_HEIGHT: u32 = 18;
const MARGIN: u32 = 8;
const MAX_PREVIEW_LEN: usize = 16 * 1024;
const ROOT: &str = "/disk";

enum View {
    List { path: String, entries: Vec<DirEntry> },
    Preview { path: String, content: String },
}

fn list_dir(path: &str) -> View {
    let mut entries = ferrumgui::read_dir(path, 8192);
    entries.sort_by(|a, b| b.is_dir.cmp(&a.is_dir).then(a.name.cmp(&b.name)));

    // Log the exact listing (path, order, kind) so the verification
    // harness can compute which on-screen row a given filename landed on
    // without having to guess or hardcode pre-existing disk contents.
    ferrumgui::write_console("[file-manager] listing ");
    ferrumgui::write_console(path);
    ferrumgui::write_console(" count=");
    ferrumgui::write_int(entries.len() as i64);
    ferrumgui::write_console("\n");
    for entry in &entries {
        ferrumgui::write_console("[file-manager] entry ");
        ferrumgui::write_console(if entry.is_dir { "d " } else { "f " });
        ferrumgui::write_console(&entry.name);
        ferrumgui::write_console("\n");
    }

    View::List { path: String::from(path), entries }
}

fn row_at(y: u32, has_up_row: bool) -> Option<usize> {
    if y < LINE_HEIGHT {
        return None;
    }
    let row = ((y - LINE_HEIGHT) / LINE_HEIGHT) as usize;
    if has_up_row {
        if row == 0 {
            return Some(usize::MAX); // sentinel for ".."
        }
        Some(row - 1)
    } else {
        Some(row)
    }
}

fn redraw(canvas: &mut Canvas, view: &View) {
    canvas.clear(0x1a, 0x1a, 0x20);
    match view {
        View::List { path, entries } => {
            canvas.fill_rect(0, 0, CANVAS_W, LINE_HEIGHT, 0x25, 0x30, 0x40);
            canvas.draw_string(MARGIN, 2, path, 0x00, 0xff, 0xcc);

            let has_up_row = path.as_str() != ROOT;
            let mut y = LINE_HEIGHT + 2;
            if has_up_row {
                canvas.draw_string(MARGIN, y, "[..]", 0xaa, 0xaa, 0xaa);
                y += LINE_HEIGHT;
            }
            for entry in entries {
                let (color, label) = if entry.is_dir {
                    ((0x66, 0xaa, 0xff), format!("[D] {}", entry.name))
                } else {
                    ((0xcc, 0xcc, 0xcc), format!("[F] {}", entry.name))
                };
                canvas.draw_string(MARGIN, y, &label, color.0, color.1, color.2);
                y += LINE_HEIGHT;
                if y >= CANVAS_H {
                    break;
                }
            }
        }
        View::Preview { path, content } => {
            canvas.fill_rect(0, 0, CANVAS_W, LINE_HEIGHT, 0x25, 0x30, 0x40);
            canvas.draw_string(MARGIN, 2, &format!("{} (click to go back)", path), 0x00, 0xff, 0xcc);

            let max_chars = ((CANVAS_W - MARGIN * 2) / ferrumgui::font::FONT_WIDTH) as usize;
            let mut y = LINE_HEIGHT + MARGIN;
            'lines: for raw_line in content.lines() {
                let mut rest = raw_line;
                loop {
                    let take = rest.chars().count().min(max_chars.max(1));
                    let (chunk, remainder) = split_at_chars(rest, take);
                    canvas.draw_string(MARGIN, y, chunk, 0xcc, 0xcc, 0xcc);
                    y += LINE_HEIGHT;
                    if y >= CANVAS_H {
                        break 'lines;
                    }
                    if remainder.is_empty() {
                        break;
                    }
                    rest = remainder;
                }
            }
        }
    }
}

fn split_at_chars(s: &str, n: usize) -> (&str, &str) {
    match s.char_indices().nth(n) {
        Some((idx, _)) => (&s[..idx], &s[idx..]),
        None => (s, ""),
    }
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        ALLOCATOR.lock().init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len());
    }

    ferrumgui::write_console("[file-manager] alive in ring 3\n");

    let window_id = ferrumgui::create_window("File Manager", CANVAS_W, CANVAS_H);
    ferrumgui::write_console("[file-manager] window created id=");
    ferrumgui::write_int(window_id as i64);
    ferrumgui::write_console("\n");

    let mut view = list_dir(ROOT);
    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    redraw(&mut canvas, &view);
    canvas.present(window_id);

    loop {
        let mut dirty = false;
        while let Some(InputEvent { tag, b, d, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag != 3 || b != 1 {
                continue;
            }
            match &view {
                View::List { path, entries } => {
                    let has_up_row = path.as_str() != ROOT;
                    if let Some(row) = row_at(d, has_up_row) {
                        if row == usize::MAX {
                            // ".." - go up one directory.
                            if let Some(idx) = path.rfind('/') {
                                let parent = if idx == 0 { ROOT } else { &path[..idx] };
                                let parent = if parent.len() < ROOT.len() { ROOT } else { parent };
                                view = list_dir(parent);
                                dirty = true;
                            }
                        } else if let Some(entry) = entries.get(row) {
                            let child_path = format!("{}/{}", path, entry.name);
                            if entry.is_dir {
                                view = list_dir(&child_path);
                            } else {
                                let content = match ferrumgui::read_file(&child_path, MAX_PREVIEW_LEN) {
                                    Some(bytes) => String::from_utf8_lossy(&bytes).into_owned(),
                                    None => String::from("(failed to read file)"),
                                };
                                ferrumgui::write_console("[file-manager] previewing ");
                                ferrumgui::write_console(&child_path);
                                ferrumgui::write_console("\n");
                                view = View::Preview { path: child_path, content };
                            }
                            dirty = true;
                        }
                    }
                }
                View::Preview { .. } => {
                    // Any click in preview mode returns to the list.
                    view = list_dir(ROOT);
                    dirty = true;
                }
            }
        }

        if dirty {
            redraw(&mut canvas, &view);
            canvas.present(window_id);
        }

        ferrumgui::sleep(30);
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    ferrumgui::exit(1);
}
