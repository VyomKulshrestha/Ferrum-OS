// ============================================================================
// FerrumOS - Settings (system + agent info viewer)
// ============================================================================
// v1 scope: read-only. Shows the hardware tier/RAM/AVX2 detection
// (SYS_SYSTEM_QUERY, the same data `config.rs` uses to auto-pick a local
// model tier) and the Heliox agent's current config.json fields, with a
// Refresh button to re-read both. Editing config is heliox-assistant-panel's
// job (its setup wizard); this app is for *seeing* what's actually active,
// which nothing on the desktop could previously show without going to a
// shell and reading the file by hand.
#![no_std]
#![no_main]

extern crate alloc;

use alloc::format;
use core::panic::PanicInfo;
use ferrumgui::{Canvas, InputEvent};
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

static mut HEAP: [u8; 1024 * 1024] = [0; 1024 * 1024];

const CANVAS_W: u32 = 420;
const CANVAS_H: u32 = 300;
const CONFIG_PATH: &str = "/disk/heliox/config.json";

const SYS_SYSTEM_QUERY: u64 = 29;

fn refresh_button_rect() -> (u32, u32, u32, u32) {
    (CANVAS_W - 90, CANVAS_H - 36, 80, 26)
}

fn point_in(px: u32, py: u32, rect: (u32, u32, u32, u32)) -> bool {
    let (x, y, w, h) = rect;
    px >= x && px < x + w && py >= y && py < y + h
}

/// Pull one `"key":"value"` or `"key":value` field out of a flat JSON
/// object without a real parser - config.json is always written in this
/// exact flat, single-line shape (see heliox-assistant-panel's
/// `finish_setup`), so a substring search is enough and avoids pulling in
/// a JSON dependency for a read-only viewer.
fn extract_field<'a>(json: &'a str, key: &str) -> Option<&'a str> {
    let needle = format!("\"{}\"", key);
    let key_pos = json.find(&needle)?;
    let after_key = &json[key_pos + needle.len()..];
    let colon_pos = after_key.find(':')?;
    let after_colon = after_key[colon_pos + 1..].trim_start();
    if let Some(rest) = after_colon.strip_prefix('"') {
        let end = rest.find('"')?;
        Some(&rest[..end])
    } else {
        let end = after_colon.find(|c: char| c == ',' || c == '}').unwrap_or(after_colon.len());
        Some(after_colon[..end].trim())
    }
}

struct State {
    config_raw: Option<alloc::vec::Vec<u8>>,
    sys_info_raw: [u8; 512],
    sys_info_len: usize,
}

impl State {
    fn load() -> Self {
        let config_raw = ferrumgui::read_file(CONFIG_PATH, 4096);
        let mut sys_info_raw = [0u8; 512];
        let sys_info_len = unsafe {
            ferrumgui::syscall4(SYS_SYSTEM_QUERY, 0, sys_info_raw.as_mut_ptr() as u64, sys_info_raw.len() as u64, 0)
        } as usize;
        State { config_raw, sys_info_raw, sys_info_len }
    }
}

fn draw_field(canvas: &mut Canvas, y: u32, label: &str, value: &str) {
    canvas.draw_string(12, y, label, 0x88, 0x88, 0x88);
    canvas.draw_string(160, y, value, 0xEE, 0xEE, 0xEE);
}

fn redraw(canvas: &mut Canvas, state: &State) {
    canvas.clear(0x14, 0x16, 0x1E);
    canvas.draw_string(12, 10, "System", 0x00, 0xCC, 0xFF);

    let sys_str = core::str::from_utf8(&state.sys_info_raw[..state.sys_info_len]).unwrap_or("{}");
    draw_field(canvas, 30, "Hardware tier:", extract_field(sys_str, "tier").unwrap_or("unknown"));
    draw_field(canvas, 48, "RAM (MB):", extract_field(sys_str, "ram_mb").unwrap_or("?"));
    draw_field(canvas, 66, "AVX2:", extract_field(sys_str, "avx2").unwrap_or("?"));
    draw_field(canvas, 84, "CPU count:", extract_field(sys_str, "cpu_count").unwrap_or("?"));
    draw_field(canvas, 102, "Uptime (ticks):", extract_field(sys_str, "uptime_ticks").unwrap_or("?"));

    canvas.draw_string(12, 132, "Heliox Agent", 0x00, 0xCC, 0xFF);
    match &state.config_raw {
        Some(bytes) => {
            let cfg_str = core::str::from_utf8(bytes).unwrap_or("");
            draw_field(canvas, 152, "Provider:", extract_field(cfg_str, "provider").unwrap_or("?"));
            draw_field(canvas, 170, "Model:", extract_field(cfg_str, "model_name").unwrap_or("?"));
            draw_field(canvas, 188, "API host:", extract_field(cfg_str, "api_host").unwrap_or("?"));
        }
        None => {
            canvas.draw_string(12, 152, "Not configured yet - open Heliox Assistant to set up.", 0xAA, 0x88, 0x00);
        }
    }

    let (bx, by, bw, bh) = refresh_button_rect();
    canvas.fill_rect(bx, by, bw, bh, 0x22, 0x28, 0x32);
    canvas.draw_rect_outline(bx, by, bw, bh, 0x44, 0x44, 0x44);
    canvas.draw_string(bx + 12, by + 8, "Refresh", 0xDD, 0xDD, 0xDD);
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        ALLOCATOR.lock().init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len());
    }

    ferrumgui::write_console("[settings] alive in ring 3\n");

    let window_id = ferrumgui::create_window("Settings", CANVAS_W, CANVAS_H);
    ferrumgui::write_console("[settings] window created id=");
    ferrumgui::write_int(window_id as i64);
    ferrumgui::write_console("\n");

    let mut state = State::load();
    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    redraw(&mut canvas, &state);
    canvas.present(window_id);

    loop {
        let mut dirty = false;
        while let Some(InputEvent { tag, b, c, d, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag == 3 && b == 1 && point_in(c, d, refresh_button_rect()) {
                state = State::load();
                ferrumgui::write_console("[settings] refreshed\n");
                dirty = true;
            }
        }

        if dirty {
            redraw(&mut canvas, &state);
            canvas.present(window_id);
        }

        ferrumgui::sleep(30);
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    ferrumgui::exit(1);
}
