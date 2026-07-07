// ============================================================================
// FerrumOS - App Store
// ============================================================================
// FerrumOS has no network package repository or installer - there is
// nowhere to "download" an app from yet. What this actually is: a browsable
// list of every app already built into the kernel image, each launchable
// with a click, so a user can discover what's available without already
// knowing the Start-menu entries by name. An honest v1, not a stand-in for
// a real app store.
#![no_std]
#![no_main]

extern crate alloc;

use core::panic::PanicInfo;
use ferrumgui::{Canvas, InputEvent};
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

static mut HEAP: [u8; 1024 * 1024] = [0; 1024 * 1024];

const CANVAS_W: u32 = 420;
const CANVAS_H: u32 = 340;
const ROW_H: u32 = 48;

struct AppEntry {
    name: &'static str,
    path: &'static str,
    description: &'static str,
}

const APPS: [AppEntry; 6] = [
    AppEntry { name: "Heliox Assistant", path: "/bin/heliox-assistant-panel", description: "Chat with the Heliox agent" },
    AppEntry { name: "Text Editor", path: "/bin/text-editor", description: "Read and write text files" },
    AppEntry { name: "Calculator", path: "/bin/calculator", description: "Basic arithmetic" },
    AppEntry { name: "File Manager", path: "/bin/file-manager", description: "Browse the filesystem" },
    AppEntry { name: "Settings", path: "/bin/settings", description: "System and agent info" },
    AppEntry { name: "Browser", path: "/bin/browser", description: "Minimal HTTP text page viewer" },
];

fn row_rect(i: usize) -> (u32, u32, u32, u32) {
    (8, 30 + (i as u32) * ROW_H, CANVAS_W - 16, ROW_H - 6)
}

fn point_in(px: u32, py: u32, rect: (u32, u32, u32, u32)) -> bool {
    let (x, y, w, h) = rect;
    px >= x && px < x + w && py >= y && py < y + h
}

fn redraw(canvas: &mut Canvas, status: &str) {
    canvas.clear(0x14, 0x16, 0x1E);
    canvas.draw_string(8, 8, "Installed Apps", 0x00, 0xCC, 0xFF);

    for (i, app) in APPS.iter().enumerate() {
        let (x, y, w, h) = row_rect(i);
        canvas.fill_rect(x, y, w, h, 0x1E, 0x22, 0x2C);
        canvas.draw_rect_outline(x, y, w, h, 0x33, 0x33, 0x33);
        canvas.draw_string(x + 8, y + 6, app.name, 0xEE, 0xEE, 0xEE);
        canvas.draw_string(x + 8, y + 24, app.description, 0x88, 0x88, 0x88);
        canvas.draw_string(x + w - 60, y + 14, "Open", 0x00, 0xCC, 0x88);
    }

    canvas.draw_string(8, CANVAS_H - 20, status, 0xAA, 0xAA, 0x00);
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        ALLOCATOR.lock().init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len());
    }

    ferrumgui::write_console("[app-store] alive in ring 3\n");

    let window_id = ferrumgui::create_window("App Store", CANVAS_W, CANVAS_H);
    ferrumgui::write_console("[app-store] window created id=");
    ferrumgui::write_int(window_id as i64);
    ferrumgui::write_console("\n");

    let mut status = "Click an app to launch it";
    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    redraw(&mut canvas, status);
    canvas.present(window_id);

    loop {
        let mut dirty = false;
        while let Some(InputEvent { tag, b, c, d, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag != 3 || b != 1 {
                continue; // only mouse-down presses drive this app
            }
            for (i, app) in APPS.iter().enumerate() {
                if point_in(c, d, row_rect(i)) {
                    match ferrumgui::exec(app.path) {
                        Some(pid) => {
                            ferrumgui::write_console("[app-store] launched ");
                            ferrumgui::write_console(app.name);
                            ferrumgui::write_console(" as pid ");
                            ferrumgui::write_int(pid as i64);
                            ferrumgui::write_console("\n");
                            status = "Launched.";
                        }
                        None => {
                            ferrumgui::write_console("[app-store] failed to launch ");
                            ferrumgui::write_console(app.name);
                            ferrumgui::write_console("\n");
                            status = "Launch failed.";
                        }
                    }
                    dirty = true;
                }
            }
        }

        if dirty {
            redraw(&mut canvas, status);
            canvas.present(window_id);
        }

        ferrumgui::sleep(30);
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    ferrumgui::exit(1);
}
