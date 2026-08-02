// ============================================================================
// FerrumOS - App Store
// ============================================================================
// Discovers built-in applications and manages release-signed packages from
// the appliance's local package cache. Package transport remains deliberately
// out of scope; install/remove are real kernel transactions, not UI toggles.
#![no_std]
#![no_main]

extern crate alloc;

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use core::panic::PanicInfo;
use ferrumgui::{Canvas, InputEvent, PackageInfo};
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

static mut HEAP: [u8; 2 * 1024 * 1024] = [0; 2 * 1024 * 1024];

const CANVAS_W: u32 = 420;
const CANVAS_H: u32 = 438;
const ROW_H: u32 = 48;

struct AppEntry {
    name: &'static str,
    program: &'static str,
    description: &'static str,
}

const APPS: [AppEntry; 8] = [
    AppEntry { name: "Heliox Assistant", program: "heliox-assistant-panel", description: "Chat with the Heliox agent" },
    AppEntry { name: "Text Editor", program: "text-editor", description: "Read and write text files" },
    AppEntry { name: "Calculator", program: "calculator", description: "Basic arithmetic" },
    AppEntry { name: "File Manager", program: "file-manager", description: "Browse the filesystem" },
    AppEntry { name: "Settings", program: "settings", description: "System and agent info" },
    AppEntry { name: "Browser", program: "browser", description: "Minimal HTTP text page viewer" },
    AppEntry { name: "Notification Center", program: "notification-center", description: "Review desktop alerts" },
    AppEntry { name: "Task Manager", program: "task-manager", description: "Inspect and end tasks" },
];

#[derive(Clone, Copy, PartialEq, Eq)]
enum Tab {
    BuiltIn,
    Signed,
}

enum PendingAction {
    Install(String),
    Remove(String),
    Rollback,
}

fn row_rect(i: usize) -> (u32, u32, u32, u32) {
    (8, 30 + (i as u32) * ROW_H, CANVAS_W - 16, ROW_H - 6)
}

fn point_in(px: u32, py: u32, rect: (u32, u32, u32, u32)) -> bool {
    let (x, y, w, h) = rect;
    px >= x && px < x + w && py >= y && py < y + h
}

fn install_button(row: (u32, u32, u32, u32)) -> (u32, u32, u32, u32) {
    let (x, y, w, h) = row;
    (x + w - 68, y + 7, 60, h - 14)
}

fn open_button(row: (u32, u32, u32, u32)) -> (u32, u32, u32, u32) {
    let (x, y, w, h) = row;
    (x + w - 132, y + 7, 56, h - 14)
}

fn pending_install(pending: &Option<PendingAction>, name: &str) -> bool {
    matches!(pending, Some(PendingAction::Install(pending_name)) if pending_name == name)
}

fn pending_remove(pending: &Option<PendingAction>, name: &str) -> bool {
    matches!(pending, Some(PendingAction::Remove(pending_name)) if pending_name == name)
}

fn draw_button(canvas: &mut Canvas, rect: (u32, u32, u32, u32), label: &str, danger: bool) {
    let (x, y, w, h) = rect;
    let (r, g, b) = if danger { (0x52, 0x24, 0x28) } else { (0x18, 0x45, 0x3A) };
    canvas.fill_rect(x, y, w, h, r, g, b);
    canvas.draw_rect_outline(x, y, w, h, 0x55, 0x88, 0x77);
    canvas.draw_string(x + 5, y + 7, label, 0xEE, 0xEE, 0xEE);
}

fn redraw(
    canvas: &mut Canvas,
    tab: Tab,
    packages: &[PackageInfo],
    pending: &Option<PendingAction>,
    status: &str,
) {
    canvas.clear(0x14, 0x16, 0x1E);
    canvas.draw_string(8, 8, "Built-in", if tab == Tab::BuiltIn { 0x00 } else { 0x88 }, 0xCC, 0xFF);
    canvas.draw_string(105, 8, "Signed Packages", if tab == Tab::Signed { 0x00 } else { 0x88 }, 0xCC, 0xFF);
    if tab == Tab::Signed {
        draw_button(
            canvas,
            (330, 2, 82, 24),
            if matches!(pending, Some(PendingAction::Rollback)) { "Confirm" } else { "Rollback" },
            true,
        );
    }

    match tab {
        Tab::BuiltIn => {
            for (i, app) in APPS.iter().enumerate() {
                let (x, y, w, h) = row_rect(i);
                canvas.fill_rect(x, y, w, h, 0x1E, 0x22, 0x2C);
                canvas.draw_rect_outline(x, y, w, h, 0x33, 0x33, 0x33);
                canvas.draw_string(x + 8, y + 6, app.name, 0xEE, 0xEE, 0xEE);
                canvas.draw_string(x + 8, y + 24, app.description, 0x88, 0x88, 0x88);
                canvas.draw_string(x + w - 60, y + 14, "Open", 0x00, 0xCC, 0x88);
            }
        }
        Tab::Signed => {
            if packages.is_empty() {
                canvas.draw_string(8, 42, "No verified signed packages in local cache.", 0xAA, 0xAA, 0xAA);
            }
            for (i, package) in packages.iter().take(6).enumerate() {
                let row = row_rect(i);
                let (x, y, w, h) = row;
                canvas.fill_rect(x, y, w, h, 0x1E, 0x22, 0x2C);
                canvas.draw_rect_outline(x, y, w, h, 0x33, 0x33, 0x33);
                canvas.draw_string(x + 8, y + 5, &format!("{} {}", package.name, package.version), 0xEE, 0xEE, 0xEE);
                canvas.draw_string(x + 8, y + 23, &package.description, 0x88, 0x88, 0x88);
                if package.installed {
                    draw_button(canvas, open_button(row), "Open", false);
                    draw_button(
                        canvas,
                        install_button(row),
                        if pending_remove(pending, &package.name) { "Confirm" } else { "Remove" },
                        true,
                    );
                } else {
                    draw_button(
                        canvas,
                        install_button(row),
                        if pending_install(pending, &package.name) { "Confirm" } else { "Install" },
                        false,
                    );
                }
            }
        }
    }

    canvas.draw_string(8, CANVAS_H - 20, status, 0xDD, 0xCC, 0x55);
}

fn log_generation(action: &str, name: &str, generation: u64) {
    ferrumgui::write_console("[app-store] ");
    ferrumgui::write_console(action);
    ferrumgui::write_console(" ");
    ferrumgui::write_console(name);
    ferrumgui::write_console(" generation ");
    ferrumgui::write_int(generation as i64);
    ferrumgui::write_console("\n");
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

    let mut tab = Tab::BuiltIn;
    let mut packages = ferrumgui::package_catalog();
    let mut pending = None;
    let mut status = String::from("Browse built-in apps or signed packages");
    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    redraw(&mut canvas, tab, &packages, &pending, &status);
    canvas.present(window_id);

    loop {
        let mut dirty = false;
        while let Some(InputEvent { tag, b, c, d, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag != 3 || b != 1 {
                continue;
            }

            if point_in(c, d, (0, 0, 98, 28)) {
                tab = Tab::BuiltIn;
                pending = None;
                status = String::from("Click a built-in app to launch it");
                dirty = true;
                continue;
            }
            if point_in(c, d, (98, 0, 180, 28)) {
                tab = Tab::Signed;
                pending = None;
                packages = ferrumgui::package_catalog();
                status = String::from("Signed packages are verified by the kernel");
                ferrumgui::write_console("[app-store] signed package catalog opened\n");
                dirty = true;
                continue;
            }
            if tab == Tab::Signed && point_in(c, d, (330, 2, 82, 24)) {
                if matches!(pending, Some(PendingAction::Rollback)) {
                    match ferrumgui::package_rollback(true) {
                        Some(generation) => {
                            log_generation("rolled back registry", "to", generation);
                            status = format!("Rolled back to generation {}", generation);
                            pending = None;
                            packages = ferrumgui::package_catalog();
                        }
                        None => status = String::from("Rollback failed."),
                    }
                } else {
                    ferrumgui::write_console("[app-store] confirmation required to rollback packages\n");
                    pending = Some(PendingAction::Rollback);
                    status = String::from("Confirm package registry rollback");
                }
                dirty = true;
                continue;
            }

            match tab {
                Tab::BuiltIn => {
                    for (i, app) in APPS.iter().enumerate() {
                        if point_in(c, d, row_rect(i)) {
                            match ferrumgui::launch_app(app.program) {
                                Some(pid) => {
                                    ferrumgui::write_console("[app-store] launched ");
                                    ferrumgui::write_console(app.name);
                                    ferrumgui::write_console(" as pid ");
                                    ferrumgui::write_int(pid as i64);
                                    ferrumgui::write_console("\n");
                                    status = String::from("Launched.");
                                }
                                None => status = String::from("Launch failed."),
                            }
                            dirty = true;
                        }
                    }
                }
                Tab::Signed => {
                    for i in 0..packages.len().min(6) {
                        let package = packages[i].clone();
                        let row = row_rect(i);
                        if package.installed && point_in(c, d, open_button(row)) {
                            match ferrumgui::package_launch(&package.name) {
                                Some(pid) => {
                                    ferrumgui::write_console("[app-store] launched package ");
                                    ferrumgui::write_console(&package.name);
                                    ferrumgui::write_console(" as pid ");
                                    ferrumgui::write_int(pid as i64);
                                    ferrumgui::write_console("\n");
                                    status = String::from("Package launched.");
                                }
                                None => status = String::from("Package launch failed."),
                            }
                            dirty = true;
                            break;
                        }
                        if !point_in(c, d, install_button(row)) {
                            continue;
                        }

                        if package.installed {
                            if pending_remove(&pending, &package.name) {
                                match ferrumgui::package_remove(&package.name, true) {
                                    Some(generation) => {
                                        log_generation("removed", &package.name, generation);
                                        status = format!("Removed {}", package.name);
                                        pending = None;
                                        packages = ferrumgui::package_catalog();
                                    }
                                    None => status = String::from("Remove failed."),
                                }
                            } else {
                                ferrumgui::write_console("[app-store] confirmation required to remove ");
                                ferrumgui::write_console(&package.name);
                                ferrumgui::write_console("\n");
                                pending = Some(PendingAction::Remove(package.name.clone()));
                                status = format!("Confirm removal of {}", package.name);
                            }
                        } else if !package.privileged_capabilities.is_empty()
                            && !pending_install(&pending, &package.name)
                        {
                            ferrumgui::write_console("[app-store] confirmation required to install ");
                            ferrumgui::write_console(&package.name);
                            ferrumgui::write_console(" capabilities=");
                            ferrumgui::write_console(&package.privileged_capabilities.join(","));
                            ferrumgui::write_console("\n");
                            pending = Some(PendingAction::Install(package.name.clone()));
                            status = format!("Confirm: {}", package.privileged_capabilities.join(", "));
                        } else {
                            let confirmed = pending_install(&pending, &package.name);
                            match ferrumgui::package_install(&package.name, confirmed) {
                                Some(generation) => {
                                    log_generation("installed", &package.name, generation);
                                    status = format!("Installed {}", package.name);
                                    pending = None;
                                    packages = ferrumgui::package_catalog();
                                }
                                None => status = String::from("Install failed."),
                            }
                        }
                        dirty = true;
                        break;
                    }
                }
            }
        }

        if dirty {
            redraw(&mut canvas, tab, &packages, &pending, &status);
            canvas.present(window_id);
        }

        ferrumgui::sleep(30);
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    ferrumgui::exit(1);
}
