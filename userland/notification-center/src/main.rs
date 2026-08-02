// ============================================================================
// FerrumOS - Notification Center
// ============================================================================
#![no_std]
#![no_main]

extern crate alloc;

use alloc::format;
use alloc::string::String;
use core::panic::PanicInfo;
use ferrumgui::{Canvas, InputEvent, NotificationInfo};
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

static mut HEAP: [u8; 2 * 1024 * 1024] = [0; 2 * 1024 * 1024];

const CANVAS_W: u32 = 460;
const CANVAS_H: u32 = 360;
const ROW_H: u32 = 38;

fn clear_rect() -> (u32, u32, u32, u32) {
    (CANVAS_W - 96, 6, 84, 24)
}

fn point_in(px: u32, py: u32, rect: (u32, u32, u32, u32)) -> bool {
    let (x, y, w, h) = rect;
    px >= x && px < x + w && py >= y && py < y + h
}

fn clipped(value: &str, limit: usize) -> String {
    value.chars().take(limit).collect()
}

fn redraw(canvas: &mut Canvas, notifications: &[NotificationInfo], status: &str) {
    canvas.clear(0x14, 0x16, 0x1E);
    canvas.draw_string(10, 10, "Notification Center", 0x00, 0xCC, 0xFF);
    let (bx, by, bw, bh) = clear_rect();
    canvas.fill_rect(bx, by, bw, bh, 0x52, 0x24, 0x28);
    canvas.draw_rect_outline(bx, by, bw, bh, 0x88, 0x55, 0x55);
    canvas.draw_string(bx + 10, by + 7, "Clear all", 0xEE, 0xEE, 0xEE);

    if notifications.is_empty() {
        canvas.draw_string(10, 56, "You're all caught up.", 0x99, 0x99, 0x99);
    }
    for (index, notification) in notifications.iter().take(7).enumerate() {
        let y = 40 + index as u32 * ROW_H;
        canvas.fill_rect(8, y, CANVAS_W - 16, ROW_H - 4, 0x1E, 0x22, 0x2C);
        canvas.draw_string(14, y + 5, &clipped(&notification.title, 36), 0xEE, 0xEE, 0xEE);
        canvas.draw_string(14, y + 20, &clipped(&notification.body, 48), 0x99, 0x99, 0x99);
        canvas.draw_string(CANVAS_W - 72, y + 5, &format!("pid {}", notification.source_pid), 0x66, 0xAA, 0x99);
    }
    canvas.draw_string(10, CANVAS_H - 20, status, 0xDD, 0xCC, 0x55);
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        ALLOCATOR.lock().init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len());
    }
    ferrumgui::write_console("[notification-center] alive in ring 3\n");
    let window_id = ferrumgui::create_window("Notification Center", CANVAS_W, CANVAS_H);
    ferrumgui::write_console("[notification-center] window created id=");
    ferrumgui::write_int(window_id as i64);
    ferrumgui::write_console("\n");

    let mut notifications = ferrumgui::notification_list();
    ferrumgui::write_console("[notification-center] loaded count=");
    ferrumgui::write_int(notifications.len() as i64);
    ferrumgui::write_console("\n");
    let mut status = String::from("Newest notifications appear first");
    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    redraw(&mut canvas, &notifications, &status);
    canvas.present(window_id);

    loop {
        let mut dirty = false;
        while let Some(InputEvent { tag, b, c, d, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag == 3 && b == 1 && point_in(c, d, clear_rect()) {
                if ferrumgui::notification_dismiss(0) {
                    notifications = ferrumgui::notification_list();
                    status = String::from("Notifications cleared");
                    ferrumgui::write_console("[notification-center] cleared all\n");
                } else {
                    status = String::from("Unable to clear notifications");
                }
                dirty = true;
            }
        }
        if dirty {
            redraw(&mut canvas, &notifications, &status);
            canvas.present(window_id);
        }
        ferrumgui::sleep(50);
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    ferrumgui::exit(1);
}
