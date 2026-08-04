// ============================================================================
// FerrumOS - File Manager (D3 core app)
// ============================================================================
// Browses the ext2 /disk filesystem, previews file contents, and opens known
// document types through the trusted app-launch broker. The selected path is
// carried as pid-scoped launch metadata rather than mutable global state.
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
const PATH_BAR_H: u32 = 22;
const TOOLBAR_H: u32 = 30;
const CONTENT_TOP: u32 = PATH_BAR_H + TOOLBAR_H;
const STATUS_H: u32 = 22;
const MAX_PREVIEW_LEN: usize = 16 * 1024;
const ROOT: &str = "/disk";

const BACK_RECT: (u32, u32, u32, u32) = (8, PATH_BAR_H + 3, 64, 24);
const FORWARD_RECT: (u32, u32, u32, u32) = (78, PATH_BAR_H + 3, 80, 24);
const UP_RECT: (u32, u32, u32, u32) = (164, PATH_BAR_H + 3, 48, 24);
const REFRESH_RECT: (u32, u32, u32, u32) = (218, PATH_BAR_H + 3, 80, 24);
const OPEN_RECT: (u32, u32, u32, u32) = (304, PATH_BAR_H + 3, 108, 24);

enum View {
    List {
        path: String,
        entries: Vec<DirEntry>,
    },
    Preview {
        path: String,
        parent_path: String,
        content: String,
    },
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum ToolbarAction {
    Back,
    Forward,
    Up,
    Refresh,
    Open,
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

    View::List {
        path: String::from(path),
        entries,
    }
}

fn point_in(x: u32, y: u32, rect: (u32, u32, u32, u32)) -> bool {
    let (rx, ry, rw, rh) = rect;
    x >= rx && x < rx + rw && y >= ry && y < ry + rh
}

fn toolbar_action_at(x: u32, y: u32) -> Option<ToolbarAction> {
    if point_in(x, y, BACK_RECT) {
        Some(ToolbarAction::Back)
    } else if point_in(x, y, FORWARD_RECT) {
        Some(ToolbarAction::Forward)
    } else if point_in(x, y, UP_RECT) {
        Some(ToolbarAction::Up)
    } else if point_in(x, y, REFRESH_RECT) {
        Some(ToolbarAction::Refresh)
    } else if point_in(x, y, OPEN_RECT) {
        Some(ToolbarAction::Open)
    } else {
        None
    }
}

fn associated_app(path: &str) -> Option<&'static str> {
    let extension = path.rsplit('.').next()?;
    match extension {
        "txt" | "md" | "json" | "log" | "toml" | "rs" | "yaml" | "yml" | "csv" => {
            Some("text-editor")
        }
        _ => None,
    }
}

fn parent_path(path: &str) -> String {
    if path == ROOT {
        return String::from(ROOT);
    }
    let trimmed = path.trim_end_matches('/');
    let parent = trimmed
        .rfind('/')
        .map(|idx| &trimmed[..idx])
        .unwrap_or(ROOT);
    if parent.len() < ROOT.len() {
        String::from(ROOT)
    } else {
        String::from(parent)
    }
}

fn row_at(y: u32) -> Option<usize> {
    if y < CONTENT_TOP || y >= CANVAS_H - STATUS_H {
        return None;
    }
    Some(((y - CONTENT_TOP) / LINE_HEIGHT) as usize)
}

fn draw_toolbar_button(
    canvas: &mut Canvas,
    rect: (u32, u32, u32, u32),
    label: &str,
    enabled: bool,
) {
    let (x, y, w, h) = rect;
    let (bg, fg) = if enabled {
        ((0x31, 0x3e, 0x50), (0xee, 0xee, 0xee))
    } else {
        ((0x24, 0x29, 0x31), (0x70, 0x70, 0x70))
    };
    canvas.fill_rect(x, y, w, h, bg.0, bg.1, bg.2);
    canvas.draw_string(x + 8, y + 7, label, fg.0, fg.1, fg.2);
}

fn redraw(canvas: &mut Canvas, view: &View, can_go_back: bool, can_go_forward: bool) {
    canvas.clear(0x1a, 0x1a, 0x20);
    match view {
        View::List { path, entries } => {
            canvas.fill_rect(0, 0, CANVAS_W, PATH_BAR_H, 0x25, 0x30, 0x40);
            canvas.draw_string(MARGIN, 2, path, 0x00, 0xff, 0xcc);
            canvas.fill_rect(0, PATH_BAR_H, CANVAS_W, TOOLBAR_H, 0x1f, 0x25, 0x30);
            let can_go_up = path.as_str() != ROOT;
            draw_toolbar_button(canvas, BACK_RECT, "Back", can_go_back);
            draw_toolbar_button(canvas, FORWARD_RECT, "Forward", can_go_forward);
            draw_toolbar_button(canvas, UP_RECT, "Up", can_go_up);
            draw_toolbar_button(canvas, REFRESH_RECT, "Refresh", true);
            draw_toolbar_button(canvas, OPEN_RECT, "Open", false);

            let mut y = CONTENT_TOP + 2;
            for entry in entries {
                let (color, label) = if entry.is_dir {
                    ((0x66, 0xaa, 0xff), format!("[D] {}", entry.name))
                } else {
                    ((0xcc, 0xcc, 0xcc), format!("[F] {}", entry.name))
                };
                canvas.draw_string(MARGIN, y, &label, color.0, color.1, color.2);
                y += LINE_HEIGHT;
                if y >= CANVAS_H - STATUS_H {
                    break;
                }
            }

            canvas.fill_rect(0, CANVAS_H - STATUS_H, CANVAS_W, STATUS_H, 0x25, 0x30, 0x40);
            let status = format!(
                "{} item{}",
                entries.len(),
                if entries.len() == 1 { "" } else { "s" }
            );
            canvas.draw_string(MARGIN, CANVAS_H - STATUS_H + 4, &status, 0x99, 0xaa, 0xbb);
        }
        View::Preview {
            path,
            parent_path,
            content,
        } => {
            canvas.fill_rect(0, 0, CANVAS_W, PATH_BAR_H, 0x25, 0x30, 0x40);
            canvas.draw_string(MARGIN, 2, path, 0x00, 0xff, 0xcc);
            canvas.fill_rect(0, PATH_BAR_H, CANVAS_W, TOOLBAR_H, 0x1f, 0x25, 0x30);
            draw_toolbar_button(canvas, BACK_RECT, "Back", true);
            draw_toolbar_button(canvas, FORWARD_RECT, "Forward", can_go_forward);
            draw_toolbar_button(canvas, UP_RECT, "Up", true);
            draw_toolbar_button(canvas, REFRESH_RECT, "Refresh", true);
            draw_toolbar_button(canvas, OPEN_RECT, "Open", associated_app(path).is_some());

            let max_chars = ((CANVAS_W - MARGIN * 2) / ferrumgui::font::FONT_WIDTH) as usize;
            let mut y = CONTENT_TOP + MARGIN;
            'lines: for raw_line in content.lines() {
                let mut rest = raw_line;
                loop {
                    let take = rest.chars().count().min(max_chars.max(1));
                    let (chunk, remainder) = split_at_chars(rest, take);
                    canvas.draw_string(MARGIN, y, chunk, 0xcc, 0xcc, 0xcc);
                    y += LINE_HEIGHT;
                    if y >= CANVAS_H - STATUS_H {
                        break 'lines;
                    }
                    if remainder.is_empty() {
                        break;
                    }
                    rest = remainder;
                }
            }

            canvas.fill_rect(0, CANVAS_H - STATUS_H, CANVAS_W, STATUS_H, 0x25, 0x30, 0x40);
            canvas.draw_string(
                MARGIN,
                CANVAS_H - STATUS_H + 4,
                &format!("Preview from {}", parent_path),
                0x99,
                0xaa,
                0xbb,
            );
        }
    }
}

fn preview_file(path: String, parent_path: String) -> View {
    let content = match ferrumgui::read_file(&path, MAX_PREVIEW_LEN) {
        Some(bytes) => String::from_utf8_lossy(&bytes).into_owned(),
        None => String::from("(failed to read file)"),
    };
    ferrumgui::write_console("[file-manager] previewing ");
    ferrumgui::write_console(&path);
    ferrumgui::write_console("\n");
    View::Preview {
        path,
        parent_path,
        content,
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
        ALLOCATOR
            .lock()
            .init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len());
    }

    ferrumgui::write_console("[file-manager] alive in ring 3\n");

    let window_id = ferrumgui::create_window("File Manager", CANVAS_W, CANVAS_H);
    ferrumgui::write_console("[file-manager] window created id=");
    ferrumgui::write_int(window_id as i64);
    ferrumgui::write_console("\n");

    let mut view = list_dir(ROOT);
    let mut back_stack: Vec<String> = Vec::new();
    let mut forward_stack: Vec<String> = Vec::new();
    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    redraw(&mut canvas, &view, false, false);
    canvas.present(window_id);

    loop {
        let mut dirty = false;
        while let Some(InputEvent { tag, b, c, d, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag != 3 || b != 1 {
                continue;
            }

            if let Some(action) = toolbar_action_at(c, d) {
                ferrumgui::write_console("[file-manager] action ");
                match action {
                    ToolbarAction::Back => {
                        ferrumgui::write_console("back\n");
                        match &view {
                            View::Preview { parent_path, .. } => view = list_dir(parent_path),
                            View::List { path, .. } => {
                                if let Some(destination) = back_stack.pop() {
                                    forward_stack.push(path.clone());
                                    view = list_dir(&destination);
                                }
                            }
                        }
                    }
                    ToolbarAction::Forward => {
                        ferrumgui::write_console("forward\n");
                        if let (View::List { path, .. }, Some(destination)) =
                            (&view, forward_stack.pop())
                        {
                            back_stack.push(path.clone());
                            view = list_dir(&destination);
                        }
                    }
                    ToolbarAction::Up => {
                        ferrumgui::write_console("up\n");
                        let current = match &view {
                            View::List { path, .. } => path.clone(),
                            View::Preview { parent_path, .. } => parent_path.clone(),
                        };
                        let destination = parent_path(&current);
                        if destination != current {
                            back_stack.push(current);
                            forward_stack.clear();
                            view = list_dir(&destination);
                        } else if matches!(view, View::Preview { .. }) {
                            view = list_dir(&current);
                        }
                    }
                    ToolbarAction::Refresh => {
                        ferrumgui::write_console("refresh\n");
                        view = match &view {
                            View::List { path, .. } => list_dir(path),
                            View::Preview {
                                path, parent_path, ..
                            } => preview_file(path.clone(), parent_path.clone()),
                        };
                    }
                    ToolbarAction::Open => {
                        if let View::Preview { path, .. } = &view {
                            if let Some(app) = associated_app(path) {
                                match ferrumgui::launch_app_with_context(app, path) {
                                    Some(pid) => {
                                        ferrumgui::write_console("[file-manager] opened ");
                                        ferrumgui::write_console(path);
                                        ferrumgui::write_console(" with ");
                                        ferrumgui::write_console(app);
                                        ferrumgui::write_console(" pid=");
                                        ferrumgui::write_int(pid as i64);
                                        ferrumgui::write_console("\n");
                                    }
                                    None => ferrumgui::write_console(
                                        "[file-manager] associated app launch failed\n",
                                    ),
                                }
                            } else {
                                ferrumgui::write_console(
                                    "[file-manager] no associated app for preview\n",
                                );
                            }
                        }
                    }
                }
                dirty = true;
                continue;
            }

            match &view {
                View::List { path, entries } => {
                    if let Some(row) = row_at(d) {
                        if let Some(entry) = entries.get(row) {
                            let child_path = format!("{}/{}", path, entry.name);
                            if entry.is_dir {
                                back_stack.push(path.clone());
                                forward_stack.clear();
                                view = list_dir(&child_path);
                            } else {
                                view = preview_file(child_path, path.clone());
                            }
                            dirty = true;
                        }
                    }
                }
                View::Preview { .. } => {}
            }
        }

        if dirty {
            let preview_can_go_back = matches!(view, View::Preview { .. });
            redraw(
                &mut canvas,
                &view,
                preview_can_go_back || !back_stack.is_empty(),
                !forward_stack.is_empty(),
            );
            canvas.present(window_id);
        }

        ferrumgui::sleep(30);
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    ferrumgui::exit(1);
}
